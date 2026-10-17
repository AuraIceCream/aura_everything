"""Closed, bounded, versioned visual data. Rendering code is never accepted."""
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
import json
import re

KINDS = ('source', 'diagram', 'comparison', 'procedure', 'plot')
RELATIONS = ('precedes', 'part_of', 'associated_with', 'activates', 'inhibits', 'causes', 'visible_arrow')


@dataclass(frozen=True)
class VisualSpec:
    version: int
    id: str
    kind: str
    title: str
    description: str
    payload: dict
    sources: tuple[dict, ...] = ()

    def as_dict(self): return asdict(self)


@dataclass(frozen=True)
class VisualResult:
    status: str
    spec: VisualSpec | None = None
    limitations: tuple[str, ...] = ()
    metadata: dict | None = None

    def as_dict(self):
        return {'status': self.status, 'spec': self.spec.as_dict() if self.spec else None,
                'limitations': list(self.limitations), 'metadata': self.metadata or {}}


def obj(properties, required=None):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties) if required is None else required}


def arr(items, maximum, minimum=0):
    return {'type': 'array', 'items': items, 'minItems': minimum, 'maxItems': maximum}


LABEL = {'type': 'string', 'minLength': 1, 'maxLength': 120}
ID = {'type': 'string', 'pattern': r'^[A-Za-z][A-Za-z0-9_-]{0,63}$', 'maxLength': 64}
OWNED_ID = {'type': 'string', 'pattern': r'^[a-f0-9]{32}$'}
CLAIMS = arr(ID, 24, 1)
BINDING = obj({'cite_id': {'type': 'integer', 'minimum': 1},
               'start': {'type': 'integer', 'minimum': 0}, 'end': {'type': 'integer', 'minimum': 1}})
BINDINGS = arr(BINDING, 8, 1)
DECIMAL = {'type': 'string', 'pattern': r'^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$', 'maxLength': 80}
BOX = obj({key: {'type': 'number', 'minimum': 0, 'maximum': 1} for key in ('x0', 'y0', 'x1', 'y1')})


