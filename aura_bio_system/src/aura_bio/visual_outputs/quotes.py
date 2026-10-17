"""Private decoding adapter: exact quotes in, original character bindings out.

This is not fuzzy matching or evidence verification. Existing grounding still
checks claim identity, population, units, provenance and relationship strength.
"""
from copy import deepcopy
import json
from .schema import obj, _load_visual, _validate


QUOTE = obj({'cite_id': {'type': 'integer', 'minimum': 1},
             'quote': {'type': 'string', 'minLength': 1, 'maxLength': 2400},
             'context': {'type': 'string', 'maxLength': 6000}})


def quote_schema(schema):
    schema = deepcopy(schema)
    def visit(value):
        if isinstance(value, dict):
            if set(value.get('properties', {})) == {'cite_id', 'start', 'end'}:
                value.clear(); value.update(deepcopy(QUOTE)); return
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(schema)
    return schema


def _unique_start(text, quote):
    first = text.find(quote)
    if first < 0 or text.find(quote, first + 1) >= 0:
        raise ValueError('Source quote is missing or ambiguous.')
    return first


def resolve_quotes(raw, schema, context):
    data = _load_visual(raw)
    _validate(data, schema)
    def visit(value):
        if isinstance(value, dict):
            if set(value) == {'cite_id', 'quote', 'context'}:
                cite, quote, scope = value['cite_id'], value['quote'], value['context']
                if not 1 <= cite <= len(context.evidence): raise ValueError('Unknown quote source.')
                source = context.evidence[cite - 1].text
                base = _unique_start(source, scope) if scope else 0
                start = base + _unique_start(scope or source, quote)
                value.clear(); value.update(cite_id=cite, start=start, end=start + len(quote))
                return
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(data)
    return json.dumps(data, ensure_ascii=False)
