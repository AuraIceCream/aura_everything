from __future__ import annotations

import unittest
from dataclasses import dataclass, field

from aura_bio.retrieval import (
    compress_evidence,
    decompose_query,
    deep_search,
    hierarchical_search,
    retrieve_for_level,
)


@dataclass
class Hit:
    chunk_id: str
    text: str
    document_id: str = "doc-1"
    source_id: str = "wikipedia_biology"
    title: str = "Title"
    section: str | None = None
    url: str | None = None
    license_id: str | None = None
    channel: str = "core_bm25"
    rrf_score: float = 0.1
    rerank_score: float | None = None


@dataclass
class FakeSearcher:
    results: list[Hit]
    queries: list[str] = field(default_factory=list)

    def search(self, query: str, top_k: int, candidate_k: int) -> list[Hit]:
        self.queries.append(query)
        # Return a fresh copy so per-query score accumulation is observable.
        return [Hit(**{**h.__dict__}) for h in self.results[:candidate_k]]


class DecomposeTests(unittest.TestCase):
    def test_comparison_splits_into_halves(self) -> None:
        parts = decompose_query("What is the difference between mitosis and meiosis?")
        self.assertGreaterEqual(len(parts), 2)
        joined = " ".join(parts).lower()
        self.assertIn("mitosis", joined)
        self.assertIn("meiosis", joined)

    def test_original_query_is_always_first(self) -> None:
        query = "Compare xylem and phloem"
        self.assertEqual(decompose_query(query)[0], query)

    def test_simple_question_is_not_over_split(self) -> None:
        self.assertEqual(decompose_query("Define osmosis"), ["Define osmosis"])

    def test_parts_are_deduplicated_and_capped(self) -> None:
        parts = decompose_query("Compare A and B and C and D", max_parts=3)
        self.assertLessEqual(len(parts), 3)
        self.assertEqual(len(parts), len(set(p.lower() for p in parts)))


class CompressionTests(unittest.TestCase):
    def test_relevant_sentences_are_kept_in_order(self) -> None:
        text = (
            "This document was last revised in April. "
            "Helicase unwinds the DNA double helix during replication. "
            "The publisher is located in Boston. "
            "Primase then synthesises a short RNA primer for the polymerase. "
            "Copyright notice applies to all figures herein."
        )
        [result] = compress_evidence("helicase primase replication", [Hit("c1", text)], max_sentences=2)
        self.assertIn("Helicase unwinds", result.text)
        self.assertIn("Primase", result.text)
        self.assertNotIn("Copyright", result.text)
        # Original ordering is preserved.
        self.assertLess(result.text.index("Helicase"), result.text.index("Primase"))

    def test_short_passages_are_left_untouched(self) -> None:
        text = "Helicase unwinds the double helix during replication of DNA."
        [result] = compress_evidence("helicase", [Hit("c1", text)])
        self.assertEqual(result.text, text)

    def test_passage_with_no_overlap_is_not_emptied(self) -> None:
        text = " ".join(f"Completely unrelated statement number {i} about publishing." for i in range(8))
        [result] = compress_evidence("photosynthesis chloroplast", [Hit("c1", text)])
        self.assertTrue(result.text)


class HierarchicalTests(unittest.TestCase):
    def test_expands_with_sibling_chunks_from_top_documents(self) -> None:
        class Connection:
            def execute(self, sql, params):
                document_id, limit = params

                class Cursor:
                    def fetchall(self_inner):
                        return [
                            {
                                "chunk_id": f"{document_id}-sib{i}",
                                "document_id": document_id,
                                "source_id": "wikipedia_biology",
                                "title": "Title",
                                "section": None,
                                "text": f"sibling {i}",
                                "url": None,
                                "license_id": None,
                            }
                            for i in range(2)
                        ]

                return Cursor()

        searcher = FakeSearcher([Hit("c1", "hit one", document_id="doc-A", rrf_score=0.9)])
        results = hierarchical_search(searcher, Connection(), "query", top_k=3)
        ids = [r.chunk_id for r in results]
        self.assertIn("c1", ids)
        self.assertTrue(any("sib" in i for i in ids))
        self.assertTrue(any(r.channel == "hierarchical_expansion" for r in results))

    def test_degrades_to_plain_results_without_a_connection(self) -> None:
        searcher = FakeSearcher([Hit("c1", "one"), Hit("c2", "two")])
        results = hierarchical_search(searcher, None, "query", top_k=2)
        self.assertEqual([r.chunk_id for r in results], ["c1", "c2"])

    def test_empty_results_are_safe(self) -> None:
        self.assertEqual(hierarchical_search(FakeSearcher([]), None, "q", top_k=5), [])


class DeepSearchTests(unittest.TestCase):
    def test_runs_each_sub_query_and_fuses(self) -> None:
        searcher = FakeSearcher([Hit("c1", "shared passage"), Hit("c2", "other")])
        deep_search(searcher, None, "difference between mitosis and meiosis", top_k=3)
        self.assertGreaterEqual(len(searcher.queries), 2)

    def test_passage_found_by_several_subqueries_ranks_higher(self) -> None:
        searcher = FakeSearcher([Hit("shared", "a"), Hit("single", "b")])
        results = deep_search(searcher, None, "compare mitosis and meiosis", top_k=2)
        self.assertEqual(results[0].chunk_id, "shared")


class DispatchTests(unittest.TestCase):
    def test_level_two_uses_plain_search(self) -> None:
        searcher = FakeSearcher([Hit("c1", "x")])
        retrieve_for_level(searcher, None, "Define osmosis", context_level=2, retrieve_k=5)
        self.assertEqual(searcher.queries, ["Define osmosis"])

    def test_level_four_decomposes(self) -> None:
        searcher = FakeSearcher([Hit("c1", "x")])
        retrieve_for_level(
            searcher, None, "difference between mitosis and meiosis", context_level=4, retrieve_k=5
        )
        self.assertGreater(len(searcher.queries), 1)


if __name__ == "__main__":
    unittest.main()
