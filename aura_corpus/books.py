from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from .catalogs import parse_catalog_links
from .net import request_bytes


_CC_URL = re.compile(
    r"creativecommons\.org/(?:licenses/(by(?:-nc)?(?:-sa)?|by-nd|by-nc-nd)|publicdomain/zero)/(\d\.\d)",
    re.IGNORECASE,
)
_ALLOWED = {"CC0", "CC BY", "CC BY-SA", "CC BY-NC", "CC BY-NC-SA"}


def _plain_text(markup: str) -> str:
    value = re.sub(r"<script\b[\s\S]*?</script>", " ", markup, flags=re.IGNORECASE)
    value = re.sub(r"<style\b[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def _licenses(links: list[tuple[str, str]]) -> list[str]:
    found: set[str] = set()
    for url, _ in links:
        match = _CC_URL.search(url)
        if not match:
            continue
        code = match.group(1)
        if code is None:
            found.add("CC0")
        else:
            found.add("CC " + code.upper())
    return sorted(found)


def audit_book_candidate(candidate: dict, *, delay_seconds: float = 5.0) -> dict:
    source_id = str(candidate.get("source_id", ""))
    base = {
        **candidate,
        "use_scope": "research_noncommercial",
        "redistribution": "follow_item_license",
    }
    if source_id != "biolibretexts_catalog":
        return {
            **base,
            "audit_decision": "rejected",
            "audit_reason": "directory listing has no explicit item-level corpus/reuse licence",
            "license_state": "unknown",
        }

    page_url = str(candidate["url"])
    page_html = request_bytes(page_url, retries=5).body.decode("utf-8", errors="replace")
    page_links = parse_catalog_links(page_html, page_url)
    pdf_urls = [url for url, _ in page_links if "/@api/deki/pages/" in url and "/pdf/" in url]
    detail_urls = []
    for url, title in page_links:
        label = (title + " " + url).lower().replace("_", " ").replace("+", " ")
        if "detailed licensing" in label:
            detail_urls.append(url)
    evidence_url = detail_urls[0] if detail_urls else page_url
    evidence_html = page_html
    if evidence_url != page_url:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        evidence_html = request_bytes(evidence_url, retries=5).body.decode("utf-8", errors="replace")
    evidence_links = parse_catalog_links(evidence_html, evidence_url)
    licenses = sorted(set(_licenses(page_links) + _licenses(evidence_links)))
    evidence_text = _plain_text(evidence_html).lower()
    unsupported_markers = []
    for marker in ("undeclared", "ck-12 license", "all rights reserved"):
        if marker in evidence_text:
            unsupported_markers.append(marker)
    unsupported_licenses = sorted(set(licenses) - _ALLOWED)
    if not pdf_urls:
        reason = "no LibreTexts PDF endpoint found"
    elif not licenses:
        reason = "no explicit supported Creative Commons licence found"
    elif unsupported_markers or unsupported_licenses:
        reason = "mixed or unsupported licensing: " + ", ".join(
            unsupported_markers + unsupported_licenses
        )
    else:
        return {
            **base,
            "audit_decision": "approved",
            "audit_reason": "explicit non-commercial-compatible LibreTexts licence evidence",
            "license_state": "allowed_noncommercial",
            "license_ids": licenses,
            "license_evidence_url": evidence_url,
            "download_url": pdf_urls[0],
        }
    return {
        **base,
        "audit_decision": "rejected",
        "audit_reason": reason,
        "license_state": "unsupported_or_ambiguous",
        "license_ids": licenses,
        "license_evidence_url": evidence_url,
    }


def load_candidates(path: Path, limit: int | None = None) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
                if limit is not None and len(records) >= limit:
                    break
    return records