def visual_schema(kind, version=1):
    if kind not in KINDS: raise ValueError('Unknown visual kind.')
    if version not in (1,2) or (version==2 and kind not in {'diagram','plot'}): raise ValueError('Unknown visual version.')
    node = obj({'id': ID, 'label': LABEL, 'claim_ids': CLAIMS})
    edge = obj({'from_id': ID, 'to_id': ID, 'relation': {'type': 'string', 'enum': list(RELATIONS)},
                'label': LABEL, 'claim_ids': CLAIMS})
    bound = obj({'text': LABEL, 'claim_ids': CLAIMS, 'bindings': BINDINGS})
    column = obj({'id': ID, **bound['properties']})
    cell = {'anyOf': [
        obj({'column_id': ID, 'text': LABEL, 'status': {'type': 'string', 'enum': ['stated']},
             'claim_ids': CLAIMS, 'bindings': BINDINGS}),
        obj({'column_id': ID, 'text': {'type': 'string', 'enum': ['']},
             'status': {'type': 'string', 'enum': ['not_stated']},
             'claim_ids': arr(ID, 0), 'bindings': arr(BINDING, 0)})]}
    point_bindings = obj({key: BINDING for key in ('group', 'value', 'unit', 'x', 'x_unit', 'scope', 'denominator')},
                         ['group', 'value', 'unit'])
    point = obj({'group': LABEL, 'value': {'anyOf': [DECIMAL, {'type': 'null'}]}, 'x': DECIMAL,
                 'claim_ids': CLAIMS, 'bindings': point_bindings}, ['group', 'value', 'claim_ids', 'bindings'])
    payloads = {
        'source': obj({'claim_ids': CLAIMS, 'pack_id': OWNED_ID, 'document_id': OWNED_ID,
                       'unit_id': OWNED_ID, 'asset_id': {'anyOf': [OWNED_ID, {'type': 'null'}]},
                       'bbox': {'anyOf': [BOX, {'type': 'null'}]}}),
        'diagram': obj({'nodes': arr(node, 20, 1), 'edges': arr(edge, 30)}),
        'comparison': obj({'columns': arr(column, 6, 1), 'rows': arr(obj({
            'id': ID, 'criterion': bound, 'cells': arr(cell, 6, 1)}), 12, 1)}),
        'procedure': obj({'steps': arr(obj({'id': ID, 'text': LABEL, 'claim_ids': CLAIMS}), 20, 1),
                           'precedes': arr(obj({'from_id': ID, 'to_id': ID, 'claim_ids': CLAIMS}), 30)}),
        'plot': obj({'chart_type': {'type': 'string', 'enum': ['bar', 'line', 'scatter']},
                     'x_label': LABEL, 'y_label': LABEL, 'unit': LABEL, 'x_unit': LABEL,
                     'series': arr(obj({'id': ID, 'label': LABEL, 'unit': LABEL, 'points': arr(point, 100, 1)}), 3, 1)},
                    ['chart_type', 'x_label', 'y_label', 'unit', 'series'])}
    if version==2 and kind=='diagram':
        node['properties']['role']={'type':'string','enum':['entity','process','condition']}
        node['required'].append('role')
        edge['properties'].update(qualifiers=arr({'type':'string','enum':
            ['may','might','could','can','not','only','unless']},8),conditions=arr(LABEL,4),bindings=BINDINGS)
        edge['required']+=['qualifiers','conditions','bindings']
        payloads['diagram']['properties'].update(
            orientation={'type':'string','enum':['TD','LR']},layout={'type':'string','enum':['pathway','cycle','hierarchy']},
            groups=arr(obj({'id':ID,'label':LABEL,'node_ids':arr(ID,20,1),
                'mode':{'type':'string','enum':['presentation','containment']},
                'claim_ids':arr(ID,24),'bindings':arr(BINDING,8)}),8))
        payloads['diagram']['required']+=['orientation','layout','groups']
    if version==2 and kind=='plot':
        point_bindings['properties'].update({key:BINDING for key in ('quantity','population','condition','column','bin_lower','bin_upper')})
        point_bindings['required'].append('quantity')
        uncertainty_scope={key:BINDING for key in ('population','condition','x','x_unit','quantity')}
        magnitude=obj({'kind':{'type':'string','enum':['SD','SEM']},'magnitude':DECIMAL,
            'bindings':obj({**{key:BINDING for key in ('group','kind','magnitude','unit')},**uncertainty_scope},['group','kind','magnitude','unit'])})
        interval=obj({'kind':{'type':'string','enum':['CI','source_interval']},'lower':DECIMAL,'upper':DECIMAL,
            'level':LABEL,'bindings':obj({**{key:BINDING for key in ('group','kind','lower','upper','unit','level')},**uncertainty_scope},
                                         ['group','kind','lower','upper','unit'])},['kind','lower','upper','bindings'])
        point['properties'].update(id=ID,quantity=LABEL,population=LABEL,condition=LABEL,column=LABEL,
            origin={'type':'string','enum':['source_observation']},bin_lower=DECIMAL,bin_upper=DECIMAL,
            uncertainty={'anyOf':[magnitude,interval,{'type':'null'}]})
        point['required']+=['id','quantity','origin','uncertainty']
        series=payloads['plot']['properties']['series']['items']
        series['properties']['identity']=bound;series['required'].append('identity')
        payloads['plot']['properties'].update(chart_type={'type':'string','enum':['bar','line','scatter','heatmap','distribution']},
            x_scale={'type':'string','enum':['linear','log']},y_scale={'type':'string','enum':['linear','log']},
            distribution_mode={'type':'string','enum':['source_bins','samples']})
        payloads['plot']['required']+=['x_scale','y_scale']
    return obj({'version': {'type': 'integer', 'enum': [version]}, 'id': ID,
                'kind': {'type': 'string', 'enum': [kind]}, 'title': LABEL,
                'description': {'type': 'string', 'maxLength': 2400}, 'payload': payloads[kind]})


