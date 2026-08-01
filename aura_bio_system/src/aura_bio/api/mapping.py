"""Translate between the frontend's vocabulary and the runtime's.

The React app predates the runtime and uses shorter enum names and a
`context_depth` word instead of a numeric level. Keeping the translation in one
place means neither side has to change to match the other.
"""

from __future__ import annotations

from typing import Any

from ..pipeline import Answer
from ..routing.schema import LearnerLevel, TeachingMode
from ..tracing import Trace

# -- request enums ----------------------------------------------------------

_LEVEL_IN: dict[str, LearnerLevel] = {
    "high_school": LearnerLevel.HIGH_SCHOOL,
    "undergraduate": LearnerLevel.UNDERGRADUATE,
    "postgraduate": LearnerLevel.POSTGRADUATE,
    "research": LearnerLevel.RESEARCH,
}

_MODE_IN: dict[str, TeachingMode] = {
    "direct": TeachingMode.DIRECT_ANSWER,
    "guided": TeachingMode.GUIDED_EXPLANATION,
    "socratic": TeachingMode.SOCRATIC,
    "exam": TeachingMode.EXAM,
    "revision": TeachingMode.REVISION,
    "research": TeachingMode.RESEARCH,
    "teach_back": TeachingMode.TEACH_BACK,
}

_MODE_OUT = {value: key for key, value in _MODE_IN.items()}
_MODE_OUT[TeachingMode.HOMEWORK_SUPPORT] = "guided"
_MODE_OUT[TeachingMode.MISCONCEPTION_REPAIR] = "guided"

_CONTEXT_DEPTH_TO_LEVEL: dict[str, int] = {
    "none": 0,
    "standard": 1,
    "expanded": 2,
    "hierarchical": 3,
}


def learner_level(value: str | None) -> LearnerLevel | None:
    return _LEVEL_IN.get(value or "")


def teaching_mode(value: str | None) -> TeachingMode | None:
    return _MODE_IN.get(value or "")


def context_level(value: str | None) -> int | None:
    return _CONTEXT_DEPTH_TO_LEVEL.get(value or "")


def teaching_mode_out(label: str) -> str:
    try:
        return _MODE_OUT.get(TeachingMode(label), "guided")
    except ValueError:
        return "guided"


# -- source classification --------------------------------------------------

_SOURCE_TYPE: dict[str, str] = {
    "wikipedia_biology": "encyclopedia",
    "pmc_oa_comm_xml": "research paper",
    "pubmed_filtered": "research paper",
    "nlm_litarch_biology": "textbook",
    "biolibretexts_catalog": "textbook",
    "uniprot_sprot": "knowledge base",
    "gene_ontology": "knowledge base",
    "mesh_descriptors": "knowledge base",
    "reactome_summaries": "knowledge base",
}


def source_type(source_id: str) -> str:
    return _SOURCE_TYPE.get(source_id, "reference")


# -- response shaping (runtime Trace -> frontend Run) -----------------------

_CONFIDENCE_BANDS = ((0.75, "high"), (0.45, "medium"))


def _confidence_band(value: float) -> str:
    for threshold, label in _CONFIDENCE_BANDS:
        if value >= threshold:
            return label
    return "low"


_VERIFICATION_OUT = {
    "accept": "verified",
    "revise": "partial",
    "insufficient_evidence": "unsupported",
}


def evidence_to_citation(item: Any, rank: int) -> dict[str, Any]:
    """Shape one runtime Evidence object into the frontend Citation type."""

    return {
        "citation_id": f"cit-{rank}",
        "source_id": getattr(item, "source_id", "") or "",
        "source_title": getattr(item, "title", "") or "Untitled",
        "source_type": source_type(getattr(item, "source_id", "") or ""),
        "section": getattr(item, "section", None) or "",
        "chunk_id": getattr(item, "chunk_id", "") or "",
        "excerpt": (getattr(item, "text", "") or "")[:600],
        "url": getattr(item, "url", None),
        "license_id": getattr(item, "license_id", None) or "unknown",
        "dense_score": None,
        "sparse_score": None,
        "rerank_score": getattr(item, "rerank_score", None),
        "rank": rank,
    }


_STAGE_MODELS = {
    "retrieval": "BGE base v1.5 + FTS5",
    "rerank": "BGE reranker base",
}


