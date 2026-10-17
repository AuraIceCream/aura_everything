"""Cache-only CPU pair scoring with a conservative, configurable relevance gate."""
import math
import os
import re
import time
from dataclasses import dataclass, replace
from functools import lru_cache

from ..retrieval.reranker import CrossEncoderReranker, RerankReport, _accepts_batch, _passage_text
from ..retrieval.strategies import query_variants
from .text import search_text
from .context import body_evidence


def _load_scorer():
    from ..resources import guard_cpu_model_load
    guard_cpu_model_load('study reranker', 2048)
    from sentence_transformers import CrossEncoder
    from torch import nn
    model = CrossEncoder('BAAI/bge-reranker-base', device='cpu', max_length=512, local_files_only=True)
    # Fix the scale explicitly across sentence-transformers 3/4/5 releases.
    # These bounded scores are ranking signals, NOT calibrated probabilities.
    if hasattr(model, 'set_activation_fn'):
        model.set_activation_fn(nn.Sigmoid(), set_default=False)
    else:
        model.default_activation_function = nn.Sigmoid()
    return model


@lru_cache(maxsize=1)
def cached_scorer():
    from .model_lifecycle import RetrievalModel
    return RetrievalModel(_load_scorer, 'BAAI/bge-reranker-base').load()


@dataclass
class StudyRerankReport(RerankReport):
    query_parts: tuple[str, ...] = ()
    score_floor: float = 0.1

    def as_dict(self):
        return {**super().as_dict(), 'query_parts': list(self.query_parts), 'score_floor': self.score_floor}


class StudyReranker(CrossEncoderReranker):
    def __init__(self, *, scorer, min_score=0.1, expand_comparisons=True, batch_size=2):
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError('Study reranker batch must be a positive integer.')
        super().__init__(device='cpu', scorer=scorer, batch_size=batch_size)
        if not math.isfinite(min_score) or not 0 <= min_score <= 1:
            raise ValueError('Study reranker score floor must be finite and between zero and one.')
        self.min_score = min_score
        self.expand_comparisons = expand_comparisons

    def rerank(self, query, evidence, top_k):
        # Retrieval already expands compound questions. Score those same parts
        # here too, or the whole-question gate discards their retrieved support.
        original_count = len(evidence)
        evidence = body_evidence(query, evidence)
        queries = query_variants(query) if self.expand_comparisons else [query]
        if self.expand_comparisons:
            # Explicit named chains are question text, not inferred facts.
            # Keep each step eligible without guessing an answer or its order.
            for chain in re.findall(r'\b[A-Z][A-Z0-9]{1,23}(?:[–—\-/][A-Z][A-Z0-9]{1,23})+\b', query):
                queries.extend(re.split(r'[–—\-/]', chain))
            queries = list(dict.fromkeys(queries))[:8]
        if not evidence or top_k <= 0:
            return [], StudyRerankReport(self.model_name, original_count, 0, 0., 0, 0, tuple(queries), self.min_score)
        copies = [replace(item, text=search_text(item.text), title=search_text(item.title or '')) for item in evidence]
        pairs = [(search_text(part), _passage_text(item)) for part in queries for item in copies]
        started = time.perf_counter()
        values = list(self.scorer.predict(pairs, batch_size=self.batch_size) if _accepts_batch(self.scorer) else self.scorer.predict(pairs))
        if len(values) != len(pairs) or any(not math.isfinite(float(value)) or not 0 <= float(value) <= 1 for value in values):
            raise ValueError('Invalid normalized study reranker scores.')
        rows = [values[n * len(evidence):(n + 1) * len(evidence)] for n in range(len(queries))]
        for n, item in enumerate(evidence):
            item.rerank_score = max(float(row[n]) for row in rows)
        ranked = sorted(evidence, key=lambda item: item.rerank_score, reverse=True)
        # One positive anchor per explicitly requested sub-question keeps
        # a strongly matching half from crowding out the other half. No anchor
        # is manufactured for unsupported parts. Final verification still gates
        # every claim; a match to one part is not support for the whole answer.
        anchors = []
        for row in (rows[1:] if len(rows) > 1 else rows):
            n = max(range(len(row)), key=lambda i: row[i])
            if float(row[n]) >= self.min_score and evidence[n] not in anchors:
                anchors.append(evidence[n])
        selected = []
        for item in [*anchors, *ranked]:
            if item.rerank_score >= self.min_score and item not in selected:
                selected.append(item)
                if len(selected) >= top_k:
                    break
        before = [item.chunk_id for item in evidence[:top_k]]
        report = StudyRerankReport(self.model_name, original_count, len(selected),
            (time.perf_counter() - started) * 1000,
            sum(a != b.chunk_id for a, b in zip(before, selected)),
            sum(item.chunk_id not in before for item in selected), tuple(queries), self.min_score)
        return selected, report


def configured_reranker():
    setting = os.environ.get('AURA_STUDY_RERANK', os.environ.get('AURA_RERANK', '1'))
    if setting.lower() in {'off', 'false', '0'}:
        return None
    return StudyReranker(scorer=cached_scorer(), min_score=float(os.environ.get('AURA_STUDY_RERANK_MIN_SCORE', '0.1')),
                         batch_size=int(os.environ.get('AURA_STUDY_RERANK_BATCH', '2')))
