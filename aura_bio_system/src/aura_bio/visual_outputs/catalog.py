"""App-assembled observations: the model chooses IDs, never rewrites numbers.

This narrow compiler recognises explicit direct observations already supported
by the numeric checker. Unknown formats stay on the general checked-proposal
path; a partial catalogue is never advertised as complete.
"""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import re

from .registry import context_identity
from .schema import arr, obj, parse_visual
from .grounding import ground_visual
from .ownership import literal_statement,source_owner

_NUMBER=r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
_DIRECT=re.compile(
    r'(?:(?P<time>At time\s+(?P<x>'+_NUMBER+r')\s+(?P<x_unit>[A-Za-zµμ]+)),\s*)?'
    r'(?P<group>[\w][\w ()/+\-]*?)\s*(?::|\bhas\b|\bhad\b|\bcontains\b|\bis\b|\bwas\b)\s*'
    r'(?:(?P<quantity>mean)\s+)?(?P<value>'+_NUMBER+r'|missing|not reported|not stated|not measured)\s+'
    r'(?P<unit>[A-Za-zµμ%]+)(?:\s+(?P<condition>(?:under|with|without|in|at|for)\s+.+?))?[.!?]?',re.I)


@dataclass(frozen=True)
class PlotCatalog:
    context_hash: str
    observations: tuple
    complete: bool


def _identity(point, *, temporal=False):
    role='group' if temporal else 'quantity'
    return {'text':point[role],'claim_ids':point['claim_ids'],
            'bindings':[point['bindings'][role]]}


def _spec(points,chart_type):
    unit=points[0]['_unit']
    if any(p['_unit']!=unit for p in points): raise ValueError('Incompatible source units.')
    series={}
    for point in points:
        temporal=chart_type in {'line','scatter'}
        key=(point.get('_owner'),point['group'] if temporal else point['quantity'],point.get('condition'),point.get('_x_unit') if temporal else None)
        if key not in series:
            identity=_identity(point,temporal=temporal)
            series[key]={'id':f's{len(series)+1}','label':identity['text'],'unit':unit,'identity':identity,'points':[]}
        series[key]['points'].append({k:deepcopy(v) for k,v in point.items() if not k.startswith('_')})
    if len(series)>3: raise ValueError('Too many source series for one visual.')
    if chart_type=='line':
        for group in series.values():
            if len(group['points'])<2: raise ValueError('A trajectory needs repeated observations of one entity.')
            group['points'].sort(key=lambda p:Decimal(p['x']))
    payload={'chart_type':chart_type,'unit':unit,'x_label':'Group','y_label':'Value',
        'x_scale':'linear','y_scale':'linear','series':list(series.values())}
    xunits={p['_x_unit'] for p in points if p.get('x') is not None}
    if xunits:
        if len(xunits)!=1: raise ValueError('Incompatible source x units.')
        payload['x_unit']=next(iter(xunits))
    return {'version':2,'id':'source-observations','kind':'plot','title':'Source-stated data','description':'','payload':payload}


def compile_plot_catalog(context):
    eligible={c.id for c in context.claims
        if context.basis_by_id[c.id].get('verification_kind')=='native_verified'
        and all(getattr(context.evidence[n-1],'provenance','native_text')=='native_text' for n in c.cite_ids)
        and (re.search(r'\d',c.claim) or re.search(r'\bmissing|not (?:reported|stated|measured)\b',c.claim,re.I))}
    observations=[];covered=set();seen=set();identity=context_identity(context)
    for cite,evidence in enumerate(context.evidence,1):
        if getattr(evidence,'provenance','native_text')!='native_text': continue
        owners=[c for c in context.claims if c.id in eligible and cite in c.cite_ids]
        if not owners: continue
        for sentence in re.finditer(r'[^\n]+?(?:[.!?](?=\s|$)|$)',evidence.text):
            text=sentence.group();offset=sentence.start()+len(text)-len(text.lstrip());text=text.strip()
            match=_DIRECT.fullmatch(text)
            if not match: continue
            def binding(role):
                a,b=match.span(role)
                return {'cite_id':cite,'start':offset+a,'end':offset+b}
            for claim in owners:
                if literal_statement(claim.claim)!=literal_statement(text): continue
                key=(cite,offset,match.end())
                if key in seen: continue
                point={'id':'o'+hashlib.sha256(f'{identity}:{cite}:{offset}'.encode()).hexdigest()[:12],
                    'group':match['group'],'quantity':match['quantity'] or match['unit'],
                    'value':match['value'] if re.fullmatch(_NUMBER,match['value']) else None,
                    'claim_ids':[claim.id],'origin':'source_observation','uncertainty':None,
                    'bindings':{role:binding(role) for role in ('group','value','unit')},
                    '_unit':match['unit'],'_owner':source_owner(evidence)}
                point['bindings']['quantity']=binding('quantity' if match['quantity'] else 'unit')
                if match['x']:
                    point.update(x=match['x'],_x_unit=match['x_unit'])
                    point['bindings'].update(x=binding('x'),x_unit=binding('x_unit'))
                if match['condition']:
                    point['condition']=match['condition'];point['bindings']['condition']=binding('condition')
                proposal=_spec([point],'bar')
                result=ground_visual(parse_visual(json.dumps(proposal),context),context)
                if result.status!='ready': continue
                seen.add(key)
                covered.add(claim.id)
                observations.append({'id':point['id'],'point':point,'source_statement':text})
    return PlotCatalog(identity,tuple(observations),bool(eligible) and eligible<=covered)


def plot_selection_schema(catalog):
    ids=[o['id'] for o in catalog.observations]
    kinds=['bar']
    if catalog.observations and all(o['point'].get('x') is not None for o in catalog.observations):
        kinds+=['scatter','line']
    return obj({'chart_type':{'type':'string','enum':kinds},
                'observation_ids':arr({'type':'string','enum':ids},100,1)})


def expand_plot_selection(selection,catalog,context):
    from .schema import _validate
    if not catalog.complete or context_identity(context)!=catalog.context_hash: raise ValueError('Incomplete or stale observation catalogue.')
    _validate(selection,plot_selection_schema(catalog))
    ids=selection['observation_ids']
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate observation selection.')
    by_id={o['id']:o['point'] for o in catalog.observations}
    proposal=_spec([by_id[id] for id in ids],selection['chart_type'])
    result=ground_visual(parse_visual(json.dumps(proposal),context),context)
    if result.status!='ready': raise ValueError('Selected observations do not form a grounded plot.')
    return proposal
