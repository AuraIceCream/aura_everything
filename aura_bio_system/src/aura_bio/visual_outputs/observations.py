"""Native scoped observations, not numbers inferred from pixels or model memory."""
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
import re


@dataclass(frozen=True)
class CheckedObservation:
    id: str
    series_id: str
    group: str
    quantity: str
    value: str | None
    unit: str
    x: str | None
    x_unit: str | None
    population: str | None
    uncertainty: object
    bindings: object
    support: object


def _values(bindings,ids,context):
    from .grounding import _binding
    values={k:_binding(b,ids,context)[0].strip() for k,b in bindings.items()}
    if any(getattr(context.evidence[b['cite_id']-1],'provenance','native_text')!='native_text' for b in bindings.values()):
        raise ValueError('Only native observed values can be drawn.')
    return values


def _clause(bindings,roles,context):
    from .grounding import _sentence_span
    if not set(roles)<=bindings.keys(): raise ValueError('Missing observation ownership binding.')
    refs=[bindings[k] for k in roles]
    if len({b['cite_id'] for b in refs})!=1: raise ValueError('Cross-source observation.')
    source=context.evidence[refs[0]['cite_id']-1].text
    lower,upper=_sentence_span(source,refs[0]['start'],refs[0]['end'])
    if any(not lower<=b['start']<b['end']<=upper for b in refs): raise ValueError('Cross-row/population observation.')
    return source,lower,upper


def _retained_statement(source,lower,upper,ids,context):
    from .ownership import literal_statement
    expected=literal_statement(source[lower:upper])
    if not any(expected==literal_statement(part.group()) for id in ids
               for part in re.finditer(r'[^\n]+?(?:[.!?;](?=\s|$)|$)',context.claims_by_id[id].claim)):
        raise ValueError('Observed statement is not a complete retained claim; signs and scope cannot be stripped.')


def _scope(source,lower,upper,bindings,point,*,matrix=False,inline=None):
    """Every prefix/suffix qualifier stays bound, not merely every number.

    Unknown prose is declined, never stripped by a bag of plausible words.
    Scope bindings include their connective (e.g. 'without oxygen'), preserving
    negation. The only unbound grammar is the explicit time/matrix-row wrapper.
    """
    group,unit=bindings['group'],bindings['unit']
    prefix=[lower,group['start']];suffix=[unit['end'],upper]
    extras=[bindings[k] for k in ('condition','population','scope','denominator') if k in bindings]
    if inline is not None:
        u=inline['bindings'];end=u.get('unit')
        if end and u['kind']['cite_id']==unit['cite_id'] and unit['end']<=u['kind']['start']<end['end']<=upper:
            extras.append({'start':u['kind']['start'],'end':end['end']})
    def remainder(bounds):
        start,end=bounds;cursor=start;pieces=[]
        for span in sorted(extras,key=lambda b:b['start']):
            if start<=span['start']<span['end']<=end:
                pieces.append(source[cursor:span['start']]);cursor=max(cursor,span['end'])
        pieces.append(source[cursor:end])
        value=''.join(pieces).strip(' \t\r\n.,;:()[]')
        if matrix and value=='Matrix row': return ''
        if point.get('x') is not None and bindings.get('x') and bindings.get('x_unit'):
            if value.casefold()==f"At time {point['x']} {point.get('_x_unit','')}".casefold(): return ''
        return value
    if remainder(prefix) or remainder(suffix): raise ValueError('Source condition/population/time scope was omitted or is ambiguous.')


