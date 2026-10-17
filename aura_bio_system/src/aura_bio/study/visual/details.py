"""Bounded interpreted panel/table structure, separate from native captions."""
import json
import re
from ...visual_outputs.schema import obj,arr,_validate,_load_visual

DETAIL_PROMPT = (' For version 2 also return version=2, panels and tables. Describe only the question-relevant '
    'panels or rows. Each observation/cell origin is vlm, never native_text. Panel observations use property '
    'organism, condition or detail. Do not assign one panel species to another by proximity. '
    'Table cells reference declared row_id and header_id; missing/unreadable cells have null value, not zero. '
    'Bounding boxes are optional normalized estimates, NOT certified highlight geometry; use null if uncertain. '
    'List unreadable/omitted details. Empty panels/tables are allowed. Caption text remains a separate source, '
    'not permission to claim its wording was visible in the pixels.')


def detail_schema():
    from .description import description_schema
    text={'type':'string','minLength':1,'maxLength':100}
    ident={'type':'string','pattern':r'^[A-Za-z][A-Za-z0-9_-]{0,31}$','maxLength':32}
    box={'anyOf':[obj({k:{'type':'number','minimum':0,'maximum':1} for k in ('x0','y0','x1','y1')}),{'type':'null'}]}
    observation=obj({'property':{'type':'string','enum':['organism','condition','detail']},'value':text,
                     'origin':{'type':'string','enum':['vlm']}})
    panel=obj({'id':ident,'label':text,'bbox':box,'observations':arr(observation,8),'uncertainties':arr(text,4)})
    label=obj({'id':ident,'label':text})
    cell=obj({'row_id':ident,'header_id':ident,'value':{'anyOf':[text,{'type':'null'}]},
              'status':{'type':'string','enum':['stated','missing','merged','unreadable']},'bbox':box,
              'origin':{'type':'string','enum':['vlm']}})
    table=obj({'id':ident,'headers':arr(label,16,1),'rows':arr(label,32,1),'cells':arr(cell,128)})
    schema=description_schema()
    for branch in schema['anyOf']:
        branch['properties'].update(version={'type':'integer','enum':[2]},panels=arr(panel,16),tables=arr(table,4))
        branch['required']+=['version','panels','tables']
    return schema


def _identities(value):
    """Retain readable IDs independently of malformed sibling fields."""
    result={}
    if not isinstance(value,dict): return result
    for family in ('panels','tables'):
        rows=value.get(family)
        if not isinstance(rows,list): continue
        result[family]={r['id']:r for r in rows if isinstance(r,dict) and isinstance(r.get('id'),str)}
    return result


def validate_details(raw, *, repair=None):
    from .description import validate_live_description
    fields=_load_visual(raw);_validate(fields,detail_schema())
    overview={k:v for k,v in fields.items() if k not in {'version','panels','tables'}}
    validate_live_description(json.dumps(overview),repair)
    for rows in (fields['panels'],fields['tables']):
        if len({r['id'] for r in rows})!=len(rows): raise ValueError('Duplicate detail identity.')
    boxes=[p['bbox'] for p in fields['panels']]
    total_cells=0
    for table in fields['tables']:
        headers={r['id'] for r in table['headers']}; rows={r['id'] for r in table['rows']}
        if len(headers)!=len(table['headers']) or len(rows)!=len(table['rows']): raise ValueError('Duplicate table identity.')
        seen=set(); total_cells+=len(table['cells'])
        for cell in table['cells']:
            key=(cell['row_id'],cell['header_id'])
            if key in seen or key[0] not in rows or key[1] not in headers: raise ValueError('Foreign/duplicate cell identity.')
            seen.add(key);boxes.append(cell['bbox'])
            if cell['status'] in {'missing','unreadable'} and cell['value'] is not None: raise ValueError('Missing cell asserts a value.')
            if cell['status']=='stated' and cell['value'] is None: raise ValueError('Stated cell has no value.')
    if total_cells>128: raise ValueError('Too many total cells.')
    if any(b is not None and (b['x0']>=b['x1'] or b['y0']>=b['y1']) for b in boxes): raise ValueError('Invalid detail box.')
    if repair is not None:
        try: prior=_load_visual(repair)
        except ValueError: prior={}
        frozen=_identities(prior)
        for family,old in frozen.items():
            for item in fields[family]:
                if item['id'] not in old or ('label' in old[item['id']] and item.get('label')!=old[item['id']]['label']):
                    raise ValueError('Repair cannot add/relabel detail identity.')
                if family=='tables':
                    for labels in ('headers','rows'):
                        known={r.get('id'):r.get('label') for r in old[item['id']].get(labels,[]) if isinstance(r,dict)}
                        if any(r['id'] not in known or r['label']!=known[r['id']] for r in item[labels]):
                            raise ValueError('Repair cannot invent table identities.')
                    known={(c.get('row_id'),c.get('header_id')):c for c in old[item['id']].get('cells',[]) if isinstance(c,dict)}
                    for cell in item['cells']:
                        prior_cell=known.get((cell['row_id'],cell['header_id']))
                        if prior_cell is None or any(key in prior_cell and prior_cell[key]!=cell[key] for key in ('value','status','origin')):
                            raise ValueError('Structural repair cannot rewrite table facts/ownership.')
                else:
                    prior_observations=old[item['id']].get('observations',[])
                    readable=[o for o in prior_observations if isinstance(o,dict) and isinstance(o.get('value'),str)]
                    if len(item['observations'])!=len(readable) or any(not any(all(key not in before or before[key]==after[key] for key in ('property','value','origin')) for before in readable) for after in item['observations']):
                        raise ValueError('Structural repair cannot rewrite panel observations.')
    return fields


def caption_observations(caption, *, unit_id, source_text=None):
    """Only explicit panel-to-group language; adjacency is not ownership."""
    records=[]
    offset=source_text.find(caption) if source_text is not None else -1
    owned=offset>=0 and source_text.find(caption,offset+1)<0
    pattern=r'\bPanels?\s+([A-Z])(?:\s*[-–]\s*([A-Z]))?\s+(?:show|depict|describe)\s+([^.;\n]+)'
    for match in re.finditer(pattern,caption):
        first,last=ord(match[1]),ord(match[2] or match[1])
        if not first<=last or last-first>15: continue
        for panel in range(first,last+1):
            records.append({'panel_id':chr(panel),'property':'subject','value':match[3].strip(),
                'origin':'native_text','source_unit_id':unit_id,'start':match.start(3)+(offset if owned else 0),
                'end':match.end(3)+(offset if owned else 0),'coordinate_basis':'source_unit' if owned else 'caption_text',
                'source_quote':match[3],'relation_quote':match[0]})
    return tuple(records)


def detail_conflicts(details, caption=()):
    values={}; conflicts=[]
    for panel in details['panels']:
        for observation in panel['observations']:
            values.setdefault((panel['id'],observation['property']),[]).append(observation)
    for observation in caption:
        # A caption names a subject, not an automatically inferred ontology
        # category. Compare a declared pixel organism to that literal subject
        # as a possible disagreement, without promoting either interpretation.
        key=(observation['panel_id'],'organism' if observation['property']=='subject' and (observation['panel_id'],'organism') in values else observation['property'])
        values.setdefault(key,[]).append(observation)
    for (panel,property),items in values.items():
        if len({' '.join(i['value'].casefold().split()) for i in items})>1:
            conflicts.append({'panel_id':panel,'property':property,'observations':items,'status':'unresolved'})
    return tuple(conflicts)
