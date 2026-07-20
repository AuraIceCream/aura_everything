from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse

from .models import RemoteFile, Source
from .net import request_bytes


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def _filename(url: str) -> str:
    return PurePosixPath(urlparse(url).path).name


def _parse_checksum_manifest(content: str) -> dict[str, tuple[str, str]]:
    checksums: dict[str, tuple[str, str]] = {}
    for line in content.splitlines():
        match = re.match(r"^([a-fA-F0-9]{32}|[a-fA-F0-9]{40}|[a-fA-F0-9]{64})\s+[* ]?(.+?)\s*$", line)
        if not match:
            continue
        digest, name = match.groups()
        algorithm = {32: "md5", 40: "sha1", 64: "sha256"}[len(digest)]
        checksums[PurePosixPath(name).name] = (algorithm, digest.lower())
    return checksums


def _allowed(name: str, source: Source) -> bool:
    if source.include_regex and not re.search(source.include_regex, name, re.IGNORECASE):
        return False
    if source.exclude_regex and re.search(source.exclude_regex, name, re.IGNORECASE):
        return False
    return True


def discover(source: Source, limit: int | None = None) -> list[RemoteFile]:
    if source.discovery == "catalog_review":
        raise ValueError(
            f"{source.id}: this is a review-only catalog; use the catalog command, "
            "then approve each item's licence before acquisition"
        )
    if source.discovery == "direct":
        if not source.url:
            raise ValueError(f"{source.id}: direct source has no URL")
        return [
            RemoteFile(
                source_id=source.id,
                category=source.category,
                url=source.url,
                filename=_filename(source.url),
                checksum_url=(source.url + ".md5") if source.checksum == "sidecar-md5" else None,
            )
        ]
    if source.discovery == "html_index":
        return _discover_html(source)
    if source.discovery == "litarch_catalog":
        return _discover_litarch(source, limit=limit)
    if source.discovery == "pmc_esearch":
        return _discover_pmc_esearch(source, limit=limit)
    if source.discovery == "pmc_efetch":
        return _discover_pmc_efetch(source, limit=limit)
    if source.discovery == "mediawiki_category":
        return _discover_mediawiki_category(source, limit=limit)
    raise ValueError(f"{source.id}: unsupported discovery type {source.discovery!r}")


def _discover_pmc_efetch(source: Source, limit: int | None = None) -> list[RemoteFile]:
    """Discover reusable PMC IDs once, then retrieve full XML in EFetch batches."""
    query = str(source.extra.get("query", "")).strip()
    if not query:
        raise ValueError(f"{source.id}: pmc_efetch source needs a query")
    date_start = str(source.extra.get("date_start", "")).strip()
    date_end = str(source.extra.get("date_end", "")).strip()
    window_tag = ""
    if date_start and date_end:
        query = (
            f"({query}) AND "
            f"{date_start.replace('-', '/')}:{date_end.replace('-', '/')}[pmcrdat]"
        )
        window_tag = f"{date_start.replace('-', '')}-{date_end.replace('-', '')}-"
    requested = limit or int(source.extra.get("retmax", 100))
    requested = max(1, min(requested, 10_000))
    search_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pmc&retmode=json&sort=date&retmax={requested}&term={quote(query)}"
    )
    print(
        f"{source.id}: requesting {requested} commercially reusable PMC IDs...",
        file=sys.stderr,
        flush=True,
    )
    search = json.loads(request_bytes(search_url).body)
    ids = search.get("esearchresult", {}).get("idlist", [])[:requested]
    batch_size = max(1, min(int(source.extra.get("batch_size", 1000)), 200))
    files: list[RemoteFile] = []
    for batch_number, start in enumerate(range(0, len(ids), batch_size), start=1):
        batch = ids[start : start + batch_size]
        params = {
            "db": "pmc",
            "retmode": "xml",
            "rettype": "xml",
            "id": ",".join(batch),
        }
        files.append(
            RemoteFile(
                source_id=source.id,
                category=source.category,
                url=(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
                    + urlencode(params)
                ),
                filename=f"pmc-commercial-{window_tag}{batch_number:05d}.xml",
                metadata={
                    "pmc_numeric_ids": batch,
                    "article_count": len(batch),
                    "license_state": "allowed_by_pmc_search_filter",
                    "license_filter": query,
                    "date_start": date_start or None,
                    "date_end": date_end or None,
                },
            )
        )
    print(
        f"{source.id}: prepared {len(files)} EFetch batch(es) for {len(ids)} articles",
        file=sys.stderr,
        flush=True,
    )
    return files


