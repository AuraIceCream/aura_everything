"""Deterministic, provenance-aware delivery of checked study claims."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..verification.schema import Support
from .claims import ClaimDraft
from .prompts import INSUFFICIENT_SUPPORT


TEACHING_TEXT = {
    'reflect': 'Try explaining this in your own words.',
    'inspect_source': 'Inspect the cited source for the supporting passage.',
    'explain_back': 'How would you explain this point to another student?',
    'connect': 'How does this point connect to the question?',
}


@dataclass(frozen=True)
class DeliveredClaims:
    text: str
    decision: str
    status: str
    delivered_ids: list[str]
    omitted_ids: list[str]
    omitted: list[dict[str, str]]
    verification: dict[str, Any]
    draft_verification: dict[str, Any]


def deliver_claims(draft: ClaimDraft, report, *, mode: str = 'tutor') -> DeliveredClaims:
    if mode not in {'tutor', 'strict'}:
        raise ValueError('answer_mode must be tutor or strict')
    if len(report.claims) != len(draft.claims) or len(report.claim_basis) != len(draft.claims):
        raise ValueError('Claim report does not match the structured draft.')
    accepted = {}
    omitted = []
    for item, checked, basis in zip(draft.claims, report.claims, report.claim_basis):
        blockers = [issue for issue in report.issues if issue.severity == 'error' and issue.span == item.claim]
        supported = checked.support == Support.SUPPORTED or (
            checked.support == Support.UNVERIFIABLE and basis.verification_kind in
            {'interpreted', 'ocr_transcribed', 'user_annotated'})
        if not supported or blockers or any(dep not in accepted for dep in item.depends_on):
            reason = ('unsupported' if not supported else 'checker_error' if blockers else 'dependency_removed')
            omitted.append({'id': item.id, 'reason': reason})
        else:
            accepted[item.id] = (item, checked, basis)
    strict_refusal = mode == 'strict' and bool(omitted)
    if strict_refusal:
        accepted = {}
    rendered = []
    delivered_ids = []
    for block in draft.blocks:
        if block.type == 'claim' and block.ref in accepted:
            item = accepted[block.ref][0]
            rendered.append(f"{item.claim} {' '.join(f'[{n}]' for n in item.cite_ids)}")
            delivered_ids.append(item.id)
        elif block.type == 'teaching' and block.after in accepted and not strict_refusal:
            rendered.append(TEACHING_TEXT[block.template])
    if not accepted:
        decision, status, text = 'insufficient_evidence', 'insufficient', INSUFFICIENT_SUPPORT
    else:
        kinds = [basis.verification_kind for _, _, basis in accepted.values()]
        if omitted:
            decision, status = 'partial', 'partial'
        elif all(kind == 'native_verified' for kind in kinds):
            decision, status = 'accept', 'supported_claims'
        else:
            decision, status = 'degraded', 'interpreted_or_transcribed_claims'
        if omitted:
            rendered.append('Some drafted statements were omitted because their supporting evidence was insufficient.')
        text = '\n\n'.join(rendered)
    final_claims = [accepted[claim_id][1].as_dict() for claim_id in delivered_ids]
    final_basis = [report.claim_basis[report.claims.index(accepted[claim_id][1])]
                   for claim_id in delivered_ids]
    verification = {'claims': final_claims,
                    'claim_basis': [dict(claim_index=n, supporting_provenance=list(basis.supporting_provenance),
                                         verification_kind=basis.verification_kind, inputs_verified=basis.inputs_verified)
                                    for n, basis in enumerate(final_basis)],
                    'issues': [issue.as_dict() for issue in report.issues if issue.kind == 'memory_pressure'],
                    'citation_coverage': 1.0 if delivered_ids else 0.0,
                    'grounded_fraction': (sum(b.verification_kind == 'native_verified' for b in final_basis) / len(final_basis)) if final_basis else 0.0,
                    'interpreted_coverage': (sum(b.verification_kind in {'interpreted', 'ocr_transcribed', 'user_annotated'} for b in final_basis) / len(final_basis)) if final_basis else 0.0,
                    'delivery_status': status,
                    'delivered_claim_count': len(delivered_ids),
                    'proposed_claim_count': len(draft.claims),
                    'omitted_claims': omitted}
    return DeliveredClaims(text, decision, status, delivered_ids, [item['id'] for item in omitted],
                           omitted, verification, report.as_dict())
