"""Cross-encoder reranking and evidence selection (SRS 14.4 and 8.x).

Fusion ranks by how often and how highly a chunk appears across channels, which
is a proxy for relevance. A cross-encoder reads the query and the passage
together and scores the pair directly, which is what actually decides whether a
passage belongs in the prompt.

The reranker is optional at runtime: SRS 25 requires measuring hybrid retrieval
with and without it, so the pipeline must run either way.
"""

from __future__ import annotations

import os
import math
import time
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

DEFAULT_MODEL = "BAAI/bge-reranker-base"

#: Truncation length for the passage half of a pair. AURA chunks target 450
#: BGE tokens, so this keeps whole chunks intact in the common case.
MAX_PASSAGE_CHARS = 2200


class Scorer(Protocol):
    def predict(self, pairs: list[tuple[str, str]]) -> Sequence[float]:
        ...


@dataclass(slots=True)
class RerankReport:
    """Latency and movement, so SRS 20.2 can show what reranking bought."""

    model: str
    candidates: int
    selected: int
    elapsed_ms: float
    rank_changes: int
    promoted_from_beyond_cut: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "candidates": self.candidates,
            "selected": self.selected,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "rank_changes": self.rank_changes,
            "promoted_from_beyond_cut": self.promoted_from_beyond_cut,
        }


