"""Checked graph records. Layout never invents biological relationships."""
from dataclasses import dataclass
from types import MappingProxyType
import re


@dataclass(frozen=True)
class CheckedRelation:
    subject_id: str
    predicate: str
    object_id: str
    qualifiers: tuple[str,...]
    claim_ids: tuple[str,...]
    bindings: tuple[dict,...]
    support: object


def checked_relations(proposal,registry,context):
    from .grounding import _relation,_binding,normalized
    from .registry import resolve_fragment
    from .ownership import source_owner
    nodes={n['id']:n for n in proposal['nodes']};checked=[];node_owners={}
    for edge in proposal['edges']:
        left=nodes[edge['from_id']]['label'];right=nodes[edge['to_id']]['label']
        conditions=edge['conditions'];qualifiers=edge['qualifiers']
        # Accept two exact representations of the SAME proposition, not a
        # semantic repair. Small models sometimes repeat node labels despite
        # the predicate-only field contract. Strip only these exact endpoints;
        # claim equality and full source binding below remain mandatory.
        suffix=right+(' '+' '.join(conditions) if conditions else '')
        full=re.fullmatch(re.escape(left)+r'\s+(.+?)\s+'+re.escape(suffix)+r'\.?',edge['label'])
        if full: edge['label']=full.group(1)
        required=set(re.findall(r'\b(?:may|might|could|can|not|only|unless)\b',edge['label'].casefold()))
        if not required<=set(q.casefold() for q in qualifiers): raise ValueError('Dropped relationship qualifier.')
        right+=' '+ ' '.join(conditions) if conditions else ''
        _relation(edge,left,right,context)
        proposition=normalized(f"{left} {edge['label']} {right}")
        bindings=[];texts=[];owners=set()
        for binding in edge['bindings']:
            if 'fragment_id' in binding:
                if registry is None: raise ValueError('Unresolved relation binding.')
                binding=resolve_fragment(registry,binding['fragment_id'],context)
            text,evidence=_binding(binding,edge['claim_ids'],context);bindings.append(binding);texts.append(text)
            if normalized(text)==proposition: owners.add(source_owner(evidence))
        if not any(normalized(text)==proposition for text in texts): raise ValueError('Relationship lacks a complete exact source binding.')
        if any(not any(normalized(q) in normalized(text) for text in texts) for q in qualifiers): raise ValueError('Unbound qualifier.')
        for node_id in (edge['from_id'],edge['to_id']):
            node_owners.setdefault(node_id,set()).update(owners)
            if len(node_owners[node_id])>1:
                raise ValueError('Same label does not establish shared entity identity across documents.')
        checked.append(CheckedRelation(edge['from_id'],edge['relation'],edge['to_id'],tuple(qualifiers),
            tuple(edge['claim_ids']),tuple(bindings),MappingProxyType(edge['support'])))
    return tuple(checked)


def check_groups(payload,context):
    from .grounding import _relation,_binding,normalized,support_for
    nodes={n['id']:n for n in payload['nodes']}
    for n,group in enumerate(payload['groups'],1):
        if group['mode']=='presentation':
            if group['claim_ids'] or group['bindings'] or not re.fullmatch(r'(?:Group|Stage) [1-8]',group['label']):
                raise ValueError('Presentation group cannot assert an unsupported compartment.')
            group['label']=f'Presentation group {n}'
            continue
        if not group['claim_ids'] or not group['bindings']: raise ValueError('Unsupported compartment.')
        for id in group['node_ids']:
            relation={'relation':'part_of','label':'part of','claim_ids':group['claim_ids']}
            _relation(relation,nodes[id]['label'],group['label'],context)
            phrase=normalized(f"{nodes[id]['label']} part of {group['label']}")
            if not any(normalized(_binding(b,group['claim_ids'],context)[0])==phrase for b in group['bindings']):
                raise ValueError('Unbound compartment membership.')
        group['support']=support_for(group['claim_ids'],context)
    check_graph_ownership(payload,context)


def check_graph_ownership(payload,context):
    """One identity invariant for every factual edge and containment group."""
    from .grounding import _binding,normalized
    from .ownership import source_owner
    nodes={n['id']:n for n in payload['nodes']};owners_by_node={}
    def proof_owners(bindings,ids,proposition):
        result=set()
        for binding in bindings:
            text,evidence=_binding(binding,ids,context)
            if normalized(text)==normalized(proposition): result.add(source_owner(evidence))
        if not result: raise ValueError('No source-owned complete proposition.')
        return result
    def attach(node_id,owners):
        owners_by_node.setdefault(node_id,set()).update(owners)
        if len(owners_by_node[node_id])>1:
            raise ValueError('Same label does not establish shared entity identity across documents.')
    for edge in payload['edges']:
        proposition=f"{nodes[edge['from_id']]['label']} {edge['label']} {nodes[edge['to_id']]['label']} {' '.join(edge['conditions'])}"
        owners=proof_owners(edge['bindings'],edge['claim_ids'],proposition)
        for id in (edge['from_id'],edge['to_id']): attach(id,owners)
    for group in payload['groups']:
        if group['mode']=='presentation': continue
        group_owners=set()
        for id in group['node_ids']:
            owners=proof_owners(group['bindings'],group['claim_ids'],f"{nodes[id]['label']} part of {group['label']}")
            group_owners.update(owners);attach(id,owners)
        if len(group_owners)>1:
            raise ValueError('Same compartment label does not establish shared container identity across documents.')
