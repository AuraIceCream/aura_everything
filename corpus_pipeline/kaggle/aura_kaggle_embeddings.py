#!/usr/bin/env python3
"""Prepare, run, and import resumable AURA-Bio embedding jobs on Kaggle.

The file is intentionally standalone: ``prepare`` copies it into the Kaggle
input dataset, where the same file provides ``benchmark`` and ``embed``. Local
``import`` reconstructs the pipeline's source-sharded vector layout without
copying chunk text into the embedding directory.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import io
import json
import multiprocessing
import os
import shutil
import sqlite3
import tarfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator


MODEL = "BAAI/bge-base-en-v1.5"
DIMENSIONS = 768
VECTOR_BYTES = DIMENSIONS * 2
QA_EXCLUDED = {"pubmedqa_labeled"}
PUBMED = {"pubmed_filtered"}
OPEN_CORE = {
    "gene_ontology",
    "pmc_oa_comm_xml",
    "reactome_summaries",
    "uniprot_sprot",
    "wikipedia_biology",
}


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _vector_digest(values: Any) -> str:
    digest = hashlib.sha256()
    for start in range(0, len(values), 65_536):
        digest.update(values[start : start + 65_536].tobytes(order="C"))
    return digest.hexdigest()


def _signature(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _source_counts(state_db: Path) -> dict[tuple[str, str], int]:
    connection = sqlite3.connect(state_db)
    try:
        rows = connection.execute(
            "SELECT output_path, records FROM processed_inputs WHERE stage=?", ("chunk",)
        )
        result: dict[tuple[str, str], int] = {}
        for output_path, records in rows:
            path = Path(output_path)
            result[(path.parent.name, path.name)] = int(records)
        return result
    finally:
        connection.close()


def _profile_sources(profile: str, available: set[str]) -> set[str]:
    retrieval = available - QA_EXCLUDED
    if profile == "open-core":
        return retrieval & OPEN_CORE
    if profile == "core":
        return retrieval - PUBMED
    if profile == "pubmed":
        return retrieval & PUBMED
    if profile == "full":
        return retrieval
    raise ValueError(f"Unknown profile: {profile}")


def _plan_rows(state_db: Path) -> tuple[dict[str, int], int]:
    counts = _source_counts(state_db)
    by_source: Counter[str] = Counter()
    for (source, _), records in counts.items():
        by_source[source] += records
    return dict(by_source), sum(by_source.values())


def plan(args: argparse.Namespace) -> dict[str, Any]:
    by_source, _ = _plan_rows(args.state_db)
    available = set(by_source)
    profiles: dict[str, Any] = {}
    for profile in ("open-core", "core", "pubmed", "full"):
        sources = _profile_sources(profile, available)
        chunks = sum(by_source[source] for source in sources)
        combined_rate = args.chunks_per_second * args.gpus
        profiles[profile] = {
            "sources": sorted(sources),
            "chunks": chunks,
            "fp16_vectors_gib": round(chunks * VECTOR_BYTES / 1024**3, 2),
            "sq8_index_gib": round(chunks * DIMENSIONS / 1024**3, 2),
            "eta_hours": round(chunks / combined_rate / 3600, 2),
        }
    result = {
        "assumed_chunks_per_second_per_gpu": args.chunks_per_second,
        "gpus": args.gpus,
        "profiles": profiles,
        "excluded_from_retrieval": sorted(QA_EXCLUDED),
    }
    print(json.dumps(result, indent=2))
    return result


class BundleWriter:
    def __init__(self, root: Path, maximum_bytes: int):
        self.root = root
        self.maximum_bytes = maximum_bytes
        self.index = -1
        self.size = 0
        self.members = 0
        self.handle: tarfile.TarFile | None = None
        self.name = ""
        self.bundle_summaries: list[dict[str, Any]] = []

    def _rotate(self) -> None:
        if self.handle is not None:
            self.handle.close()
            path = self.root / self.name
            self.bundle_summaries.append(
                {"file": self.name, "bytes": path.stat().st_size, "members": self.members}
            )
        self.index += 1
        self.name = f"bundle-{self.index:03d}.tar"
        self.handle = tarfile.open(self.root / self.name, "w")
        self.size = 0
        self.members = 0

    def add(self, path: Path, member_name: str) -> str:
        size = path.stat().st_size
        if self.handle is None or (self.members and self.size + size > self.maximum_bytes):
            self._rotate()
        assert self.handle is not None
        info = tarfile.TarInfo(member_name)
        info.size = size
        info.mtime = int(path.stat().st_mtime)
        with path.open("rb") as source:
            self.handle.addfile(info, source)
        self.size += size
        self.members += 1
        return self.name

    def close(self) -> list[dict[str, Any]]:
        if self.handle is not None:
            self.handle.close()
            path = self.root / self.name
            self.bundle_summaries.append(
                {"file": self.name, "bytes": path.stat().st_size, "members": self.members}
            )
            self.handle = None
        return self.bundle_summaries


def _split_gzip_rows(path: Path, scratch: Path, maximum_rows: int) -> Iterator[tuple[Path, int, int]]:
    """Yield temporary gzip segments as (path, original_start, count)."""

    scratch.mkdir(parents=True, exist_ok=True)
    start = 0
    segment_index = 0
    source = gzip.open(path, "rt", encoding="utf-8")
    try:
        while True:
            segment = scratch / f"segment-{segment_index:04d}.jsonl.gz"
            count = 0
            with gzip.open(segment, "wt", encoding="utf-8", compresslevel=1) as target:
                while count < maximum_rows:
                    line = source.readline()
                    if not line:
                        break
                    if line.strip():
                        target.write(line)
                        count += 1
            if not count:
                segment.unlink(missing_ok=True)
                break
            yield segment, start, count
            start += count
            segment_index += 1
    finally:
        source.close()


def _build_jobs(tasks: list[dict[str, Any]], maximum_chunks: int, profile: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    chunks = 0
    for task in tasks:
        if current and chunks + task["records"] > maximum_chunks:
            index = len(jobs)
            jobs.append(_job_record(profile, index, current, chunks))
            current = []
            chunks = 0
        current.append(task)
        chunks += task["records"]
    if current:
        jobs.append(_job_record(profile, len(jobs), current, chunks))
    return jobs


def _job_record(profile: str, index: int, tasks: list[dict[str, Any]], chunks: int) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for task in tasks:
        counts[task["source_id"]] += task["records"]
    return {
        "job_id": f"{profile}-{index:03d}",
        "index": index,
        "chunks": chunks,
        "estimated_vector_bytes": chunks * VECTOR_BYTES,
        "source_counts": dict(sorted(counts.items())),
        "tasks": tasks,
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    chunk_root = args.chunk_root.resolve()
    output = args.output.resolve()
    counts = _source_counts(args.state_db)
    available = {source for source, _ in counts}
    selected_sources = _profile_sources(args.profile, available)
    selected_paths = sorted(
        path
        for source in selected_sources
        for path in (chunk_root / source).glob("*.jsonl.gz")
    )
    if output.exists() and any(output.iterdir()):
        if not args.force:
            raise SystemExit(f"Output is not empty: {output}. Use --force to rebuild it.")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / ".scratch"
    bundle_writer = BundleWriter(output, int(args.bundle_gib * 1024**3))
    tasks: list[dict[str, Any]] = []
    try:
        for file_index, path in enumerate(selected_paths, 1):
            source = path.parent.name
            records = counts.get((source, path.name))
            if records is None:
                raise ValueError(f"No completed chunk record count in state DB for {path}")
            signature = _signature(path)
            relative = f"{source}/{path.name}"
            if records <= args.max_task_chunks:
                member = f"chunks/{relative}"
                bundle = bundle_writer.add(path, member)
                tasks.append(
                    {
                        "bundle": bundle,
                        "member": member,
                        "source_id": source,
                        "chunk_relpath": relative,
                        "original_start": 0,
                        "records": records,
                        "input_signature": signature,
                    }
                )
            else:
                split_total = 0
                split_root = scratch / source / path.stem
                for segment_path, original_start, count in _split_gzip_rows(
                    path, split_root, args.max_task_chunks
                ):
                    member = f"chunks/{source}/{path.name}.segment-{original_start:09d}.jsonl.gz"
                    bundle = bundle_writer.add(segment_path, member)
                    tasks.append(
                        {
                            "bundle": bundle,
                            "member": member,
                            "source_id": source,
                            "chunk_relpath": relative,
                            "original_start": original_start,
                            "records": count,
                            "input_signature": signature,
                        }
                    )
                    split_total += count
                    segment_path.unlink()
                if split_total != records:
                    raise ValueError(f"State DB says {records} rows but split read {split_total}: {path}")
            if file_index % 100 == 0 or file_index == len(selected_paths):
                print(f"prepare files={file_index}/{len(selected_paths)} tasks={len(tasks)}", flush=True)
    finally:
        bundles = bundle_writer.close()
        shutil.rmtree(scratch, ignore_errors=True)

    jobs = _build_jobs(tasks, args.job_chunks, args.profile)
    manifest = {
        "schema_version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "profile": args.profile,
        "model": args.model,
        "dimensions": DIMENSIONS,
        "dtype": "float16",
        "normalized": True,
        "selected_sources": sorted(selected_sources),
        "excluded_sources": sorted(available - selected_sources),
        "total_chunks": sum(task["records"] for task in tasks),
        "jobs": jobs,
        "bundles": bundles,
    }
    manifest_path = output / "embedding-manifest.json"
    _json_dump(manifest_path, manifest)
    shutil.copy2(Path(__file__), output / Path(__file__).name)
    if args.kaggle_username:
        _json_dump(
            output / "dataset-metadata.json",
            {
                "title": f"AURA Bio embedding input ({args.profile})",
                "id": f"{args.kaggle_username}/{args.dataset_slug}",
                "licenses": [{"name": "other"}],
            },
        )
    result = {
        "output": str(output),
        "profile": args.profile,
        "sources": sorted(selected_sources),
        "chunk_files": len(selected_paths),
        "tasks": len(tasks),
        "jobs": len(jobs),
        "chunks": manifest["total_chunks"],
        "input_gib": round(sum(item["bytes"] for item in bundles) / 1024**3, 2),
        "fp16_output_gib": round(manifest["total_chunks"] * VECTOR_BYTES / 1024**3, 2),
        "manifest_sha256": _sha256_file(manifest_path),
    }
    print(json.dumps(result, indent=2))
    return result


def _load_manifest(input_root: Path) -> tuple[Path, dict[str, Any]]:
    candidates = list(input_root.rglob("embedding-manifest.json"))
    if len(candidates) != 1:
        raise ValueError(f"Expected one embedding-manifest.json under {input_root}; found {len(candidates)}")
    path = candidates[0]
    return path, json.loads(path.read_text(encoding="utf-8"))


def _load_model(model_name: str, device: str) -> Any:
    os.environ.setdefault("USE_TF", "0")
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    import torch
    from sentence_transformers import SentenceTransformer

    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    model = SentenceTransformer(model_name, device=device)
    model.max_seq_length = 512
    if device.startswith("cuda"):
        model.half()
    return model


def _encode(model: Any, texts: list[str], batch_size: int) -> tuple[Any, int]:
    import torch

    active_batch = min(batch_size, len(texts))
    while True:
        try:
            values = model.encode(
                texts,
                batch_size=active_batch,
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            return values, active_batch
        except RuntimeError as exc:
            if "out of memory" not in str(exc).lower() or active_batch <= 1:
                raise
            active_batch = max(1, active_batch // 2)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print(f"CUDA OOM: retrying with batch_size={active_batch}", flush=True)


def _task_rows(input_root: Path, task: dict[str, Any], tar_cache: dict[str, tarfile.TarFile]) -> Iterator[dict[str, Any]]:
    bundle_name = task["bundle"]
    # Kaggle may automatically expand an uploaded ``bundle-000.tar`` into a
    # directory named ``bundle-000``. Support that mounted representation as
    # well as the original TAR so users never have to extract inputs manually.
    expanded_name = Path(bundle_name).stem if bundle_name.lower().endswith(".tar") else bundle_name
    expanded_matches = [
        path
        for path in input_root.rglob(expanded_name)
        if path.is_dir() and (path / task["member"]).is_file()
    ]
    if expanded_matches:
        if len(expanded_matches) != 1:
            raise ValueError(
                f"Expected one expanded {expanded_name} containing {task['member']} "
                f"under {input_root}; found {len(expanded_matches)}"
            )
        with gzip.open(expanded_matches[0] / task["member"], "rt", encoding="utf-8") as text:
            for line in text:
                if line.strip():
                    yield json.loads(line)
        return

    handle = tar_cache.get(bundle_name)
    if handle is None:
        matches = [path for path in input_root.rglob(bundle_name) if path.is_file()]
        if len(matches) != 1:
            raise ValueError(
                f"Expected either {bundle_name} or expanded directory {expanded_name} "
                f"under {input_root}; found neither. The attached Dataset version may not "
                "match embedding-manifest.json."
            )
        handle = tarfile.open(matches[0], "r")
        tar_cache[bundle_name] = handle
    member = handle.extractfile(task["member"])
    if member is None:
        raise ValueError(f"Missing tar member {task['member']} in {bundle_name}")
    with member, gzip.GzipFile(fileobj=member, mode="rb") as compressed:
        with io.TextIOWrapper(compressed, encoding="utf-8") as text:
            for line in text:
                if line.strip():
                    yield json.loads(line)


def benchmark(args: argparse.Namespace) -> dict[str, Any]:
    input_root = args.input_root.resolve()
    _, manifest = _load_manifest(input_root)
    model = _load_model(manifest["model"], args.device)
    texts: list[str] = []
    tar_cache: dict[str, tarfile.TarFile] = {}
    try:
        for task in manifest["jobs"][0]["tasks"]:
            for row in _task_rows(input_root, task, tar_cache):
                texts.append(str(row["text"]))
                if len(texts) >= args.chunks:
                    break
            if len(texts) >= args.chunks:
                break
    finally:
        for handle in tar_cache.values():
            handle.close()
    if len(texts) < 100:
        raise ValueError("Benchmark requires at least 100 chunks")
    warmup = min(32, len(texts))
    _encode(model, texts[:warmup], args.batch_size)
    started = time.perf_counter()
    _, used_batch = _encode(model, texts, args.batch_size)
    elapsed = time.perf_counter() - started
    rate = len(texts) / elapsed
    combined_rate = rate * args.gpus
    result = {
        "profile": manifest["profile"],
        "model": manifest["model"],
        "benchmark_chunks": len(texts),
        "seconds": round(elapsed, 2),
        "chunks_per_second_per_gpu": round(rate, 2),
        "assumed_parallel_gpus": args.gpus,
        "effective_batch_size": used_batch,
        "projected_hours": round(manifest["total_chunks"] / combined_rate / 3600, 2),
        "total_chunks": manifest["total_chunks"],
    }
    print(json.dumps(result, indent=2))
    return result


def _embed_job(
    input_root_text: str,
    output_root_text: str,
    job_index: int,
    device: str,
    batch_size: int,
) -> dict[str, Any]:
    import numpy as np

    input_root = Path(input_root_text)
    output_root = Path(output_root_text)
    manifest_path, manifest = _load_manifest(input_root)
    job = manifest["jobs"][job_index]
    output_dir = output_root / manifest["profile"]
    output_dir.mkdir(parents=True, exist_ok=True)
    vector_path = output_dir / f"{job['job_id']}.vectors.npy"
    marker_path = output_dir / f"{job['job_id']}.complete.json"
    if vector_path.is_file() and marker_path.is_file():
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if marker.get("manifest_sha256") == _sha256_file(manifest_path):
            print(f"skip completed {job['job_id']}", flush=True)
            return marker

    model = _load_model(manifest["model"], device)
    temporary = vector_path.with_name(vector_path.name + ".part")
    temporary.unlink(missing_ok=True)
    vectors = np.lib.format.open_memmap(
        temporary, mode="w+", dtype=np.float16, shape=(job["chunks"], manifest["dimensions"])
    )
    cursor = 0
    active_batch = batch_size
    segments: list[dict[str, Any]] = []
    tar_cache: dict[str, tarfile.TarFile] = {}
    started = time.perf_counter()
    try:
        for task in job["tasks"]:
            segment_start = cursor
            batch: list[str] = []
            read = 0
            for row in _task_rows(input_root, task, tar_cache):
                batch.append(str(row["text"]))
                read += 1
                if len(batch) >= active_batch:
                    encoded, active_batch = _encode(model, batch, active_batch)
                    vectors[cursor : cursor + len(batch)] = encoded.astype(np.float16)
                    cursor += len(batch)
                    batch.clear()
                    if cursor % 10_000 < active_batch:
                        elapsed = time.perf_counter() - started
                        rate = cursor / elapsed
                        eta = (job["chunks"] - cursor) / max(rate, 0.001) / 60
                        print(
                            f"{job['job_id']} {cursor:,}/{job['chunks']:,} "
                            f"rate={rate:.1f}/s eta={eta:.1f}m",
                            flush=True,
                        )
            if batch:
                encoded, active_batch = _encode(model, batch, active_batch)
                vectors[cursor : cursor + len(batch)] = encoded.astype(np.float16)
                cursor += len(batch)
            if read != task["records"]:
                raise ValueError(f"Expected {task['records']} rows but read {read}: {task['member']}")
            segments.append(
                {
                    "source_id": task["source_id"],
                    "chunk_relpath": task["chunk_relpath"],
                    "original_start": task["original_start"],
                    "count": read,
                    "output_offset": segment_start,
                    "input_signature": task["input_signature"],
                }
            )
        if cursor != job["chunks"]:
            raise ValueError(f"Expected {job['chunks']} total rows but embedded {cursor}")
        vectors.flush()
        digest = _vector_digest(vectors)
        del vectors
        os.replace(temporary, vector_path)
        marker = {
            "schema_version": 1,
            "profile": manifest["profile"],
            "job_id": job["job_id"],
            "job_index": job_index,
            "model": manifest["model"],
            "dimensions": manifest["dimensions"],
            "dtype": "float16",
            "normalized": True,
            "vectors": cursor,
            "vector_file": vector_path.name,
            "vectors_sha256": digest,
            "manifest_sha256": _sha256_file(manifest_path),
            "segments": segments,
            "device": device,
            "batch_size": active_batch,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        }
        _json_dump(marker_path, marker)
        print(json.dumps({key: marker[key] for key in ("job_id", "vectors", "elapsed_seconds", "device")}, indent=2))
        return marker
    except Exception:
        # ``vectors`` has already been deleted after a successful flush, so
        # marker-write failures must not be masked by an UnboundLocalError.
        if "vectors" in locals():
            try:
                vectors.flush()
            except Exception:
                pass
            del vectors
        temporary.unlink(missing_ok=True)
        raise
    finally:
        for handle in tar_cache.values():
            handle.close()


def embed_jobs(args: argparse.Namespace) -> list[dict[str, Any]]:
    input_root = args.input_root.resolve()
    output_root = args.output_root.resolve()
    _, manifest = _load_manifest(input_root)
    job_indices = list(range(args.job_start, min(args.job_start + args.job_count, len(manifest["jobs"]))))
    if not job_indices:
        raise ValueError("No jobs selected")
    parallel = args.parallel_jobs
    if parallel == 0:
        import torch

        parallel = max(1, min(torch.cuda.device_count(), len(job_indices)))
    if parallel <= 1:
        return [
            _embed_job(str(input_root), str(output_root), index, args.device, args.batch_size)
            for index in job_indices
        ]
    devices = [f"cuda:{index}" for index in range(parallel)]
    context = multiprocessing.get_context("spawn")
    results: list[dict[str, Any]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=parallel, mp_context=context) as executor:
        futures = {
            executor.submit(
                _embed_job,
                str(input_root),
                str(output_root),
                job_index,
                devices[position % len(devices)],
                args.batch_size,
            ): job_index
            for position, job_index in enumerate(job_indices)
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: item["job_index"])


def import_outputs(args: argparse.Namespace) -> dict[str, Any]:
    import numpy as np

    output_root = args.kaggle_output.resolve()
    chunk_root = args.chunk_root.resolve()
    embedding_root = args.embedding_root.resolve()
    markers = [json.loads(path.read_text(encoding="utf-8")) | {"_path": str(path)} for path in output_root.rglob("*.complete.json")]
    if not markers:
        raise ValueError(f"No Kaggle completion markers found under {output_root}")
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for marker in markers:
        vector_path = Path(marker["_path"]).with_name(marker["vector_file"])
        if not vector_path.is_file():
            raise ValueError(f"Missing vector file for marker: {vector_path}")
        marker["_vector_path"] = str(vector_path)
        for segment in marker["segments"]:
            grouped[segment["chunk_relpath"]].append((marker, segment))

    completed = skipped = vectors_total = 0
    for relative, parts in sorted(grouped.items()):
        source_path = chunk_root / Path(relative)
        if not source_path.is_file():
            raise ValueError(f"Local chunk shard is missing: {source_path}")
        parts.sort(key=lambda item: item[1]["original_start"])
        expected_start = 0
        for _, segment in parts:
            if segment["original_start"] != expected_start:
                raise ValueError(f"Non-contiguous vector segments for {relative} at {expected_start}")
            if segment["input_signature"] != _signature(source_path):
                raise ValueError(f"Chunk shard changed since Kaggle packaging: {source_path}")
            expected_start += segment["count"]
        source = source_path.parent.name
        stem = source_path.name.removesuffix(".jsonl.gz")
        target_dir = embedding_root / source
        target_dir.mkdir(parents=True, exist_ok=True)
        vector_target = target_dir / f"{stem}.vectors.npy"
        marker_target = target_dir / f"{stem}.complete.json"
        if vector_target.is_file() and marker_target.is_file():
            existing = json.loads(marker_target.read_text(encoding="utf-8"))
            if (
                existing.get("signature") == _signature(source_path)
                and existing.get("model") == markers[0]["model"]
                and existing.get("vectors") == expected_start
            ):
                skipped += 1
                vectors_total += expected_start
                continue
        temporary = vector_target.with_name(vector_target.name + ".part")
        temporary.unlink(missing_ok=True)
        target = np.lib.format.open_memmap(
            temporary,
            mode="w+",
            dtype=np.float16,
            shape=(expected_start, int(markers[0]["dimensions"])),
        )
        for marker, segment in parts:
            job_vectors = np.load(marker["_vector_path"], mmap_mode="r", allow_pickle=False)
            output_start = segment["output_offset"]
            output_end = output_start + segment["count"]
            local_start = segment["original_start"]
            target[local_start : local_start + segment["count"]] = job_vectors[output_start:output_end]
        target.flush()
        digest = _vector_digest(target)
        del target
        os.replace(temporary, vector_target)
        _json_dump(
            marker_target,
            {
                "source_chunk_file": str(source_path),
                "signature": _signature(source_path),
                "model": markers[0]["model"],
                "dimensions": int(markers[0]["dimensions"]),
                "vectors": expected_start,
                "dtype": "float16",
                "maximum_chunks": None,
                "vectors_sha256": digest,
                "imported_from_kaggle": True,
            },
        )
        completed += 1
        vectors_total += expected_start
        if completed % 100 == 0:
            print(f"import shards={completed} vectors={vectors_total:,}", flush=True)
    result = {
        "completed_shards": completed,
        "skipped_shards": skipped,
        "vectors": vectors_total,
        "embedding_root": str(embedding_root),
    }
    print(json.dumps(result, indent=2))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    plan_parser = commands.add_parser("plan", help="show profile counts, storage, and ETA")
    plan_parser.add_argument("--state-db", type=Path, default=Path("G:/aura_llm/AURA-Bio-Processed/state/pipeline.sqlite3"))
    plan_parser.add_argument("--chunks-per-second", type=float, default=100.0, help="measured per-GPU rate")
    plan_parser.add_argument("--gpus", type=int, default=1)

    prepare_parser = commands.add_parser("prepare", help="bundle completed chunks as a private Kaggle dataset")
    prepare_parser.add_argument("--profile", choices=("open-core", "core", "pubmed", "full"), default="open-core")
    prepare_parser.add_argument("--chunk-root", type=Path, default=Path("D:/aura_data/AURA-Bio-Processed/02_chunks"))
    prepare_parser.add_argument("--state-db", type=Path, default=Path("G:/aura_llm/AURA-Bio-Processed/state/pipeline.sqlite3"))
    prepare_parser.add_argument("--output", type=Path, required=True)
    prepare_parser.add_argument("--model", default=MODEL)
    prepare_parser.add_argument("--job-chunks", type=int, default=1_000_000)
    prepare_parser.add_argument("--max-task-chunks", type=int, default=250_000)
    prepare_parser.add_argument("--bundle-gib", type=float, default=4.0)
    prepare_parser.add_argument("--kaggle-username")
    prepare_parser.add_argument("--dataset-slug", default="aura-bio-embedding-input")
    prepare_parser.add_argument("--force", action="store_true")

    benchmark_parser = commands.add_parser("benchmark", help="measure Kaggle GPU throughput and project the profile ETA")
    benchmark_parser.add_argument("--input-root", type=Path, default=Path("/kaggle/input"))
    benchmark_parser.add_argument("--chunks", type=int, default=20_000)
    benchmark_parser.add_argument("--batch-size", type=int, default=48)
    benchmark_parser.add_argument("--device", default="cuda:0")
    benchmark_parser.add_argument("--gpus", type=int, default=1)

    embed_parser = commands.add_parser("embed", help="embed one or more bounded manifest jobs")
    embed_parser.add_argument("--input-root", type=Path, default=Path("/kaggle/input"))
    embed_parser.add_argument("--output-root", type=Path, default=Path("/kaggle/working/aura-embeddings"))
    embed_parser.add_argument("--job-start", type=int, default=0)
    embed_parser.add_argument("--job-count", type=int, default=1)
    embed_parser.add_argument("--parallel-jobs", type=int, default=0, help="0 detects available GPUs")
    embed_parser.add_argument("--batch-size", type=int, default=48)
    embed_parser.add_argument("--device", default="cuda:0")

    import_parser = commands.add_parser("import", help="reconstruct local source-sharded vectors from Kaggle outputs")
    import_parser.add_argument("--kaggle-output", type=Path, required=True)
    import_parser.add_argument("--chunk-root", type=Path, default=Path("D:/aura_data/AURA-Bio-Processed/02_chunks"))
    import_parser.add_argument("--embedding-root", type=Path, default=Path("G:/aura_llm/AURA-Bio-Processed/03_embeddings"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        plan(args)
    elif args.command == "prepare":
        prepare(args)
    elif args.command == "benchmark":
        benchmark(args)
    elif args.command == "embed":
        result = embed_jobs(args)
        print(json.dumps({"jobs": result}, indent=2))
    elif args.command == "import":
        import_outputs(args)
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
