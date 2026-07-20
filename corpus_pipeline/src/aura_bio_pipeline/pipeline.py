from __future__ import annotations

import gzip
import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import fields
from pathlib import Path
from typing import Any

from .chunking import chunk_document
from .cleaning import clean_structured_text, clean_text
from .config import PipelineConfig, SourceConfig
from .dedup import StateStore, content_digest
from .jsonl import read_jsonl, write_jsonl_atomic
from .models import Document
from .parsers import parse_file
from .provenance import AcquisitionManifest


DOCUMENT_FIELDS = {item.name for item in fields(Document)}
PIPELINE_REVISION = "3"


def file_signature(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _relative_key(config: PipelineConfig, path: Path) -> str:
    try:
        return path.relative_to(config.corpus_root).as_posix()
    except ValueError:
        return path.as_posix()


def _shard_name(config: PipelineConfig, source: SourceConfig, path: Path) -> str:
    relative = _relative_key(config, path)
    digest = hashlib.sha1(relative.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"{source.id}-{digest}.jsonl.gz"


def discover(config: PipelineConfig, source_ids: set[str] | None = None) -> Iterator[tuple[SourceConfig, Path]]:
    """Yield each configured input once, in deterministic source/path order."""

    seen: set[Path] = set()
    for source in sorted(config.sources, key=lambda item: (item.priority, item.id)):
        if source_ids and source.id not in source_ids:
            continue
        for pattern in source.patterns:
            for path in sorted(config.corpus_root.glob(pattern)):
                resolved = path.resolve()
                if not path.is_file() or path.suffix.lower() == ".part" or resolved in seen:
                    continue
                seen.add(resolved)
                yield source, path


def create_inventory(
    config: PipelineConfig, source_ids: set[str] | None = None, maximum_files: int | None = None
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()
    for source, path in discover(config, source_ids):
        if maximum_files is not None and len(rows) >= maximum_files:
            break
        stat = path.stat()
        rows.append(
            {
                "source_id": source.id,
                "category": source.category,
                "parser": source.parser,
                "license_id": source.license_id,
                "path": str(path),
                "relative_path": _relative_key(config, path),
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "signature": file_signature(path),
            }
        )
        totals[source.id] += 1
    output = config.output_root / "00_inventory" / "files.jsonl.gz"
    write_jsonl_atomic(output, rows)
    report = {
        "files": len(rows),
        "bytes": sum(row["bytes"] for row in rows),
        "by_source": dict(sorted(totals.items())),
        "output": str(output),
    }
    _write_report(config, "inventory.json", report)
    return report


def probe_sources(
    config: PipelineConfig, source_ids: set[str] | None = None
) -> dict[str, Any]:
    """Parse one real document from one input file for every selected source.

    This is a fast format/readability gate. It performs no writes to the
    canonical document store and does not change deduplication state.
    """

    results: list[dict[str, Any]] = []
    visited: set[str] = set()
    for source, path in discover(config, source_ids):
        if source.id in visited:
            continue
        visited.add(source.id)
        iterator = parse_file(path, source)
        try:
            document = next(iterator)
            cleaned = clean_text(document.text)
            results.append(
                {
                    "source_id": source.id,
                    "parser": source.parser,
                    "path": str(path),
                    "document_id": document.document_id,
                    "title": document.title,
                    "cleaned_chars": len(cleaned),
                    "status": "ok" if len(cleaned) >= config.min_document_chars else "short",
                }
            )
        except StopIteration:
            results.append(
                {"source_id": source.id, "parser": source.parser, "path": str(path), "status": "empty"}
            )
        except Exception as exc:
            results.append(
                {
                    "source_id": source.id,
                    "parser": source.parser,
                    "path": str(path),
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        finally:
            close = getattr(iterator, "close", None)
            if close:
                close()
    report = {
        "sources": len(results),
        "ok": sum(item["status"] == "ok" for item in results),
        "short": sum(item["status"] == "short" for item in results),
        "empty": sum(item["status"] == "empty" for item in results),
        "errors": sum(item["status"] == "error" for item in results),
        "results": results,
    }
    _write_report(config, "probe.json", report)
    return report


def _write_report(config: PipelineConfig, name: str, report: dict[str, Any]) -> None:
    path = config.output_root / "05_reports" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _ingest_trusted_file(
    config: PipelineConfig,
    source: SourceConfig,
    path: Path,
    output: Path,
    rejected_output: Path,
    acquisition: AcquisitionManifest,
) -> tuple[int, int, int]:
    """Process a provider-ID-keyed shard without touching shared SQLite state.

    This function is safe to run in a worker thread. The caller records the
    completed input in SQLite only after both gzip outputs are atomically
    renamed.
    """

    output.parent.mkdir(parents=True, exist_ok=True)
    rejected_output.parent.mkdir(parents=True, exist_ok=True)
    output_part = output.with_name(output.name + ".part")
    rejected_part = rejected_output.with_name(rejected_output.name + ".part")
    accepted = rejected = 0
    local_document_ids: set[str] = set()
    compression_level = min(9, max(1, source.compression_level))
    cleaner = clean_structured_text if source.structured_cleaning else clean_text
    try:
        with gzip.open(
            output_part, "wt", encoding="utf-8", compresslevel=compression_level
        ) as good, gzip.open(
            rejected_part, "wt", encoding="utf-8", compresslevel=compression_level
        ) as bad:
            for document in parse_file(path, source):
                acquisition.enrich(document, path)
                original_chars = len(document.text)
                document.text = cleaner(document.text)
                reason: str | None = None
                if len(document.text) < config.min_document_chars:
                    reason = "too_short"
                elif document.document_id in local_document_ids:
                    reason = "duplicate_stable_id_in_input"
                else:
                    local_document_ids.add(document.document_id)
                if reason:
                    bad.write(
                        json.dumps(
                            {
                                "stage": "ingest",
                                "reason": reason,
                                "document_id": document.document_id,
                                "source_id": source.id,
                                "source_path": str(path),
                                "original_chars": original_chars,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                    rejected += 1
                    continue
                document.metadata = dict(document.metadata)
                document.metadata["content_sha256"] = content_digest(document.text)
                document.metadata["parser"] = source.parser
                document.metadata["deduplication_key"] = "stable_external_id"
                good.write(json.dumps(document.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")
                accepted += 1
        os.replace(output_part, output)
        os.replace(rejected_part, rejected_output)
        return accepted, rejected, 0
    except Exception:
        output_part.unlink(missing_ok=True)
        rejected_part.unlink(missing_ok=True)
        raise


def ingest(
    config: PipelineConfig,
    source_ids: set[str] | None = None,
    maximum_files: int | None = None,
    workers: int = 4,
) -> dict[str, Any]:
    state = StateStore(config.output_root / "state" / "pipeline.sqlite3")
    acquisition = AcquisitionManifest(config.corpus_root)
    stats: Counter[str] = Counter()
    try:
        selected_inputs = list(discover(config, source_ids))
        if maximum_files is not None:
            selected_inputs = selected_inputs[:maximum_files]
        index = 0
        while index < len(selected_inputs):
            source, path = selected_inputs[index]
            if source.trusted_unique and not source.paragraph_dedup:
                end = index
                group: list[tuple[SourceConfig, Path]] = []
                while end < len(selected_inputs):
                    candidate_source, candidate_path = selected_inputs[end]
                    if not candidate_source.trusted_unique or candidate_source.paragraph_dedup:
                        break
                    group.append((candidate_source, candidate_path))
                    end += 1
                pending: list[tuple[SourceConfig, Path, str, str, Path, Path]] = []
                for group_source, group_path in group:
                    key = _relative_key(config, group_path)
                    signature = (
                        file_signature(group_path)
                        + f":r{PIPELINE_REVISION}:min{config.min_document_chars}"
                        + f":p{config.paragraph_dedup_min_chars}"
                    )
                    output = (
                        config.output_root
                        / "01_documents"
                        / group_source.id
                        / _shard_name(config, group_source, group_path)
                    )
                    rejected_output = config.output_root / "05_reports" / "rejections" / output.name
                    if state.is_processed("ingest", key, signature, output):
                        stats["skipped_inputs"] += 1
                    else:
                        pending.append(
                            (group_source, group_path, key, signature, output, rejected_output)
                        )
                if pending:
                    group_names = ", ".join(dict.fromkeys(item[0].id for item in pending))
                    print(
                        f"ingest starting: sources={group_names} files={len(pending)} "
                        f"workers={max(1, workers)}",
                        flush=True,
                    )
                with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
                    futures = {
                        executor.submit(
                            _ingest_trusted_file,
                            config,
                            item[0],
                            item[1],
                            item[4],
                            item[5],
                            acquisition,
                        ): item
                        for item in pending
                    }
                    for future in as_completed(futures):
                        item = futures[future]
                        accepted, rejected, paragraphs_removed = future.result()
                        state.begin()
                        state.commit_input("ingest", item[2], item[3], item[4], accepted)
                        stats["inputs"] += 1
                        stats["documents"] += accepted
                        stats["rejected"] += rejected
                        print(
                            f"ingest {item[0].id}: {item[1].name} "
                            f"documents={accepted} rejected={rejected}",
                            flush=True,
                        )
                index = end
                continue
            key = _relative_key(config, path)
            signature = (
                file_signature(path)
                + f":r{PIPELINE_REVISION}:min{config.min_document_chars}"
                + f":p{config.paragraph_dedup_min_chars}"
            )
            output = config.output_root / "01_documents" / source.id / _shard_name(config, source, path)
            rejected_output = config.output_root / "05_reports" / "rejections" / output.name
            if state.is_processed("ingest", key, signature, output):
                stats["skipped_inputs"] += 1
                index += 1
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            rejected_output.parent.mkdir(parents=True, exist_ok=True)
            output_part = output.with_name(output.name + ".part")
            rejected_part = rejected_output.with_name(rejected_output.name + ".part")
            accepted = rejected = paragraphs_removed = 0
            state.begin()
            try:
                compression_level = min(9, max(1, source.compression_level))
                cleaner = clean_structured_text if source.structured_cleaning else clean_text
                local_document_ids: set[str] = set()
                with gzip.open(
                    output_part, "wt", encoding="utf-8", compresslevel=compression_level
                ) as good, gzip.open(
                    rejected_part, "wt", encoding="utf-8", compresslevel=compression_level
                ) as bad:
                    for document in parse_file(path, source):
                        acquisition.enrich(document, path)
                        original_chars = len(document.text)
                        document.text = cleaner(document.text)
                        reason: str | None = None
                        if len(document.text) < config.min_document_chars:
                            reason = "too_short"
                        digest = content_digest(document.text) if document.text else ""
                        if not reason and source.trusted_unique:
                            if document.document_id in local_document_ids:
                                reason = "duplicate_stable_id_in_input"
                            else:
                                local_document_ids.add(document.document_id)
                        elif not reason and not state.accept(
                            f"document:{source.id}", digest, document.document_id
                        ):
                            reason = "duplicate_document"
                        if not reason and source.paragraph_dedup:
                            document.text, removed = state.deduplicate_paragraphs(
                                document.text,
                                document.document_id,
                                config.paragraph_dedup_min_chars,
                                kind=f"paragraph:{source.id}",
                            )
                            paragraphs_removed += removed
                            if len(document.text) < config.min_document_chars:
                                reason = "too_short_after_deduplication"
                        if reason:
                            bad.write(
                                json.dumps(
                                    {
                                        "stage": "ingest",
                                        "reason": reason,
                                        "document_id": document.document_id,
                                        "source_id": source.id,
                                        "source_path": str(path),
                                        "original_chars": original_chars,
                                    },
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                                + "\n"
                            )
                            rejected += 1
                            continue
                        document.metadata = dict(document.metadata)
                        document.metadata["content_sha256"] = content_digest(document.text)
                        document.metadata["parser"] = source.parser
                        if source.trusted_unique:
                            document.metadata["deduplication_key"] = "stable_external_id"
                        good.write(
                            json.dumps(document.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
                        )
                        accepted += 1
                os.replace(output_part, output)
                os.replace(rejected_part, rejected_output)
                state.commit_input("ingest", key, signature, output, accepted)
            except Exception:
                state.rollback()
                output_part.unlink(missing_ok=True)
                rejected_part.unlink(missing_ok=True)
                raise
            stats["inputs"] += 1
            stats["documents"] += accepted
            stats["rejected"] += rejected
            stats["paragraphs_removed"] += paragraphs_removed
            print(
                f"ingest {source.id}: {path.name} documents={accepted} rejected={rejected}",
                flush=True,
            )
            index += 1
    finally:
        state.close()
    report = dict(stats)
    _write_report(config, "ingest.json", report)
    return report


def _document_from_row(row: dict[str, Any]) -> Document:
    return Document(**{key: value for key, value in row.items() if key in DOCUMENT_FIELDS})


def _chunk_trusted_file(
    config: PipelineConfig,
    source: SourceConfig,
    path: Path,
    output: Path,
    tokenizer: Any,
) -> tuple[int, int, int]:
    """Chunk one provider-ID-keyed shard without shared SQLite writes."""

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part")
    accepted = duplicate = short = 0
    local_chunk_digests: set[str] = set()
    try:
        with gzip.open(
            temporary,
            "wt",
            encoding="utf-8",
            compresslevel=min(9, max(1, source.compression_level)),
        ) as handle:
            for row in read_jsonl(path):
                document = _document_from_row(row)
                for item in chunk_document(
                    document,
                    tokenizer,
                    config.chunk_min_tokens,
                    config.chunk_target_tokens,
                    config.chunk_max_tokens,
                    config.chunk_overlap_tokens,
                ):
                    if (
                        item.token_count < config.min_chunk_output_tokens
                        and item.category != "knowledge_base"
                    ):
                        short += 1
                        continue
                    digest = content_digest(item.text)
                    if digest in local_chunk_digests:
                        duplicate += 1
                        continue
                    local_chunk_digests.add(digest)
                    handle.write(
                        json.dumps(item.to_dict(), ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    )
                    accepted += 1
        os.replace(temporary, output)
        return accepted, duplicate, short
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def chunk(
    config: PipelineConfig,
    source_ids: set[str] | None = None,
    maximum_files: int | None = None,
    tokenizer_name: str | None = None,
    workers: int = 4,
    delete_documents_after_success: bool = False,
) -> dict[str, Any]:
    os.environ.setdefault("USE_TF", "0")
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    from transformers import AutoTokenizer

    tokenizer_name = tokenizer_name or config.embedding_model
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name, use_fast=True)
    # We intentionally tokenize complete source sections before splitting them.
    # Raising only this counting tokenizer's advisory limit avoids a misleading
    # warning; emitted chunks are still enforced against chunk_max_tokens.
    tokenizer.model_max_length = 1_000_000_000
    state = StateStore(config.output_root / "state" / "pipeline.sqlite3")
    sources_by_id = {source.id: source for source in config.sources}
    stats: Counter[str] = Counter()
    inputs: list[tuple[SourceConfig, Path]] = []
    for path in sorted((config.output_root / "01_documents").glob("*/*.jsonl.gz")):
        source = sources_by_id[path.parent.name]
        if source_ids and source.id not in source_ids:
            continue
        inputs.append((source, path))
    if maximum_files is not None:
        inputs = inputs[:maximum_files]
    try:
        index = 0
        while index < len(inputs):
            source, path = inputs[index]
            source_id = source.id
            if source.trusted_unique and not source.paragraph_dedup:
                end = index
                group: list[tuple[SourceConfig, Path]] = []
                while end < len(inputs):
                    candidate_source, candidate_path = inputs[end]
                    if not candidate_source.trusted_unique or candidate_source.paragraph_dedup:
                        break
                    group.append((candidate_source, candidate_path))
                    end += 1
                pending: list[tuple[SourceConfig, Path, str, str, Path]] = []
                for group_source, group_path in group:
                    key = str(group_path.resolve())
                    signature = (
                        file_signature(group_path)
                        + f":r{PIPELINE_REVISION}:{tokenizer_name}"
                        + f":{config.chunk_min_tokens}:{config.chunk_target_tokens}"
                        + f":{config.chunk_max_tokens}:{config.chunk_overlap_tokens}"
                        + f":{config.min_chunk_output_tokens}"
                    )
                    output = config.chunk_root / group_source.id / group_path.name
                    if state.is_processed("chunk", key, signature, output):
                        stats["skipped_inputs"] += 1
                        if delete_documents_after_success:
                            group_path.unlink()
                            stats["document_shards_deleted"] += 1
                    else:
                        pending.append((group_source, group_path, key, signature, output))
                if pending:
                    group_names = ", ".join(dict.fromkeys(item[0].id for item in pending))
                    print(
                        f"chunk starting: sources={group_names} files={len(pending)} "
                        f"workers={max(1, workers)}",
                        flush=True,
                    )
                with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
                    futures = {
                        executor.submit(
                            _chunk_trusted_file,
                            config,
                            item[0],
                            item[1],
                            item[4],
                            tokenizer,
                        ): item
                        for item in pending
                    }
                    for future in as_completed(futures):
                        item = futures[future]
                        accepted, duplicate, short = future.result()
                        state.begin()
                        state.commit_input("chunk", item[2], item[3], item[4], accepted)
                        if delete_documents_after_success:
                            item[1].unlink()
                            stats["document_shards_deleted"] += 1
                        stats["inputs"] += 1
                        stats["chunks"] += accepted
                        stats["duplicates"] += duplicate
                        stats["short_chunks_removed"] += short
                        print(
                            f"chunk {item[0].id}: {item[1].name} "
                            f"chunks={accepted} duplicates={duplicate}",
                            flush=True,
                        )
                index = end
                continue
            key = str(path.resolve())
            signature = (
                file_signature(path)
                + f":r{PIPELINE_REVISION}:{tokenizer_name}"
                + f":{config.chunk_min_tokens}:{config.chunk_target_tokens}"
                + f":{config.chunk_max_tokens}:{config.chunk_overlap_tokens}"
                + f":{config.min_chunk_output_tokens}"
            )
            output = config.chunk_root / source_id / path.name
            if state.is_processed("chunk", key, signature, output):
                stats["skipped_inputs"] += 1
                if delete_documents_after_success:
                    path.unlink()
                    stats["document_shards_deleted"] += 1
                index += 1
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name(output.name + ".part")
            accepted = duplicate = 0
            # Provider IDs already guarantee document identity for structured
            # sources. Keep exact chunk dedup local to each shard so PubMed-scale
            # processing does not insert tens of millions of hashes into SQLite.
            local_chunk_digests: set[str] = set()
            state.begin()
            try:
                with gzip.open(
                    temporary,
                    "wt",
                    encoding="utf-8",
                    compresslevel=min(9, max(1, source.compression_level)),
                ) as handle:
                    for row in read_jsonl(path):
                        document = _document_from_row(row)
                        for item in chunk_document(
                            document,
                            tokenizer,
                            config.chunk_min_tokens,
                            config.chunk_target_tokens,
                            config.chunk_max_tokens,
                            config.chunk_overlap_tokens,
                        ):
                            if (
                                item.token_count < config.min_chunk_output_tokens
                                and item.category != "knowledge_base"
                            ):
                                stats["short_chunks_removed"] += 1
                                continue
                            digest = content_digest(item.text)
                            if source.trusted_unique and not source.paragraph_dedup:
                                is_new = digest not in local_chunk_digests
                                local_chunk_digests.add(digest)
                            else:
                                is_new = state.accept(f"chunk:{source_id}", digest, item.chunk_id)
                            if not is_new:
                                duplicate += 1
                                continue
                            handle.write(
                                json.dumps(item.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
                            )
                            accepted += 1
                os.replace(temporary, output)
                state.commit_input("chunk", key, signature, output, accepted)
                if delete_documents_after_success:
                    path.unlink()
                    stats["document_shards_deleted"] += 1
            except Exception:
                state.rollback()
                temporary.unlink(missing_ok=True)
                raise
            stats["inputs"] += 1
            stats["chunks"] += accepted
            stats["duplicates"] += duplicate
            print(f"chunk {source_id}: {path.name} chunks={accepted} duplicates={duplicate}", flush=True)
            index += 1
    finally:
        state.close()
    report = dict(stats)
    report["tokenizer"] = tokenizer_name
    _write_report(config, "chunk.json", report)
    return report


def pipeline_status(config: PipelineConfig) -> dict[str, Any]:
    result: dict[str, Any] = {
        "output_root": str(config.output_root),
        "chunk_root": str(config.chunk_root),
    }
    for name, root, pattern in (
        ("documents", config.output_root / "01_documents", "*/*.jsonl.gz"),
        ("chunks", config.chunk_root, "*/*.jsonl.gz"),
        ("embedding_shards", config.output_root / "03_embeddings", "*/*.vectors.npy"),
    ):
        files = list(root.glob(pattern))
        result[name] = {"files": len(files), "bytes": sum(path.stat().st_size for path in files)}
    result["faiss_index"] = str(config.output_root / "04_indexes" / "dense.faiss")
    result["metadata_index"] = str(config.output_root / "04_indexes" / "chunks.sqlite3")
    return result