def _uncertainty(point,series,context):
    u=point['uncertainty']
    if u is None: return None
    ids=point['claim_ids'];b=dict(u['bindings'])
    same_statement=(b['group']==point['bindings']['group'])
    scope_keys=[k for k in ('population','condition','x') if k in point]
    if point.get('x') is not None and point.get('_x_unit'): scope_keys.append('x_unit')
    # Same-clause inline uncertainty can share its already-bound scope words;
    # another statement must establish them independently.
    if same_statement:
        for key in scope_keys:
            if key not in b and key in point['bindings']: b[key]=point['bindings'][key]
    v=_values(b,ids,context)
    roles=['group','kind','unit']+(['magnitude'] if u['kind'] in {'SD','SEM'} else ['lower','upper'])
    for key in scope_keys:
        expected=point.get('_x_unit') if key=='x_unit' else point[key]
        if v.get(key)!=expected: raise ValueError('Uncertainty has a different or unstated observation scope.')
        roles.append(key)
    if point['quantity'] not in {'mean',series['unit']}:
        if v.get('quantity')!=point['quantity']: raise ValueError('Uncertainty quantity is not source-owned.')
        roles.append('quantity')
    source,lower,upper=_clause(b,roles,context)
    _retained_statement(source,lower,upper,ids,context)
    _scope(source,lower,upper,b,point)
    if v['group']!=point['group'] or v['unit']!=series['unit']: raise ValueError('Uncertainty belongs to another observation.')
    if u['kind']!='source_interval' and v['kind']!=u['kind']: raise ValueError('Uncertainty definition changed.')
    if u['kind']=='source_interval' and v['kind'].casefold() not in {'range','interval'}: raise ValueError('Unknown source interval definition.')
    amount='magnitude' if 'magnitude' in u else 'lower'
    if not b['group']['end']<=b['kind']['start']<b['kind']['end']<=b[amount]['start']: raise ValueError('Uncertainty is not attached to this group.')
    between=source[b['group']['end']:b['kind']['start']].strip()
    if same_statement and point['bindings']['unit']['end']<=b['kind']['start']:
        center=source[b['group']['end']:point['bindings']['unit']['end']].strip()
        if between.startswith(center) and not between[len(center):].strip(' ([:;'): between=''
    if between and ('level' not in u or between!=u['level']): raise ValueError('Ambiguous uncertainty group/definition.')
    if not re.fullmatch(r'\s*[:=]?\s*',source[b['kind']['end']:b[amount]['start']]): raise ValueError('Ambiguous uncertainty amount.')
    if any(v[k]!=u[k] for k in ('magnitude','lower','upper') if k in u): raise ValueError('Uncertainty number changed.')
    if 'magnitude' in u:
        if Decimal(u['magnitude'])<0: raise ValueError('Negative uncertainty.')
        if source[b['magnitude']['end']:b['unit']['start']].strip(): raise ValueError('Uncertainty unit mismatch.')
    else:
        low,high=Decimal(u['lower']),Decimal(u['upper'])
        if low>high or point['value'] is not None and not low<=Decimal(point['value'])<=high: raise ValueError('Interval does not contain stated center.')
        if not re.fullmatch(r'\s*(?:-|–|to|,)\s*',source[b['lower']['end']:b['upper']['start']]): raise ValueError('Interval endpoints not associated.')
        if source[b['upper']['end']:b['unit']['start']].strip(): raise ValueError('Interval unit mismatch.')
        if 'level' in u:
            if v.get('level')!=u['level']: raise ValueError('Unstated confidence level.')
            _clause(b,roles+['level'],context)
        elif u['kind']=='CI': raise ValueError('Confidence interval needs its stated confidence level.')
    from .grounding import _contains
    if not any(all(_contains(v[k],context.claims_by_id[id].claim) for k in roles) for id in ids):
        raise ValueError('Uncertainty is absent from a retained scoped claim.')
    return MappingProxyType(u)


