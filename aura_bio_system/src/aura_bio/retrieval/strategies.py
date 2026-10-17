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
from copy import copy
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


def question_parts(query: str, max_parts: int = 6) -> list[str]:
    """Split explicit requests, never commas inside a subject enumeration."""
    start = r'(?:what|which|how|when|where|why|does|do|did|is|are|can|could|whether)\b'
    parts = re.split(r'(?:[?;]\s*|,\s*(?:and\s+)?|\s+and\s+)(?=' + start + ')', query, flags=re.I)
    if len(parts) == 1:
        return [query.strip()]
    # A document/title prefix applies to the original query, not every facet.
    if re.match(r'^\s*(?:in|from|according to)\b', parts[0], re.I):
        match = re.search(r'\b' + start, parts[0], re.I)
        if match:
            parts[0] = parts[0][match.start():]
        elif not re.search(r'\b(?:compare|contrast|explain|describe|list|state)\b', parts[0], re.I):
            parts = parts[1:]
    return [part.strip(' ,;?.') for part in parts if part.strip(' ,;?.')][:max_parts]


def query_variants(query: str, max_parts: int = 4) -> list[str]:
    """Bounded expansion of explicit subjects, with no invented answers.

    Preserve the original question and shared attributes for list/comparison
    subjects. Simple single-topic questions retain their original query.
    """
    requests = question_parts(query)
    if len(requests) > 1 or requests != [query.strip()]:
        return list(dict.fromkeys([query, *requests]))[:max_parts]
    cleaned = _LEAD_IN.sub("", query).strip(" ?.")
    comparison = bool(_COMPARISON.search(query))
    cleaned = _COMPARISON.sub("", cleaned).strip()
    shared = ""
    # In "compare X with Y", the first subject's attribute is not shared by Y.
    explicit_with = comparison and bool(re.search(r"\s+(?:with|to)\s+", cleaned, re.I))
    attribute = None if explicit_with else re.match(r"^(?:the\s+)?(.{3,45}?)\s+of\s+(.+)$", cleaned, re.I)
    if attribute:
        shared, cleaned = attribute.groups()
    separator = r",\s*(?:and\s+)?|\s+(?:and|versus|vs\.?|or" + (r"|with|to" if comparison else "") + r")\s+"
    subjects = re.split(separator, cleaned, flags=re.I)
    parts = [query]
    if len(subjects) > 1:
        for subject in subjects:
            subject = re.sub(r"^(?:a|an|the)\s+", "", subject.strip(" ,?."), flags=re.I)
            if 3 <= len(subject) <= (240 if comparison else 100) and len(subject.split()) <= (30 if comparison else 10):
                part = f"{shared} of {subject}" if shared else subject
                if part.casefold() != query.casefold():
                    parts.append(part)
    return list(dict.fromkeys(parts))[:max_parts]


def evidence_identity(hit):
    return (getattr(hit, 'pack_id', ''), getattr(hit, 'chunk_id', None))


def multi_query_search(searcher: SearcherLike, query: str, top_k: int, candidate_k: int) -> list[Any]:
    """Fuse explicit query variants by weighted reciprocal rank.

    Work on copies so scoring a second query cannot overwrite another query's
    results, including when a searcher caches Evidence objects.
    """
    pooled: dict[str, Any] = {}
    for number, part in enumerate(query_variants(query)):
        weight = 1.0 if number == 0 else 0.55
        for rank, hit in enumerate(searcher.search(part, top_k=top_k, candidate_k=candidate_k), 1):
            key = evidence_identity(hit)
            if key[1] is None:
                continue
            if key not in pooled:
                pooled[key] = copy(hit)
                pooled[key].rrf_score = 0.0
            pooled[key].rrf_score += weight / (60 + rank)
    return sorted(pooled.values(), key=lambda hit: hit.rrf_score, reverse=True)[:min(top_k * 2, 100)]


def hierarchical_search(
    searcher: SearcherLike,
    core_connection: Any,
    query: str,
    top_k: int,
    candidate_k: int = 60,
    documents: int = 4,
    per_document: int = 4,
    neighbor_fetch: Any = None,
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
    known = {evidence_identity(h) for h in expanded}
    if neighbor_fetch is not None:
        for item in neighbor_fetch(expanded, 1, 16):
            if evidence_identity(item) not in known:
                expanded.append(item)
                known.add(evidence_identity(item))
        return expanded
    if core_connection is not None and top_documents:
        try:
            from aura_bio_pipeline.retrieval import Evidence, chunks_in_documents

            siblings = chunks_in_documents(core_connection, top_documents, per_document)
        except Exception:
            siblings = {}
        for document_id, rows in siblings.items():
            for row in rows:
                if ('', row["chunk_id"]) in known:
                    continue
                known.add(('', row["chunk_id"]))
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
    neighbor_fetch: Any = None,
) -> list[Any]:
    """Level 4: decompose the query, retrieve each part, then expand documents."""

    pooled: dict[str, Any] = {}
    for part in decompose_query(query):
        for rank, hit in enumerate(searcher.search(part, top_k=top_k, candidate_k=candidate_k), 1):
            chunk_id = evidence_identity(hit)
            if chunk_id[1] is None:
                continue
            existing = pooled.get(chunk_id)
            # A passage found by several sub-queries is more central, so its
            # fused contribution accumulates.
            if existing is None:
                # Searchers may return cached objects. Fusing on a copy keeps
                # repeat requests and subsequent variants independent.
                fused = copy(hit)
                fused.rrf_score = getattr(hit, "rrf_score", 0.0) + 1 / (60 + rank)
                pooled[chunk_id] = fused
            else:
                existing.rrf_score += 1 / (60 + rank)
    ranked = sorted(pooled.values(), key=lambda item: getattr(item, "rrf_score", 0.0), reverse=True)
    if not ranked:
        return []
    return hierarchical_search(
        _FixedSearcher(ranked), core_connection, query, top_k, candidate_k, documents=5, per_document=3, neighbor_fetch=neighbor_fetch
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
        trimmed = copy(item)
        trimmed.text = " ".join(ordered)
        compressed.append(trimmed)
    return compressed


def retrieve_for_level(
    searcher: SearcherLike,
    core_connection: Any,
    query: str,
    context_level: int,
    retrieve_k: int,
    candidate_k: int | None = None,
    expand_queries: bool = False,
    neighbor_fetch: Any = None,
) -> list[Any]:
    """Dispatch to the retrieval strategy the routed context level calls for."""

    candidate_k = candidate_k or max(retrieve_k * 2, 50)
    if expand_queries:
        ranked = multi_query_search(searcher, query, retrieve_k, candidate_k)
        if context_level >= 3:
            return hierarchical_search(_FixedSearcher(ranked), core_connection, query,
                                       len(ranked), candidate_k, neighbor_fetch=neighbor_fetch)
        return ranked
    if context_level >= 4:
        return deep_search(searcher, core_connection, query, retrieve_k, candidate_k, neighbor_fetch=neighbor_fetch)
    if context_level == 3:
        return hierarchical_search(searcher, core_connection, query, retrieve_k, candidate_k, neighbor_fetch=neighbor_fetch)
    return searcher.search(query, top_k=retrieve_k, candidate_k=candidate_k)
