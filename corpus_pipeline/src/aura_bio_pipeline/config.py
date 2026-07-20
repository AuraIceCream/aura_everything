from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceConfig:
    id: str
    category: str
    parser: str
    patterns: tuple[str, ...]
    license_id: str | None = None
    priority: int = 100
    trusted_unique: bool = False
    paragraph_dedup: bool = True
    structured_cleaning: bool = False
    compression_level: int = 6


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    corpus_root: Path
    output_root: Path
    chunk_root: Path
    min_document_chars: int
    paragraph_dedup_min_chars: int
    chunk_min_tokens: int
    chunk_target_tokens: int
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    min_chunk_output_tokens: int
    embedding_model: str
    embedding_batch_size: int
    sources: tuple[SourceConfig, ...]


def _resolve(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_config(path: str | Path) -> PipelineConfig:
    config_path = Path(path).resolve()
    with config_path.open("rb") as handle:
        raw: dict[str, Any] = tomllib.load(handle)
    settings = raw["pipeline"]
    output_root = _resolve(settings["output_root"], config_path.parent)
    chunk_root = (
        _resolve(settings["chunk_root"], config_path.parent)
        if settings.get("chunk_root")
        else output_root / "02_chunks"
    )
    sources = tuple(
        SourceConfig(
            id=item["id"],
            category=item["category"],
            parser=item["parser"],
            patterns=tuple(item["patterns"]),
            license_id=item.get("license_id"),
            priority=int(item.get("priority", 100)),
            trusted_unique=bool(item.get("trusted_unique", False)),
            paragraph_dedup=bool(item.get("paragraph_dedup", True)),
            structured_cleaning=bool(item.get("structured_cleaning", False)),
            compression_level=int(item.get("compression_level", 6)),
        )
        for item in raw.get("sources", [])
    )
    return PipelineConfig(
        corpus_root=_resolve(settings["corpus_root"], config_path.parent),
        output_root=output_root,
        chunk_root=chunk_root,
        min_document_chars=int(settings.get("min_document_chars", 200)),
        paragraph_dedup_min_chars=int(settings.get("paragraph_dedup_min_chars", 180)),
        chunk_min_tokens=int(settings.get("chunk_min_tokens", 500)),
        chunk_target_tokens=int(settings.get("chunk_target_tokens", 700)),
        chunk_max_tokens=int(settings.get("chunk_max_tokens", 900)),
        chunk_overlap_tokens=int(settings.get("chunk_overlap_tokens", 80)),
        min_chunk_output_tokens=int(settings.get("min_chunk_output_tokens", 32)),
        embedding_model=settings.get("embedding_model", "BAAI/bge-base-en-v1.5"),
        embedding_batch_size=int(settings.get("embedding_batch_size", 32)),
        sources=sources,
    )
