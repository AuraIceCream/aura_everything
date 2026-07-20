from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Document:
    """Canonical unit produced by every source parser.

    A document is a logical article, Wikipedia page, book section, ontology
    term, protein record, or QA example. Keeping all sources in this one schema
    lets later stages remain completely source-agnostic.
    """

    document_id: str
    source_id: str
    category: str
    title: str
    text: str
    source_path: str
    external_id: str | None = None
    url: str | None = None
    license_id: str | None = None
    authors: list[str] = field(default_factory=list)
    published: str | None = None
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Chunk:
    """Retrieval-ready section-aware passage with stable provenance."""

    chunk_id: str
    document_id: str
    source_id: str
    category: str
    title: str
    text: str
    token_count: int
    ordinal: int
    source_path: str
    external_id: str | None = None
    url: str | None = None
    license_id: str | None = None
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

