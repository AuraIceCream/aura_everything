"""Retrieval evaluation metrics (SRS 14.5 and 24.4).

Kept dependency-free and separate from the searcher so the retrieval lab can
score BM25, dense, hybrid, and hybrid-plus-reranker runs with identical code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    truth = set(relevant)
    if not truth:
        return 0.0
    return len(set(retrieved[:k]) & truth) / len(truth)


def reciprocal_rank(retrieved: Sequence[str], relevant: Iterable[str]) -> float:
    truth = set(relevant)
    for rank, chunk_id in enumerate(retrieved, 1):
        if chunk_id in truth:
            return 1 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Binary-gain nDCG; graded relevance is not available in the benchmark."""

    truth = set(relevant)
    if not truth:
        return 0.0
    gain = sum(
        1 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(retrieved[:k], 1)
        if chunk_id in truth
    )
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(truth), k) + 1))
    return gain / ideal if ideal else 0.0


def context_precision(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    if not retrieved[:k]:
        return 0.0
    return len(set(retrieved[:k]) & set(relevant)) / len(retrieved[:k])


def source_diversity(source_ids: Sequence[str]) -> float:
    """Distinct sources over passages returned; 1.0 means no source repeats."""

    return len(set(source_ids)) / len(source_ids) if source_ids else 0.0


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    """One benchmark question and the chunk ids that should answer it."""

    query: str
    relevant_chunk_ids: tuple[str, ...]
    subdomain: str | None = None


def evaluate_run(
    cases: Sequence[RetrievalCase],
    results: Sequence[Sequence[str]],
    sources: Sequence[Sequence[str]] | None = None,
    ks: tuple[int, ...] = (5, 10),
) -> dict[str, Any]:
    """Aggregate metrics over a whole benchmark run."""

    if len(cases) != len(results):
        raise ValueError(f"{len(cases)} cases but {len(results)} result lists")
    totals: dict[str, float] = {}
    for k in ks:
        totals[f"recall@{k}"] = 0.0
        totals[f"ndcg@{k}"] = 0.0
        totals[f"context_precision@{k}"] = 0.0
    totals["mrr"] = 0.0
    for case, retrieved in zip(cases, results):
        for k in ks:
            totals[f"recall@{k}"] += recall_at_k(retrieved, case.relevant_chunk_ids, k)
            totals[f"ndcg@{k}"] += ndcg_at_k(retrieved, case.relevant_chunk_ids, k)
            totals[f"context_precision@{k}"] += context_precision(
                retrieved, case.relevant_chunk_ids, k
            )
        totals["mrr"] += reciprocal_rank(retrieved, case.relevant_chunk_ids)
    count = len(cases) or 1
    summary = {name: round(value / count, 4) for name, value in totals.items()}
    summary["cases"] = len(cases)
    if sources is not None:
        summary["source_diversity"] = round(
            sum(source_diversity(item) for item in sources) / count, 4
        )
    return summary