def trace_to_events(trace: Trace, model_name: str) -> list[dict[str, Any]]:
    """Turn a runtime Trace into the frontend's ordered TraceEvent list."""

    events: list[dict[str, Any]] = []
    order = ["routing", "retrieval", "rerank", "evidence_selection", "generation",
             "verification", "critique"]
    stage_label = {
        "routing": "routing",
        "retrieval": "retrieval",
        "rerank": "retrieval",
        "evidence_selection": "evidence",
        "generation": "generation",
        "verification": "verification",
        "critique": "critique",
    }
    for stage in order:
        if stage not in trace.stage_ms:
            continue
        events.append(
            {
                "event_id": f"evt-{stage}",
                "stage": stage_label[stage],
                "status": "completed",
                "timestamp": _iso(trace.created_at),
                "duration_ms": round(trace.stage_ms[stage], 1),
                "model": _STAGE_MODELS.get(stage, model_name if stage == "generation" else None),
                "summary": _stage_summary(stage, trace),
                "details": _stage_details(stage, trace),
            }
        )
    if len(trace.revisions) > 1:
        events.append(
            {
                "event_id": "evt-revision",
                "stage": "revision",
                "status": "completed",
                "timestamp": _iso(trace.created_at),
                "model": model_name,
                "summary": f"Revised once after verification ({trace.revisions[-1]['decision']}).",
            }
        )
    events.append(
        {
            "event_id": "evt-complete",
            "stage": "complete",
            "status": "completed",
            "timestamp": _iso(trace.created_at),
            "summary": f"Answer completed with decision '{trace.decision}'.",
        }
    )
    return events


def _stage_summary(stage: str, trace: Trace) -> str:
    if stage == "routing":
        route = trace.route
        return (
            f"Classified as {route.get('task_type', {}).get('label', '?')} in "
            f"{route.get('subdomain', {}).get('label', '?')} at "
            f"{route.get('learner_level', {}).get('label', '?')} level."
        )
    if stage == "retrieval":
        r = trace.retrieval
        return f"Hybrid search returned {r.get('candidates', 0)} candidates across channels."
    if stage == "rerank":
        rr = trace.rerank or {}
        return f"Cross-encoder reranked {rr.get('candidates', 0)} candidates to {rr.get('selected', 0)}."
    if stage == "evidence_selection":
        return f"Selected {len(trace.evidence)} passages for grounding."
    if stage == "generation":
        return "Generated a level-adapted, citation-marked answer."
    if stage == "verification":
        last = trace.revisions[0]["verification"] if trace.revisions else {}
        return (
            f"{len(last.get('claims', []))} claims checked; "
            f"{last.get('unsupported_claim_count', 0)} unsupported."
        )
    if stage == "critique":
        return "External critique applied."
    return stage


def _stage_details(stage: str, trace: Trace) -> dict[str, Any] | None:
    if stage == "routing":
        return trace.route.get("task_type") and {
            "task": trace.route["task_type"]["label"],
            "subdomain": trace.route["subdomain"]["label"],
            "context_level": trace.route.get("context_level"),
        }
    if stage == "retrieval":
        return trace.retrieval.get("channels")
    if stage == "verification" and trace.revisions:
        v = trace.revisions[0]["verification"]
        return {
            "supported_claims": sum(
                1 for c in v.get("claims", []) if c.get("support") == "supported"
            ),
            "unsupported_claims": v.get("unsupported_claim_count", 0),
            "grounded_fraction": v.get("grounded_fraction"),
        }
    return None


def answer_payload(answer: Answer, model_name: str) -> dict[str, Any]:
    """Shape the runtime Answer into the frontend Answer type."""

    verification = answer.trace.revisions[0]["verification"] if answer.trace.revisions else {}
    limitations: list[str] = []
    for issue in verification.get("issues", []):
        if issue.get("severity") in ("warning", "error"):
            limitations.append(issue.get("detail", ""))
    return {
        "markdown": answer.text,
        "citations": [
            evidence_to_citation(_EvidenceView(item), index)
            for index, item in enumerate(answer.trace.evidence, 1)
        ],
        "confidence": _confidence_band(answer.confidence),
        "confidence_rationale": (
            f"Grounded fraction {verification.get('grounded_fraction', 0):.2f} over "
            f"{len(verification.get('claims', []))} checked claims."
        ),
        "verification_status": _VERIFICATION_OUT.get(answer.decision, "pending"),
        "revised": len(answer.trace.revisions) > 1,
        "limitations": limitations[:5],
        "latency_ms": round(answer.trace.latency_ms, 1),
    }


class _EvidenceView:
    """Adapts a trace evidence dict back to attribute access for shaping."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        return self._data.get(name)


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
