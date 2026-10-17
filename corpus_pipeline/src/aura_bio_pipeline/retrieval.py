"""Storage-aware hybrid retrieval for dense core evidence and lexical PubMed.

The dense BGE corpus and the full PubMed lexical corpus intentionally remain
separate. PubMed is not silently treated as dense coverage when only the core
profile has been embedded on Kaggle.

Two hardware facts drive the design and are not incidental:

* The dense core is 10,394,250 x 768 vectors. An SQ8 index of that corpus is
  roughly 7.4 GiB, which does not fit in the free RAM of a 16 GiB laptop while
  anything else is running. Index construction therefore writes per-job blocks
  and merges them into on-disk inverted lists, and search memory-maps the
  result instead of loading it.
* A ``detail=full`` FTS5 index over all 26.4M filtered PubMed chunks projects
  to about 72 GiB, more than the free disk budget. ``detail=none`` measured
  byte-identical BM25 scores and ordering over 12 queries x top-50 while being
  23% smaller, so it is the PubMed default. It costs roughly 3x query time and
  gives up phrase/NEAR support, which the term-oriented PubMed channel does not
  use. Storing zlib text under a contentless FTS5 table was measured and
  rejected: ``content=''`` makes ``bm25()`` return -0.0 for every row.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from .embedding import QUERY_PREFIX, re_terms
from .jsonl import read_jsonl


CORE_SOURCES = frozenset(
    {
        "biolibretexts_catalog",
        "gene_ontology",
        "mesh_descriptors",
        "nlm_litarch_biology",
        "pmc_oa_comm_xml",
        "reactome_summaries",
        "uniprot_sprot",
        "wikipedia_biology",
    }
)
PUBMED_SOURCES = frozenset({"pubmed_filtered"})
QA_SOURCES = frozenset({"pubmedqa_labeled"})

RRF_K = 60
DENSE_WEIGHT = 1.0
CORE_SPARSE_WEIGHT = 0.65
PHRASE_WEIGHT = 2.0


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _chunks_for_sources(chunk_root: Path, source_ids: set[str]) -> list[Path]:
    paths: list[Path] = []
    for source_id in sorted(source_ids - QA_SOURCES):
        paths.extend(sorted((chunk_root / source_id).glob("*.jsonl.gz")))
    return paths


# ---------------------------------------------------------------------------
# Sparse (BM25 / FTS5)
# ---------------------------------------------------------------------------

_BASE_COLUMNS = """
    row_id INTEGER PRIMARY KEY,
    chunk_id TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    section TEXT,
    token_count INTEGER NOT NULL,
    url TEXT,
    license_id TEXT,
    metadata_json TEXT NOT NULL
"""

_TOKENIZER = "unicode61 remove_diacritics 2"


def _new_chunk_database(path: Path, compact: bool) -> sqlite3.Connection:
    """Create an empty BM25 store, optionally without positional detail.

    ``compact`` selects ``detail=none``: measured identical BM25 scores and
    ordering, 23% less disk, roughly 3x the query time, and no phrase or NEAR
    support. It is the right trade for PubMed and the wrong one for the core
    corpus, where phrase queries are cheap and useful.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=MEMORY")
    detail = "none" if compact else "full"
    connection.executescript(
        f"""
        CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE chunks ({_BASE_COLUMNS}, text TEXT NOT NULL);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            title, section, text, content='chunks', content_rowid='row_id',
            detail='{detail}', tokenize='{_TOKENIZER}'
        );
        CREATE INDEX chunks_source_id ON chunks(source_id);
        """
    )
    connection.execute("INSERT INTO index_meta VALUES ('detail', ?)", (detail,))
    return connection


def sparse_detail(connection: sqlite3.Connection) -> str:
    try:
        row = connection.execute("SELECT value FROM index_meta WHERE key='detail'").fetchone()
    except sqlite3.OperationalError:
        return "full"
    return row[0] if row else "full"


