import json
import unittest
from dataclasses import replace
from types import MappingProxyType
from aura_bio.study.claims import StructuredClaim
from aura_bio.visual_outputs.schema import parse_visual
from aura_bio.visual_outputs.grounding import ground_visual
from visual_output_fixtures import context


def fixture(sentences=('At time 0 h, Culture A: 33 cells.','At time 1 h, Culture A: 38 cells.'),method='native_text'):
    ctx=context(method);text=' '.join(sentences)
    claims=tuple(StructuredClaim(f'c{i+1}',s,(1,)) for i,s in enumerate(sentences))
    ctx=replace(ctx,claims=claims,claims_by_id=MappingProxyType({c.id:c for c in claims}),
        basis_by_id=MappingProxyType({c.id:ctx.basis_by_id['c1'] for c in claims}),evidence=(replace(ctx.evidence[0],text=text,provenance=method),))
    def bind(needle,sentence=0):
        offset=sum(len(s)+1 for s in sentences[:sentence]);start=text.index(needle,offset,offset+len(sentences[sentence]))
        return {'cite_id':1,'start':start,'end':start+len(needle)}
    points=[]
    for i,s in enumerate(sentences):
        if ': 33' not in s and ': 38' not in s: continue
        value='33' if ': 33' in s else '38';group='Culture A' if 'Culture A' in s else 'Culture B'
        points.append({'id':f'o{i}','group':group,'value':value,'quantity':'cells','origin':'source_observation',
            'claim_ids':[f'c{i+1}'],'uncertainty':None,'bindings':{k:bind(v,i) for k,v in
                {'group':group,'value':value,'unit':'cells','quantity':'cells'}.items()}})
        if s.startswith('At time'):
            points[-1]['x']=str(i);points[-1]['bindings'].update(x=bind(str(i),i),x_unit=bind('h',i))
    identity_text='Culture A' if 'Culture A' in sentences[0] else sentences[0]
    identity={'text':identity_text,'claim_ids':['c1'],'bindings':[bind(identity_text)]}
    spec={'version':2,'id':'plot','kind':'plot','title':'Data','description':'','payload':{
        'chart_type':'line','x_label':'Time','y_label':'Count','unit':'cells','x_unit':'h','x_scale':'linear','y_scale':'linear',
        'series':[{'id':'s1','label':'Culture A','unit':'cells','identity':identity,'points':points}]}}
    return ctx,spec,bind


