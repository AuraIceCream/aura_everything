"""Retain the selected delivery, never reconstruct factual claims from prose."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
from ..study.claims import StructuredClaim


@dataclass(frozen=True)
class VisualContext:
    claims: tuple[StructuredClaim, ...]
    claims_by_id: Mapping[str, StructuredClaim]
    basis_by_id: Mapping[str, Mapping[str, Any]]
    evidence: tuple[Any, ...]


def build_visual_context(draft, delivered, evidence):
    if draft is None or delivered is None:
        return None
    by_id = {item.id: item for item in draft.claims}
    ids = tuple(delivered.delivered_ids)
    bases = delivered.verification.get('claim_basis', [])
    if len(ids) != len(set(ids)) or any(id not in by_id for id in ids) or len(bases) != len(ids):
        raise ValueError('Visual context does not match the selected delivered claims.')
    if any(any(dep not in ids for dep in by_id[id].depends_on) for id in ids):
        raise ValueError('Visual context contains a removed dependency.')
    return VisualContext(tuple(by_id[id] for id in ids),
        MappingProxyType({id: by_id[id] for id in ids}),
        MappingProxyType({id: MappingProxyType(dict(basis)) for id, basis in zip(ids, bases)}),
        tuple(evidence))


def build_core_visual_context(trace, evidence):
    """Project final NLI findings; do not regenerate or upgrade core prose."""
    import re
    from ..verification.provenance import _claim_spans
    record = trace.final_record
    report = record.get('verification', {})
    if (trace.decision not in {'accept', 'degraded'} or record.get('answer') != trace.final_answer
            or report.get('support_backend') != 'nli'
            or report.get('checker_status', {}).get('nli', '').startswith('unavailable')):
        return None
    spans = {}
    for claim, span in _claim_spans(trace.final_answer):
        spans.setdefault(claim, []).append(span)
    claims, bases, seen = [], {}, set()
    for finding in report.get('claims', []):
        index, text = finding.get('index'), finding.get('text')
        if type(index) is not int or index < 0 or index in seen: return None
        seen.add(index)
        if finding.get('support') != 'supported' or text not in spans: continue
        supporting = set(finding.get('evidence_chunk_ids', ()))
        cited = {int(n) for span in spans[text] for n in re.findall(r'\[(\d+)\]', span)}
        citations = tuple(sorted(n for n in cited if 1 <= n <= len(evidence)
            and evidence[n - 1].chunk_id in supporting
            and getattr(evidence[n - 1], 'provenance', 'native_text') == 'native_text'))
        if not citations: continue
        id = f'core-c{index}'
        claims.append(StructuredClaim(id, text, citations))
        bases[id] = MappingProxyType({'verification_kind': 'native_verified', 'inputs_verified': True,
            'supporting_provenance': [{'chunk_id': evidence[n - 1].chunk_id, 'provenance': 'native_text'}
                                     for n in citations]})
        if len(claims) == 24: break
    if not claims: return None
    return VisualContext(tuple(claims), MappingProxyType({c.id: c for c in claims}),
                         MappingProxyType(bases), tuple(evidence))
