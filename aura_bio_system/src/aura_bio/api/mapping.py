"""Translate between the frontend's vocabulary and the runtime's.

The React app predates the runtime and uses shorter enum names and a
`context_depth` word instead of a numeric level. Keeping the translation in one
place means neither side has to change to match the other.
"""

from __future__ import annotations

import re
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
    "degraded": "partial",
    "partial": "partial",
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
        **({'pack_id': item.pack_id, 'document_id': item.document_id,
            'unit_ids': list(item.unit_ids), 'locators': [loc.as_dict() if hasattr(loc, 'as_dict') else loc for loc in item.locators],
            'generation': item.generation,
            'provenance':getattr(item,'provenance','native_text') or 'native_text',
            'provenance_details':getattr(item,'provenance_details',{}) or {},
            'preview_url': f'/api/v1/study-packs/{item.pack_id}/documents/{item.document_id}/units/{item.unit_ids[0]}' if item.unit_ids else None,
            'source_type': 'study material', 'license_id': 'user-provided'} if getattr(item, 'pack_id', None) else {}),
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
                "model": {'sparse': 'FTS5', 'hybrid': 'BGE + FTS5', 'mixed': 'Per-source sparse / hybrid'}.get(trace.retrieval.get('mode'), 'Pack retrieval') if stage == 'retrieval' and trace.retrieval.get('evidence_scope') == 'pack_only' else _STAGE_MODELS.get(stage, model_name if stage == "generation" else None),
                "summary": _stage_summary(stage, trace),
                "details": _stage_details(stage, trace),
            }
        )
    if trace.revision_count:
        events.append(
            {
                "event_id": "evt-revision",
                "stage": "revision",
                "status": "completed",
                "timestamp": _iso(trace.created_at),
                "model": model_name,
                "summary": f"Ran {trace.revision_count} revision(s); selected answer decision: {trace.decision}.",
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
        if r.get('evidence_scope') == 'pack_only':
            return f"Pack-only {r.get('mode', 'sparse')} search returned {r.get('candidates', 0)} candidates in generation {r.get('generation', '?')}."
        return f"Hybrid search returned {r.get('candidates', 0)} candidates across channels."
    if stage == "rerank":
        rr = trace.rerank or {}
        return f"Cross-encoder reranked {rr.get('candidates', 0)} candidates to {rr.get('selected', 0)}."
    if stage == "evidence_selection":
        return f"Selected {len(trace.evidence)} passages for grounding."
    if stage == "generation":
        return "Generated a level-adapted, citation-marked answer."
    if stage == "verification":
        last = trace.final_verification
        return (
            f"{len(last.get('claims', []))} claims checked; "
            f"{last.get('unsupported_claim_count', 0)} unsupported."
        )
    if stage == "critique":
        return "External critique applied."
    return stage


def _stage_details(stage: str, trace: Trace) -> dict[str, Any] | None:
    """What each stage actually decided, in enough detail to audit it.

    The trace page is the project's answer to "why did it say that", so a
    summary line is not enough: a reader needs the routed labels and where
    they came from, which retrieval channels contributed, which passages were
    kept, which checkers fired, and the per-claim entailment labels the NLI
    model produced.
    """

    if stage == "routing":
        route = trace.route
        if not route.get("task_type"):
            return None

        def dimension(name: str) -> dict[str, Any] | None:
            entry = route.get(name)
            if not isinstance(entry, dict):
                return None
            return {
                "label": entry.get("label"),
                "confidence": entry.get("confidence"),
                # "llm" here means the trained encoder classifier answered;
                # "rules" means the hand-written table did.
                "decided_by": entry.get("source"),
                "matched": list(entry.get("matched") or ())[:4],
            }

        return {
            "task_type": dimension("task_type"),
            "subdomain": dimension("subdomain"),
            "learner_level": dimension("learner_level"),
            "teaching_mode": dimension("teaching_mode"),
            "context_level": route.get("context_level"),
            "retrieve_k": route.get("retrieve_k"),
            "rerank_k": route.get("rerank_k"),
            "max_revisions": route.get("max_revisions"),
            "explicit_overrides": list(route.get("explicit_overrides") or ()),
        }

    if stage == "retrieval":
        retrieval = dict(trace.retrieval)
        return {
            "strategy": retrieval.get("strategy"),
            "candidates": retrieval.get("candidates"),
            "channels": retrieval.get("channels"),
        }

    if stage == "rerank":
        return dict(trace.rerank or {}) or None

    if stage == "evidence_selection":
        return {
            "selected": len(trace.evidence),
            "passages": [
                {
                    "rank": index,
                    "title": item.get("title"),
                    "source_id": item.get("source_id"),
                    "chunk_id": item.get("chunk_id"),
                }
                for index, item in enumerate(trace.evidence, 1)
            ],
        }

    if stage == "verification" and trace.revisions:
        report = trace.final_verification
        claims = report.get("claims", [])
        support_counts: dict[str, int] = {}
        for claim in claims:
            key = str(claim.get("support"))
            support_counts[key] = support_counts.get(key, 0) + 1
        checkers: dict[str, int] = {}
        for issue in report.get("issues", []):
            key = f"{issue.get('checker')}/{issue.get('kind')}"
            checkers[key] = checkers.get(key, 0) + 1
        return {
            "decision": report.get("decision"),
            "grounded_fraction": report.get("grounded_fraction"),
            "citation_coverage": report.get("citation_coverage"),
            "claims_checked": len(claims),
            "unsupported_claims": report.get("unsupported_claim_count", 0),
            # Per-claim entailment labels, which is the checker most people
            # want to inspect and the one a summary hides completely.
            "claim_support": support_counts,
            "checkers_fired": checkers,
            "issues": [
                {
                    "checker": issue.get("checker"),
                    "kind": issue.get("kind"),
                    "severity": issue.get("severity"),
                    "detail": issue.get("detail"),
                }
                for issue in report.get("issues", [])
            ],
            "claims": [
                {
                    "index": claim.get("index"),
                    "text": claim.get("text"),
                    "support": claim.get("support"),
                    "certainty": claim.get("certainty"),
                    "evidence_chunk_ids": claim.get("evidence_chunk_ids"),
                    **({'verification_kind':claim.get('verification_kind'),'inputs_verified':claim.get('inputs_verified')} if 'verification_kind' in claim else {}),
                    **({'verification_kind':claim.get('verification_kind'),'inputs_verified':claim.get('inputs_verified')} if 'verification_kind' in claim else {}),
                }
                for claim in claims
            ],
            "numerical": report.get("numerical") or [],
        }

    if stage == "critique" and trace.revisions:
        critique = trace.final_record.get("critique")
        return dict(critique) if critique else None

    return None


def answer_payload(answer: Answer, model_name: str) -> dict[str, Any]:
    """Shape the runtime Answer into the frontend Answer type."""

    verification = answer.trace.final_verification
    limitations: list[str] = []
    for issue in verification.get("issues", []):
        if issue.get("severity") in ("warning", "error"):
            limitations.append(issue.get("detail", ""))
    if verification.get('omitted_claims'):
        limitations.append(f"{len(verification['omitted_claims'])} drafted claim(s) were left out because the selected material did not support them.")
    visual = answer.trace.final_record.get('visual')
    no_visual_needed = bool(visual and visual.get('status') == 'omitted' and
        visual.get('metadata', {}).get('requested_mode') == 'auto' and
        visual.get('metadata', {}).get('selected_kind') == 'none' and not visual.get('limitations'))
    if visual:
        limitations.extend(visual.get('limitations', []))
    elif answer.trace.retrieval.get('visual_output', 'none') != 'none':
        visual = {'status': 'omitted', 'spec': None, 'metadata': {}, 'limitations': [
            'Visuals require eligible source-checked claims; this answer remains text-only.']}
        limitations.extend(visual['limitations'])
    kinds={b.get('verification_kind') for b in verification.get('claim_basis',[])}
    status=_VERIFICATION_OUT.get(answer.decision,'pending')
    if answer.decision in {'accept','degraded'}:
        if 'interpreted' in kinds: status='interpreted'
        elif 'ocr_transcribed' in kinds: status='transcribed'
        elif 'user_annotated' in kinds: status='annotated'
    delivery = answer.trace.final_record.get('delivery')
    visible_citations = None
    if delivery is not None:
        ids = delivery.get('delivered_cite_ids')
        if ids is None:  # Traces created before claim citation IDs were recorded.
            ids = [int(number) for number in re.findall(r'\[(\d+)\]', answer.text)]
        visible_citations = {number for number in ids if isinstance(number, int)}
    return {
        "markdown": answer.text,
        "citations": [
            evidence_to_citation(_EvidenceView(item), index)
            for index, item in enumerate(answer.trace.evidence, 1)
            if visible_citations is None or index in visible_citations
        ],
        "confidence": _confidence_band(answer.confidence),
        "confidence_rationale": (
            f"Grounded fraction {verification.get('grounded_fraction', 0):.2f} over "
            f"{len(verification.get('claims', []))} checked claims."
        ),
        "verification_status": status,
        "revised": answer.trace.revision_count > 0,
        "limitations": limitations[:5],
        "latency_ms": round(answer.trace.latency_ms, 1),
        "delivery": answer.trace.final_record.get('delivery'),
        **({'visuals': [visual]} if visual is not None and not no_visual_needed else {}),
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
