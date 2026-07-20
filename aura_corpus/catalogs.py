from __future__ import annotations

import hashlib
import re
import time
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin

from .models import Source
from .net import request_bytes


@dataclass(frozen=True)
class CatalogCandidate:
    source_id: str
    title: str
    url: str
    license_state: str = "unknown"
    acquisition_state: str = "manual_license_review"

    def as_record(self, source: Source) -> dict:
        return {
            "candidate_id": hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:20],
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "category": source.category,
            "license_state": self.license_state,
            "license_id": source.license_id,
            "acquisition_state": self.acquisition_state,
            "catalog_url": source.index_url,
            "license_reference": source.license_url,
            "notes": source.notes,
        }


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag.lower() == "a" and attributes.get("href"):
            self._href = attributes["href"]
            self._parts = [attributes.get("title") or ""]
        elif tag.lower() == "img" and self._href:
            self._parts.extend([attributes.get("alt") or "", attributes.get("title") or ""])

    def handle_data(self, data: str) -> None:
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        title = " ".join(" ".join(self._parts).split())
        self.links.append((self._href, title))
        self._href = None
        self._parts = []


def parse_catalog_links(html: str, base_url: str) -> list[tuple[str, str]]:
    parser = _AnchorParser()
    parser.feed(html)
    links: list[tuple[str, str]] = []
    for href, title in parser.links:
        if href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        url, _ = urldefrag(urljoin(base_url, href))
        links.append((url, title))
    return links


def discover_catalog(
    source: Source,
    *,
    max_candidates: int | None = None,
    max_pages: int | None = None,
) -> list[CatalogCandidate]:
    """Crawl only catalog pages and emit review records; never download linked books."""
    if source.discovery != "catalog_review" or not source.index_url:
        raise ValueError(f"{source.id}: not a catalog_review source")
    candidate_pattern = str(source.extra.get("candidate_regex", ""))
    if not candidate_pattern:
        raise ValueError(f"{source.id}: catalog source needs candidate_regex")
    candidate_re = re.compile(candidate_pattern, re.IGNORECASE)
    crawl_pattern = str(source.extra.get("crawl_regex", ""))
    crawl_re = re.compile(crawl_pattern, re.IGNORECASE) if crawl_pattern else None
    max_depth = int(source.extra.get("crawl_depth", 0))
    delay = float(source.extra.get("crawl_delay_seconds", 1.0))
    page_limit = max_pages or int(source.extra.get("max_pages", 100))

    queue = deque([(source.index_url, 0)])
    seen_pages: set[str] = set()
    seen_candidates: set[str] = set()
    candidates: list[CatalogCandidate] = []
    while queue and len(seen_pages) < page_limit:
        page_url, depth = queue.popleft()
        if page_url in seen_pages:
            continue
        if seen_pages and delay > 0:
            time.sleep(delay)
        seen_pages.add(page_url)
        response = request_bytes(page_url)
        html = response.body.decode("utf-8", errors="replace")
        for url, title in parse_catalog_links(html, page_url):
            if candidate_re.search(url) and url not in seen_candidates:
                seen_candidates.add(url)
                candidates.append(
                    CatalogCandidate(
                        source_id=source.id,
                        title=title or url.rsplit("/", 1)[-1],
                        url=url,
                    )
                )
                if max_candidates is not None and len(candidates) >= max_candidates:
                    return candidates
            if (
                crawl_re
                and depth < max_depth
                and crawl_re.search(url)
                and url not in seen_pages
            ):
                queue.append((url, depth + 1))
    return candidates
