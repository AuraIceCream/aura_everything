from __future__ import annotations

import unittest
from dataclasses import dataclass

from aura_bio.retrieval import (
    CrossEncoderReranker,
    RetrievalCase,
    context_precision,
    evaluate_run,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    select_evidence,
    source_diversity,
)


@dataclass
class FakeEvidence:
    chunk_id: str
    text: str
    source_id: str = "wikipedia_biology"
    title: str = "Title"
    section: str | None = "Section"
    rerank_score: float | None = None


class StubScorer:
    """Scores by how many query words the passage contains."""

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores = []
        for query, passage in pairs:
            words = set(query.lower().split())
            scores.append(float(len(words & set(passage.lower().split()))))
        return scores


class RerankerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reranker = CrossEncoderReranker(scorer=StubScorer())
        # Overlap with "helicase dna replication" must differ per passage:
        # a matches 0 terms, b matches 1, c matches all 3.
        self.evidence = [
            FakeEvidence("a", "chloroplasts are green organelles"),
            FakeEvidence("b", "helicase unwinds the double helix"),
            FakeEvidence("c", "dna replication is semiconservative and uses helicase"),
        ]

    def test_reranking_reorders_by_pair_score(self) -> None:
        selected, report = self.reranker.rerank("helicase dna replication", self.evidence, top_k=2)
        self.assertEqual([item.chunk_id for item in selected], ["c", "b"])
        self.assertEqual(report.candidates, 3)
        self.assertEqual(report.selected, 2)
        self.assertGreater(selected[0].rerank_score, selected[1].rerank_score)

    def test_report_counts_promotions_from_beyond_the_cut(self) -> None:
        _, report = self.reranker.rerank("helicase dna replication", self.evidence, top_k=1)
        # "c" was third before reranking and first after.
        self.assertEqual(report.promoted_from_beyond_cut, 1)
        self.assertEqual(report.rank_changes, 1)

    def test_empty_candidates_are_safe(self) -> None:
        selected, report = self.reranker.rerank("anything", [], top_k=5)
        self.assertEqual(selected, [])
        self.assertEqual(report.candidates, 0)

    def test_section_heading_is_given_to_the_scorer(self) -> None:
        captured: list[str] = []

        class Capturing:
            def predict(self, pairs):
                captured.extend(passage for _, passage in pairs)
                return [1.0] * len(pairs)

        CrossEncoderReranker(scorer=Capturing()).rerank(
            "q", [FakeEvidence("a", "body", title="Mitosis", section="Anaphase")], top_k=1
        )
        self.assertIn("Mitosis - Anaphase", captured[0])


class EvidenceSelectionTests(unittest.TestCase):
    def test_per_source_cap_preserves_diversity(self) -> None:
        evidence = [FakeEvidence(str(i), "text", source_id="uniprot_sprot") for i in range(6)]
        evidence.append(FakeEvidence("w", "text", source_id="wikipedia_biology"))
        chosen = select_evidence(evidence, max_passages=5, per_source_cap=2)
        sources = [item.source_id for item in chosen]
        self.assertEqual(sources.count("uniprot_sprot"), 2)
        self.assertIn("wikipedia_biology", sources)

    def test_character_budget_is_respected(self) -> None:
        evidence = [FakeEvidence(str(i), "x" * 4000, source_id=f"s{i}") for i in range(5)]
        chosen = select_evidence(evidence, max_passages=5, max_chars=9000)
        self.assertLessEqual(sum(len(item.text) for item in chosen), 9000)

    def test_first_passage_is_kept_even_when_oversized(self) -> None:
        evidence = [FakeEvidence("big", "x" * 50_000)]
        self.assertEqual(len(select_evidence(evidence, max_passages=3, max_chars=100)), 1)


class MetricTests(unittest.TestCase):
    def test_recall(self) -> None:
        self.assertAlmostEqual(recall_at_k(["a", "b", "c"], {"a", "d"}, 3), 0.5)
        self.assertAlmostEqual(recall_at_k(["a", "b", "c"], {"c"}, 2), 0.0)

    def test_reciprocal_rank(self) -> None:
        self.assertAlmostEqual(reciprocal_rank(["x", "y", "a"], {"a"}), 1 / 3)
        self.assertEqual(reciprocal_rank(["x"], {"a"}), 0.0)

    def test_ndcg_rewards_earlier_hits(self) -> None:
        early = ndcg_at_k(["a", "x", "y"], {"a"}, 3)
        late = ndcg_at_k(["x", "y", "a"], {"a"}, 3)
        self.assertGreater(early, late)
        self.assertAlmostEqual(early, 1.0)

    def test_context_precision(self) -> None:
        self.assertAlmostEqual(context_precision(["a", "b"], {"a"}, 2), 0.5)

    def test_source_diversity(self) -> None:
        self.assertAlmostEqual(source_diversity(["a", "a", "b", "c"]), 0.75)
        self.assertEqual(source_diversity([]), 0.0)

    def test_evaluate_run_aggregates(self) -> None:
        cases = [
            RetrievalCase("q1", ("a",)),
            RetrievalCase("q2", ("z",)),
        ]
        results = [["a", "b"], ["x", "y"]]
        summary = evaluate_run(cases, results, sources=[["s1", "s2"], ["s1", "s1"]])
        self.assertEqual(summary["cases"], 2)
        self.assertAlmostEqual(summary["recall@5"], 0.5)
        self.assertAlmostEqual(summary["mrr"], 0.5)
        self.assertAlmostEqual(summary["source_diversity"], 0.75)

    def test_mismatched_lengths_raise(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_run([RetrievalCase("q", ("a",))], [["a"], ["b"]])


if __name__ == "__main__":
    unittest.main()
