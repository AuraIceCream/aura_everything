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
    per_source_cap: int = 4,
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
        if per_source.get(source, 0) >= per_source_cap:
            continue
        text = getattr(item, "text", "") or ""
        if chosen and used + len(text) > max_chars:
            continue
        chosen.append(item)
        per_source[source] = per_source.get(source, 0) + 1
        used += len(text)
    return chosen
