"""Create a compact, reproducible fine-tuning source pack from clean chunks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .retrieval import CORE_SOURCES, PUBMED_SOURCES, QA_SOURCES


def _stable_order(paths: list[Path], root: Path) -> list[Path]:
    """Choose spread-out source shards without depending on filesystem order."""

    return sorted(
        paths,
        key=lambda path: hashlib.sha256(str(path.relative_to(root)).encode("utf-8")).hexdigest(),
    )


def _materialize(source: Path, target: Path, copy_files: bool) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    if copy_files:
        shutil.copy2(source, target)
        return "copy"
    try:
        os.link(source, target)
        return "hardlink"
    except OSError:
        shutil.copy2(source, target)
        return "copy-fallback"


def make_finetune_pack(
    chunk_root: Path,
    output_root: Path,
    pubmed_gib: float = 5.8,
    copy_files: bool = False,
    include_qa: bool = True,
) -> dict[str, Any]:
    """Materialize ~9 GiB of clean training-ready data without raw duplicates.

    The default is all non-PubMed core chunks (~3.2 GiB) plus a deterministic
    5.8 GiB spread of PubMed shards. On the same NTFS volume it creates hard
    links, so it is safe to delete the original selected source later: the pack
    continues to own the data blocks.
    """

    output_root = output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"Fine-tune pack already exists and is not empty: {output_root}")
    if output_root == chunk_root.resolve() or output_root.is_relative_to(chunk_root.resolve()):
        raise ValueError("Fine-tune output must not be inside the source chunk tree")
    target_bytes = int(pubmed_gib * 1024**3)
    selected: list[Path] = []
    core_paths = [
        path for source in sorted(CORE_SOURCES) for path in sorted((chunk_root / source).glob("*.jsonl.gz"))
    ]
    selected.extend(core_paths)
    pubmed_paths = _stable_order(sorted((chunk_root / "pubmed_filtered").glob("*.jsonl.gz")), chunk_root)
    pubmed_total = 0
    for path in pubmed_paths:
        if pubmed_total and pubmed_total + path.stat().st_size > target_bytes:
            continue
        selected.append(path)
        pubmed_total += path.stat().st_size
        if pubmed_total >= target_bytes:
            break
    if not pubmed_total:
        raise ValueError("No PubMed chunk shards selected")
    if include_qa:
        for source in QA_SOURCES:
            selected.extend(sorted((chunk_root / source).glob("*.jsonl.gz")))

    modes: dict[str, int] = {}
    files: list[dict[str, Any]] = []
    for source in selected:
        relative = source.relative_to(chunk_root)
        target = output_root / "chunks" / relative
        mode = _materialize(source, target, copy_files)
        modes[mode] = modes.get(mode, 0) + 1
        files.append({"path": str(relative), "bytes": source.stat().st_size, "mode": mode})
    core_bytes = sum(path.stat().st_size for path in core_paths)
    result = {
        "schema_version": 1,
        "chunk_root": str(chunk_root),
        "output": str(output_root),
        "core_gib": round(core_bytes / 1024**3, 3),
        "pubmed_gib": round(pubmed_total / 1024**3, 3),
        "total_gib": round(sum(item["bytes"] for item in files) / 1024**3, 3),
        "files": len(files),
        "modes": modes,
        "files_detail": files,
        "qa_included": include_qa,
    }
    manifest = output_root / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