class ObservationV2Tests(unittest.TestCase):
    def check(self,ctx,spec):
        try: return ground_visual(parse_visual(json.dumps(spec),ctx),ctx)
        except ValueError: return None

    def test_same_entity_time_series_allowed_but_different_groups_cannot_join(self):
        ctx,spec,_=fixture();result=self.check(ctx,spec)
        self.assertIsNotNone(result,'V2 observation contract is absent');self.assertEqual(result.status,'ready')
        ctx,spec,_=fixture(('At time 0 h, Culture A: 33 cells.','At time 1 h, Culture B: 38 cells.'))
        self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')

    def test_swapped_value_rejected(self):
        ctx,spec,_=fixture();spec['payload']['series'][0]['points'][0]['value']='38'
        self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')

    def test_general_plot_cannot_drop_a_retained_condition_or_numeric_sign(self):
        for retained in ('Culture A: 33 cells without oxygen.','Culture A: -33 cells.'):
            with self.subTest(retained=retained):
                ctx,spec,_=fixture(('Culture A: 33 cells.',))
                claim=StructuredClaim('c1',retained,(1,))
                ctx=replace(ctx,claims=(claim,),claims_by_id=MappingProxyType({'c1':claim}))
                spec['payload']['chart_type']='bar'
                self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')

    def test_vlm_ocr_or_simulation_origin_rejected(self):
        for method in ('vlm','ocr'):
            ctx,spec,_=fixture(method=method)
            self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')
        ctx,spec,_=fixture();spec['payload']['series'][0]['points'][0]['origin']='simulation'
        self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')

    def test_source_sd_is_not_an_inferred_ci(self):
        ctx,spec,bind=fixture(('Sample A mean: 10 cells.','Sample A SD: 2 cells.'))
        point={'id':'o1','group':'Sample A','value':'10','quantity':'mean','origin':'source_observation',
            'claim_ids':['c1','c2'],'bindings':{k:bind(v) for k,v in {'group':'Sample A','value':'10','unit':'cells','quantity':'mean'}.items()},
            'uncertainty':{'kind':'SD','magnitude':'2','bindings':{k:bind(v,1) for k,v in {'group':'Sample A','kind':'SD','magnitude':'2','unit':'cells'}.items()}}}
        spec['payload'].update(chart_type='bar');series=spec['payload']['series'][0]
        series.update(points=[point],identity={'text':'Sample A','claim_ids':['c1'],'bindings':[bind('Sample A')]})
        result=self.check(ctx,spec)
        self.assertIsNotNone(result,'V2 uncertainty contract is absent');self.assertEqual(result.status,'ready')
        self.assertEqual(result.spec.payload['series'][0]['points'][0]['uncertainty']['magnitude'],'2')
        point['uncertainty']['kind']='SEM'
        self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')
        point['uncertainty']['kind']='SD';spec['payload']['chart_type']='distribution';spec['payload']['distribution_mode']='samples'
        self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')

    def test_heatmap_cells_keep_row_and_column_ownership(self):
        ctx,spec,bind=fixture(('Matrix row Gene A, column Sample A: 2 units.',))
        point={'id':'o1','group':'Gene A','column':'Sample A','value':'2','quantity':'units','origin':'source_observation',
            'claim_ids':['c1'],'uncertainty':None,'bindings':{k:bind(v) for k,v in
                {'group':'Gene A','column':'Sample A','value':'2','unit':'units','quantity':'units'}.items()}}
        spec['payload'].update(chart_type='heatmap',unit='units');series=spec['payload']['series'][0]
        series.update(unit='units',points=[point],identity={'text':'Gene A','claim_ids':['c1'],'bindings':[bind('Gene A')]})
        result=self.check(ctx,spec)
        self.assertIsNotNone(result,'V2 heatmap contract is absent');self.assertEqual(result.status,'ready')
        point['column']='Sample B'
        self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')

    def test_missing_stays_null_not_zero(self):
        ctx,spec,bind=fixture(('Culture A: not reported cells.',))
        point={'id':'o1','group':'Culture A','value':None,'quantity':'cells','origin':'source_observation',
            'claim_ids':['c1'],'uncertainty':None,'bindings':{k:bind(v) for k,v in
                {'group':'Culture A','value':'not reported','unit':'cells','quantity':'cells'}.items()}}
        spec['payload']['chart_type']='bar';spec['payload']['series'][0]['points']=[point]
        result=self.check(ctx,spec)
        self.assertIsNotNone(result,'V2 missing-value contract is absent');self.assertEqual(result.status,'ready')
        self.assertIsNone(result.spec.payload['series'][0]['points'][0]['value'])

    def test_negation_cannot_be_removed_as_a_quantity_label(self):
        ctx,spec,bind=fixture(('Culture A no: 33 cells.',))
        spec['payload']['chart_type']='bar';point=spec['payload']['series'][0]['points'][0]
        point['quantity']='no';point['bindings']['quantity']=bind('no')
        self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')

    def test_omitted_prefix_and_suffix_conditions_cannot_become_unconditional_data(self):
        ctx,spec,_=fixture(('At time 0 h, Culture A: 33 cells with treatment.',
                            'At time 1 h, Culture A: 38 cells without treatment.'))
        self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')
        ctx,spec,_=fixture(('Without oxygen, Culture A: 33 cells.',))
        spec['payload']['chart_type']='bar'
        self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')

    def test_explicit_condition_is_retained_in_a_bar(self):
        ctx,spec,bind=fixture(('Without oxygen, Culture A: 33 cells.',))
        spec['payload']['chart_type']='bar';p=spec['payload']['series'][0]['points'][0]
        p['condition']='Without oxygen';p['bindings']['condition']=bind('Without oxygen')
        result=self.check(ctx,spec)
        self.assertIsNotNone(result);self.assertEqual(result.status,'ready')

    def test_sd_cannot_attach_to_a_different_condition(self):
        ctx,spec,bind=fixture(('Culture A mean: 33 cells under treatment.',
                              'Culture A SD: 2 cells without treatment.'))
        spec['payload']['chart_type']='bar';p=spec['payload']['series'][0]['points'][0]
        p.update(quantity='mean',condition='under treatment',claim_ids=['c1','c2'])
        p['bindings'].update(quantity=bind('mean'),condition=bind('under treatment'))
        p['uncertainty']={'kind':'SD','magnitude':'2','bindings':{k:bind(v,1) for k,v in
            {'group':'Culture A','kind':'SD','magnitude':'2','unit':'cells'}.items()}}
        self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')

    def test_source_value_cannot_be_relabelled_as_an_independent_x(self):
        ctx,spec,bind=fixture(('Culture A: 33 cells.','Culture A: 38 cells.'))
        spec['payload'].pop('x_unit')
        for n,p in enumerate(spec['payload']['series'][0]['points']):
            p['x']=p['value'];p['bindings']['x']=bind(p['value'],n)
        self.assertNotEqual(getattr(self.check(ctx,spec),'status',None),'ready')


if __name__=='__main__': unittest.main()