def _validate(value, schema):
    if 'anyOf' in schema:
        for branch in schema['anyOf']:
            try: _validate(value, branch); return
            except ValueError: pass
        raise ValueError('Invalid visual value.')
    kind = schema['type']
    valid = {'object': lambda: isinstance(value, dict), 'array': lambda: isinstance(value, list),
             'string': lambda: isinstance(value, str), 'integer': lambda: type(value) is int,
             'number': lambda: type(value) in (int, float) and Decimal(str(value)).is_finite(),
             'null': lambda: value is None, 'boolean': lambda: type(value) is bool}[kind]()
    if not valid: raise ValueError('Invalid visual field type.')
    if 'enum' in schema and value not in schema['enum']: raise ValueError('Invalid visual option.')
    if kind == 'object':
        if set(schema['required']) - value.keys() or value.keys() - schema['properties'].keys():
            raise ValueError('Missing or unknown visual fields.')
        for key, item in value.items(): _validate(item, schema['properties'][key])
    elif kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 100):
            raise ValueError('Visual array exceeds limits.')
        for item in value: _validate(item, schema['items'])
    elif kind == 'string':
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 65536):
            raise ValueError('Invalid visual text length.')
        if 'pattern' in schema and not re.fullmatch(schema['pattern'], value):
            raise ValueError('Invalid visual string.')
    elif kind in ('integer', 'number'):
        if value < schema.get('minimum', value) or value > schema.get('maximum', value):
            raise ValueError('Visual number outside limits.')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate visual field.')
        result[key] = value
    return result


