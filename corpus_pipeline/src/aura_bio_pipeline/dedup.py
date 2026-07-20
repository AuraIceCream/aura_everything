from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

from .cleaning import normalized_fingerprint_text, split_paragraphs


def content_digest(text: str) -> str:
    return hashlib.sha256(normalized_fingerprint_text(text).encode("utf-8")).hexdigest()


class StateStore:
    """Durable exact-deduplication and resumability state.

    Each input is processed inside one SQLite transaction. Fingerprints are
    committed only after its atomic output shard is present.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS seen (
                kind TEXT NOT NULL,
                digest TEXT NOT NULL,
                first_id TEXT NOT NULL,
                PRIMARY KEY (kind, digest)
            );
            CREATE TABLE IF NOT EXISTS processed_inputs (
                stage TEXT NOT NULL,
                input_key TEXT NOT NULL,
                signature TEXT NOT NULL,
                output_path TEXT NOT NULL,
                records INTEGER NOT NULL,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (stage, input_key)
            );
            """
        )

    def close(self) -> None:
        self.connection.close()

    def is_processed(self, stage: str, key: str, signature: str, output: Path) -> bool:
        row = self.connection.execute(
            "SELECT signature, output_path FROM processed_inputs WHERE stage=? AND input_key=?",
            (stage, key),
        ).fetchone()
        if not row:
            return False
        if row[0] != signature:
            raise RuntimeError(
                f"A previously processed {stage} input changed: {key}. "
                "Global deduplication makes incremental replacement ambiguous; "
                "run 'aura-process reset --yes' and rebuild from the frozen corpus."
            )
        return bool(Path(row[1]).is_file() and output.is_file())

    def begin(self) -> None:
        self.connection.execute("BEGIN IMMEDIATE")

    def commit_input(
        self, stage: str, key: str, signature: str, output: Path, records: int
    ) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO processed_inputs
               (stage, input_key, signature, output_path, records)
               VALUES (?, ?, ?, ?, ?)""",
            (stage, key, signature, str(output), records),
        )
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def accept(self, kind: str, digest: str, record_id: str) -> bool:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO seen(kind, digest, first_id) VALUES (?, ?, ?)",
            (kind, digest, record_id),
        )
        return cursor.rowcount == 1

    def deduplicate_paragraphs(
        self, text: str, record_id: str, minimum: int, kind: str = "paragraph"
    ) -> tuple[str, int]:
        kept: list[str] = []
        removed = 0
        for paragraph in split_paragraphs(text):
            if len(paragraph) < minimum:
                kept.append(paragraph)
                continue
            digest = content_digest(paragraph)
            if self.accept(kind, digest, record_id):
                kept.append(paragraph)
            else:
                removed += 1
        return "\n\n".join(kept), removed


def compact_state(path: Path) -> dict[str, int]:
    """Rebuild resumability state without obsolete fingerprint rows.

    Canonical outputs and ``processed_inputs`` are preserved. The large
    ``seen`` cache is deliberately recreated empty; source-scoped deduplication
    will repopulate it only for sources that actually need content hashing.
    A replacement database is fully built and checked before the old file is
    removed, so interruption cannot strand the pipeline without state.
    """

    if not path.is_file():
        raise FileNotFoundError(path)
    temporary = path.with_name(path.name + ".compact")
    backup = path.with_name(path.name + ".backup")
    for candidate in (temporary, temporary.with_name(temporary.name + "-wal"),
                      temporary.with_name(temporary.name + "-shm"), backup):
        candidate.unlink(missing_ok=True)

    original_bytes = path.stat().st_size
    old = sqlite3.connect(path)
    try:
        old.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        rows = old.execute(
            """SELECT stage, input_key, signature, output_path, records, completed_at
               FROM processed_inputs"""
        ).fetchall()
    finally:
        old.close()

    new = sqlite3.connect(temporary)
    try:
        new.executescript(
            """
            PRAGMA journal_mode=DELETE;
            CREATE TABLE seen (
                kind TEXT NOT NULL,
                digest TEXT NOT NULL,
                first_id TEXT NOT NULL,
                PRIMARY KEY (kind, digest)
            );
            CREATE TABLE processed_inputs (
                stage TEXT NOT NULL,
                input_key TEXT NOT NULL,
                signature TEXT NOT NULL,
                output_path TEXT NOT NULL,
                records INTEGER NOT NULL,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (stage, input_key)
            );
            """
        )
        new.executemany(
            """INSERT INTO processed_inputs
               (stage, input_key, signature, output_path, records, completed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        new.commit()
        if new.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Compacted state database failed integrity_check")
    finally:
        new.close()

    # No database connection is open during the atomic swap (required on Windows).
    os.replace(path, backup)
    try:
        os.replace(temporary, path)
        check = sqlite3.connect(path)
        try:
            preserved = check.execute("SELECT COUNT(*) FROM processed_inputs").fetchone()[0]
        finally:
            check.close()
        if preserved != len(rows):
            raise RuntimeError("Compacted state database lost resumability rows")
    except Exception:
        path.unlink(missing_ok=True)
        os.replace(backup, path)
        raise
    backup.unlink()
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    return {
        "processed_inputs": len(rows),
        "bytes_before": original_bytes,
        "bytes_after": path.stat().st_size,
    }