def build_sparse_index(
    chunk_root: Path,
    index_path: Path,
    source_ids: set[str],
    maximum_chunks: int | None = None,
    compact: bool = False,
    batch_rows: int = 20_000,
) -> dict[str, Any]:
    """Build an independent BM25/FTS5 store for the selected sources.

    ``maximum_chunks`` is intentionally a benchmark-only cap: it makes it
    possible to measure disk growth and query latency before committing to the
    full PubMed index.
    """

    sources = set(source_ids) - QA_SOURCES
    if not sources:
        raise ValueError("Select at least one non-QA source")
    temporary = index_path.with_name(index_path.name + ".part")
    temporary.unlink(missing_ok=True)
    connection = _new_chunk_database(temporary, compact)
    started = time.perf_counter()
    chunk_count = 0
    inserted = 0
    files = 0
    text_bytes = 0
    try:
        for chunk_path in _chunks_for_sources(chunk_root, sources):
            base: list[tuple[Any, ...]] = []
            for row in read_jsonl(chunk_path):
                chunk_count += 1
                text_bytes += len(row["text"])
                base.append(
                    (
                        chunk_count,
                        row["chunk_id"],
                        row["document_id"],
                        row["source_id"],
                        row["category"],
                        row["title"],
                        row.get("section"),
                        int(row["token_count"]),
                        row.get("url"),
                        row.get("license_id"),
                        json.dumps(row.get("metadata") or {}, ensure_ascii=False),
                        row["text"],
                    )
                )
                if len(base) >= batch_rows:
                    inserted += _flush_sparse(connection, base)
                    base.clear()
                if maximum_chunks is not None and chunk_count >= maximum_chunks:
                    break
            inserted += _flush_sparse(connection, base)
            files += 1
            print(f"sparse {chunk_path.name}: chunks={chunk_count:,}", flush=True)
            if maximum_chunks is not None and chunk_count >= maximum_chunks:
                break
        # The FTS index is populated inline during the flush, so there is no
        # multi-minute terminal 'rebuild' step to be killed at a session
        # boundary. Only the lightweight optimize remains.
        connection.execute("INSERT INTO index_meta VALUES ('chunks', ?)", (str(inserted),))
        connection.execute(
            "INSERT INTO index_meta VALUES ('sources', ?)", (json.dumps(sorted(sources)),)
        )
        connection.execute("PRAGMA optimize")
        connection.commit()
        connection.close()
        os.replace(temporary, index_path)
    except Exception:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    elapsed = time.perf_counter() - started
    size = index_path.stat().st_size
    return {
        "index": str(index_path),
        "detail": "none" if compact else "full",
        "sources": sorted(sources),
        "files": files,
        "chunks_read": chunk_count,
        "chunks_indexed": inserted,
        "duplicate_chunk_ids": chunk_count - inserted,
        "elapsed_seconds": round(elapsed, 2),
        "chunks_per_second": round(chunk_count / elapsed, 2) if elapsed else None,
        "gib": round(size / 1024**3, 3),
        "bytes_per_chunk": round(size / inserted, 1) if inserted else None,
        "text_gib": round(text_bytes / 1024**3, 3),
        "partial": maximum_chunks is not None,
    }


def _flush_sparse(connection: sqlite3.Connection, base: list[tuple[Any, ...]]) -> int:
    """Insert a batch and its FTS rows, skipping duplicate chunk ids.

    A chunk id is ``sha256(document_id, ordinal, text)``, so a collision means
    the identical document was chunked into two shards (for example a PMC
    article that appears in two fetch windows). Indexing it twice would just
    return the same passage twice, so the first copy wins.

    FTS rows are written here rather than by a terminal ``rebuild`` so a large
    build never has a long, kill-prone final step. Only rows that actually
    landed in ``chunks`` (not duplicate-skipped) are mirrored into the FTS,
    which the ``changes()`` check per row guarantees.
    """

    if not base:
        return 0
    inserted = 0
    for row in base:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row
        )
        if cursor.rowcount:
            # row = (row_id, chunk_id, document_id, source_id, category,
            #        title, section, token_count, url, license_id, meta, text)
            connection.execute(
                "INSERT INTO chunks_fts(rowid, title, section, text) VALUES (?,?,?,?)",
                (row[0], row[5], row[6], row[11]),
            )
            inserted += 1
    connection.commit()
    return inserted


