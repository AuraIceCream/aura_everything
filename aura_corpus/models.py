from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    category: str
    discovery: str
    license_id: str
    license_url: str
    documentation_url: str
    risk: str = "small"
    index_url: str | None = None
    url: str | None = None
    base_url: str | None = None
    include_regex: str | None = None
    exclude_regex: str | None = None
    checksum: str | None = None
    checksum_manifest_url: str | None = None
    selection_regex: str | None = None
    notes: str = ""
    enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RemoteFile:
    source_id: str
    category: str
    url: str
    filename: str
    expected_bytes: int | None = None
    checksum_algorithm: str | None = None
    expected_checksum: str | None = None
    checksum_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def destination(self, corpus_root: Path) -> Path:
        return corpus_root / self.category / "raw" / self.source_id / self.filename

