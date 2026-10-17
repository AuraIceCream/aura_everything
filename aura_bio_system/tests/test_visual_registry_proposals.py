import json
import unittest
from dataclasses import replace
from types import MappingProxyType
from unittest.mock import patch
from aura_bio.study.claims import StructuredClaim
from visual_output_fixtures import context,plot,diagram
from aura_bio.api.generation import OllamaGenerator
from aura_bio.visual_outputs.planner import plan_visual


class RegistryProposalTests(unittest.TestCase):
    def call(self, *, auto=False, swap=False, foreign=False):
        sent=[]; ctx=context()
        # Keep this fixture on the general fragment protocol: a non-canonical
        # checked observation must not be silently dropped by the simple compiler.
        extra=StructuredClaim('c6','The median count is approximately 2 cells.',(1,))
        ctx=replace(ctx,claims=ctx.claims+(extra,),
            claims_by_id=MappingProxyType({**ctx.claims_by_id,'c6':extra}),
            basis_by_id=MappingProxyType({**ctx.basis_by_id,'c6':ctx.basis_by_id['c4']}),
            evidence=(replace(ctx.evidence[0],text=ctx.evidence[0].text+' '+extra.claim),))
        class Response:
            def __init__(self,value): self.value=value
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return json.dumps({'done_reason':'stop','message':{'content':json.dumps(self.value)}}).encode()
        def request(req,**kwargs):
            payload=json.loads(req.data);sent.append(payload)
            user=json.loads(payload['messages'][-1]['content'])
            fragments=user.get('source_fragments',[])
            proposal=plot()
            proposal['version']=2;proposal['payload'].update(x_scale='linear',y_scale='linear')
            proposal['payload']['series'][0]['identity']={'text':'cells','claim_ids':['c4'],
                'bindings':[{'fragment_id':next((f['id'] for f in fragments if f['text']=='cells' and 'c4' in f['claims']),'missing-registry')}]}
            for point in proposal['payload']['series'][0]['points']:
                claim=point['claim_ids'][0]
                point.update(id=claim,quantity='cells',origin='source_observation',uncertainty=None)
                point['bindings']['quantity']=dict(point['bindings']['unit'])
                for role,binding in point['bindings'].items():
                    text=ctx.evidence[0].text[binding['start']:binding['end']]
                    chosen=next((f['id'] for f in fragments if f['text']==text and claim in f['claims']), 'missing-registry')
                    point['bindings'][role]={'fragment_id':chosen}
            if swap:
                first,second=proposal['payload']['series'][0]['points']
                first['value']='38';first['bindings']['value']=second['bindings']['value']
            if foreign: proposal['payload']['series'][0]['points'][0]['bindings']['value']={'fragment_id':'foreign'}
            if auto: proposal={'selected_kind':'plot','reason':'numeric_pattern','visual':proposal,'source_id':None}
            return Response(proposal)
        generator=OllamaGenerator(model='fixed-fixture')
        self.diagnostics={}
        with patch('urllib.request.urlopen',side_effect=request),patch.object(OllamaGenerator,'_wait_for_unload',return_value=1):
            result=plan_visual('auto' if auto else 'plot','Compare the counts',ctx,generator,None,diagnostics=self.diagnostics)
        return result,sent

    def test_plot_selects_ids_without_recopying_quotes(self):
        result,sent=self.call()
        self.assertEqual(result.status,'ready')
        self.assertEqual(result.spec.payload['series'][0]['points'][1]['bindings']['unit'],
                         {'cite_id':1,'start':98,'end':103})
        binding=sent[0]['format']['properties']['payload']['properties']['series']['items']['properties']['points']['items']['properties']['bindings']['properties']['value']
        self.assertIn('fragment_id',binding['properties'])
        self.assertEqual(len(sent),1)
        user=json.loads(sent[0]['messages'][-1]['content'])
        self.assertNotIn('numbered_sources',user,'Do not duplicate complete sources alongside the exact fragment registry.')

    def test_plot_prompt_excludes_unrelated_mechanisms_but_keeps_both_observations(self):
        result,sent=self.call()
        user=json.loads(sent[0]['messages'][-1]['content'])
        self.assertEqual([c['id'] for c in user['retained_claims']],['c4','c5','c6'])
        self.assertTrue(user['source_fragments'])
        self.assertTrue(all(set(f['claims']) <= {'c4','c5','c6'} for f in user['source_fragments']))
        self.assertEqual(result.status,'ready')

    def test_auto_uses_same_registry(self):
        result,sent=self.call(auto=True)
        self.assertEqual(result.status,'ready');self.assertEqual(result.spec.kind,'plot')
        self.assertEqual(len(sent),1)

    def test_valid_id_cannot_swap_group_values(self):
        result,sent=self.call(swap=True)
        self.assertEqual(result.status,'omitted');self.assertEqual(len(sent),1)
        self.assertIn('grounding_error',self.diagnostics)
        self.assertNotIn('grounding_error',result.metadata)

    def test_foreign_id_fails_without_repair_and_has_safe_reason(self):
        result,sent=self.call(foreign=True)
        self.assertEqual(result.status,'failed');self.assertEqual(len(sent),1)
        self.assertEqual(result.metadata.get('reason_code'),'invalid_proposal')
        self.assertNotIn('ORION',json.dumps(result.metadata))

    def test_numeric_catalog_transport_uses_only_checked_observation_ids(self):
        for auto in (False,True):
            with self.subTest(auto=auto):
                sent=[]
                class Response:
                    def __init__(self,value): self.value=value
                    def __enter__(self): return self
                    def __exit__(self,*args): pass
                    def read(self): return json.dumps({'done_reason':'stop','message':{'content':json.dumps(self.value)}}).encode()
                def request(req,**kwargs):
                    body=json.loads(req.data);sent.append(body)
                    user=json.loads(body['messages'][-1]['content'])
                    self.assertEqual([o['value'] for o in user['observation_candidates']],['33','38'])
                    payload={'chart_type':'bar','observation_ids':[o['id'] for o in user['observation_candidates']]}
                    value={'version':2,'id':'v1','kind':'plot','title':'Data','description':'','payload':payload}
                    if auto: value={'selected_kind':'plot','reason':'numeric_pattern','visual':value,'source_id':None}
                    return Response(value)
                generator=OllamaGenerator(model='fixed-fixture')
                with patch('urllib.request.urlopen',side_effect=request),patch.object(OllamaGenerator,'_wait_for_unload',return_value=1):
                    result=plan_visual('auto' if auto else 'plot','Compare the counts',context(),generator,None)
                self.assertEqual(result.status,'ready');self.assertEqual(len(sent),1)
                self.assertEqual([p['value'] for p in result.spec.payload['series'][0]['points']],['33','38'])

    def test_structural_catalogs_use_one_call_in_manual_and_auto_modes(self):
        for kind in ('diagram','comparison','procedure'):
            for auto in (False,True):
                with self.subTest(kind=kind,auto=auto):
                    sent=[]
                    class Response:
                        def __init__(self,value): self.value=value
                        def __enter__(self): return self
                        def __exit__(self,*args): pass
                        def read(self): return json.dumps({'done_reason':'stop','message':{'content':json.dumps(self.value)}}).encode()
                    def request(req,**kwargs):
                        body=json.loads(req.data);sent.append(body)
                        user=json.loads(body['messages'][-1]['content'])
                        payload={'fact_ids':[f['id'] for f in user['checked_fact_candidates'][kind]]}
                        if kind=='diagram': payload.update(orientation='LR',layout='pathway')
                        value={'version':2 if kind=='diagram' else 1,'id':'v1','kind':kind,'title':'Data','description':'','payload':payload}
                        if auto: value={'selected_kind':kind,'reason':'explicit_request','visual':value,'source_id':None}
                        return Response(value)
                    generator=OllamaGenerator(model='fixed-fixture')
                    with patch('urllib.request.urlopen',side_effect=request),patch.object(OllamaGenerator,'_wait_for_unload',return_value=1):
                        result=plan_visual('auto' if auto else kind,'Visualize the source statements',context(),generator,None)
                    self.assertEqual(result.status,'ready');self.assertEqual(len(sent),1)
                    if kind=='diagram': self.assertEqual(len(result.spec.payload['edges']),3)
                    if kind=='procedure': self.assertEqual([s['text'] for s in result.spec.payload['steps']],['ORION','VEGA'])
                    if kind=='comparison': self.assertEqual([c['text'] for c in result.spec.payload['columns']],['Group A','Group B'])