def open_sparse(index_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


#: Rank inside the FTS table, then join ``chunks`` for the survivors only.
#:
#: The obvious form — ``FROM chunks_fts JOIN chunks ... ORDER BY bm25() LIMIT``
#: — makes SQLite materialise the joined row, including the multi-kilobyte
#: ``text`` column, for *every* match before sorting and discarding all but
#: ``LIMIT``. A broad query matches hundreds of thousands of chunks, and every
#: data partition on this machine lives on one SATA hard disk, so that read
#: dominated everything: retrieval measured 167 s mean / 209 s median per
#: question, larger than generation.
#:
#: Ranking first touches only the FTS index and hands the join 50 row ids.
#: Measured over real benchmark questions this is 57-560x faster
#: (bio-0250: 195.44 s -> 0.37 s) and returns byte-identical results, so it is
#: a pure execution-plan fix with no effect on ranking.
_SEARCH_SQL = """
    SELECT chunks.*, ranked.bm25_score
    FROM (
        SELECT rowid AS rid, bm25(chunks_fts) AS bm25_score
        FROM chunks_fts
        WHERE chunks_fts MATCH ?
        ORDER BY bm25(chunks_fts)
        LIMIT ?
    ) AS ranked
    JOIN chunks ON chunks.row_id = ranked.rid
    ORDER BY ranked.bm25_score
"""


#: Words that carry no retrieval signal. Interrogatives and task verbs are the
#: costly half: "Explain why classification systems change over time" ANDs
#: "explain", "why", "over" and "time" against the corpus, which favours long
#: rambling documents that happen to contain all of them over documents actually
#: about classification. Measured over 60 random benchmark questions, dropping
#: them raised the share of required concepts present in the retrieved passages
#: from 0.902 to 0.932.
_QUERY_NOISE = frozenset(
    """
    a an the is are was were be been being am do does did doing have has had having
    of in on at to for from by with without and or but if then than that this these
    those it its as into over under about above below between within during after before
    while because however therefore although though such some any all each both more most
    other another there their they them his her our your you we i he she
    what why how when where which who whom whose can could should would may might must
    will shall explain describe state list give define discuss compare contrast outline
    name mention identify true accurate correct sure also very just only own same too
    """.split()
)


def query_terms(query: str) -> list[str]:
    """Content terms for BM25, falling back to everything if nothing survives.

    A query of pure function words ("what is it") would otherwise search for
    nothing at all, so the unfiltered terms are kept as a floor.
    """

    terms = re_terms(query)
    kept = [term for term in terms if term.lower() not in _QUERY_NOISE and len(term) > 2]
    return kept or terms


def sparse_search(
    index: Path | sqlite3.Connection,
    query: str,
    candidate_k: int = 50,
    mode: str = "auto",
) -> list[dict[str, Any]]:
    """BM25 search, conjunctive first.

    ``ORDER BY bm25()`` has to score every matching row, so a plain OR of all
    query terms degrades badly once a corpus reaches PubMed scale: a single
    common term such as "cell" drags in millions of rows. ``auto`` runs the
    conjunctive query first and only relaxes to OR when AND is too selective,
    which is also the semantics the exact-term PubMed channel wants.
    """

    terms = query_terms(query)
    if not terms:
        return []
    owned = isinstance(index, Path)
    connection = open_sparse(index) if owned else index
    try:
        quoted = [f'"{term}"' for term in terms]
        attempts: list[str] = []
        if mode in ("auto", "and") and len(quoted) > 1:
            attempts.append(" AND ".join(quoted))
        if mode in ("auto", "or") or len(quoted) == 1:
            attempts.append(" OR ".join(quoted))
        rows: list[sqlite3.Row] = []
        for match in attempts:
            rows = connection.execute(_SEARCH_SQL, (match, candidate_k)).fetchall()
            if len(rows) >= candidate_k or mode != "auto":
                break
        return [dict(row) for row in rows]
    finally:
        if owned:
            connection.close()


def phrase_search(
    connection: sqlite3.Connection, query: str, candidate_k: int = 8
) -> list[dict[str, Any]]:
    """Find adjacent query terms that identify a core source title."""

    terms = re_terms(query)
    phrases: list[str] = []
    for left, right in zip(terms, terms[1:]):
        if (
            len(left) > 2 and len(right) > 2
            and left.lower() not in _QUERY_NOISE
            and right.lower() not in _QUERY_NOISE
        ):
            phrase = f"{left.lower()} {right.lower()}"
            if phrase not in phrases:
                phrases.append(phrase)
    if not phrases:
        return []
    selected = phrases[:3]
    match = " OR ".join(f'title:"{phrase}"' for phrase in selected)
    rows = connection.execute(_SEARCH_SQL, (match, max(candidate_k * 4, 32))).fetchall()
    exact_rows = [
        dict(row) for row in rows
        if " ".join(re_terms((row["title"] or "").split(" (", 1)[0])).lower() in selected
    ]

    asks_definition = bool(
        re.match(r"\s*(?:what\s+(?:is|are)|define|definition|meaning)\b", query, re.I)
    )

    def section_priority(row: dict[str, Any]) -> tuple[int, int, float]:
        section = row.get("section") or ""
        section_terms = set(query_terms(section))
        query_overlap = len(section_terms & set(query_terms(query)))
        overview = section.strip().casefold() in {
            "introduction", "overview", "definition", "summary", "abstract"
        }
        return (
            0 if asks_definition and overview else 1,
            -query_overlap,
            float(row["bm25_score"]),
        )

    exact_rows.sort(key=section_priority)
    per_title: dict[tuple[str, str], int] = {}
    results: list[dict[str, Any]] = []
    for row in exact_rows:
        key = (
            row.get("source_id", ""),
            " ".join(re_terms((row.get("title") or "").split(" (", 1)[0])).lower(),
        )
        if per_title.get(key, 0) >= 2:
            continue
        per_title[key] = per_title.get(key, 0) + 1
        results.append(row)
        if len(results) >= candidate_k:
            break
    return results


def chunks_in_documents(
    index: sqlite3.Connection, document_ids: list[str], limit_per_document: int = 6
) -> dict[str, list[dict[str, Any]]]:
    """Fetch chunks belonging to whole documents, for hierarchical retrieval.

    SRS 10.4 wants Level 3 to select relevant sections and then pull detailed
    chunks. Once fusion has identified which documents matter, this returns
    their neighbouring passages so the answer sees continuous context instead
    of isolated fragments.
    """

    if not document_ids:
        return {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for document_id in document_ids:
        rows = index.execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY row_id LIMIT ?",
            (document_id, limit_per_document),
        ).fetchall()
        if rows:
            grouped[document_id] = [dict(row) for row in rows]
    return grouped


def chunks_by_id(index: sqlite3.Connection, chunk_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Resolve dense hits back to full evidence rows in one round trip."""

    if not chunk_ids:
        return {}
    placeholders = ",".join("?" * len(chunk_ids))
    rows = index.execute(
        f"SELECT * FROM chunks WHERE chunk_id IN ({placeholders})", chunk_ids
    ).fetchall()
    return {row["chunk_id"]: dict(row) for row in rows}


def benchmark_sparse(
    index_path: Path, query: str, repeats: int = 5, mode: str = "auto"
) -> dict[str, Any]:
    connection = open_sparse(index_path)
    try:
        detail = sparse_detail(connection)
        chunks = connection.execute(
            "SELECT value FROM index_meta WHERE key='chunks'"
        ).fetchone()
        timings = []
        hits = 0
        for _ in range(repeats):
            started = time.perf_counter()
            rows = sparse_search(connection, query, mode=mode)
            timings.append(time.perf_counter() - started)
            hits = len(rows)
    finally:
        connection.close()
    return {
        "index": str(index_path),
        "detail": detail,
        "indexed_chunks": int(chunks[0]) if chunks else None,
        "query": query,
        "mode": mode,
        "hits": hits,
        "repeats": repeats,
        "median_ms": round(sorted(timings)[len(timings) // 2] * 1000, 2),
        "min_ms": round(min(timings) * 1000, 2),
    }


# ---------------------------------------------------------------------------
# Dense (FAISS)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EmbeddingJob:
    """One atomic Kaggle GPU output: vectors plus their chunk-range mapping."""

    job_index: int
    vectors: int
    vector_path: Path
    dimensions: int
    model: str
    segments: tuple[dict[str, Any], ...]
    dense_offset: int


def load_embedding_jobs(job_root: Path) -> list[EmbeddingJob]:
    """Read extracted Kaggle job markers and verify they form a complete run.

    This reads the downloaded job layout directly. Running the importer first
    would rewrite the same 14.9 GiB into a per-source layout for no retrieval
    benefit, which the available disk does not justify.
    """

    markers = sorted(job_root.rglob("*.complete.json"))
    if not markers:
        raise ValueError(f"No embedding job markers found under {job_root}")
    raw: list[dict[str, Any]] = []
    for path in markers:
        marker = json.loads(path.read_text(encoding="utf-8"))
        vector_path = path.with_name(marker["vector_file"])
        if not vector_path.is_file():
            raise ValueError(f"Missing vector file for marker: {vector_path}")
        marker["_vector_path"] = vector_path
        raw.append(marker)
    raw.sort(key=lambda item: int(item["job_index"]))
    indexes = [int(item["job_index"]) for item in raw]
    if indexes != list(range(len(indexes))):
        missing = sorted(set(range(max(indexes) + 1)) - set(indexes))
        raise ValueError(f"Embedding run is incomplete; missing job_index values: {missing}")
    models = {item["model"] for item in raw}
    dimensions = {int(item["dimensions"]) for item in raw}
    manifests = {item.get("manifest_sha256") for item in raw}
    if len(models) != 1 or len(dimensions) != 1 or len(manifests) != 1:
        raise ValueError(
            f"Jobs disagree on model/dimensions/manifest: {models} {dimensions} {manifests}"
        )
    jobs: list[EmbeddingJob] = []
    offset = 0
    for item in raw:
        jobs.append(
            EmbeddingJob(
                job_index=int(item["job_index"]),
                vectors=int(item["vectors"]),
                vector_path=item["_vector_path"],
                dimensions=int(item["dimensions"]),
                model=item["model"],
                segments=tuple(item["segments"]),
                dense_offset=offset,
            )
        )
        offset += int(item["vectors"])
    return jobs


def _resumable_map(path: Path) -> bool:
    """Every mapped id must be attributable to a recorded shard.

    A partial file written before resume existed, or by a run killed between
    the insert and the progress row, would otherwise re-insert ids it already
    holds and fail on the primary key.
    """

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "dense_map" not in tables:
            return False
        rows = connection.execute("SELECT count(*) FROM dense_map").fetchone()[0]
        if "map_progress" not in tables:
            return rows == 0
        recorded = connection.execute("SELECT coalesce(sum(ids), 0) FROM map_progress").fetchone()[0]
        return int(recorded) == int(rows)
    except sqlite3.DatabaseError:
        return False
    finally:
        connection.close()


def _completed_map_size(map_path: Path) -> int | None:
    """Row count of a finished map, or None if it is absent or still partial.

    A finished map has its ``map_progress`` scratch table dropped, so its
    presence marks an interrupted run whose rows must not be trusted wholesale.
    """

    if not map_path.is_file():
        return None
    connection = sqlite3.connect(f"file:{map_path}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "dense_map" not in tables or "map_progress" in tables:
            return None
        return int(connection.execute("SELECT count(*) FROM dense_map").fetchone()[0])
    except sqlite3.DatabaseError:
        return None
    finally:
        connection.close()


def _write_dense_map(
    jobs: list[EmbeddingJob], chunk_root: Path, map_path: Path
) -> dict[str, Any]:
    """Map every dense id to its chunk id by reading each shard exactly once.

    Segments of one shard are spread across jobs, so the naive per-segment read
    would decompress the 707 MiB UniProt shard 22 times.
    """

    grouped: dict[str, list[tuple[EmbeddingJob, dict[str, Any]]]] = {}
    for job in jobs:
        for segment in job.segments:
            grouped.setdefault(segment["chunk_relpath"], []).append((job, segment))

    map_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = map_path.with_name(map_path.name + ".part")
    # Mapping 9,939 shards takes long enough that an interrupted run must not
    # start over, so progress is committed per shard and resumed here.
    if temporary.exists() and not _resumable_map(temporary):
        print("dense map: discarding an unusable partial file", flush=True)
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    # Not journal_mode=OFF: resume depends on each shard's commit being atomic
    # if the process is killed. synchronous=OFF keeps that cheap.
    connection.execute("PRAGMA synchronous=OFF")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS dense_map (dense_id INTEGER PRIMARY KEY, chunk_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS map_progress (
            chunk_relpath TEXT PRIMARY KEY, ids INTEGER NOT NULL, uncovered INTEGER NOT NULL
        );
        """
    )
    done = {
        row[0]: (int(row[1]), int(row[2]))
        for row in connection.execute("SELECT chunk_relpath, ids, uncovered FROM map_progress")
    }
    mapped = sum(ids for ids, _ in done.values())
    uncovered = sum(value for _, value in done.values())
    shards = len(done)
    if done:
        print(f"dense map resuming: shards={shards:,} ids={mapped:,}", flush=True)
    try:
        for relative, parts in sorted(grouped.items()):
            if relative in done:
                continue
            shard = chunk_root / Path(relative)
            if not shard.is_file():
                raise ValueError(f"Local chunk shard is missing: {shard}")
            parts.sort(key=lambda item: int(item[1]["original_start"]))
            expected = 0
            for _, segment in parts:
                if int(segment["original_start"]) != expected:
                    raise ValueError(
                        f"Non-contiguous embedding segments for {relative} at {expected}"
                    )
                expected += int(segment["count"])
            rows: list[tuple[int, str]] = []
            cursor = 0
            iterator = read_jsonl(shard)
            for job, segment in parts:
                start = int(segment["original_start"])
                count = int(segment["count"])
                base = job.dense_offset + int(segment["output_offset"])
                while cursor < start:
                    next(iterator)
                    cursor += 1
                for offset in range(count):
                    rows.append((base + offset, next(iterator)["chunk_id"]))
                    cursor += 1
            leftover = sum(1 for _ in iterator)
            connection.executemany("INSERT INTO dense_map VALUES (?, ?)", rows)
            connection.execute(
                "INSERT INTO map_progress VALUES (?, ?, ?)", (relative, len(rows), leftover)
            )
            connection.commit()
            uncovered += leftover
            mapped += len(rows)
            shards += 1
            if shards % 500 == 0:
                print(f"dense map shards={shards:,} ids={mapped:,}", flush=True)
        connection.execute("DROP TABLE map_progress")
        connection.commit()
        connection.close()
        os.replace(temporary, map_path)
    except Exception:
        # The .part file is deliberately kept so the next run resumes.
        connection.close()
        raise
    return {"shards": shards, "mapped": mapped, "unembedded_chunks": uncovered}


def _pq_subquantizers(dimensions: int) -> int:
    """Bytes per vector under PQ: aim for 8 dimensions per 8-bit subquantizer."""

    if dimensions < 64:
        return dimensions
    for candidate in range(dimensions // 8, 0, -1):
        if dimensions % candidate == 0:
            return candidate
    return 1


def _factory_string(index_type: str, nlist: int, dimensions: int) -> str:
    if index_type == "ivf-pq":
        return f"IVF{nlist},PQ{_pq_subquantizers(dimensions)}x8"
    if index_type == "ivf-sq8":
        return f"IVF{nlist},SQ8"
    if index_type == "sq8":
        return "SQ8"
    if index_type == "flat":
        return "Flat"
    raise ValueError("index_type must be 'ivf-pq', 'ivf-sq8', 'sq8', or 'flat'")


@contextmanager
def _open_vectors(path: Path) -> Iterator[np.ndarray]:
    """Memory-map a vector shard and release the handle deterministically.

    Windows keeps the file locked for as long as the mapping is open, so
    relying on garbage collection would leave job shards undeletable.
    """

    values = np.load(path, mmap_mode="r", allow_pickle=False)
    try:
        yield values
    finally:
        handle = getattr(values, "_mmap", None)
        if handle is not None:
            handle.close()


def _training_sample(jobs: list[EmbeddingJob], wanted: int) -> np.ndarray:
    """Sample evenly across jobs so IVF centroids see every source."""

    per_job = max(1, wanted // len(jobs))
    parts: list[np.ndarray] = []
    for job in jobs:
        with _open_vectors(job.vector_path) as values:
            take = min(len(values), per_job)
            step = max(1, len(values) // take)
            parts.append(np.asarray(values[: take * step : step], dtype=np.float32))
    return np.concatenate(parts, axis=0)


def build_dense_index_from_jobs(
    job_root: Path,
    chunk_root: Path,
    index_root: Path,
    index_type: str = "ivf-pq",
    training_vectors: int = 300_000,
    batch_vectors: int = 32_768,
    nlist: int | None = None,
    nprobe: int = 32,
) -> dict[str, Any]:
    """Build a FAISS index in one pass straight from Kaggle job shards.

    The default is ``ivf-pq`` for a hard hardware reason: this FAISS build's
    ``IO_FLAG_MMAP`` cannot read IVF indexes at all, so an index must fit in RAM
    to be served. An SQ8 core index is ~7.6 GiB; a PQ index of the same corpus
    is roughly 1 GiB, which loads comfortably beside the embedder and reranker
    on a 16 GiB laptop. The on-disk block-merge approach was removed because it
    depends on the same broken mmap path.

    Vectors are added in job order and, within a job, in vector order, so a
    single sequential ``add`` numbers them 0..N-1 exactly as ``dense_map``
    records. No explicit ids are needed, which also keeps flat indexes (whose
    base type rejects ``add_with_ids``) on the same code path.
    """

    import faiss

    jobs = load_embedding_jobs(job_root)
    dimensions = jobs[0].dimensions
    total_vectors = sum(job.vectors for job in jobs)
    index_root.mkdir(parents=True, exist_ok=True)
    index_path = index_root / "core-dense.faiss"
    map_path = index_root / "core-dense-map.sqlite3"

    started = time.perf_counter()
    existing = _completed_map_size(map_path)
    if existing == total_vectors:
        print(f"dense map: reusing complete map ({existing:,} ids)", flush=True)
        mapping = {"shards": None, "mapped": existing, "unembedded_chunks": None}
    else:
        mapping = _write_dense_map(jobs, chunk_root, map_path)
    if mapping["mapped"] != total_vectors:
        raise ValueError(f"Mapped {mapping['mapped']:,} chunk ids for {total_vectors:,} vectors")
    map_seconds = time.perf_counter() - started

    is_ivf = index_type.startswith("ivf")
    if is_ivf:
        nlist = nlist or min(4096, max(256, int(total_vectors**0.5)))
        if total_vectors < nlist:
            raise ValueError(f"nlist ({nlist}) cannot exceed vector count ({total_vectors})")

    index = faiss.index_factory(
        dimensions, _factory_string(index_type, nlist or 0, dimensions), faiss.METRIC_INNER_PRODUCT
    )
    started = time.perf_counter()
    if not index.is_trained:
        index.train(_training_sample(jobs, max(training_vectors, (nlist or 0) * 50)))
    train_seconds = time.perf_counter() - started

    index_tmp = index_path.with_name(index_path.name + ".part")
    index_tmp.unlink(missing_ok=True)
    started = time.perf_counter()
    try:
        added = 0
        for job in jobs:
            added += _add_job(index, job, batch_vectors)
            print(f"dense add job {job.job_index}: vectors={added:,}", flush=True)
        if index.ntotal != total_vectors:
            raise ValueError(f"Added {index.ntotal:,} vectors, expected {total_vectors:,}")
        if is_ivf:
            index.nprobe = min(nprobe, int(nlist or 1))
        faiss.write_index(index, str(index_tmp))
        os.replace(index_tmp, index_path)
    except Exception:
        index_tmp.unlink(missing_ok=True)
        raise
    add_seconds = time.perf_counter() - started

    manifest = {
        "schema_version": 3,
        "job_root": str(job_root),
        "jobs": len(jobs),
        "vectors": total_vectors,
        "dimensions": dimensions,
        "model": jobs[0].model,
        "index_type": index_type,
        "nlist": nlist if is_ivf else None,
        "nprobe": min(nprobe, int(nlist or 1)) if is_ivf else None,
        "dense_index": str(index_path),
        "dense_map": str(map_path),
        "map_seconds": round(map_seconds, 2),
        "train_seconds": round(train_seconds, 2),
        "add_seconds": round(add_seconds, 2),
    } | mapping
    _atomic_json(index_root / "core-dense.manifest.json", manifest)
    return manifest | {
        "index_gib": round(index_path.stat().st_size / 1024**3, 3),
        "map_gib": round(map_path.stat().st_size / 1024**3, 3),
    }


def _add_job(index: Any, job: EmbeddingJob, batch_vectors: int) -> int:
    """Add one job in float32 batches; a whole 1M-vector cast would not fit."""

    with _open_vectors(job.vector_path) as values:
        if values.shape[0] != job.vectors:
            raise ValueError(
                f"{job.vector_path.name} holds {values.shape[0]:,} vectors, "
                f"marker claims {job.vectors:,}"
            )
        for offset in range(0, len(values), batch_vectors):
            index.add(np.asarray(values[offset : offset + batch_vectors], dtype=np.float32))
    return job.vectors


def write_retrieval_manifest(index_root: Path, **artifacts: Path | None) -> dict[str, Any]:
    """Record exactly which dense and lexical coverage a deployment has."""

    result: dict[str, Any] = {
        name: str(path) if path and path.is_file() else None for name, path in artifacts.items()
    }
    result["schema_version"] = 2
    _atomic_json(index_root / "retrieval.manifest.json", result)
    return result


# ---------------------------------------------------------------------------
# Hybrid search
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Evidence:
    """One retrieved chunk with the provenance of how it was found."""

    chunk_id: str
    source_id: str
    title: str
    section: str | None
    text: str
    url: str | None
    license_id: str | None
    channel: str
    rrf_score: float
    #: The parent document, which hierarchical retrieval groups and expands on.
    document_id: str = ""
    dense_rank: int | None = None
    core_bm25_rank: int | None = None
    pubmed_bm25_rank: int | None = None
    phrase_bm25_rank: int | None = None
    rerank_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "source_id": self.source_id,
            "title": self.title,
            "section": self.section,
            "text": self.text,
            "url": self.url,
            "license_id": self.license_id,
            "channel": self.channel,
            "rrf_score": round(self.rrf_score, 6),
            "dense_rank": self.dense_rank,
            "core_bm25_rank": self.core_bm25_rank,
            "pubmed_bm25_rank": self.pubmed_bm25_rank,
            "phrase_bm25_rank": self.phrase_bm25_rank,
            "rerank_score": None if self.rerank_score is None else round(self.rerank_score, 4),
        }


class HybridSearcher:
    """Loads every index once and answers many queries.

    The previous per-call implementation re-read the FAISS index and rebuilt
    the SentenceTransformer for every query, which is unusable interactively
    once the dense index reaches gigabyte scale.
    """

    def __init__(
        self,
        index_root: Path,
        device: str | None = None,
        model_name: str = "BAAI/bge-base-en-v1.5",
        nprobe: int | None = None,
        dense_enabled: bool = True,
        phrase_enabled: bool = False,
    ) -> None:
        manifest_path = index_root / "retrieval.manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"No retrieval manifest at {manifest_path}; build indexes first")
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.index_root = index_root
        self.device = device
        self.model_name = model_name
        self._nprobe = nprobe
        # The dense index (~1 GiB) plus the BGE encoder need several GiB of RAM
        # to co-reside. On a memory-constrained host, disabling dense keeps the
        # searcher to the instant BM25 channels rather than paging to a halt.
        self.dense_enabled = dense_enabled
        self.phrase_enabled = phrase_enabled
        self._model: Any = None
        self._dense: Any = None
        self._dense_map: sqlite3.Connection | None = None

        core = self.manifest.get("core_sparse")
        if not core or not Path(core).is_file():
            raise ValueError("A core sparse index is required to resolve dense evidence")
        self.core = open_sparse(Path(core))
        pubmed = self.manifest.get("pubmed_sparse")
        self.pubmed = open_sparse(Path(pubmed)) if pubmed and Path(pubmed).is_file() else None

    # -- lazy heavy resources -------------------------------------------------

    @property
    def dense(self) -> Any | None:
        if not self.dense_enabled:
            return None
        if self._dense is None:
            path = self.manifest.get("dense_index")
            if not path or not Path(path).is_file():
                return None
            import faiss

            # IO_FLAG_MMAP is deliberately not used: this FAISS build cannot
            # mmap an IVF index, and the PQ core index is ~1 GiB so a normal
            # load into RAM is both correct and fast.
            self._dense = faiss.read_index(str(path))
            if self._nprobe is not None and hasattr(self._dense, "nprobe"):
                self._dense.nprobe = self._nprobe
        return self._dense

    @property
    def dense_map(self) -> sqlite3.Connection | None:
        if self._dense_map is None:
            path = self.manifest.get("dense_map")
            if not path or not Path(path).is_file():
                return None
            self._dense_map = sqlite3.connect(
                f"file:{path}?mode=ro", uri=True, check_same_thread=False
            )
        return self._dense_map

    @property
    def model(self) -> Any:
        if self._model is None:
            os.environ.setdefault("USE_TF", "0")
            os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def close(self) -> None:
        self.core.close()
        if self.pubmed is not None:
            self.pubmed.close()
        if self._dense_map is not None:
            self._dense_map.close()

    def __enter__(self) -> HybridSearcher:
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()

    # -- channels -------------------------------------------------------------

    def encode(self, query: str) -> np.ndarray:
        return self.model.encode(
            [QUERY_PREFIX + query], normalize_embeddings=True, convert_to_numpy=True
        ).astype(np.float32)

    def _dense_candidates(self, query: str, candidate_k: int) -> list[tuple[str, int]]:
        index = self.dense
        mapping = self.dense_map
        if index is None or mapping is None:
            return []
        _, dense_ids = index.search(self.encode(query), candidate_k)
        wanted = [int(value) for value in dense_ids[0] if value >= 0]
        if not wanted:
            return []
        placeholders = ",".join("?" * len(wanted))
        rows = mapping.execute(
            f"SELECT dense_id, chunk_id FROM dense_map WHERE dense_id IN ({placeholders})", wanted
        ).fetchall()
        by_dense_id = {int(dense_id): chunk_id for dense_id, chunk_id in rows}
        return [
            (by_dense_id[value], rank)
            for rank, value in enumerate(wanted, 1)
            if value in by_dense_id
        ]

    def search(
        self,
        query: str,
        top_k: int = 10,
        candidate_k: int = 50,
        pubmed_weight: float = 0.85,
        use_dense: bool = True,
    ) -> list[Evidence]:
        """Reciprocal Rank Fusion over dense, core BM25, and PubMed BM25."""

        pooled: dict[str, dict[str, Any]] = {}

        def register(row: dict[str, Any], channel: str, key: str, rank: int, weight: float) -> None:
            item = pooled.setdefault(
                row["chunk_id"],
                {"row": row, "score": 0.0, "channels": set(), "dense_rank": None,
                 "core_bm25_rank": None, "pubmed_bm25_rank": None,
                 "phrase_bm25_rank": None},
            )
            item["score"] += weight / (RRF_K + rank)
            item["channels"].add(channel)
            item[key] = rank

        for rank, row in enumerate(sparse_search(self.core, query, candidate_k), 1):
            register(row, "core_bm25", "core_bm25_rank", rank, CORE_SPARSE_WEIGHT)
        if self.phrase_enabled:
            for rank, row in enumerate(phrase_search(self.core, query), 1):
                register(row, "phrase_bm25", "phrase_bm25_rank", rank, PHRASE_WEIGHT)
        if self.pubmed is not None:
            for rank, row in enumerate(sparse_search(self.pubmed, query, candidate_k), 1):
                register(row, "pubmed_bm25", "pubmed_bm25_rank", rank, pubmed_weight)
        if use_dense:
            dense_hits = self._dense_candidates(query, candidate_k)
            resolved = chunks_by_id(self.core, [chunk_id for chunk_id, _ in dense_hits])
            for chunk_id, rank in dense_hits:
                row = resolved.get(chunk_id)
                if row is not None:
                    register(row, "dense", "dense_rank", rank, DENSE_WEIGHT)

        ranked = sorted(pooled.values(), key=lambda item: item["score"], reverse=True)[:top_k]
        return [
            Evidence(
                chunk_id=item["row"]["chunk_id"],
                document_id=item["row"].get("document_id", ""),
                source_id=item["row"]["source_id"],
                title=item["row"]["title"],
                section=item["row"].get("section"),
                text=item["row"]["text"],
                url=item["row"].get("url"),
                license_id=item["row"].get("license_id"),
                channel="+".join(sorted(item["channels"])),
                rrf_score=item["score"],
                dense_rank=item["dense_rank"],
                core_bm25_rank=item["core_bm25_rank"],
                pubmed_bm25_rank=item["pubmed_bm25_rank"],
                phrase_bm25_rank=item["phrase_bm25_rank"],
            )
            for item in ranked
        ]


def hybrid_search(
    index_root: Path,
    query: str,
    top_k: int = 10,
    candidate_k: int = 50,
    pubmed_weight: float = 0.85,
    device: str | None = None,
) -> list[dict[str, Any]]:
    """One-shot convenience wrapper; prefer HybridSearcher for repeated queries."""

    with HybridSearcher(index_root, device=device) as searcher:
        return [item.as_dict() for item in searcher.search(query, top_k, candidate_k, pubmed_weight)]


def iter_all_chunks(chunk_root: Path, source_ids: set[str]) -> Iterator[dict[str, Any]]:
    for path in _chunks_for_sources(chunk_root, source_ids):
        yield from read_jsonl(path)
