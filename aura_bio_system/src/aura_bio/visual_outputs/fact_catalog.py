"""Exact source-stated structures selected by ID, never semantic fact repair."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re

from .catalog import compile_plot_catalog, _DIRECT
from .grounding import ground_visual
from .registry import context_identity
from .ownership import literal_statement,source_owner
from .schema import arr, obj, parse_visual, _validate

_VERBS={'activates':'activates','activate':'activates','inhibits':'inhibits','inhibit':'inhibits',
    'causes':'causes','cause':'causes','associated with':'associated_with','is associated with':'associated_with',
    'part of':'part_of','is part of':'part_of','precedes':'precedes','before':'precedes','points to':'visible_arrow'}
_RELATION=re.compile(r'(?P<left>.+?)\s+(?P<label>(?:(?:may|might|could|can|not|only|unless)\s+)*'
    r'(?P<verb>'+ '|'.join(re.escape(v) for v in sorted(_VERBS,key=len,reverse=True))+r'))\s+(?P<right>.+?)\.?$',re.I)


@dataclass(frozen=True)
class FactCatalog:
    kind: str
    context_hash: str
    facts: tuple
    complete: bool


def _envelope(kind,payload):
    return {'version':2 if kind=='diagram' else 1,'id':'checked-'+kind,'kind':kind,
            'title':'Source-grounded visual','description':'','payload':payload}


def _graph(facts,orientation='LR',layout='pathway'):
    nodes={};edges=[]
    for fact in facts:
        owner=fact['owner']
        for label in (fact['left'],fact['right']):
            key=(owner,label)
            if key not in nodes:
                nodes[key]={'id':f'n{len(nodes)+1}','label':label,'role':'entity','claim_ids':[]}
            nodes[key]['claim_ids']=sorted(set(nodes[key]['claim_ids'])|set(fact['claim_ids']))
        edges.append({'from_id':nodes[(owner,fact['left'])]['id'],'to_id':nodes[(owner,fact['right'])]['id'],
            'relation':fact['relation'],'label':fact['label'],'claim_ids':fact['claim_ids'],
            'qualifiers':fact['qualifiers'],'conditions':fact['conditions'],'bindings':[fact['binding']]})
    return {'nodes':list(nodes.values()),'edges':edges,'groups':[],'orientation':orientation,'layout':layout}


def _procedure(facts):
    graph=_graph(facts)
    return {'steps':[{'id':n['id'],'text':n['label'],'claim_ids':n['claim_ids']} for n in graph['nodes']],
            'precedes':[{'from_id':e['from_id'],'to_id':e['to_id'],'claim_ids':e['claim_ids']} for e in graph['edges']]}


def _comparison(facts,context):
    columns={};rows={};seen=set()
    for fact in facts:
        p=fact['point'];group=p['group'];quantity=p['quantity'];owned=(p.get('_owner'),group);key=(owned,quantity)
        if key in seen: raise ValueError('Ambiguous repeated comparison cell.')
        seen.add(key)
        if owned not in columns:
            columns[owned]={'id':f'col{len(columns)+1}','text':group,'claim_ids':p['claim_ids'],'bindings':[p['bindings']['group']]}
        if quantity not in rows:
            rows[quantity]={'id':f'row{len(rows)+1}','criterion':{'text':quantity,'claim_ids':p['claim_ids'],
                'bindings':[p['bindings']['quantity']]},'cells':[]}
        span={'cite_id':p['bindings']['value']['cite_id'],'start':p['bindings']['value']['start'],'end':p['bindings']['unit']['end']}
        text=context.evidence[span['cite_id']-1].text[span['start']:span['end']]
        rows[quantity]['cells'].append({'column_id':columns[owned]['id'],'text':text,'status':'stated',
                                      'claim_ids':p['claim_ids'],'bindings':[span]})
    for row in rows.values():
        present={c['column_id'] for c in row['cells']}
        row['cells'] += [{'column_id':c['id'],'text':'','status':'not_stated','claim_ids':[],'bindings':[]}
                         for c in columns.values() if c['id'] not in present]
    return {'columns':list(columns.values()),'rows':list(rows.values())}


def compile_fact_catalog(kind,context):
    if kind not in {'diagram','procedure','comparison'}: raise ValueError('Unknown checked structure.')
    identity=context_identity(context)
    numeric=compile_plot_catalog(context)
    numeric_ids={id for observation in numeric.observations for id in observation['point']['claim_ids']}
    all_ids={c.id for c in context.claims}
    if kind=='comparison':
        relations=compile_fact_catalog('diagram',context)
        relation_ids={id for fact in relations.facts for id in fact['claim_ids']}
        facts=tuple({'id':o['id'],'point':o['point'],'source_statement':o['source_statement']}
                    for o in numeric.observations if o['point']['value'] is not None
                    and not any(k in o['point'] for k in ('condition','population','x')))
        complete=(numeric.complete and len(facts)==len(numeric.observations) and bool(facts)
                  and all_ids <= numeric_ids|relation_ids)
        if complete:
            try:
                spec=parse_visual(json.dumps(_envelope(kind,_comparison(facts,context))),context)
                complete=ground_visual(spec,context).status=='ready'
            except ValueError: complete=False
        return FactCatalog(kind,identity,facts,complete)
    # Unknown statements must not disappear merely because a vocabulary failed
    # to classify them. Exclude only structures positively checked as another
    # kind; otherwise preserve the general constrained proposal path.
    # Recognising a direct numeric statement's *shape* only separates it from
    # a relationship diagram. It never admits interpreted numbers to a plot or
    # comparison catalogue, where native checked observations remain mandatory.
    numeric_shapes={c.id for c in context.claims if _DIRECT.fullmatch(c.claim.strip())}
    relevant=all_ids-numeric_ids-numeric_shapes
    if kind=='procedure':
        relations=compile_fact_catalog('diagram',context)
        non_order={id for fact in relations.facts if fact['relation']!='precedes' for id in fact['claim_ids']}
        relevant-=non_order
    facts=[];covered=set()
    for claim in context.claims:
        if claim.id not in relevant: continue
        for cite in claim.cite_ids:
            source=context.evidence[cite-1].text
            for sentence in re.finditer(r'[^\n]+?(?:[.!?](?=\s|$)|$)',source):
                raw=sentence.group();text=raw.strip()
                if literal_statement(text)!=literal_statement(claim.claim): continue
                match=_RELATION.fullmatch(text)
                if not match: continue
                relation=_VERBS[match['verb'].casefold()]
                if kind=='procedure' and relation!='precedes': continue
                left,right=match['left'],match['right'];conditions=[]
                condition=re.fullmatch(r'(.+?)\s+((?:without|under|with|during|when|if|in the presence of)\s+.+)',right,re.I)
                if condition: right=condition[1];conditions=[condition[2]]
                offset=sentence.start()+len(raw)-len(raw.lstrip())
                fact={'id':'r'+hashlib.sha256(f'{identity}:{claim.id}:{cite}:{offset}'.encode()).hexdigest()[:12],
                    'left':left,'right':right,'relation':relation,'label':match['label'],'claim_ids':[claim.id],
                    'owner':source_owner(context.evidence[cite-1]),
                    'qualifiers':re.findall(r'\b(?:may|might|could|can|not|only|unless)\b',match['label'].casefold()),
                    'conditions':conditions,'binding':{'cite_id':cite,'start':offset,'end':offset+len(text)},'source_statement':text}
                try:
                    payload=_graph([fact]) if kind=='diagram' else _procedure([fact])
                    result=ground_visual(parse_visual(json.dumps(_envelope(kind,payload)),context),context)
                except ValueError: continue
                if result.status!='ready': continue
                facts.append(fact);covered.add(claim.id);break
            if claim.id in covered: break
    return FactCatalog(kind,identity,tuple(facts),bool(relevant) and relevant<=covered)


def fact_selection_schema(catalog):
    props={'fact_ids':arr({'type':'string','enum':[f['id'] for f in catalog.facts]},30,1)}
    if catalog.kind=='diagram':
        props.update(orientation={'type':'string','enum':['LR','TD']},layout={'type':'string','enum':['pathway','cycle','hierarchy']})
    return obj(props)


def expand_fact_selection(selection,catalog,context):
    if not catalog.complete or context_identity(context)!=catalog.context_hash: raise ValueError('Incomplete or stale checked structure.')
    _validate(selection,fact_selection_schema(catalog));ids=selection['fact_ids']
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate fact selection.')
    by_id={f['id']:f for f in catalog.facts};facts=[deepcopy(by_id[id]) for id in ids]
    kind=catalog.kind
    payload=(_graph(facts,selection['orientation'],selection['layout']) if kind=='diagram' else
             _procedure(facts) if kind=='procedure' else _comparison(facts,context))
    value=_envelope(kind,payload)
    if ground_visual(parse_visual(json.dumps(value),context),context).status!='ready':
        raise ValueError('Selected facts do not form a grounded visual.')
    return value
