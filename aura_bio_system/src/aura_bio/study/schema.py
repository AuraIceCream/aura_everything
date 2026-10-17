"""Versioned storage/extraction records, independent of model runtimes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class StudyError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class Limits:
    max_upload_bytes: int = 50 * 1024**2
    max_expanded_bytes: int = 200 * 1024**2
    max_pages_or_slides: int = 2000
    max_workbook_cells: int = 200000
    workers: int = 1
    timeout_seconds: float = 180
    max_image_pixels: int = 25_000_000
    max_render_pixels: int = 12_000_000
    render_dpi: int = 150
    max_visual_bytes: int = 512 * 1024**2
    page_timeout_seconds: float = 60
    ocr_timeout_seconds: float = 60


@dataclass(frozen=True)
class Pack:
    pack_id: str
    name: str
    domain: str
    created_at: float
    generation: int = 0
    state: str = 'empty'
    retention: str = 'saved'
    expires_at: float | None = None
    lifecycle_schema: int = 1


@dataclass(frozen=True)
class Document:
    document_id: str
    pack_id: str
    filename: str
    checksum: str
    kind: str
    active: bool = True
    state: str = 'queued'
    warnings: list[str] = field(default_factory=list)
    coverage: dict[str, int] = field(default_factory=dict)
    parser_version: str = ''


@dataclass(frozen=True)
class Job:
    job_id: str
    pack_id: str
    document_id: str | None
    state: str
    error: str | None = None
    kind: str = 'extract'


@dataclass(frozen=True)
class PurgeResult:
    pack_id: str
    document_id: str | None
    deleted: bool
    invalidated_history: bool = True


@dataclass(frozen=True)
class Locator:
    kind: str
    page: int | None = None
    page_label: str | None = None
    slide: int | None = None
    shape_id: int | None = None
    sheet: str | None = None
    cell_range: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    role: str = 'body'

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class Unit:
    unit_id: str
    document_id: str
    ordinal: int
    role: str
    title: str
    breadcrumb: str
    text: str
    locators: tuple[Locator, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    asset_ids: tuple[str, ...] = ()
    provenance: str = 'native_text'
    provenance_details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        from .provenance import source_method
        source_method(self.provenance, self.role)


@dataclass(frozen=True)
class Asset:
    asset_id: str
    unit_id: str
    mime_type: str
    content: bytes
    coordinates: dict[str, int]


@dataclass(frozen=True)
class Extraction:
    units: list[Unit]
    assets: list[Asset]
    warnings: list[str]
    coverage: dict[str, int]
    parser_version: str


@dataclass(frozen=True)
class StudyChunk:
    chunk_id: str
    document_id: str
    unit_ids: tuple[str, ...]
    locators: tuple[Locator, ...]
    spans: tuple[dict[str, Any], ...]
    text: str
    token_count: int
    ordinal: int
    provenance: str = 'native_text'
    provenance_details: dict[str, Any] = field(default_factory=dict)


def unit_from_dict(value: dict[str, Any]) -> Unit:
    from .provenance import source_method
    return Unit(**{**value, 'locators': tuple(Locator(**loc) for loc in value['locators']),
                   'provenance': source_method(value.get('provenance'), value['role']),
                   'asset_ids': tuple(value.get('asset_ids', ()))})
