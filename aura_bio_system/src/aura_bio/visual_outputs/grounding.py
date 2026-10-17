"""Conservative visual transcription from retained facts and exact source spans."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import re
import unicodedata
from .schema import VisualResult

TITLES = {'source': 'Source view', 'diagram': 'Source-grounded diagram',
          'comparison': 'Source-grounded comparison', 'procedure': 'Source-stated procedure',
          'plot': 'Source-stated data'}
_KINDS = ('native_verified', 'interpreted', 'ocr_transcribed', 'user_annotated', 'native_unverified')


def normalized(text):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def support_for(ids, context):
    bases = [context.basis_by_id[id] for id in ids]
    kinds = [basis.get('verification_kind', 'unsupported') for basis in bases]
    if not kinds or any(kind not in _KINDS for kind in kinds): raise ValueError('Unsupported visual fact.')
    cites = sorted({n for id in ids for n in context.claims_by_id[id].cite_ids})
    if any(not 1 <= n <= len(context.evidence) for n in cites): raise ValueError('Invalid retained citation.')
    return {'claim_ids': list(ids), 'cite_ids': [f'cit-{n}' for n in cites],
            'status': max(kinds, key=_KINDS.index),
            'provenance': sorted({getattr(context.evidence[n-1], 'provenance', 'native_text') for n in cites})}


def _contains(needle, haystack):
    return bool(normalized(needle)) and (' ' + normalized(needle) + ' ') in (' ' + normalized(haystack) + ' ')


def _label(item, context, key='label'):
    ids = item['claim_ids']; text = item[key]
    if not any(_contains(text, context.claims_by_id[id].claim) for id in ids):
        raise ValueError('Visual label is not in its retained claim.')
    item['support'] = support_for(ids, context)


def _relation(edge, left, right, context, relation=None):
    relation = relation or edge['relation']
    label = edge.get('label', 'precedes')
    vocabulary = {'activates': r'activat', 'inhibits': r'inhibit', 'causes': r'caus',
                  'associated_with': r'associat', 'part_of': r'part of|belongs to',
                  'precedes': r'preced|before|then', 'visible_arrow': r'arrow|points to'}
    if not re.search(vocabulary[relation], label, re.I): raise ValueError('Relationship type disagrees with its label.')
    proposition = normalized(f'{left} {label} {right}')
    claims = [context.claims_by_id[id].claim for id in edge['claim_ids']]
    exact = any(proposition == normalized(claim) for claim in claims)
    if relation == 'precedes' and not exact:
        exact = any(re.fullmatch(r'(?:first )?' + re.escape(normalized(left)) + r'(?: and)? then '
                                + re.escape(normalized(right)), normalized(claim)) for claim in claims)
    if not exact:
        # Labels alone, partial substrings, dropped qualifiers and association
        # never establish a new edge. Version 1 transcribes a checked relation;
        # paraphrases needing a new inference are declined, not rescored away.
        raise ValueError('Relationship is not a complete retained proposition.')
    edge['support'] = support_for(edge['claim_ids'], context)
    if relation == 'visible_arrow' and edge['support']['status'] == 'native_verified':
        # Native text can state that an arrow exists, not that its mechanism is true.
        edge['support']['status'] = 'interpreted'


def _binding(binding, ids, context):
    cite = binding['cite_id']
    if not any(cite in context.claims_by_id[id].cite_ids for id in ids):
        raise ValueError('Binding is outside the referenced claims.')
    evidence = context.evidence[cite - 1]
    text = evidence.text[binding['start']:binding['end']]
    return text, evidence


def _bound_text(item, context):
    _label(item, context, 'text')
    if not any(_contains(item['text'], _binding(binding, item['claim_ids'], context)[0])
               for binding in item['bindings']):
        raise ValueError('Text is not in the bound source span.')


def _sentence_span(text, start, end):
    # Text boundaries, not citation position, establish one scoped observation.
    boundaries = [match.end() for match in re.finditer(r'[.!?;](?:\s|$)', text)]
    lower = max([0] + [n for n in boundaries if n <= start])
    upper = min([len(text)] + [n for n in boundaries if n >= end])
    return lower, upper


def _plot(payload, context):
    # Axis/series names are presentation, never an extra channel for model facts.
    payload['x_label'] = 'Group' if payload['chart_type'] == 'bar' else 'Source x'
    payload['y_label'] = 'Value'
    for series_index, series in enumerate(payload['series'], 1):
        series['label'] = f'Series {series_index}'
        if series['unit'] != payload['unit']: raise ValueError('Incompatible plot units.')
        xs = []
        for point in series['points']:
            ids = point['claim_ids']; support = support_for(ids, context)
            if support['status'] != 'native_verified' or support['provenance'] != ['native_text']:
                raise ValueError('Only native checked numbers may be plotted.')
            values = {key: _binding(binding, ids, context) for key, binding in point['bindings'].items()}
            if any(getattr(evidence, 'provenance', 'native_text') != 'native_text' for _, evidence in values.values()):
                raise ValueError('Interpreted numeric binding.')
            if values['group'][0].strip() != point['group'] or values['unit'][0].strip() != series['unit']:
                raise ValueError('Plot label or unit differs from its source.')
            if point['value'] is None:
                if not re.fullmatch(r'(?:not (?:reported|stated|measured)|missing)', values['value'][0].strip(), re.I):
                    raise ValueError('Missing observation is not source-stated.')
            elif values['value'][0].strip() != point['value']:
                raise ValueError('Plot value differs from its source.')
            core = ['group', 'value', 'unit']
            if payload['chart_type'] in {'line', 'scatter'} or 'x' in point:
                if 'x' not in point or 'x' not in values or values['x'][0].strip() != point['x']:
                    raise ValueError('Numeric x must be source-bound.')
                xs.append(Decimal(point['x'])); core.append('x')
                if payload.get('x_unit'):
                    if 'x_unit' not in values or values['x_unit'][0].strip() != payload['x_unit']:
                        raise ValueError('Missing x unit binding.')
                    core.append('x_unit')
            if re.search(r'%|percent|proportion|rate', series['unit'], re.I):
                if not {'scope', 'denominator'} <= values.keys(): raise ValueError('Missing population or denominator.')
                core += ['scope', 'denominator']
            cites = {point['bindings'][key]['cite_id'] for key in core}
            if len(cites) != 1: raise ValueError('One observation must bind to one population statement.')
            citation = next(iter(cites)); source = context.evidence[citation - 1].text
            group = point['bindings']['group']; limits = _sentence_span(source, group['start'], group['end'])
            if any(not limits[0] <= point['bindings'][key]['start'] < point['bindings'][key]['end'] <= limits[1] for key in core):
                raise ValueError('Values attach to a different group or population.')
            observation = source[limits[0]:limits[1]]
            value_span, unit_span = point['bindings']['value'], point['bindings']['unit']
            # Containment alone attaches 38 days to 33 cells, or Group B's value
            # to Group A. Transcribe a direct group -> quantity -> unit phrase.
            if not group['end'] <= value_span['start'] < value_span['end'] <= unit_span['start']:
                raise ValueError('Quantity order is not source-established.')
            connector = source[group['end']:value_span['start']].strip()
            if not re.fullmatch(r'(?::|=|has|had|contains|is|was)?', connector, re.I):
                raise ValueError('Quantity is not directly attached to its group.')
            if source[value_span['end']:unit_span['start']].strip():
                raise ValueError('Value is not directly attached to its unit.')
            if not any(all(_contains(values[key][0], context.claims_by_id[id].claim) for key in core)
                       for id in ids):
                raise ValueError('Observation does not occur in one retained scoped claim.')
            # Multiple different groups in one clause require more semantic
            # interpretation than an exact span binding; decline ambiguity.
            all_groups = {p['group'] for p in series['points']}
            if sum(_contains(group, observation) for group in all_groups) != 1:
                raise ValueError('Ambiguous group/value association.')
            point['support'] = support
        if payload['chart_type'] == 'line' and any(a >= b for a, b in zip(xs, xs[1:])):
            raise ValueError('Line x values must be strictly increasing.')


def _procedure(payload, context):
    steps = {step['id']: step for step in payload['steps']}
    for step in steps.values(): _label(step, context, 'text')
    incoming = {id: set() for id in steps}; outgoing = {id: set() for id in steps}
    for edge in payload['precedes']:
        a, b = edge['from_id'], edge['to_id']
        _relation(edge, steps[a]['text'], steps[b]['text'], context, 'precedes')
        incoming[b].add(a); outgoing[a].add(b)
    for id, step in steps.items():
        exact = any(normalized(step['text']) == normalized(context.claims_by_id[c].claim)
                    for c in step['claim_ids'])
        # A complete explicit ordering proposition may supply its exact action
        # endpoints; arbitrary substrings of another instruction may not.
        endpoint = any(id in (edge['from_id'], edge['to_id']) and
                       set(step['claim_ids']) & set(edge['claim_ids'])
                       for edge in payload['precedes'])
        if not exact and not endpoint:
            raise ValueError('Procedure step drops part of its retained instruction.')
    order, total = [], True
    while incoming:
        ready = [id for id in incoming if not incoming[id]]
        if not ready: raise ValueError('Procedure ordering contains a cycle.')
        total = total and len(ready) == 1
        for id in ready:
            order.append(id); del incoming[id]
            for followers in incoming.values(): followers.discard(id)
    payload['ordering'] = 'total' if total else 'partial'
    payload['steps'] = [steps[id] for id in order]


def _comparison_fact(cell, column, criterion, context):
    """Only complete simple group/attribute/value propositions in version 1."""
    group, key, value = map(normalized, (column['text'], criterion['text'], cell['text']))
    connectors = ('', 'has', 'had', 'is', 'was', 'contains')
    statements = set()
    for first in connectors:
        if _contains(criterion['text'], cell['text']):
            statements.add(' '.join(filter(None, (group, first, value))))
        for second in connectors:
            statements.add(' '.join(filter(None, (group, first, key, second, value))))
    if not any(normalized(context.claims_by_id[id].claim) in statements for id in cell['claim_ids']):
        raise ValueError('Comparison does not preserve a complete group/criterion/value fact.')


def ground_visual(spec, context, verifier=None, *, diagnostics=None):
    """No new factual inference: facts inherit only their retained claim support."""
    try:
        payload = deepcopy(spec.payload)
        if spec.kind == 'diagram':
            nodes = {node['id']: node for node in payload['nodes']}
            for node in nodes.values(): _label(node, context)
            if spec.version==2:
                from .relations import checked_relations,check_groups
                checked_relations(payload,None,context);check_groups(payload,context)
            else:
                for edge in payload['edges']:
                    _relation(edge, nodes[edge['from_id']]['label'], nodes[edge['to_id']]['label'], context)
        elif spec.kind == 'plot':
            if spec.version==2:
                from .observations import checked_observations
                checked_observations(payload,None,context)
            else: _plot(payload, context)
        elif spec.kind == 'procedure': _procedure(payload, context)
        elif spec.kind == 'comparison':
            columns = {column['id']: column for column in payload['columns']}
            for column in columns.values(): _bound_text(column, context)
            for row in payload['rows']:
                _bound_text(row['criterion'], context)
                units = set()
                for cell in row['cells']:
                    column = columns[cell['column_id']]
                    if cell['status'] == 'not_stated':
                        if cell['text'] or cell['claim_ids'] or cell['bindings']: raise ValueError('Absent cell asserts content.')
                        if any(_contains(column['text'], claim.claim) and
                               _contains(row['criterion']['text'], claim.claim) for claim in context.claims):
                            raise ValueError('A retained comparison value cannot be hidden as absent.')
                        continue
                    _bound_text(cell, context)
                    if not any(_contains(column['text'], context.claims_by_id[id].claim)
                               for id in cell['claim_ids']): raise ValueError('Cell belongs to another comparison group.')
                    _comparison_fact(cell, column, row['criterion'], context)
                    if re.search(r'\d', cell['text']):
                        units.add(re.sub(r'[-+\d.eE\s]', '', cell['text']))
                if len(units) > 1: raise ValueError('Incompatible comparison units.')
        elif spec.kind == 'source':
            payload['support'] = support_for(payload['claim_ids'], context)
            if not any(getattr(context.evidence[n-1], 'pack_id', None) == payload['pack_id'] and
                       getattr(context.evidence[n-1], 'document_id', None) == payload['document_id'] and
                       payload['unit_id'] in getattr(context.evidence[n-1], 'unit_ids', ())
                       for id in payload['claim_ids'] for n in context.claims_by_id[id].cite_ids):
                raise ValueError('Source does not belong to a retained citation.')
        used = set()
        def collect(value):
            if isinstance(value, dict):
                used.update(value.get('claim_ids', []))
                for item in value.values(): collect(item)
            elif isinstance(value, list):
                for item in value: collect(item)
        collect(payload)
        description = ' '.join(item.claim for item in context.claims if item.id in used)[:2400]
        citations = sorted({n for id in used for n in context.claims_by_id[id].cite_ids})
        sources = tuple({'citation_id': f'cit-{n}', 'title': getattr(context.evidence[n-1], 'title', '') or 'Source',
                         'pack_id': getattr(context.evidence[n-1], 'pack_id', None) or None,
                         'document_id': (getattr(context.evidence[n-1], 'document_id', None) or None)
                                        if getattr(context.evidence[n-1], 'pack_id', None) else None,
                         'unit_ids': list(getattr(context.evidence[n-1], 'unit_ids', ()))
                                     if getattr(context.evidence[n-1], 'pack_id', None) else [],
                         'locators': [loc.as_dict() if hasattr(loc, 'as_dict') else loc
                                      for loc in getattr(context.evidence[n-1], 'locators', ())],
                         'provenance': getattr(context.evidence[n-1], 'provenance', 'native_text')}
                        for n in citations)
        return VisualResult('ready', replace(spec, title=TITLES[spec.kind], description=description, payload=payload, sources=sources))
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        if diagnostics is not None: diagnostics['grounding_error']=f'{type(exc).__name__}: {exc}'[:2000]
        return VisualResult('omitted', limitations=('The requested visual could not be grounded in retained claims and exact source bindings.',),
                            metadata={'stage':'grounding','reason_code':'unbound_fact'})
