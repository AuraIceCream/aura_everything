import json
import unittest
from dataclasses import replace
from types import MappingProxyType

from aura_bio.study.claims import StructuredClaim
from aura_bio.visual_outputs.schema import parse_visual
from aura_bio.visual_outputs.grounding import ground_visual
from visual_output_fixtures import context


class PlotCatalogTests(unittest.TestCase):
    def api(self):
        from aura_bio.visual_outputs import catalog
        return catalog

    def test_checked_counts_are_assembled_without_model_recopy(self):
        api=self.api();ctx=context();catalog=api.compile_plot_catalog(ctx)
        self.assertTrue(catalog.complete)
        self.assertEqual([o['point']['value'] for o in catalog.observations],['33','38'])
        self.assertEqual([o['point']['group'] for o in catalog.observations],['Group A','Group B'])
        ids=[o['id'] for o in catalog.observations]
        spec=api.expand_plot_selection({'chart_type':'bar','observation_ids':ids},catalog,ctx)
        result=ground_visual(parse_visual(json.dumps(spec),ctx),ctx)
        self.assertEqual(result.status,'ready')
        self.assertEqual(result.spec.payload['series'][0]['points'][1]['bindings']['value'],
                         {'cite_id':1,'start':95,'end':97})

    def test_non_native_numbers_never_enter_catalog(self):
        self.assertEqual(self.api().compile_plot_catalog(context('vlm')).observations,())
        self.assertEqual(self.api().compile_plot_catalog(context('ocr')).observations,())

    def test_stale_foreign_duplicate_and_invented_chart_requests_fail_closed(self):
        api=self.api();ctx=context();catalog=api.compile_plot_catalog(ctx)
        ids=[o['id'] for o in catalog.observations]
        for choice in ({'chart_type':'line','observation_ids':ids},
                       {'chart_type':'bar','observation_ids':['foreign']},
                       {'chart_type':'bar','observation_ids':[ids[0],ids[0]]}):
            with self.assertRaises(ValueError): api.expand_plot_selection(choice,catalog,ctx)
        stale=replace(ctx,evidence=(replace(ctx.evidence[0],generation=99),))
        with self.assertRaises(ValueError):
            api.expand_plot_selection({'chart_type':'bar','observation_ids':ids},catalog,stale)

    def one_claim(self,text):
        ctx=context();claim=StructuredClaim('c4',text,(1,))
        return replace(ctx,claims=(claim,),claims_by_id=MappingProxyType({'c4':claim}),
            basis_by_id=MappingProxyType({'c4':ctx.basis_by_id['c4']}),
            evidence=(replace(ctx.evidence[0],text=text),))

    def test_source_conditions_are_kept_and_missing_is_not_zero(self):
        api=self.api();ctx=self.one_claim('Group A: 33 cells without oxygen.')
        catalog=api.compile_plot_catalog(ctx)
        self.assertEqual(catalog.observations[0]['point']['condition'],'without oxygen')
        ctx=self.one_claim('Group A: missing cells.')
        catalog=api.compile_plot_catalog(ctx)
        self.assertIsNone(catalog.observations[0]['point']['value'])

    def test_unknown_numeric_formats_are_not_silently_dropped(self):
        catalog=self.api().compile_plot_catalog(self.one_claim('The median is approximately 33 cells, possibly more.'))
        self.assertFalse(catalog.complete)
        self.assertEqual(catalog.observations,())

    def test_extra_numeric_scope_in_same_claim_does_not_qualify_for_simple_catalog(self):
        catalog=self.api().compile_plot_catalog(self.one_claim('Group A: 33 cells. The SD is 2 cells.'))
        self.assertFalse(catalog.complete)

    def test_same_entity_time_points_can_form_line_but_different_entities_cannot(self):
        api=self.api();ctx=context()
        claims=(StructuredClaim('c4','At time 0 h, Group A: 33 cells.',(1,)),
                StructuredClaim('c5','At time 1 h, Group A: 38 cells.',(1,)))
        ctx=replace(ctx,claims=claims,claims_by_id=MappingProxyType({c.id:c for c in claims}),
            basis_by_id=MappingProxyType({c.id:ctx.basis_by_id[c.id] for c in claims}),
            evidence=(replace(ctx.evidence[0],text=' '.join(c.claim for c in claims)),))
        catalog=api.compile_plot_catalog(ctx)
        ids=[o['id'] for o in catalog.observations]
        self.assertEqual(len(ids),2)
        spec=api.expand_plot_selection({'chart_type':'line','observation_ids':ids},catalog,ctx)
        self.assertEqual([p['x'] for p in spec['payload']['series'][0]['points']],['0','1'])

    def test_source_sentence_cannot_drop_the_retained_claim_condition(self):
        ctx=context();claims=(StructuredClaim('c4','Group A: 33 cells with oxygen.',(1,)),
                              StructuredClaim('c5','Group B: 38 cells.',(1,)))
        ctx=replace(ctx,claims=claims,claims_by_id=MappingProxyType({c.id:c for c in claims}),
            basis_by_id=MappingProxyType({c.id:ctx.basis_by_id[c.id] for c in claims}),
            evidence=(replace(ctx.evidence[0],text=' '.join(c.claim for c in claims)+' Group A: 33 cells.'),))
        catalog=self.api().compile_plot_catalog(ctx)
        self.assertTrue(catalog.complete)
        self.assertEqual(len(catalog.observations),2)
        self.assertEqual(catalog.observations[0]['point']['condition'],'with oxygen')

    def test_numeric_sign_mismatch_does_not_enter_catalog(self):
        ctx=self.one_claim('Group A: 33 cells.')
        ctx=replace(ctx,evidence=(replace(ctx.evidence[0],text='Group A: -33 cells.'),))
        catalog=self.api().compile_plot_catalog(ctx)
        self.assertFalse(catalog.complete);self.assertEqual(catalog.observations,())

    def test_same_label_in_distinct_documents_does_not_establish_one_trajectory(self):
        api=self.api();ctx=context()
        claims=(StructuredClaim('c4','At time 0 h, Group A: 33 cells.',(1,)),
                StructuredClaim('c5','At time 1 h, Group A: 38 cells.',(2,)))
        evidence=(replace(ctx.evidence[0],text=claims[0].claim,document_id='a'*32),
                  replace(ctx.evidence[0],text=claims[1].claim,document_id='b'*32,chunk_id='chunk2'))
        ctx=replace(ctx,claims=claims,claims_by_id=MappingProxyType({c.id:c for c in claims}),
            basis_by_id=MappingProxyType({c.id:ctx.basis_by_id[c.id] for c in claims}),evidence=evidence)
        catalog=api.compile_plot_catalog(ctx)
        with self.assertRaises(ValueError):
            api.expand_plot_selection({'chart_type':'line','observation_ids':[o['id'] for o in catalog.observations]},catalog,ctx)


if __name__=='__main__': unittest.main()
