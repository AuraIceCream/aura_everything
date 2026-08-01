"""Reranking, evidence selection, and retrieval evaluation.

Index construction and the hybrid searcher live in ``aura_bio_pipeline``; this
package is the query-time layer above them.
"""

from .metrics import (
    RetrievalCase,
    context_precision,
    evaluate_run,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    source_diversity,
)
from .reranker import CrossEncoderReranker, RerankReport, select_evidence
from .strategies import (
    compress_evidence,
    decompose_query,
    deep_search,
    hierarchical_search,
    retrieve_for_level,
)

__all__ = [
    "CrossEncoderReranker",
    "RerankReport",
    "RetrievalCase",
    "compress_evidence",
    "context_precision",
    "decompose_query",
    "deep_search",
    "hierarchical_search",
    "retrieve_for_level",
    "evaluate_run",
    "ndcg_at_k",
    "recall_at_k",
    "reciprocal_rank",
    "select_evidence",
    "source_diversity",
]