def _discover_mediawiki_category(
    source: Source, limit: int | None = None
) -> list[RemoteFile]:
    """Build bounded revision-JSON batches from a MediaWiki category tree."""
    api_url = source.index_url
    root_category = str(source.extra.get("root_category", "")).strip()
    if not api_url or not root_category:
        raise ValueError(f"{source.id}: mediawiki_category needs index_url and root_category")

    max_depth = max(0, int(source.extra.get("category_depth", 2)))
    batch_size = max(1, min(int(source.extra.get("batch_size", 50)), 50))
    max_articles = max(1, int(source.extra.get("max_articles", 5_000)))
    if limit is not None:
        max_articles = min(max_articles, max(1, limit) * batch_size)
    category_exclude = re.compile(
        str(source.extra.get("exclude_category_regex", r"$^")), re.IGNORECASE
    )
    title_exclude = re.compile(
        str(source.extra.get("exclude_title_regex", r"$^")), re.IGNORECASE
    )
    request_delay = max(0.0, float(source.extra.get("request_delay_seconds", 0.25)))
    fingerprint_data = {
        "api_url": api_url,
        "root_category": root_category,
        "max_depth": max_depth,
        "category_exclude": category_exclude.pattern,
        "title_exclude": title_exclude.pattern,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_data, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cache_dir = Path(__file__).resolve().parent.parent / ".cache"
    cache_path = cache_dir / f"{source.id}-category-discovery.json"
    categories: list[tuple[str, int]] = [(root_category, 0)]
    seen_categories: set[str] = set()
    pages: dict[int, str] = {}
    position = 0
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint:
                categories = [(str(name), int(depth)) for name, depth in cached["categories"]]
                seen_categories = {str(value) for value in cached["seen_categories"]}
                pages = {int(key): str(value) for key, value in cached["pages"].items()}
                position = int(cached["position"])
                print(
                    f"{source.id}: resumed discovery cache at {position} categories / {len(pages)} pages",
                    file=sys.stderr,
                    flush=True,
                )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            categories = [(root_category, 0)]
            seen_categories = set()
            pages = {}
            position = 0

    def save_checkpoint() -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "categories": categories,
                    "seen_categories": sorted(seen_categories),
                    "pages": pages,
                    "position": position,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        temporary.replace(cache_path)

    last_category: str | None = None
    while position < len(categories) and len(pages) < max_articles:
        category, depth = categories[position]
        last_category = category
        position += 1
        if category in seen_categories or category_exclude.search(category):
            continue
        seen_categories.add(category)
        continuation: str | None = None
        while len(pages) < max_articles:
            params = {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "list": "categorymembers",
                "cmtitle": category,
                "cmtype": "page|subcat",
                "cmnamespace": "0|14",
                "cmprop": "ids|title|type",
                "cmlimit": "500",
                "maxlag": "5",
            }
            if continuation:
                params["cmcontinue"] = continuation
            query_url = api_url + "?" + urlencode(params)
            if request_delay:
                time.sleep(request_delay)
            payload = json.loads(request_bytes(query_url, retries=6).body)
            for member in payload.get("query", {}).get("categorymembers", []):
                member_type = member.get("type")
                title = str(member.get("title", ""))
                if member_type == "page" and not title_exclude.search(title):
                    pages[int(member["pageid"])] = title
                    if len(pages) >= max_articles:
                        break
                elif member_type == "subcat" and depth < max_depth:
                    if not category_exclude.search(title):
                        categories.append((title, depth + 1))
            continuation = payload.get("continue", {}).get("cmcontinue")
            if not continuation:
                break
        if position == 1 or position % 10 == 0:
            print(
                f"{source.id}: scanned {position} categories, selected {len(pages)}/{max_articles} pages",
                file=sys.stderr,
                flush=True,
            )
        if position % 10 == 0:
            save_checkpoint()

    # If the page target interrupted a category, revisit it when a later run
    # requests a larger target; page IDs make the repeated members harmless.
    if len(pages) >= max_articles and last_category in seen_categories:
        seen_categories.remove(last_category)
        position = max(0, position - 1)
    save_checkpoint()

    page_items = sorted(pages.items())
    files: list[RemoteFile] = []
    for batch_number, start in enumerate(range(0, len(page_items), batch_size), start=1):
        batch = page_items[start : start + batch_size]
        page_ids = "|".join(str(page_id) for page_id, _ in batch)
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "revisions|info",
            "pageids": page_ids,
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
            "inprop": "url",
        }
        url = api_url + "?" + urlencode(params)
        files.append(
            RemoteFile(
                source_id=source.id,
                category=source.category,
                url=url,
                filename=f"biology-pages-{batch_number:05d}.json",
                metadata={
                    "root_category": root_category,
                    "page_count": len(batch),
                    "page_ids": [page_id for page_id, _ in batch],
                    "titles": [title for _, title in batch],
                    "license_id": source.license_id,
                    "license_state": "allowed",
                },
            )
        )
        if limit is not None and len(files) >= limit:
            break
    return files


