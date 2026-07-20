from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

from .config import PipelineConfig
from .jsonl import read_jsonl
from .pipeline import _write_report, file_signature


QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _embedding_paths(root: Path, chunk_path: Path) -> tuple[Path, Path, Path]:
    source = chunk_path.parent.name
    stem = chunk_path.name.removesuffix(".jsonl.gz")
    directory = root / "03_embeddings" / source
    return (
        directory / f"{stem}.vectors.npy",
        directory / f"{stem}.chunks.jsonl.gz",
        directory / f"{stem}.complete.json",
    )


def embed(
    config: PipelineConfig,
    source_ids: set[str] | None = None,
    maximum_files: int | None = None,
    device: str | None = None,
    model_name: str | None = None,
    batch_size: int | None = None,
    maximum_chunks: int | None = None,
) -> dict[str, Any]:
    """Embed chunk shards independently so an interrupted run can resume."""

    model_name = model_name or config.embedding_model
    batch_size = batch_size or config.embedding_batch_size
    inputs = sorted(config.chunk_root.glob("*/*.jsonl.gz"))
    stats: dict[str, Any] = {"inputs": 0, "skipped_inputs": 0, "vectors": 0, "model": model_name}
    pending: list[tuple[Path, Path, Path, Path, str]] = []
    selected = 0
    for path in inputs:
        source_id = path.parent.name
        if source_ids and source_id not in source_ids:
            continue
        if maximum_files is not None and selected >= maximum_files:
            break
        selected += 1
        vectors_path, chunks_path, marker_path = _embedding_paths(config.output_root, path)
        signature = file_signature(path)
        if marker_path.is_file() and vectors_path.is_file() and chunks_path.is_file():
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            if (
                marker.get("signature") == signature
                and marker.get("model") == model_name
                and marker.get("maximum_chunks") == maximum_chunks
            ):
                stats["skipped_inputs"] += 1
                continue
        pending.append((path, vectors_path, chunks_path, marker_path, signature))

    if not pending:
        _write_report(config, "embed.json", stats)
        return stats

    os.environ.setdefault("USE_TF", "0")
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    import torch
    from sentence_transformers import SentenceTransformer

    if device and device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(
            "A CUDA device was requested, but this PyTorch installation is CPU-only. "
            "Use --device cpu or install a CUDA-enabled PyTorch build."
        )
    model = SentenceTransformer(model_name, device=device)
    model.max_seq_length = min(int(model.max_seq_length), config.chunk_max_tokens)

    for path, vectors_path, chunks_path, marker_path, signature in pending:
        source_id = path.parent.name
        rows = list(read_jsonl(path))
        if maximum_chunks is not None and len(rows) > maximum_chunks:
            # Evenly sample the shard for a representative pilot instead of
            # embedding only the first document's chunks.
            indices = np.linspace(0, len(rows) - 1, num=maximum_chunks, dtype=int)
            rows = [rows[int(index)] for index in indices]
        texts = [str(row["text"]) for row in rows]
        if texts:
            vectors = model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=len(texts) > batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
            ).astype(np.float16)
        else:
            vectors = np.empty((0, model.get_sentence_embedding_dimension()), dtype=np.float16)
        vectors_path.parent.mkdir(parents=True, exist_ok=True)
        vectors_tmp = vectors_path.with_name(vectors_path.name + ".part")
        chunks_tmp = chunks_path.with_name(chunks_path.name + ".part")
        marker_tmp = marker_path.with_name(marker_path.name + ".part")
        try:
            with vectors_tmp.open("wb") as handle:
                np.save(handle, vectors, allow_pickle=False)
            with gzip.open(chunks_tmp, "wt", encoding="utf-8", compresslevel=6) as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            marker = {
                "source_chunk_file": str(path),
                "signature": signature,
                "model": model_name,
                "dimensions": int(vectors.shape[1]),
                "vectors": int(vectors.shape[0]),
                "dtype": "float16",
                "maximum_chunks": maximum_chunks,
                "vectors_sha256": hashlib.sha256(vectors.tobytes()).hexdigest(),
            }
            marker_tmp.write_text(json.dumps(marker, indent=2), encoding="utf-8")
            os.replace(vectors_tmp, vectors_path)
            os.replace(chunks_tmp, chunks_path)
            os.replace(marker_tmp, marker_path)
        except Exception:
            vectors_tmp.unlink(missing_ok=True)
            chunks_tmp.unlink(missing_ok=True)
            marker_tmp.unlink(missing_ok=True)
            raise
        stats["inputs"] += 1
        stats["vectors"] += len(rows)
        print(f"embed {source_id}: {path.name} vectors={len(rows)}", flush=True)
    _write_report(config, "embed.json", stats)
    return stats


