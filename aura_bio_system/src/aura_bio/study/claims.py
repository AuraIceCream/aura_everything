"""Bounded, model-independent wire format for grounded study claims."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


MAX_CLAIMS = 24
GENERATION_MAX_CLAIMS = 6
MAX_CLAIM_CHARS = 1200
MAX_JSON_BYTES = 65536
TEACHING_TEMPLATES = frozenset({'reflect', 'inspect_source', 'explain_back', 'connect'})
_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,31}\Z')


@dataclass(frozen=True)
class StructuredClaim:
    id: str
    claim: str
    cite_ids: tuple[int, ...]
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimBlock:
    type: str
    ref: str | None = None
    template: str | None = None
    after: str | None = None


@dataclass(frozen=True)
class ClaimDraft:
    version: int
    claims: tuple[StructuredClaim, ...]
    blocks: tuple[ClaimBlock, ...]


def merge_claims(base: ClaimDraft, delivered_ids, supplement: ClaimDraft) -> ClaimDraft:
    """Keep checked base facts; append new proposals with collision-free IDs.

    This does not confer support on any claim: the entire merged draft must be
    checked again. Citation numbers still refer to the unchanged evidence list.
    """
    from dataclasses import replace
    wanted = set(delivered_ids)
    retained = []
    kept = set()
    for item in base.claims:
        if item.id in wanted and all(dep in kept for dep in item.depends_on):
            retained.append(item)
            kept.add(item.id)
    blocks = [block for block in base.blocks
              if (block.ref if block.type == 'claim' else block.after) in kept]
    used = {item.id for item in base.claims}
    def signature(item):
        return (' '.join(item.claim.casefold().split()), tuple(sorted(item.cite_ids)), item.depends_on)
    existing = {signature(item): item.id for item in retained}
    aliases = {}
    for item in supplement.claims:
        depends = tuple(aliases[dep] for dep in item.depends_on)
        proposal = replace(item, depends_on=depends)
        key = signature(proposal)
        if key in existing:
            aliases[item.id] = existing[key]
            continue
        if len(retained) >= MAX_CLAIMS:
            raise ValueError('Enriched draft exceeds the claim limit.')
        n = 1
        while f'c{n}' in used:
            n += 1
        claim_id = f'c{n}'
        used.add(claim_id)
        aliases[item.id] = claim_id
        existing[key] = claim_id
        retained.append(replace(proposal, id=claim_id))
        blocks.append(ClaimBlock('claim', ref=claim_id))
        blocks.extend(replace(block, after=claim_id) for block in supplement.blocks
                      if block.type == 'teaching' and block.after == item.id)
    return ClaimDraft(1, tuple(retained), tuple(blocks))


def claim_schema() -> dict[str, Any]:
    """Schema sent to Ollama; local validation below remains authoritative."""
    claim = {'type': 'object', 'additionalProperties': False,
             'required': ['claim', 'cite_ids'],
             'properties': {
                 'claim': {'type': 'string', 'maxLength': 400},
                 'cite_ids': {'type': 'array', 'items': {'type': 'integer'}},
             }}
    return {'type': 'object', 'additionalProperties': False,
            'required': ['version', 'claims'],
            'properties': {'version': {'type': 'integer', 'enum': [1]},
                           'claims': {'type': 'array', 'maxItems': GENERATION_MAX_CLAIMS, 'items': claim}}}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON field: {key}')
        result[key] = value
    return result


def parse_claims(raw: str, evidence_count: int) -> ClaimDraft:
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_JSON_BYTES:
        raise ValueError('Structured answer exceeds the size limit.')
    if isinstance(evidence_count, bool) or not isinstance(evidence_count, int) or evidence_count < 0:
        raise ValueError('Invalid evidence count.')
    try:
        data = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError('Invalid structured answer JSON.') from exc
    if not isinstance(data, dict) or set(data) not in ({'version', 'claims'}, {'version', 'claims', 'blocks'}) or data['version'] != 1 or type(data['version']) is not int:
        raise ValueError('Invalid structured answer envelope.')
    rows, blocks = data['claims'], data.get('blocks')
    if not isinstance(rows, list) or len(rows) > MAX_CLAIMS or (blocks is not None and (not isinstance(blocks, list) or len(blocks) > MAX_CLAIMS * 2)):
        raise ValueError('Too many claims or blocks.')
    claims = []
    seen = set()
    model_rows = bool(rows) and all(isinstance(row, dict) and set(row) == {'claim', 'cite_ids'} for row in rows)
    if model_rows and blocks is not None:
        raise ValueError('Model claims use deterministic display blocks.')
    for row in rows:
        if not isinstance(row, dict) or not (model_rows or {'id', 'claim', 'cite_ids'} <= set(row)) or set(row) - {'id', 'claim', 'cite_ids', 'depends_on'}:
            raise ValueError('Invalid claim fields.')
        claim_id, statement = (f'c{len(claims) + 1}' if model_rows else row['id']), row['claim']
        cites, depends = row['cite_ids'], row.get('depends_on', [])
        if not isinstance(claim_id, str) or not _ID.fullmatch(claim_id) or claim_id in seen:
            raise ValueError('Duplicate or invalid claim ID.')
        if not isinstance(statement, str) or not statement.strip() or len(statement) > MAX_CLAIM_CHARS or '\n' in statement:
            raise ValueError('Invalid claim text.')
        if not isinstance(cites, list) or not cites or len(cites) != len(set(map(str, cites))) or any(type(n) is not int or not 1 <= n <= evidence_count for n in cites):
            raise ValueError('Invalid evidence citation.')
        if not isinstance(depends, list) or any(not isinstance(ref, str) or ref not in seen for ref in depends) or len(depends) != len(set(depends)):
            raise ValueError('Dependency must name a distinct earlier claim.')
        claims.append(StructuredClaim(claim_id, statement.strip(), tuple(cites), tuple(depends)))
        seen.add(claim_id)
    if blocks is None:
        return ClaimDraft(1, tuple(claims), tuple(ClaimBlock('claim', ref=item.id) for item in claims))
    parsed_blocks = []
    displayed = set()
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError('Invalid answer block.')
        if block.get('type') == 'claim' and set(block) == {'type', 'ref'} and block['ref'] in seen and block['ref'] not in displayed:
            displayed.add(block['ref'])
            parsed_blocks.append(ClaimBlock('claim', ref=block['ref']))
        elif (block.get('type') == 'teaching' and set(block) == {'type', 'template', 'after'}
              and block['template'] in TEACHING_TEMPLATES and block['after'] in displayed):
            parsed_blocks.append(ClaimBlock('teaching', template=block['template'], after=block['after']))
        else:
            raise ValueError('Unsupported or unanchored answer block.')
    if displayed != seen:
        raise ValueError('Every claim must have one display block.')
    return ClaimDraft(1, tuple(claims), tuple(parsed_blocks))