def _discover_html(source: Source) -> list[RemoteFile]:
    if not source.index_url:
        raise ValueError(f"{source.id}: html_index source has no index_url")
    response = request_bytes(source.index_url)
    parser = _LinkParser()
    parser.feed(response.body.decode("utf-8", errors="replace"))

    checksum_map: dict[str, tuple[str, str]] = {}
    if source.checksum_manifest_url:
        checksum_response = request_bytes(source.checksum_manifest_url)
        checksum_map = _parse_checksum_manifest(
            checksum_response.body.decode("utf-8", errors="replace")
        )

    files: list[RemoteFile] = []
    seen: set[str] = set()
    for href in parser.links:
        url = urljoin(source.index_url, href)
        name = _filename(url)
        if not name or name in seen or not _allowed(name, source):
            continue
        seen.add(name)
        checksum = checksum_map.get(name)
        files.append(
            RemoteFile(
                source_id=source.id,
                category=source.category,
                url=url,
                filename=name,
                checksum_algorithm=checksum[0] if checksum else None,
                expected_checksum=checksum[1] if checksum else None,
                checksum_url=(url + ".md5") if source.checksum == "sidecar-md5" else None,
            )
        )
    return sorted(files, key=lambda item: item.filename)


def _discover_litarch(source: Source, limit: int | None = None) -> list[RemoteFile]:
    if not source.index_url or not source.base_url:
        raise ValueError(f"{source.id}: litarch source needs index_url and base_url")
    response = request_bytes(source.index_url)
    text = response.body.decode("utf-8-sig", errors="replace")
    selection = re.compile(source.selection_regex or ".*", re.IGNORECASE)
    files: list[RemoteFile] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 5:
            continue
        path = row[0].strip()
        if not path.endswith(".tar.gz"):
            continue
        title = row[1].strip()
        if not selection.search(title):
            continue
        files.append(
            RemoteFile(
                source_id=source.id,
                category=source.category,
                url=urljoin(source.base_url, path),
                filename=PurePosixPath(path).name,
                metadata={
                    "title": title,
                    "publisher": row[2].strip(),
                    "year": row[3].strip(),
                    "accession": row[4].strip(),
                },
            )
        )
        if limit is not None and len(files) >= limit:
            break
    return sorted(files, key=lambda item: item.filename)