def build_indexes(config: PipelineConfig, index_type: str = "sq8") -> dict[str, Any]:
    """Build a compact dense FAISS index and an SQLite FTS5 sparse index."""

    import faiss

    vector_paths = sorted((config.output_root / "03_embeddings").glob("*/*.vectors.npy"))
    if not vector_paths:
        raise ValueError("No embedding shards found; run the embed stage first")
    first = np.load(vector_paths[0], mmap_mode="r", allow_pickle=False)
    if first.ndim != 2:
        raise ValueError(f"Expected a 2-D vector shard: {vector_paths[0]}")
    dimensions = int(first.shape[1])
    if index_type == "flat":
        index = faiss.IndexFlatIP(dimensions)
    elif index_type == "sq8":
        index = faiss.IndexScalarQuantizer(
            dimensions, faiss.ScalarQuantizer.QT_8bit, faiss.METRIC_INNER_PRODUCT
        )
        # Scalar quantization learns one range per dimension. A bounded sample
        # is sufficient and avoids loading the entire corpus into RAM.
        training_parts: list[np.ndarray] = []
        remaining = 100_000
        for path in vector_paths:
            if remaining <= 0:
                break
            values = np.load(path, mmap_mode="r", allow_pickle=False)
            take = min(len(values), remaining)
            if take:
                training_parts.append(np.asarray(values[:take], dtype=np.float32))
                remaining -= take
        training = np.concatenate(training_parts, axis=0)
        index.train(training)
    else:
        raise ValueError("index_type must be 'sq8' or 'flat'")

    output_dir = config.output_root / "04_indexes"
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "chunks.sqlite3"
    db_tmp = output_dir / "chunks.sqlite3.part"
    index_path = output_dir / "dense.faiss"
    index_tmp = output_dir / "dense.faiss.part"
    db_tmp.unlink(missing_ok=True)
    connection = sqlite3.connect(db_tmp)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.executescript(
        """
        CREATE TABLE chunks (
            row_id INTEGER PRIMARY KEY,
            chunk_id TEXT NOT NULL UNIQUE,
            document_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            section TEXT,
            text TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            url TEXT,
            license_id TEXT,
            metadata_json TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            title, section, text, content='chunks', content_rowid='row_id',
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TABLE dense_map (
            dense_id INTEGER PRIMARY KEY,
            chunk_row_id INTEGER NOT NULL UNIQUE REFERENCES chunks(row_id)
        );
        """
    )
    chunk_row_id = 0
    dense_id = 0
    try:
        # Sparse coverage is independent of dense coverage. This permits all
        # cleaned PubMed-scale chunks to remain BM25-searchable while BGE is
        # generated first for a smaller high-value source subset.
        chunk_paths = sorted(config.chunk_root.glob("*/*.jsonl.gz"))
        for chunk_path in chunk_paths:
            # PubMedQA is supervised/evaluation material, not retrieval
            # evidence. Keeping it out prevents answer leakage.
            if chunk_path.parent.name == "pubmedqa_labeled":
                continue
            records = []
            for row in read_jsonl(chunk_path):
                chunk_row_id += 1
                records.append(
                    (
                        chunk_row_id,
                        row["chunk_id"],
                        row["document_id"],
                        row["source_id"],
                        row["category"],
                        row["title"],
                        row.get("section"),
                        row["text"],
                        int(row["token_count"]),
                        row.get("url"),
                        row.get("license_id"),
                        json.dumps(row.get("metadata") or {}, ensure_ascii=False),
                    )
                )
            connection.executemany(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", records
            )
            connection.commit()
            print(f"sparse-index: {chunk_path.name} total={chunk_row_id}", flush=True)

        for vector_path in vector_paths:
            stem = vector_path.name.removesuffix(".vectors.npy")
            chunk_path = vector_path.with_name(f"{stem}.chunks.jsonl.gz")
            if not chunk_path.is_file():
                # Kaggle imports deliberately avoid duplicating tens of
                # gigabytes of chunk text beside the vectors. Their completion
                # marker points back to the immutable local chunk shard.
                marker_path = vector_path.with_name(f"{stem}.complete.json")
                if marker_path.is_file():
                    marker = json.loads(marker_path.read_text(encoding="utf-8"))
                    source_chunk_file = marker.get("source_chunk_file")
                    if source_chunk_file:
                        chunk_path = Path(source_chunk_file)
            if not chunk_path.is_file():
                raise ValueError(f"Chunk metadata is absent for vector shard: {vector_path}")
            vectors = np.asarray(np.load(vector_path, allow_pickle=False), dtype=np.float32)
            rows = list(read_jsonl(chunk_path))
            if len(rows) != len(vectors):
                raise ValueError(f"Vector/metadata count mismatch for {vector_path}")
            if vectors.size:
                index.add(vectors)
            mappings = []
            for row in rows:
                match = connection.execute(
                    "SELECT row_id FROM chunks WHERE chunk_id=?", (row["chunk_id"],)
                ).fetchone()
                if not match:
                    raise ValueError(f"Embedded chunk is absent from chunk store: {row['chunk_id']}")
                mappings.append((dense_id, int(match[0])))
                dense_id += 1
            connection.executemany("INSERT INTO dense_map VALUES (?, ?)", mappings)
            connection.commit()
            print(f"dense-index: {vector_path.name} total={dense_id}", flush=True)
        connection.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        connection.commit()
        connection.execute("PRAGMA optimize")
        connection.close()
        faiss.write_index(index, str(index_tmp))
        os.replace(index_tmp, index_path)
        os.replace(db_tmp, db_path)
    except Exception:
        connection.close()
        index_tmp.unlink(missing_ok=True)
        db_tmp.unlink(missing_ok=True)
        raise
    report = {
        "dense_vectors": dense_id,
        "sparse_chunks": chunk_row_id,
        "dimensions": dimensions,
        "index_type": index_type,
        "dense_index": str(index_path),
        "metadata_index": str(db_path),
    }
    _write_report(config, "index.json", report)
    return report


