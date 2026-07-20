from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import Document


def _path_key(value: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(value)))


class AcquisitionManifest:
    """Small lookup view over the provenance-first acquisition manifest."""

    def __init__(self, corpus_root: Path) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        path = corpus_root / "05_Metadata" / "manifests" / "files.jsonl"
        if not path.is_file():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                local_path = row.get("local_path")
                if local_path:
                    self.records[_path_key(local_path)] = row
                # Filtering/decompression records retain the raw local_path and
                # write the normalized destination into the audit message.
                error = row.get("error") or ""
                marker = "normalized to "
                if marker in error:
                    normalized = error.split(marker, 1)[1].strip()
                    if normalized:
                        self.records[_path_key(normalized)] = row

    def enrich(self, document: Document, source_path: Path) -> None:
        row = self.records.get(_path_key(source_path))
        if not row:
            return
        item_metadata = row.get("metadata") or {}
        license_ids = item_metadata.get("license_ids")
        if isinstance(license_ids, list) and license_ids:
            document.license_id = "; ".join(str(item) for item in license_ids)
        elif item_metadata.get("license_id"):
            document.license_id = str(item_metadata["license_id"])
        if not document.url and item_metadata.get("page_url"):
            document.url = str(item_metadata["page_url"])
        document.metadata = dict(document.metadata)
        document.metadata["acquisition"] = {
            key: value
            for key, value in {
                "status": row.get("status"),
                "sha256": row.get("sha256"),
                "provider_url": row.get("url"),
                "expected_checksum": row.get("expected_checksum"),
                "checksum_algorithm": row.get("checksum_algorithm"),
                "actual_bytes": row.get("actual_bytes"),
                "license_state": item_metadata.get("license_state"),
                "license_evidence_url": item_metadata.get("license_evidence_url"),
                "use_scope": item_metadata.get("use_scope"),
            }.items()
            if value is not None
        }

