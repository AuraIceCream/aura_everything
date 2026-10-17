"""Rank verified answers without consulting an evaluation answer key."""

from __future__ import annotations

from typing import Any

from ..verification.checkers import content_tokens, split_claims


def candidate_quality(query: str, answer: str, verification: dict[str, Any],
                      critique: dict[str, Any] | None, decision: str,
                      provenance: dict[str, Any]) -> tuple[tuple[float, ...], dict[str, Any]]:
    """Prefer clean candidates, then completeness, citations and concision.

    This is an explainable ranking heuristic, not a correctness probability.
    More keyword overlap or citations cannot compensate for a blocking error.
    Exact duplicate claims do not increase coverage or support.
    """
    claims = verification.get("claims", [])
    issues = verification.get("issues", [])
    delivery_kinds = {"truncated_answer", "source_context_echo"}
    blocking = sum(issue.get("severity") == "error" for issue in issues)
    factual_blocking = sum(issue.get("severity") == "error" and issue.get("kind") not in delivery_kinds
                           for issue in issues)
    # Include historical warning-level delivery flags when replaying traces.
    delivery_errors = sum(issue.get("kind") in delivery_kinds for issue in issues)
    contradictions = sum(claim.get("support") == "contradictory" for claim in claims)
    trusted = critique if critique and critique.get("trusted") else {}
    unchecked = bool(critique is not None and not critique.get("trusted"))
    critic_errors = sum(len(trusted.get(key, [])) for key in (
        "unsupported_claims", "terminology_errors", "process_errors"))
    asked = content_tokens(query)
    coverage = len(asked & content_tokens(answer)) / max(1, len(asked))
    sentences = split_claims(answer)
    unique = {sentence.casefold().strip() for sentence in sentences}
    repetition = 1.0 - len(unique) / max(1, len(sentences)) if sentences else 0.0
    supported = {claim["text"].casefold() for claim in claims if claim.get("support") == "supported"}
    support_rate = len(supported) / max(1, len({claim["text"].casefold() for claim in claims}))
    is_pack=verification.get('checker_status',{}).get('scope')=='pack_only'
    if is_pack: support_rate=max(support_rate,float(verification.get('interpreted_coverage',0)))
    key = (
        float(bool(answer.strip())), -float(factual_blocking), -float(delivery_errors),
        -float(blocking), -float(unchecked), float(decision == "accept" or is_pack and decision=='degraded'),
        -float(contradictions), -float(critic_errors),
        -float(len(trusted.get("missing_concepts", []))), coverage,
        -repetition, float(provenance.get("claim_citation_rate", 0.0)), support_rate,
    )
    details = {"blocking_errors": blocking, "factual_blocking_errors": factual_blocking,
               "delivery_errors": delivery_errors, "critic_unchecked": unchecked, "contradictions": contradictions,
               "critic_errors": critic_errors, "question_term_coverage": round(coverage, 4),
               "repeated_claim_fraction": round(repetition, 4), "selection_key": list(key)}
    return key, details