def hybrid_search(
    config: PipelineConfig,
    query: str,
    top_k: int = 10,
    candidate_k: int = 50,
    device: str | None = None,
) -> list[dict[str, Any]]:
    import faiss
    os.environ.setdefault("USE_TF", "0")
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    from sentence_transformers import SentenceTransformer

    index_path = config.output_root / "04_indexes" / "dense.faiss"
    db_path = config.output_root / "04_indexes" / "chunks.sqlite3"
    if not index_path.is_file() or not db_path.is_file():
        raise ValueError("Indexes not found; run the index stage first")
    model = SentenceTransformer(config.embedding_model, device=device)
    vector = model.encode(
        [QUERY_PREFIX + query], normalize_embeddings=True, convert_to_numpy=True
    ).astype(np.float32)
    index = faiss.read_index(str(index_path))
    _, dense_ids = index.search(vector, candidate_k)
    dense_rank: dict[int, int] = {}

    terms = re_terms(query)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    for rank, item in enumerate(dense_ids[0], 1):
        if item < 0:
            continue
        mapped = connection.execute(
            "SELECT chunk_row_id FROM dense_map WHERE dense_id=?", (int(item),)
        ).fetchone()
        if mapped:
            dense_rank[int(mapped[0])] = rank
    sparse_ids: list[int] = []
    if terms:
        match = " OR ".join(f'"{term}"' for term in terms)
        sparse_ids = [
            int(row[0])
            for row in connection.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
                (match, candidate_k),
            )
        ]
    sparse_rank = {item: rank for rank, item in enumerate(sparse_ids, 1)}
    candidates = set(dense_rank) | set(sparse_rank)
    scored = sorted(
        candidates,
        key=lambda item: (
            (1 / (60 + dense_rank[item]) if item in dense_rank else 0)
            + (1 / (60 + sparse_rank[item]) if item in sparse_rank else 0)
        ),
        reverse=True,
    )[:top_k]
    results: list[dict[str, Any]] = []
    for item in scored:
        row = connection.execute("SELECT * FROM chunks WHERE row_id=?", (item,)).fetchone()
        if row:
            value = dict(row)
            value["rrf_score"] = (
                (1 / (60 + dense_rank[item]) if item in dense_rank else 0)
                + (1 / (60 + sparse_rank[item]) if item in sparse_rank else 0)
            )
            value["dense_rank"] = dense_rank.get(item)
            value["sparse_rank"] = sparse_rank.get(item)
            results.append(value)
    connection.close()
    return results


def re_terms(query: str) -> list[str]:
    import re

    return list(dict.fromkeys(re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}", query)))
