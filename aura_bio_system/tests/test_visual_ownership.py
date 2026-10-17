import json
import unittest
from dataclasses import replace
from types import MappingProxyType
from aura_bio.study.claims import StructuredClaim
from aura_bio.visual_outputs.schema import parse_visual
from aura_bio.visual_outputs.grounding import ground_visual
from visual_output_fixtures import context


class VisualOwnershipTests(unittest.TestCase):
    def owned_context(self,texts,ids):
        ctx=context();claims=tuple(StructuredClaim(id,text,(n+1,)) for n,(id,text) in enumerate(zip(ids,texts)))
        return replace(ctx,claims=claims,claims_by_id=MappingProxyType({c.id:c for c in claims}),
            basis_by_id=MappingProxyType({c.id:ctx.basis_by_id[c.id] for c in claims}),
            evidence=tuple(replace(ctx.evidence[0],text=text,document_id=letter*32,chunk_id=f'chunk{n}')
                           for n,(text,letter) in enumerate(zip(texts,'ab'))))

    def test_general_proposal_cannot_merge_document_owned_graph_nodes(self):
        from aura_bio.visual_outputs.fact_catalog import compile_fact_catalog,expand_fact_selection
        ctx=self.owned_context(['A activates B.','B inhibits C.'],['c1','c2'])
        catalog=compile_fact_catalog('diagram',ctx)
        spec=expand_fact_selection({'fact_ids':[f['id'] for f in catalog.facts],'orientation':'LR','layout':'pathway'},catalog,ctx)
        edges=spec['payload']['edges'];old=edges[1]['from_id'];shared=edges[0]['to_id']
        edges[1]['from_id']=shared
        spec['payload']['nodes']=[n for n in spec['payload']['nodes'] if n['id']!=old]
        next(n for n in spec['payload']['nodes'] if n['id']==shared)['claim_ids']=['c1','c2']
        self.assertNotEqual(ground_visual(parse_visual(json.dumps(spec),ctx),ctx).status,'ready')

    def test_general_proposal_cannot_merge_document_owned_trajectories(self):
        from aura_bio.visual_outputs.catalog import compile_plot_catalog
        ctx=self.owned_context(['At time 0 h, Group A: 33 cells.','At time 1 h, Group A: 38 cells.'],['c4','c5'])
        catalog=compile_plot_catalog(ctx)
        points=[{k:v for k,v in o['point'].items() if not k.startswith('_')} for o in catalog.observations]
        identity={'text':'Group A','claim_ids':['c4'],'bindings':[points[0]['bindings']['group']]}
        spec={'version':2,'id':'line','kind':'plot','title':'Data','description':'','payload':{
            'chart_type':'line','unit':'cells','x_unit':'h','x_label':'Time','y_label':'Cells','x_scale':'linear','y_scale':'linear',
            'series':[{'id':'s1','label':'Group A','unit':'cells','identity':identity,'points':points}]}}
        self.assertNotEqual(ground_visual(parse_visual(json.dumps(spec),ctx),ctx).status,'ready')

    def test_containment_cannot_attach_another_documents_membership_to_a_node(self):
        from aura_bio.visual_outputs.fact_catalog import compile_fact_catalog,expand_fact_selection
        ctx=self.owned_context(['A activates B.','B part of Membrane.'],['c1','c2'])
        catalog=compile_fact_catalog('diagram',ctx)
        spec=expand_fact_selection({'fact_ids':[catalog.facts[0]['id']],'orientation':'LR','layout':'pathway'},catalog,ctx)
        member=spec['payload']['edges'][0]['to_id']
        spec['payload']['groups']=[{'id':'g1','label':'Membrane','node_ids':[member],'mode':'containment',
            'claim_ids':['c2'],'bindings':[{'cite_id':2,'start':0,'end':len(ctx.evidence[1].text)}]}]
        self.assertNotEqual(ground_visual(parse_visual(json.dumps(spec),ctx),ctx).status,'ready')

    def test_same_compartment_label_cannot_merge_distinct_document_containers(self):
        from aura_bio.visual_outputs.fact_catalog import compile_fact_catalog,expand_fact_selection
        ctx=self.owned_context(['A part of Membrane.','B part of Membrane.'],['c1','c2'])
        catalog=compile_fact_catalog('diagram',ctx)
        spec=expand_fact_selection({'fact_ids':[f['id'] for f in catalog.facts],'orientation':'LR','layout':'pathway'},catalog,ctx)
        members=[e['from_id'] for e in spec['payload']['edges']]
        spec['payload']['groups']=[{'id':'g1','label':'Membrane','node_ids':members,'mode':'containment',
            'claim_ids':['c1','c2'],'bindings':[{'cite_id':n+1,'start':0,'end':len(e.text)} for n,e in enumerate(ctx.evidence)]}]
        self.assertNotEqual(ground_visual(parse_visual(json.dumps(spec),ctx),ctx).status,'ready')


if __name__=='__main__': unittest.main()
