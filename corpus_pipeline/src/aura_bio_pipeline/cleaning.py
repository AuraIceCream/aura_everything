from __future__ import annotations

import html
import re
import unicodedata

from ftfy import fix_text


CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SPACE_RE = re.compile(r"[ \t]+")
BLANK_RE = re.compile(r"\n{3,}")
URL_ONLY_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
BOILERPLATE_HEADINGS = {
    "references",
    "external links",
    "see also",
    "further reading",
    "acknowledgments",
    "acknowledgements",
}


def normalize_text(text: str) -> str:
    """Repair common encoding damage and normalize layout without lowercasing.

    Case, punctuation, formulae, and section boundaries carry biological meaning,
    so cleaning is intentionally less aggressive than web-search preprocessing.
    """

    text = fix_text(html.unescape(text or ""))
    text = unicodedata.normalize("NFKC", text)
    text = CONTROL_RE.sub(" ", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [SPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    return BLANK_RE.sub("\n\n", "\n".join(lines)).strip()


def clean_text(text: str) -> str:
    """Remove obvious boilerplate while retaining source wording and headings."""

    text = normalize_text(text)
    kept: list[str] = []
    skipping_tail = False
    for line in text.splitlines():
        heading = line.lstrip("# ").strip().casefold()
        if heading in BOILERPLATE_HEADINGS:
            skipping_tail = True
            continue
        if skipping_tail:
            # A later major heading can resume useful content, although most
            # documents place these boilerplate sections at the end.
            if line.startswith("## ") and heading not in BOILERPLATE_HEADINGS:
                skipping_tail = False
            else:
                continue
        if URL_ONLY_RE.match(line) or line.casefold() in {"table of contents", "contents"}:
            continue
        kept.append(line)
    return BLANK_RE.sub("\n\n", "\n".join(kept)).strip()


def clean_structured_text(text: str) -> str:
    """Fast conservative cleanup for text assembled by trusted parsers.

    OBO, MeSH, UniProt, Reactome, and PubMedQA parsers already decode markup
    and select useful fields. Running HTML repair and boilerplate detection on
    every short record is both redundant and costly for multi-gigabyte flat
    files, so this path keeps only Unicode and whitespace normalization.
    """

    text = unicodedata.normalize("NFKC", text or "")
    text = CONTROL_RE.sub(" ", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [SPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    return BLANK_RE.sub("\n\n", "\n".join(lines)).strip()


def normalized_fingerprint_text(text: str) -> str:
    """Canonical text used only for exact duplicate hashing."""

    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def split_paragraphs(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
