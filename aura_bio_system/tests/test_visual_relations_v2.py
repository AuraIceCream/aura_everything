import json
import unittest
from dataclasses import replace
from types import MappingProxyType
from aura_bio.study.claims import StructuredClaim
from aura_bio.visual_outputs.schema import parse_visual
from aura_bio.visual_outputs.grounding import ground_visual
from visual_output_fixtures import context,diagram,binding


def graph():
    value=diagram();value['version']=2
    value['payload'].update(orientation='LR',layout='pathway',groups=[])
    for node in value['payload']['nodes']: node['role']='entity'
    value['payload']['edges'][0].update(qualifiers=[],conditions=[],bindings=[binding('ORION activates VEGA.')])
    return value


class VisualRelationsV2Tests(unittest.TestCase):
    def check(self,value,ctx=None):
        ctx=ctx or context()
        try: return ground_visual(parse_visual(json.dumps(value),ctx),ctx)
        except ValueError: return None

    def test_v1_graph_unchanged(self):
        self.assertEqual(self.check(diagram()).status,'ready')

    def test_qualifier_field_cannot_carry_invented_metadata(self):
        value=graph()
        value['payload']['edges'][0]['qualifiers']=['modality: activation']
        with self.assertRaises(ValueError):
            parse_visual(json.dumps(value),context())

    def test_complete_source_sentence_label_is_canonicalized_without_changing_fact(self):
        value=graph();value['payload']['edges'][0]['label']='ORION activates VEGA'
        result=self.check(value)
        self.assertEqual(result.status,'ready')
        self.assertEqual(result.spec.payload['edges'][0]['label'],'activates')
        value['payload']['edges'][0]['label']='ORION causes VEGA'
        self.assertNotEqual(self.check(value).status,'ready')

    def test_full_sentence_cannot_retarget_a_relation_or_drop_modality(self):
        value=graph();edge=value['payload']['edges'][0]
        value['payload']['nodes'][0].update(label='VEGA',claim_ids=['c2'])
        value['payload']['nodes'][1].update(label='LUMEN',claim_ids=['c2'])
        edge.update(relation='inhibits',label='VEGA inhibit LUMEN',claim_ids=['c2'],qualifiers=[],
                    bindings=[binding('VEGA may inhibit LUMEN.')])
        self.assertNotEqual(self.check(value).status,'ready')
        edge.update(label='ORION activates VEGA',relation='activates')
        self.assertNotEqual(self.check(value).status,'ready')

    def test_may_inhibit_and_negative_condition_survive(self):
        value=graph();ctx=context()
        claim=StructuredClaim('c2','VEGA may not inhibit LUMEN without oxygen.',(1,))
        evidence=replace(ctx.evidence[0],text=claim.claim)
        ctx=replace(ctx,claims=(claim,),claims_by_id=MappingProxyType({'c2':claim}),
                    basis_by_id=MappingProxyType({'c2':ctx.basis_by_id['c2']}),evidence=(evidence,))
        value['payload']['nodes']=[{'id':'n1','label':'VEGA','role':'entity','claim_ids':['c2']},
                                   {'id':'n2','label':'LUMEN','role':'entity','claim_ids':['c2']}]
        edge=value['payload']['edges'][0]
        edge.update(relation='inhibits',label='may not inhibit',qualifiers=['may','not'],conditions=['without oxygen'],
                    claim_ids=['c2'],bindings=[{'cite_id':1,'start':0,'end':len(claim.claim)}])
        result=self.check(value,ctx)
        self.assertIsNotNone(result,'V2 relationship contract is absent')
        self.assertEqual(result.status,'ready')
        self.assertIn('may',result.spec.payload['edges'][0]['qualifiers'])
        edge['qualifiers']=[]
        self.assertNotEqual(getattr(self.check(value,ctx),'status',None),'ready')

    def test_group_membership_requires_own_support(self):
        value=graph()
        value['payload']['groups']=[{'id':'g','label':'Membrane','node_ids':['n1'],
            'mode':'containment','claim_ids':['c1'],'bindings':[binding('ORION activates VEGA.')]}]
        self.assertNotEqual(getattr(self.check(value),'status',None),'ready')
        value['payload']['groups'][0].update(mode='presentation',label='Group 1',claim_ids=[],bindings=[])
        result=self.check(value)
        self.assertIsNotNone(result,'V2 grouping contract is absent')
        self.assertEqual(result.status,'ready')

    def test_cycle_layout_cannot_invent_return_edge(self):
        value=graph();value['payload']['layout']='cycle'
        result=self.check(value)
        self.assertIsNotNone(result,'V2 cycle contract is absent')
        self.assertEqual(result.status,'ready');self.assertEqual(len(result.spec.payload['edges']),1)
        value['payload']['edges'].append({**value['payload']['edges'][0],'from_id':'n2','to_id':'n1'})
        self.assertNotEqual(getattr(self.check(value),'status',None),'ready')

    def test_association_as_causation_rejected(self):
        value=graph();value['payload']['edges'][0].update(relation='causes',label='causes')
        self.assertNotEqual(getattr(self.check(value),'status',None),'ready')

    def test_source_binding_cannot_be_a_node_cooccurrence(self):
        value=graph();value['payload']['edges'][0]['bindings']=[binding('ORION')]
        self.assertNotEqual(getattr(self.check(value),'status',None),'ready')


if __name__=='__main__': unittest.main()
