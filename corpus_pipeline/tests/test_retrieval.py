from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from aura_bio_pipeline.retrieval import (
    HybridSearcher,
    benchmark_sparse,
    build_dense_index_from_jobs,
    build_sparse_index,
    chunks_by_id,
    load_embedding_jobs,
    open_sparse,
    phrase_search,
    sparse_detail,
    sparse_search,
    write_retrieval_manifest,
)


def _chunk(chunk_id: str, source_id: str, text: str, title: str = "Mitochondrial apoptosis") -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "document_id": f"document:{chunk_id}",
        "source_id": source_id,
        "category": "literature",
        "title": title,
        "section": "Abstract",
        "text": text,
        "token_count": 8,
        "url": "https://example.test/article",
        "license_id": "test",
        "metadata": {},
    }


class SparseTests(unittest.TestCase):
    def _write_shard(self, root: Path, source: str, rows: list[dict[str, object]], name: str = "sample") -> Path:
        path = root / source / f"{name}.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return path

    def test_sparse_index_and_query_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunks = root / "chunks"
            self._write_shard(
                chunks,
                "pubmed_filtered",
                [
                    _chunk("pmid:1", "pubmed_filtered", "Mitochondrial apoptosis activates caspase pathways."),
                    _chunk("pmid:2", "pubmed_filtered", "Plants use chlorophyll for photosynthesis."),
                ],
            )
            index = root / "pubmed.sqlite3"
            report = build_sparse_index(chunks, index, {"pubmed_filtered"})
            self.assertEqual(report["chunks_indexed"], 2)
            self.assertEqual(report["duplicate_chunk_ids"], 0)
            self.assertEqual(report["detail"], "full")
            results = sparse_search(index, "mitochondrial apoptosis")
            self.assertEqual(results[0]["chunk_id"], "pmid:1")
            self.assertEqual(results[0]["text"], "Mitochondrial apoptosis activates caspase pathways.")
            benchmark = benchmark_sparse(index, "mitochondrial apoptosis", repeats=3)
            self.assertGreaterEqual(benchmark["hits"], 1)
            self.assertEqual(benchmark["indexed_chunks"], 2)

    def test_compact_detail_none_matches_full_ranking(self) -> None:
        """detail=none was adopted for PubMed only because ranking is identical."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunks = root / "chunks"
            rows = [
                _chunk(f"pmid:{i}", "pubmed_filtered", text)
                for i, text in enumerate(
                    [
                        "Mitochondrial apoptosis activates caspase nine and caspase three.",
                        "Caspase activation follows cytochrome c release during apoptosis.",
                        "Plants use chlorophyll for photosynthesis in the thylakoid membrane.",
                        "Apoptosis is programmed cell death.",
                    ]
                )
            ]
            self._write_shard(chunks, "pubmed_filtered", rows)
            plain = root / "plain.sqlite3"
            compact = root / "compact.sqlite3"
            build_sparse_index(chunks, plain, {"pubmed_filtered"})
            report = build_sparse_index(chunks, compact, {"pubmed_filtered"}, compact=True)
            self.assertEqual(report["detail"], "none")
            query = "caspase apoptosis"
            left = sparse_search(plain, query, mode="or")
            right = sparse_search(compact, query, mode="or")
            self.assertEqual(
                [row["chunk_id"] for row in left], [row["chunk_id"] for row in right]
            )
            for a, b in zip(left, right):
                self.assertAlmostEqual(a["bm25_score"], b["bm25_score"], places=6)

    def test_rank_first_sql_matches_the_join_first_form(self) -> None:
        """The execution-plan fix must not change ranking, only cost.

        ``_SEARCH_SQL`` ranks inside ``chunks_fts`` and joins ``chunks`` for the
        surviving row ids. The join-first form it replaced was 57-560x slower on
        the real corpus because it materialised every matching row's ``text``
        before discarding all but ``LIMIT``. This pins the two to the same
        answer so a future "simplification" back to the obvious form is caught.
        """

        join_first = """
            SELECT chunks.*, bm25(chunks_fts) AS bm25_score
            FROM chunks_fts JOIN chunks ON chunks.row_id = chunks_fts.rowid
            WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunks = root / "chunks"
            rows = [
                _chunk(f"pmid:{i}", "pubmed_filtered", text)
                for i, text in enumerate(
                    [
                        "Helicase unwinds the DNA double helix during replication.",
                        "Primase lays down an RNA primer so polymerase can begin.",
                        "Okazaki fragments form on the lagging strand and ligase joins them.",
                        "Photosynthesis converts light energy into glucose in chloroplasts.",
                        "DNA polymerase extends the leading strand continuously.",
                    ]
                )
            ]
            self._write_shard(chunks, "pubmed_filtered", rows)
            index = root / "core.sqlite3"
            build_sparse_index(chunks, index, {"pubmed_filtered"})

            connection = open_sparse(index)
            try:
                for query in ("dna replication strand", "polymerase", "ligase glucose"):
                    expected = [
                        dict(row)
                        for row in connection.execute(
                            join_first, (" OR ".join(f'"{t}"' for t in query.split()), 50)
                        ).fetchall()
                    ]
                    actual = sparse_search(connection, query, mode="or")
                    self.assertEqual(
                        [row["chunk_id"] for row in actual],
                        [row["chunk_id"] for row in expected],
                        f"ranking diverged for {query!r}",
                    )
                    for left, right in zip(actual, expected):
                        self.assertAlmostEqual(
                            left["bm25_score"], right["bm25_score"], places=6
                        )
                        self.assertEqual(left["text"], right["text"])
            finally:
                connection.close()

    def test_conjunctive_first_then_relaxes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunks = root / "chunks"
            self._write_shard(
                chunks,
                "pubmed_filtered",
                [
                    _chunk("pmid:1", "pubmed_filtered", "Helicase unwinds DNA during replication."),
                    _chunk("pmid:2", "pubmed_filtered", "Ribosomes translate messenger RNA."),
                ],
            )
            index = root / "pubmed.sqlite3"
            build_sparse_index(chunks, index, {"pubmed_filtered"})
            connection = open_sparse(index)
            try:
                self.assertEqual(sparse_detail(connection), "full")
                strict = sparse_search(connection, "helicase replication", mode="and")
                self.assertEqual([row["chunk_id"] for row in strict], ["pmid:1"])
                # No document holds both terms, so auto must fall back to OR.
                relaxed = sparse_search(connection, "helicase ribosomes", mode="auto")
                self.assertEqual({row["chunk_id"] for row in relaxed}, {"pmid:1", "pmid:2"})
                resolved = chunks_by_id(connection, ["pmid:2"])
                self.assertIn("Ribosomes", resolved["pmid:2"]["text"])
            finally:
                connection.close()

    def test_duplicate_chunk_ids_are_skipped_not_fatal(self) -> None:
        """The same document chunked into two shards must not abort the build."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunks = root / "chunks"
            duplicated = _chunk("chunk:same", "pmc_oa_comm_xml", "Shared PMC passage about caspases.")
            self._write_shard(chunks, "pmc_oa_comm_xml", [duplicated], name="shard-a")
            self._write_shard(
                chunks,
                "pmc_oa_comm_xml",
                [duplicated, _chunk("chunk:other", "pmc_oa_comm_xml", "A distinct passage.")],
                name="shard-b",
            )
            index = root / "core.sqlite3"
            report = build_sparse_index(chunks, index, {"pmc_oa_comm_xml"})
            self.assertEqual(report["chunks_read"], 3)
            self.assertEqual(report["chunks_indexed"], 2)
            self.assertEqual(report["duplicate_chunk_ids"], 1)
            results = sparse_search(index, "caspases")
            self.assertEqual(sum(1 for r in results if r["chunk_id"] == "chunk:same"), 1)

    def test_qa_source_is_never_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                build_sparse_index(root / "chunks", root / "x.sqlite3", {"pubmedqa_labeled"})


class DenseJobTests(unittest.TestCase):
    """The extracted Kaggle layout is segment-based, not one file per source."""

    def _fixture(self, root: Path, dimensions: int = 8) -> tuple[Path, Path]:
        chunk_root = root / "chunks"
        job_root = root / "jobs"
        job_root.mkdir(parents=True)
        texts = {
            "wikipedia_biology": [
                "Mitochondria generate ATP by oxidative phosphorylation.",
                "Ribosomes synthesize proteins from messenger RNA.",
                "Chloroplasts perform photosynthesis in plant cells.",
            ],
            "gene_ontology": [
                "Apoptotic process: programmed cell death.",
                "Glycolytic process: conversion of glucose to pyruvate.",
            ],
        }
        for source, values in texts.items():
            path = chunk_root / source / f"{source}-aaaa.jsonl.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                for i, text in enumerate(values):
                    handle.write(json.dumps(_chunk(f"{source}:{i}", source, text, source)) + "\n")

        # Job 0 covers wikipedia rows 0-1; job 1 covers wikipedia row 2 then
        # all of gene_ontology, so one shard deliberately spans two jobs.
        plans = [
            (0, [("wikipedia_biology", 0, 2, 0)]),
            (1, [("wikipedia_biology", 2, 1, 0), ("gene_ontology", 0, 2, 1)]),
        ]
        rng = np.random.default_rng(0)
        for job_index, segments in plans:
            total = sum(item[2] for item in segments)
            vectors = rng.normal(size=(total, dimensions)).astype(np.float16)
            np.save(job_root / f"core-{job_index:03d}.vectors.npy", vectors, allow_pickle=False)
            (job_root / f"core-{job_index:03d}.complete.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "job_index": job_index,
                        "model": "BAAI/bge-base-en-v1.5",
                        "dimensions": dimensions,
                        "vectors": total,
                        "vector_file": f"core-{job_index:03d}.vectors.npy",
                        "manifest_sha256": "deadbeef",
                        "segments": [
                            {
                                "source_id": source,
                                "chunk_relpath": f"{source}/{source}-aaaa.jsonl.gz",
                                "original_start": start,
                                "count": count,
                                "output_offset": offset,
                            }
                            for source, start, count, offset in segments
                        ],
                    }
                ),
                encoding="utf-8",
            )
        return chunk_root, job_root

    def test_jobs_must_be_contiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, job_root = self._fixture(root)
            (job_root / "core-000.complete.json").unlink()
            with self.assertRaisesRegex(ValueError, "missing job_index"):
                load_embedding_jobs(job_root)

    def test_dense_ids_follow_job_then_segment_order(self) -> None:
        try:
            import faiss  # noqa: F401
        except ImportError:  # pragma: no cover - declared dependency, optional in test envs
            self.skipTest("faiss is not installed")
        import sqlite3

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunk_root, job_root = self._fixture(root)
            index_root = root / "indexes"
            report = build_dense_index_from_jobs(
                job_root, chunk_root, index_root, index_type="flat"
            )
            self.assertEqual(report["vectors"], 5)
            self.assertEqual(report["mapped"], 5)
            self.assertEqual(report["unembedded_chunks"], 0)
            connection = sqlite3.connect(index_root / "core-dense-map.sqlite3")
            try:
                mapped = connection.execute(
                    "SELECT dense_id, chunk_id FROM dense_map ORDER BY dense_id"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(
                [chunk_id for _, chunk_id in mapped],
                [
                    "wikipedia_biology:0",
                    "wikipedia_biology:1",
                    "wikipedia_biology:2",
                    "gene_ontology:0",
                    "gene_ontology:1",
                ],
            )

    def test_unaccounted_partial_map_is_discarded_not_reused(self) -> None:
        """A partial map whose rows no shard claims must never be resumed."""

        try:
            import faiss  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("faiss is not installed")
        import sqlite3

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunk_root, job_root = self._fixture(root)
            index_root = root / "indexes"
            index_root.mkdir(parents=True)
            partial = index_root / "core-dense-map.sqlite3.part"
            connection = sqlite3.connect(partial)
            connection.executescript(
                """
                CREATE TABLE dense_map (dense_id INTEGER PRIMARY KEY, chunk_id TEXT NOT NULL);
                INSERT INTO dense_map VALUES (0, 'stale:0'), (1, 'stale:1');
                """
            )
            connection.commit()
            connection.close()

            report = build_dense_index_from_jobs(
                job_root, chunk_root, index_root, index_type="flat"
            )
            self.assertEqual(report["mapped"], 5)
            connection = sqlite3.connect(index_root / "core-dense-map.sqlite3")
            try:
                stale = connection.execute(
                    "SELECT count(*) FROM dense_map WHERE chunk_id LIKE 'stale:%'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(stale, 0)

    def test_resume_reuses_recorded_shards(self) -> None:
        try:
            import faiss  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("faiss is not installed")
        import sqlite3

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunk_root, job_root = self._fixture(root)
            index_root = root / "indexes"
            build_dense_index_from_jobs(job_root, chunk_root, index_root, index_type="flat")
            finished = index_root / "core-dense-map.sqlite3"
            # Recreate the mid-run state: gene_ontology mapped, wikipedia not.
            partial = index_root / "core-dense-map.sqlite3.part"
            connection = sqlite3.connect(partial)
            connection.executescript(
                """
                CREATE TABLE dense_map (dense_id INTEGER PRIMARY KEY, chunk_id TEXT NOT NULL);
                CREATE TABLE map_progress (
                    chunk_relpath TEXT PRIMARY KEY, ids INTEGER NOT NULL, uncovered INTEGER NOT NULL
                );
                INSERT INTO dense_map VALUES (3, 'gene_ontology:0'), (4, 'gene_ontology:1');
                INSERT INTO map_progress VALUES
                    ('gene_ontology/gene_ontology-aaaa.jsonl.gz', 2, 0);
                """
            )
            connection.commit()
            connection.close()
            finished.unlink()

            report = build_dense_index_from_jobs(
                job_root, chunk_root, index_root, index_type="flat"
            )
            self.assertEqual(report["mapped"], 5)
            connection = sqlite3.connect(finished)
            try:
                mapped = connection.execute(
                    "SELECT chunk_id FROM dense_map ORDER BY dense_id"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(
                [row[0] for row in mapped],
                [
                    "wikipedia_biology:0",
                    "wikipedia_biology:1",
                    "wikipedia_biology:2",
                    "gene_ontology:0",
                    "gene_ontology:1",
                ],
            )

    def test_completed_map_is_reused_not_rebuilt(self) -> None:
        try:
            import faiss  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("faiss is not installed")
        import sqlite3

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunk_root, job_root = self._fixture(root)
            index_root = root / "indexes"
            build_dense_index_from_jobs(job_root, chunk_root, index_root, index_type="flat")
            # Mark every chunk id so a rebuild (which reads the shards) would be
            # visible; reuse must keep these exact rows.
            map_path = index_root / "core-dense-map.sqlite3"
            connection = sqlite3.connect(map_path)
            connection.execute("UPDATE dense_map SET chunk_id = chunk_id || ':kept'")
            connection.commit()
            connection.close()

            report = build_dense_index_from_jobs(
                job_root, chunk_root, index_root, index_type="flat"
            )
            self.assertEqual(report["mapped"], 5)
            connection = sqlite3.connect(map_path)
            try:
                kept = connection.execute(
                    "SELECT count(*) FROM dense_map WHERE chunk_id LIKE '%:kept'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(kept, 5)

    def test_ivf_pq_build_is_searchable(self) -> None:
        try:
            import faiss  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("faiss is not installed")
        # PQ trains 256 centroids per 8-bit subquantizer, so the fixture must
        # supply enough vectors; a real corpus dwarfs this.
        count, dimensions = 512, 16
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunk_root = root / "chunks"
            job_root = root / "jobs"
            job_root.mkdir(parents=True)
            shard = chunk_root / "wikipedia_biology" / "wikipedia_biology-aaaa.jsonl.gz"
            shard.parent.mkdir(parents=True)
            with gzip.open(shard, "wt", encoding="utf-8") as handle:
                for i in range(count):
                    handle.write(json.dumps(_chunk(f"wiki:{i}", "wikipedia_biology", "text")) + "\n")
            vectors = np.random.default_rng(1).normal(size=(count, dimensions)).astype(np.float16)
            np.save(job_root / "core-000.vectors.npy", vectors, allow_pickle=False)
            (job_root / "core-000.complete.json").write_text(
                json.dumps(
                    {
                        "job_index": 0,
                        "model": "BAAI/bge-base-en-v1.5",
                        "dimensions": dimensions,
                        "vectors": count,
                        "vector_file": "core-000.vectors.npy",
                        "manifest_sha256": "abc",
                        "segments": [
                            {
                                "source_id": "wikipedia_biology",
                                "chunk_relpath": "wikipedia_biology/wikipedia_biology-aaaa.jsonl.gz",
                                "original_start": 0,
                                "count": count,
                                "output_offset": 0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index_root = root / "indexes"
            report = build_dense_index_from_jobs(
                job_root, chunk_root, index_root, index_type="ivf-pq", nlist=4
            )
            self.assertEqual(report["index_type"], "ivf-pq")
            self.assertEqual(report["vectors"], count)
            index = faiss.read_index(str(index_root / "core-dense.faiss"))
            self.assertEqual(index.ntotal, count)
            _, ids = index.search(np.asarray(vectors[:1], dtype=np.float32), 3)
            self.assertGreaterEqual(int(ids[0][0]), 0)

    def test_hybrid_searcher_fuses_dense_and_sparse(self) -> None:
        try:
            import faiss  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("faiss is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunk_root, job_root = self._fixture(root)
            index_root = root / "indexes"
            build_dense_index_from_jobs(job_root, chunk_root, index_root, index_type="flat")
            core = index_root / "core.sqlite3"
            build_sparse_index(chunk_root, core, {"wikipedia_biology", "gene_ontology"})
            write_retrieval_manifest(
                index_root,
                dense_index=index_root / "core-dense.faiss",
                dense_map=index_root / "core-dense-map.sqlite3",
                core_sparse=core,
                pubmed_sparse=None,
            )
            with HybridSearcher(index_root) as searcher:
                results = searcher.search("photosynthesis chloroplasts", use_dense=False)
            self.assertTrue(results)
            self.assertEqual(results[0].chunk_id, "wikipedia_biology:2")
            self.assertEqual(results[0].channel, "core_bm25")
            self.assertIsNotNone(results[0].core_bm25_rank)
            self.assertIn("chloroplast", results[0].text.lower())

    def test_phrase_channel_recovers_adjacent_biological_term(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunks = root / "chunks"
            rows = [
                _chunk(
                    "genetics:test-cross", "wikipedia_biology",
                    "A homozygous recessive partner reveals an unknown genotype.",
                    title="Test cross",
                ),
                _chunk(
                    "immunology:cross-reactivity", "wikipedia_biology",
                    "A cross-reactivity test is useful in antibody screening.",
                    title="Cross-reactivity testing",
                ),
            ]
            shard = chunks / "wikipedia_biology" / "sample.jsonl.gz"
            shard.parent.mkdir(parents=True)
            with gzip.open(shard, "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            index_root = root / "indexes"
            core = index_root / "core.sqlite3"
            build_sparse_index(chunks, core, {"wikipedia_biology"})
            write_retrieval_manifest(
                index_root, dense_index=None, dense_map=None,
                core_sparse=core, pubmed_sparse=None,
            )

            with HybridSearcher(index_root, dense_enabled=False, phrase_enabled=True) as searcher:
                results = searcher.search(
                    "What is a test cross and why is it useful?", top_k=2, candidate_k=2
                )

            self.assertEqual(results[0].chunk_id, "genetics:test-cross")
            self.assertIn("phrase_bm25", results[0].channel)

    def test_phrase_channel_ignores_body_only_generic_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shard = root / "chunks" / "wikipedia_biology" / "sample.jsonl.gz"
            shard.parent.mkdir(parents=True)
            rows = [
                _chunk(
                    "physiology:homeostasis", "wikipedia_biology",
                    "Homeostasis maintains a stable internal environment through regulation.",
                    title="Homeostasis",
                ),
                _chunk(
                    "respiration:generic", "wikipedia_biology",
                    "This process affects the human body in many ways.",
                    title="Human body temperature",
                ),
            ]
            with gzip.open(shard, "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            index_root = root / "indexes"
            core = index_root / "core.sqlite3"
            build_sparse_index(root / "chunks", core, {"wikipedia_biology"})
            write_retrieval_manifest(
                index_root, dense_index=None, dense_map=None,
                core_sparse=core, pubmed_sparse=None,
            )

            with HybridSearcher(index_root, dense_enabled=False, phrase_enabled=True) as searcher:
                results = searcher.search(
                    "Define homeostasis and give one example in the human body.",
                    top_k=2, candidate_k=2,
                )

            self.assertTrue(all("phrase_bm25" not in row.channel for row in results))

    def test_phrase_channel_prefers_definition_over_repeated_examples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shard = root / "chunks" / "wikipedia_biology" / "sample.jsonl.gz"
            shard.parent.mkdir(parents=True)
            rows = [
                _chunk(
                    "genetics:intro", "wikipedia_biology",
                    "A test cross determines whether an individual is heterozygous "
                    "by mating with a homozygous recessive partner.",
                    title="Test cross",
                ),
                _chunk(
                    "genetics:examples", "wikipedia_biology",
                    "Test cross with C. elegans. Repeat the test cross and compare "
                    "offspring from the test cross with another test cross.",
                    title="Test cross",
                ),
                _chunk(
                    "genetics:types", "wikipedia_biology",
                    "Test cross types include monohybrid and dihybrid crosses.",
                    title="Test cross",
                ),
            ]
            rows[0]["section"] = "Introduction"
            rows[1]["section"] = "C. elegans"
            rows[2]["section"] = "Test cross types"
            with gzip.open(shard, "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            index_root = root / "indexes"
            core = index_root / "core.sqlite3"
            build_sparse_index(root / "chunks", core, {"wikipedia_biology"})

            connection = open_sparse(core)
            try:
                results = phrase_search(connection, "What is a test cross and why useful?")
            finally:
                connection.close()

            selected_ids = [row["chunk_id"] for row in results]
            self.assertEqual(selected_ids[0], "genetics:intro")
            self.assertIn("genetics:intro", selected_ids)
            self.assertIn("genetics:types", selected_ids)
            self.assertNotIn("genetics:examples", selected_ids)

    def test_dense_can_be_disabled_for_low_memory_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunk_root, job_root = self._fixture(root)
            index_root = root / "indexes"
            core = index_root / "core.sqlite3"
            build_sparse_index(chunk_root, core, {"wikipedia_biology", "gene_ontology"})
            write_retrieval_manifest(
                index_root,
                dense_index=index_root / "missing.faiss",  # absent; must not be needed
                dense_map=None,
                core_sparse=core,
                pubmed_sparse=None,
            )
            with HybridSearcher(index_root, dense_enabled=False) as searcher:
                self.assertIsNone(searcher.dense)
                results = searcher.search("photosynthesis chloroplasts")
            self.assertTrue(results)
            self.assertTrue(all(r.dense_rank is None for r in results))

    def test_searcher_requires_core_sparse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index_root = root / "indexes"
            write_retrieval_manifest(index_root, core_sparse=None, dense_index=None)
            with self.assertRaisesRegex(ValueError, "core sparse index is required"):
                HybridSearcher(index_root)


if __name__ == "__main__":
    unittest.main()