def _load_visual(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 65536:
        raise ValueError('Visual exceeds size limit.')
    try:
        data = json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite visual number.')))
    except (TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Invalid visual JSON.') from exc
    if not isinstance(data, dict): raise ValueError('Invalid visual envelope.')
    return data


def selection_schema(source_ids=(), version=1):
    """One constrained semantic selection, optionally carrying its layout."""
    reasons = {'none': ['simple_answer', 'no_added_value', 'insufficient_support'],
               'source': ['explicit_request', 'source_inspection'],
               'diagram': ['explicit_request', 'relationships'],
               'comparison': ['explicit_request', 'comparison'],
               'procedure': ['explicit_request', 'ordered_steps'],
               'plot': ['explicit_request', 'numeric_pattern']}
    branches = []
    for kind, choices in reasons.items():
        if kind == 'source' and not source_ids: continue
        branches.append(obj({'selected_kind': {'type': 'string', 'enum': [kind]},
            'reason': {'type': 'string', 'enum': choices},
            'visual': visual_schema(kind,version if kind in {'diagram','plot'} else 1) if kind in KINDS and kind != 'source' else {'type': 'null'},
            'source_id': {'type': 'string', 'enum': list(source_ids)} if kind == 'source' else {'type': 'null'}}))
    return {'anyOf': branches}


def parse_selection(raw, source_ids=()):
    data = _load_visual(raw)
    _validate(data, {'anyOf':[selection_schema(source_ids),selection_schema(source_ids,2)]})
    return data


def parse_visual(raw, context):
    data = _load_visual(raw)
    _validate(data, visual_schema(data.get('kind'),data.get('version')))
    if context is None or not context.claims: raise ValueError('No retained visual claims.')
    def inspect(value):
        if isinstance(value, dict):
            if 'claim_ids' in value and (len(value['claim_ids']) != len(set(value['claim_ids'])) or
                    any(id not in context.claims_by_id for id in value['claim_ids'])):
                raise ValueError('Visual references a discarded claim.')
            if {'cite_id', 'start', 'end'} == value.keys() and not (
                    1 <= value['cite_id'] <= len(context.evidence) and
                    0 <= value['start'] < value['end'] <= len(context.evidence[value['cite_id']-1].text)):
                raise ValueError('Visual evidence span is outside its source.')
            for item in value.values(): inspect(item)
        elif isinstance(value, list):
            for item in value: inspect(item)
    inspect(data['payload'])
    payload = data['payload']
    items = payload.get('nodes', payload.get('steps', payload.get('series', payload.get('columns', []))))
    ids = [item['id'] for item in items]
    if len(ids) != len(set(ids)): raise ValueError('Duplicate visual IDs.')
    if data['kind']=='diagram' and data['version']==2:
        groups=payload['groups']
        if len({g['id'] for g in groups})!=len(groups): raise ValueError('Duplicate group IDs.')
        grouped=[]
        for group in groups:
            if any(id not in ids for id in group['node_ids']): raise ValueError('Dangling group member.')
            grouped+=group['node_ids']
        if len(grouped)!=len(set(grouped)): raise ValueError('Overlapping diagram groups.')
    for edge in payload.get('edges', payload.get('precedes', [])):
        if edge['from_id'] not in ids or edge['to_id'] not in ids:
            raise ValueError('Dangling visual relationship.')
    if data['kind'] == 'plot':
        if sum(len(series['points']) for series in items) > 100: raise ValueError('Too many plot points.')
        if data['version']==2:
            observations=[p['id'] for series in items for p in series['points']]
            if len(observations)!=len(set(observations)): raise ValueError('Duplicate observation identity.')
        for series in items:
            for point in series['points']:
                for key in ('value', 'x'):
                    if point.get(key) is not None and not Decimal(point[key]).is_finite():
                        raise ValueError('Non-finite plot number.')
    if data['kind'] == 'comparison':
        rows = payload['rows']
        if len({row['id'] for row in rows}) != len(rows): raise ValueError('Duplicate comparison row.')
        for row in rows:
            if len({cell['column_id'] for cell in row['cells']}) != len(row['cells']) or any(cell['column_id'] not in ids for cell in row['cells']):
                raise ValueError('Invalid comparison column binding.')
    if data['kind'] == 'source' and payload['bbox']:
        box = payload['bbox']
        if box['x0'] >= box['x1'] or box['y0'] >= box['y1']: raise ValueError('Empty source region.')
    return VisualSpec(**data)


def public_visual_schema(kind, version=1):
    """Response schema adds app-assigned support; it is never used for decoding."""
    from copy import deepcopy
    schema = deepcopy(visual_schema(kind,1 if kind=='source' else version))
    if version not in (1,2): raise ValueError('Unknown public visual version.')
    schema['properties']['version']['enum']=[version]
    support = obj({'claim_ids': CLAIMS,
                   'cite_ids': arr({'type': 'string', 'pattern': r'^cit-[1-9][0-9]*$'}, 24, 1),
                   'status': {'type': 'string', 'enum': ['native_verified', 'interpreted', 'ocr_transcribed', 'user_annotated', 'native_unverified']},
                   'provenance': arr({'type': 'string', 'enum': ['native_text', 'ocr', 'vlm', 'user_annotation']}, 4, 1)})
    def enrich(value):
        if isinstance(value, dict):
            if value.get('type') == 'object' and 'claim_ids' in value.get('properties', {}):
                value['properties']['support'] = deepcopy(support)
                if 'status' not in value['properties'] and 'mode' not in value['properties']: value['required'].append('support')
            for key, item in list(value.items()):
                if key != 'support': enrich(item)
        elif isinstance(value, list):
            for item in value: enrich(item)
    enrich(schema['properties']['payload'])
    locator = obj({'kind': {'type': 'string'}, 'page': {'type': 'integer'}, 'page_label': {'type': 'string'},
                   'slide': {'type': 'integer'}, 'shape_id': {'type': 'integer'}, 'sheet': {'type': 'string'},
                   'cell_range': {'type': 'string'}, 'start_line': {'type': 'integer'}, 'end_line': {'type': 'integer'},
                   'role': {'type': 'string'}}, ['kind'])
    nullable_id = {'anyOf': [OWNED_ID, {'type': 'null'}]}
    schema['properties']['sources'] = arr(obj({'citation_id': {'type': 'string'}, 'title': {'type': 'string'},
        'pack_id': nullable_id, 'document_id': nullable_id, 'unit_ids': arr(OWNED_ID, 100),
        'locators': arr(locator, 100), 'provenance': {'type': 'string'}}), 24)
    schema['required'].append('sources')
    payload = schema['properties']['payload']
    if kind == 'source':
        extras = {'revision_id': OWNED_ID, 'source_checksum': {'type': 'string'},
                  'asset_checksum': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                  'generation': {'type': 'integer', 'minimum': 0}, 'locators': arr(locator, 100),
                  'coordinates': {'type': 'string', 'enum': ['upright_normalized']},
                  'highlight_precision': {'type': 'string', 'enum': ['region', 'whole_asset', 'unit_only']},
                  'resolved': {'type': 'boolean', 'enum': [True]}}
        payload['properties'].update(extras); payload['required'].extend(extras)
        if version==2:
            extras={'highlights':arr(obj({'id':ID,'bbox':BOX,'precision':{'type':'string','enum':['region','panel','table_row']}}),2),
                    'warnings':arr({'type':'string','maxLength':1000},8),'geometry_revision_ids':arr(OWNED_ID,2,1)}
            payload['properties']['highlight_precision']['enum']+=['panel','table_row']
            payload['properties'].update(extras);payload['required'].extend(extras)
    if kind == 'procedure':
        payload['properties']['ordering'] = {'type': 'string', 'enum': ['total', 'partial']}
        payload['required'].append('ordering')
    return schema