def checked_observations(payload,registry,context):
    from .grounding import _bound_text,_contains,support_for
    from .registry import resolve_fragment
    from .ownership import source_owner
    if registry is not None:
        raise ValueError('Resolve request-scoped bindings before observation checking.')
    result=[];kind=payload['chart_type'];matrix_cells=set()
    if kind in {'bar','distribution','heatmap'} and payload['y_scale']!='linear': raise ValueError('Categorical/bar views require a linear source scale.')
    if kind=='heatmap' and payload['x_scale']!='linear': raise ValueError('Heatmap axes are categorical.')
    payload['x_label']='Group' if kind in {'bar','distribution'} else 'Source x'
    payload['y_label']='Value'
    for series in payload['series']:
        _bound_text(series['identity'],context);series['label']=series['identity']['text']
        if series['unit']!=payload['unit']: raise ValueError('Incompatible source units.')
        last_x=None;trajectory=None
        for p in series['points']:
            if p['origin']!='source_observation': raise ValueError('Calculated/simulated observations are not supported.')
            if re.search(r'\b(?:no|not|never|without|absent|none|may|might)\b',p['quantity'],re.I): raise ValueError('Negation/modality is not an observation quantity.')
            support=support_for(p['claim_ids'],context)
            if support['status']!='native_verified' or support['provenance']!=['native_text']: raise ValueError('Unverified observed number.')
            b=p['bindings'];v=_values(b,p['claim_ids'],context)
            roles=['group','value','unit','quantity']
            for key in ('population','condition','column','bin_lower','bin_upper','x'):
                if key in p:
                    if v.get(key)!=p[key]: raise ValueError('Changed source observation field.')
                    roles.append(key)
            if 'x' in p and payload.get('x_unit'):
                if v.get('x_unit')!=payload['x_unit']: raise ValueError('Unbound x unit.')
                roles.append('x_unit')
            if re.search(r'%|percent|proportion|rate',series['unit'],re.I): roles+=['scope','denominator']
            source,lower,upper=_clause(b,roles,context)
            _retained_statement(source,lower,upper,p['claim_ids'],context)
            if 'x' in p:
                # Span existence does not give a number an independent-variable
                # role. This source grammar explicitly states time and its unit;
                # unrecognised native table/prose formats remain declined.
                xunit=payload.get('x_unit')
                pattern=r'\bAt time\s+(?P<x>'+re.escape(p['x'])+r')\s+(?P<unit>'+re.escape(xunit or '')+r')(?!\w)'
                explicit=any(m.span('x')==(b['x']['start'],b['x']['end']) and
                    b.get('x_unit') and m.span('unit')==(b['x_unit']['start'],b['x_unit']['end']) and
                    (m.end()<=b['group']['start'] or m.start()>=b['unit']['end'])
                    for m in re.finditer(pattern,source,flags=re.I)) if xunit else False
                if not explicit: raise ValueError('Numeric x has no explicit source-stated independent-variable ownership.')
            scoped_point={**p,'_x_unit':payload.get('x_unit')}
            _scope(source,lower,upper,b,scoped_point,matrix=kind=='heatmap',inline=p['uncertainty'])
            if v['group']!=p['group'] or v['unit']!=series['unit'] or v['quantity']!=p['quantity']: raise ValueError('Changed group/unit/quantity.')
            if p['value'] is None:
                if not re.fullmatch(r'not (?:reported|stated|measured)|missing',v['value'],re.I): raise ValueError('Unstated missing value.')
                if p['uncertainty'] is not None: raise ValueError('Missing center cannot have a regenerated uncertainty bar.')
            elif v['value']!=p['value']: raise ValueError('Changed observed number.')
            if not b['group']['end']<=b['value']['start']<b['value']['end']<=b['unit']['start']: raise ValueError('Wrong quantity ownership.')
            connector=source[b['group']['end']:b['value']['start']]
            if kind=='heatmap':
                if 'column' not in p or not re.fullmatch(r'\s*,\s*column\s+'+re.escape(p['column'])+r'\s*:\s*',connector): raise ValueError('Missing row/header association.')
                cell=(p['group'],p['column'])
                if cell in matrix_cells: raise ValueError('Duplicate matrix cell.')
                matrix_cells.add(cell)
            else:
                if b['group']['end']<=b['quantity']['start']<b['quantity']['end']<=b['value']['start']:
                    connector=source[b['group']['end']:b['quantity']['start']]+source[b['quantity']['end']:b['value']['start']]
                if not re.fullmatch(r'\s*(?::|=|has|had|contains|is|was)?\s*',connector,re.I): raise ValueError('Ambiguous direct observation.')
            if source[b['value']['end']:b['unit']['start']].strip(): raise ValueError('Value/unit attachment changed.')
            if not any(all(_contains(v[k],context.claims_by_id[id].claim) for k in roles) for id in p['claim_ids']): raise ValueError('Observation absent from retained scoped claim.')
            if kind in {'line','scatter'} and 'x' not in p: raise ValueError('Missing observed x.')
            if kind=='line':
                current=(source_owner(context.evidence[b['group']['cite_id']-1]),
                         p['group'],p.get('population'),p.get('condition'),p['quantity'])
                if series['identity']['text']!=p['group'] or trajectory is not None and current!=trajectory: raise ValueError('Cross-entity trajectory.')
                trajectory=current;x=Decimal(p['x'])
                if last_x is not None and x<=last_x: raise ValueError('Unordered trajectory.')
                last_x=x
            if kind=='distribution':
                mode=payload.get('distribution_mode')
                if mode=='source_bins':
                    if not {'bin_lower','bin_upper'}<=p.keys() or Decimal(p['bin_lower'])>=Decimal(p['bin_upper']): raise ValueError('Unstated distribution bin.')
                    if not (b['group']['start']<=b['bin_lower']['start']<b['bin_lower']['end']<=b['bin_upper']['start']<b['bin_upper']['end']<=b['group']['end']): raise ValueError('Foreign distribution bin endpoints.')
                elif mode!='samples' or re.search(r'\b(?:mean|average|SD|SEM|CI|bin)\b',source[lower:upper],re.I): raise ValueError('Summary statistics are not individual samples.')
            for axis,value in (('x',p.get('x')),('y',p['value'])):
                if payload[f'{axis}_scale']=='log' and value is not None and Decimal(value)<=0: raise ValueError('Nonpositive log observation.')
            uncertainty=_uncertainty(scoped_point,series,context);p['support']=support
            result.append(CheckedObservation(p['id'],series['id'],p['group'],p['quantity'],p['value'],series['unit'],p.get('x'),payload.get('x_unit'),p.get('population'),uncertainty,MappingProxyType(b),MappingProxyType(support)))
    return tuple(result)
