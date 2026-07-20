from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .models import RemoteFile


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    source_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    category TEXT NOT NULL,
    url TEXT NOT NULL,
    local_path TEXT NOT NULL,
    expected_bytes INTEGER,
    checksum_algorithm TEXT,
    expected_checksum TEXT,
    status TEXT NOT NULL,
    actual_bytes INTEGER,
    sha256 TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source_id, filename)
);
CREATE INDEX IF NOT EXISTS files_status_idx ON files(status);
"""


class ManifestStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.connection:
            self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def plan(self, item: RemoteFile, local_path: Path) -> None:
        now = datetime.now(UTC).isoformat()
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO files (
                    source_id, filename, category, url, local_path, expected_bytes,
                    checksum_algorithm, expected_checksum, status, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?)
                ON CONFLICT(source_id, filename) DO UPDATE SET
                    category=excluded.category, url=excluded.url, local_path=excluded.local_path,
                    expected_bytes=COALESCE(excluded.expected_bytes, files.expected_bytes),
                    checksum_algorithm=COALESCE(excluded.checksum_algorithm, files.checksum_algorithm),
                    expected_checksum=COALESCE(excluded.expected_checksum, files.expected_checksum),
                    metadata_json=excluded.metadata_json, updated_at=excluded.updated_at
                """,
                (
                    item.source_id,
                    item.filename,
                    item.category,
                    item.url,
                    str(local_path),
                    item.expected_bytes,
                    item.checksum_algorithm,
                    item.expected_checksum,
                    json.dumps(item.metadata, sort_keys=True),
                    now,
                ),
            )

    def update(self, source_id: str, filename: str, status: str, **fields: object) -> None:
        allowed = {"actual_bytes", "sha256", "error", "expected_checksum", "checksum_algorithm"}
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Unsupported manifest fields: {invalid}")
        assignments = ["status = ?", "updated_at = ?"]
        values: list[object] = [status, datetime.now(UTC).isoformat()]
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(value)
        values.extend([source_id, filename])
        with self.lock, self.connection:
            self.connection.execute(
                f"UPDATE files SET {', '.join(assignments)} WHERE source_id = ? AND filename = ?",
                values,
            )

    def rows(self, status: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM files"
        parameters: tuple[object, ...] = ()
        if status:
            query += " WHERE status = ?"
            parameters = (status,)
        query += " ORDER BY source_id, filename"
        return list(self.connection.execute(query, parameters))

    def export_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in self.rows():
                record = dict(row)
                record["metadata"] = json.loads(record.pop("metadata_json"))
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