def _s3_to_https(url: str) -> tuple[str, str | None]:
    parsed = urlparse(url)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Unexpected PMC object URL: {url}")
    query = parse_qs(parsed.query)
    checksum = query.get("md5", [None])[0]
    https = f"https://{parsed.netloc}.s3.amazonaws.com{parsed.path}"
    return https, checksum


def _discover_pmc_esearch(source: Source, limit: int | None = None) -> list[RemoteFile]:
    """Discover current PMC article-version objects through the official ESearch-S3 flow."""
    query = str(source.extra.get("query", "")).strip()
    if not query:
        raise ValueError(f"{source.id}: pmc_esearch source needs a query")
    requested = limit or int(source.extra.get("retmax", 100))
    requested = max(1, min(requested, 10_000))
    search_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pmc&retmode=json&sort=date&retmax={requested}&term={quote(query)}"
    )
    search = json.loads(request_bytes(search_url).body)
    ids = search.get("esearchresult", {}).get("idlist", [])[:requested]
    allowed_licenses = {"CC0", "CC BY", "CC BY-SA", "CC BY-ND"}

    def resolve(numeric_id: str) -> RemoteFile | None:
        pmcid = f"PMC{numeric_id}"
        listing_url = (
            "https://pmc-oa-opendata.s3.amazonaws.com/"
            f"?list-type=2&delimiter=/&prefix={quote(pmcid + '.')}"
        )
        listing = ET.fromstring(request_bytes(listing_url).body)
        prefixes = [
            child.text.rstrip("/")
            for element in listing.iter()
            if element.tag.endswith("CommonPrefixes")
            for child in element
            if child.tag.endswith("Prefix") and child.text
        ]
        if not prefixes:
            return None
        prefixes.sort(key=lambda value: int(value.rsplit(".", 1)[-1]))
        versioned = prefixes[-1]
        metadata_url = f"https://pmc-oa-opendata.s3.amazonaws.com/metadata/{versioned}.json"
        metadata = json.loads(request_bytes(metadata_url).body)
        if (
            metadata.get("license_code") not in allowed_licenses
            or metadata.get("is_retracted") is True
            or metadata.get("is_pmc_openaccess") is not True
        ):
            return None
        object_url = metadata.get("xml_url") or metadata.get("text_url")
        if not object_url:
            return None
        url, md5 = _s3_to_https(object_url)
        return RemoteFile(
            source_id=source.id,
            category=source.category,
            url=url,
            filename=_filename(url),
            checksum_algorithm="md5" if md5 else None,
            expected_checksum=md5,
            metadata={
                "pmcid": metadata.get("pmcid"),
                "pmid": metadata.get("pmid"),
                "doi": metadata.get("doi"),
                "title": metadata.get("title"),
                "citation": metadata.get("citation"),
                "license_id": metadata.get("license_code"),
                "license_state": "allowed",
                "retracted": False,
                "version": metadata.get("version"),
            },
        )

    files: list[RemoteFile] = []
    discovery_workers = max(1, min(int(source.extra.get("discovery_workers", 8)), 16))
    print(
        f"{source.id}: resolving {len(ids)} PMC article objects with {discovery_workers} workers...",
        file=sys.stderr,
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=discovery_workers) as pool:
        for index, item in enumerate(pool.map(resolve, ids), start=1):
            if item is not None:
                files.append(item)
            if index == 1 or index % 25 == 0 or index == len(ids):
                print(
                    f"{source.id}: resolved {index}/{len(ids)} IDs; {len(files)} reusable XML files",
                    file=sys.stderr,
                    flush=True,
                )
    return files