class CrossEncoderReranker:
    """Lazily loads a cross-encoder and scores (query, passage) pairs."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        batch_size: int = 16,
        scorer: Scorer | None = None,
    ) -> None:
        from ..device import resolve_device

        self.model_name = model_name
        # Prefer the GPU wherever this runs; an explicit device still wins.
        self.device = resolve_device(device)
        self.batch_size = batch_size
        self._scorer = scorer

    @property
    def scorer(self) -> Scorer:
        if self._scorer is None:
            # TensorFlow is installed in this environment and costs minutes to
            # import through transformers if it is not disabled first.
            os.environ.setdefault("USE_TF", "0")
            os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
            from sentence_transformers import CrossEncoder

            self._scorer = CrossEncoder(self.model_name, device=self.device, max_length=512)
        return self._scorer

    def rerank(
        self, query: str, evidence: Sequence[Any], top_k: int
    ) -> tuple[list[Any], RerankReport]:
        """Score every candidate against the query and return the best ``top_k``.

        ``evidence`` items must expose ``text`` and accept a ``rerank_score``
        attribute; the pipeline's Evidence dataclass satisfies both.
        """

        if not evidence:
            return [], RerankReport(self.model_name, 0, 0, 0.0, 0, 0)
        pairs = [(query, _passage_text(item)) for item in evidence]
        started = time.perf_counter()
        scores = self.scorer.predict(pairs, batch_size=self.batch_size) if _accepts_batch(
            self.scorer
        ) else self.scorer.predict(pairs)
        elapsed = (time.perf_counter() - started) * 1000
        for item, score in zip(evidence, scores):
            item.rerank_score = float(score)
        ranked = sorted(evidence, key=lambda item: item.rerank_score, reverse=True)
        selected = ranked[:top_k]

        before = [id(item) for item in evidence[:top_k]]
        after = [id(item) for item in selected]
        rank_changes = sum(1 for left, right in zip(before, after) if left != right)
        promoted = len([item for item in selected if id(item) not in set(before)])
        return selected, RerankReport(
            self.model_name, len(evidence), len(selected), elapsed, rank_changes, promoted
        )


def _passage_text(item: Any) -> str:
    """Give the cross-encoder the section heading; it disambiguates chunks."""

    title = getattr(item, "title", "") or ""
    section = getattr(item, "section", None) or ""
    body = (getattr(item, "text", "") or "")[:MAX_PASSAGE_CHARS]
    header = " - ".join(part for part in (title, section) if part)
    return f"{header}\n{body}" if header else body


def _accepts_batch(scorer: Scorer) -> bool:
    import inspect

    try:
        return "batch_size" in inspect.signature(scorer.predict).parameters
    except (TypeError, ValueError):
        return False


def select_evidence(
    evidence: Sequence[Any],
    max_passages: int,
    max_chars: int = 14000,
    per_source_cap: int | None = 4,
) -> list[Any]:
    """Trim reranked passages to what the local model can actually read.

    A per-source cap keeps one prolific source (UniProt is over half the dense
    corpus) from filling the whole prompt and starving source diversity, which
    SRS 14.5 measures.

    ``max_chars`` was 9,000 — about 2,300 tokens — chosen against the old 2,048
    Modelfile context. The generator now runs at 8,192, so with a ~700 token
    system prompt and a 2,048 token answer budget there is room for roughly
    3,500 tokens of evidence. Passages were being dropped while two thirds of
    the context window sat empty.
    """

    chosen: list[Any] = []
    used = 0
    per_source: dict[str, int] = {}
    for item in evidence:
        if len(chosen) >= max_passages:
            break
        source = getattr(item, "source_id", "") or ""
        if per_source_cap is not None and per_source.get(source, 0) >= per_source_cap:
            continue
        text = getattr(item, "text", "") or ""
        if chosen and used + len(text) > max_chars:
            continue
        chosen.append(item)
        per_source[source] = per_source.get(source, 0) + 1
        used += len(text)
    return chosen


def select_diverse_evidence(
    query: str,
    evidence: Sequence[Any],
    max_passages: int,
    max_chars: int = 9000,
    per_source_cap: int | None = 4,
    per_document_cap: int | None = 2,
    min_relevance_ratio: float = 0.2,
) -> list[Any]:
    """Greedy MMR with query coverage and a hard prompt budget.

    Relevance comes from the input ranking, diversity from passage-token
    overlap, and coverage from the user's question alone. No answer keys or
    generated facts enter selection. Full reranked candidates are eligible;
    redundant chunks cannot crowd out a complementary comparison subject.
    """
    from ..verification.checkers import content_tokens

    if max_passages <= 0 or max_chars <= 0:
        return []
    asked = content_tokens(query)
    raw_scores = [getattr(item, "rerank_score", None) for item in evidence]
    available = [float(score) for score in raw_scores if score is not None]
    logits = any(score < 0 or score > 1 for score in available)
    relevance_scores = [None if score is None else (
        1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, float(score))))) if logits else float(score)
    ) for score in raw_scores]
    best_score = max((score for score in relevance_scores if score is not None), default=0.0)
    floor = max(0.1, best_score * min_relevance_ratio)
    pool = []
    for rank, item in enumerate(evidence):
        text = getattr(item, "text", "") or ""
        if not text.strip() or len(text) > max_chars:
            continue
        if relevance_scores[rank] is not None and relevance_scores[rank] < floor:
            continue
        tokens = content_tokens(text)
        title_tokens = content_tokens(getattr(item, "title", "") or "")
        pool.append((rank, item, tokens, (tokens | title_tokens) & asked))

    selected: list[Any] = []
    selected_tokens: list[set[str]] = []
    covered: set[str] = set()
    sources: dict[str, int] = {}
    documents: dict[str, int] = {}
    used = 0
    while pool and len(selected) < max_passages:
        eligible = []
        for rank, item, tokens, matches in pool:
            source = getattr(item, "source_id", "") or ""
            document = getattr(item, "document_id", "") or (
                source + ":" + (getattr(item, "title", "") or str(getattr(item, "chunk_id", rank)))
            )
            if used + len(item.text) > max_chars or (per_source_cap is not None and sources.get(source, 0) >= per_source_cap):
                continue
            # The document cap must not exclude a third explicitly requested
            # subject simply because one textbook chapter covers all three.
            if per_document_cap is not None and documents.get(document, 0) >= per_document_cap and not (matches - covered):
                continue
            similarity = max((len(tokens & old) / max(1, len(tokens | old))
                              for old in selected_tokens), default=0.0)
            if similarity >= 0.85:
                continue
            novelty = len(matches - covered) / max(1, len(asked))
            rank_relevance = 1.0 / (1.0 + 0.08 * rank)
            relevance = rank_relevance if relevance_scores[rank] is None else (
                0.7 * relevance_scores[rank] + 0.3 * rank_relevance
            )
            score = relevance + 0.65 * novelty - 0.55 * similarity - 0.12 * documents.get(document, 0)
            # Preserve the best feasible ranked passage as the first anchor.
            key = (-rank,) if not selected else (score, -rank)
            eligible.append((key, rank, item, tokens, matches, source, document))
        if not eligible:
            break
        _, rank, item, tokens, matches, source, document = max(eligible, key=lambda row: row[0])
        selected.append(item)
        selected_tokens.append(tokens)
        covered.update(matches)
        sources[source] = sources.get(source, 0) + 1
        documents[document] = documents.get(document, 0) + 1
        used += len(item.text)
        pool = [row for row in pool if row[0] != rank]
    return selected
