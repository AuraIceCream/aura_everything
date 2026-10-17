"""Repeated retrieval must not contaminate searcher-owned cached evidence."""

import unittest
from dataclasses import dataclass

from aura_bio.retrieval.strategies import deep_search, multi_query_search


@dataclass
class Hit:
    chunk_id: str
    text: str
    rrf_score: float = 0.02
    document_id: str = "doc"
    source_id: str = "textbook"


class CachedSearcher:
    def __init__(self):
        self.hits = [Hit("a", "Mitosis separates chromosomes."),
                     Hit("b", "Meiosis reduces chromosome number.", 0.01)]

    def search(self, query, top_k, candidate_k):
        return self.hits


class IsolationTests(unittest.TestCase):
    def test_deep_fusion_does_not_change_cached_scores_or_accumulate_across_requests(self):
        searcher = CachedSearcher()
        first = deep_search(searcher, None, "Compare mitosis and meiosis", 2)
        first_scores = [(h.chunk_id, h.rrf_score) for h in first]
        second = deep_search(searcher, None, "Compare mitosis and meiosis", 2)
        self.assertEqual([h.rrf_score for h in searcher.hits], [0.02, 0.01])
        self.assertEqual(first_scores, [(h.chunk_id, h.rrf_score) for h in second])
        self.assertIsNot(first[0], searcher.hits[0])

    def test_multi_query_fusion_also_preserves_cached_scores(self):
        searcher = CachedSearcher()
        first = multi_query_search(searcher, "Compare mitosis and meiosis", 2, 10)
        second = multi_query_search(searcher, "Compare mitosis and meiosis", 2, 10)
        self.assertEqual([h.rrf_score for h in searcher.hits], [0.02, 0.01])
        self.assertEqual([h.rrf_score for h in first], [h.rrf_score for h in second])
