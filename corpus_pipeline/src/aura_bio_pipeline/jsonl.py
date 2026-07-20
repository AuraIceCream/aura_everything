from __future__ import annotations

import gzip
import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.name.lower().endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc


def write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """Write a complete gzip JSONL file and expose it with one atomic rename."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    count = 0
    opener = gzip.open if path.name.lower().endswith(".gz") else open
    kwargs = {"compresslevel": 6} if opener is gzip.open else {}
    try:
        with opener(temporary, "wt", encoding="utf-8", **kwargs) as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
                count += 1
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return count
