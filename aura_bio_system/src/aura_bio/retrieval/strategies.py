"""Context-level retrieval strategies (SRS 10.3-10.5).

Levels 0-2 are plain top-k hybrid retrieval at increasing depth, which the
searcher already does. The two deeper levels need real strategy:

* **Level 3, hierarchical.** Broad retrieval identifies which *documents*
  matter, then neighbouring chunks from the best documents are pulled in. A
  textbook section split across four chunks is far more useful read together
  than as one isolated fragment.
* **Level 4, deep reasoning.** The query is decomposed into sub-queries,
  retrieved for separately, and the union is fused. A question like "compare X
  and Y" retrieves poorly as one string because no single passage covers both
  halves.

Both feed :func:`compress_evidence`, which trims passages to the sentences that
actually bear on the query so a fixed prompt budget holds more distinct
evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from ..verification.checkers import STOPWORDS, content_tokens


class SearcherLike(Protocol):
    def search(self, query: str, top_k: int, candidate_k: int) -> list[Any]:
        ...


#: Splitting on these yields sub-questions worth retrieving for separately.
_COMPARISON = re.compile(
    r"\b(?:difference between|compare|contrast|versus|vs\.?)\b", re.I
)
_CONJUNCTION = re.compile(r"\s+(?:and|versus|vs\.?|or)\s+", re.I)
#: Interrogative scaffolding that carries no retrieval signal once the query
#: has been split, e.g. "What is the ... mitosis" -> "mitosis".
_LEAD_IN = re.compile(
    r"^\s*(?:what|which|how|why|when|where|explain|describe|state|list|give)\b"
    r"(?:\s+(?:is|are|was|were|do|does|did|the|a|an|me|us))*\s*",
    re.I,
)


def decompose_query(query: str, max_parts: int = 3) -> list[str]:
    """Split a multi-part question into retrievable sub-queries.

    Returns the original query first so its own ranking is never lost; extra
    parts are only added when the question genuinely has separable halves.
    """

    parts: list[str] = [query]
    stripped = _COMPARISON.sub(" ", query).strip(" ?.")
    if _COMPARISON.search(query):
        halves = [h.strip(" ?.,") for h in _CONJUNCTION.split(stripped) if len(h.strip()) > 3]
        for half in halves:
            half = re.sub(r"\s{2,}", " ", _LEAD_IN.sub("", half)).strip(" ?.,")
            # A single biological term ("meiosis") is a perfectly good sub-query,
            # so length in characters matters here, not word count.
            if len(half) >= 4 and half.lower() != query.lower():
                parts.append(half)
    if len(parts) == 1:
        # Fall back to the salient noun-ish terms for a broad second sweep.
        tokens = [t for t in re.findall(r"[A-Za-z][A-Za-z-]{3,}", query)
                  if t.lower() not in STOPWORDS]
        if len(tokens) >= 4:
            parts.append(" ".join(tokens[:6]))
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        key = part.lower()
        if key not in seen:
            seen.add(key)
            unique.append(part)
    return unique[:max_parts]


def hierarchical_search(
    searcher: SearcherLike,
    core_connection: Any,
    query: str,
    top_k: int,
    candidate_k: int = 60,
    documents: int = 4,
    per_document: int = 4,
) -> list[Any]:
    """Level 3: find the best documents, then read around the hits inside them.

    ``core_connection`` is the sparse store used to fetch sibling chunks; when
    it is unavailable this degrades to plain retrieval rather than failing.
    """

    hits = searcher.search(query, top_k=candidate_k, candidate_k=candidate_k)
    if not hits:
        return []
    # Rank documents by the best score any of their chunks achieved.
    best_by_document: dict[str, float] = {}
    for hit in hits:
        document_id = getattr(hit, "document_id", "") or ""
        if not document_id:
            continue
        score = getattr(hit, "rrf_score", 0.0)
        if score > best_by_document.get(document_id, -1.0):
            best_by_document[document_id] = score
    top_documents = [
        document_id
        for document_id, _ in sorted(best_by_document.items(), key=lambda kv: kv[1], reverse=True)
    ][:documents]

    expanded: list[Any] = list(hits[:top_k])
    known = {getattr(h, "chunk_id", None) for h in expanded}
    if core_connection is not None and top_documents:
        try:
            from aura_bio_pipeline.retrieval import Evidence, chunks_in_documents

            siblings = chunks_in_documents(core_connection, top_documents, per_document)
        except Exception:
            siblings = {}
        for document_id, rows in siblings.items():
            for row in rows:
                if row["chunk_id"] in known:
                    continue
                known.add(row["chunk_id"])
                expanded.append(
                    Evidence(
                        chunk_id=row["chunk_id"],
                        document_id=row.get("document_id", ""),
                        source_id=row["source_id"],
                        title=row["title"],
                        section=row.get("section"),
                        text=row["text"],
                        url=row.get("url"),
                        license_id=row.get("license_id"),
                        channel="hierarchical_expansion",
                        rrf_score=0.0,
                    )
                )
    return expanded


def deep_search(
    searcher: SearcherLike,
    core_connection: Any,
    query: str,
    top_k: int,
    candidate_k: int = 80,
) -> list[Any]:
    """Level 4: decompose the query, retrieve each part, then expand documents."""

    pooled: dict[str, Any] = {}
    for part in decompose_query(query):
        for rank, hit in enumerate(searcher.search(part, top_k=top_k, candidate_k=candidate_k), 1):
            chunk_id = getattr(hit, "chunk_id", None)
            if chunk_id is None:
                continue
            existing = pooled.get(chunk_id)
            # A passage found by several sub-queries is more central, so its
            # fused contribution accumulates.
            if existing is None:
                hit.rrf_score = getattr(hit, "rrf_score", 0.0) + 1 / (60 + rank)
                pooled[chunk_id] = hit
            else:
                existing.rrf_score += 1 / (60 + rank)
    ranked = sorted(pooled.values(), key=lambda item: getattr(item, "rrf_score", 0.0), reverse=True)
    if not ranked:
        return []
    return hierarchical_search(
        _FixedSearcher(ranked), core_connection, query, top_k, candidate_k, documents=5, per_document=3
    )


@dataclass(slots=True)
class _FixedSearcher:
    """Replays an already-fused candidate list through the hierarchical step."""

    results: list[Any]

    def search(self, query: str, top_k: int, candidate_k: int) -> list[Any]:
        return self.results[:candidate_k]


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def compress_evidence(
    query: str, evidence: Sequence[Any], max_sentences: int = 4, min_overlap: float = 0.06
) -> list[Any]:
    """Trim each passage to the sentences that bear on the query (SRS 10.3).

    Deep retrieval returns many passages; sending them whole would blow the
    context budget. Scoring sentences by query-token overlap keeps the relevant
    parts and drops boilerplate, while preserving original order so the text
    still reads coherently. Passages with nothing relevant are returned as-is
    rather than emptied, so nothing silently loses its content.
    """

    query_tokens = content_tokens(query)
    if not query_tokens:
        return list(evidence)
    compressed: list[Any] = []
    for item in evidence:
        text = getattr(item, "text", "") or ""
        sentences = [s.strip() for s in _SENTENCE.split(text) if len(s.strip()) > 25]
        if len(sentences) <= max_sentences:
            compressed.append(item)
            continue
        scored: list[tuple[int, float, str]] = []
        for index, sentence in enumerate(sentences):
            tokens = content_tokens(sentence)
            if not tokens:
                continue
            overlap = len(tokens & query_tokens) / len(query_tokens)
            scored.append((index, overlap, sentence))
        keep = [entry for entry in sorted(scored, key=lambda e: e[1], reverse=True)[:max_sentences]
                if entry[1] >= min_overlap]
        if not keep:
            compressed.append(item)
            continue
        ordered = [sentence for _, _, sentence in sorted(keep, key=lambda e: e[0])]
        item.text = " ".join(ordered)
        compressed.append(item)
    return compressed


def retrieve_for_level(
    searcher: SearcherLike,
    core_connection: Any,
    query: str,
    context_level: int,
    retrieve_k: int,
    candidate_k: int | None = None,
) -> list[Any]:
    """Dispatch to the retrieval strategy the routed context level calls for."""

    candidate_k = candidate_k or max(retrieve_k * 2, 50)
    if context_level >= 4:
        return deep_search(searcher, core_connection, query, retrieve_k, candidate_k)
    if context_level == 3:
        return hierarchical_search(searcher, core_connection, query, retrieve_k, candidate_k)
    return searcher.search(query, top_k=retrieve_k, candidate_k=candidate_k)
