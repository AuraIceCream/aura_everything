import json
import unittest
from dataclasses import replace
from types import MappingProxyType
from aura_bio.study.claims import StructuredClaim
from aura_bio.visual_outputs.schema import parse_visual
from aura_bio.visual_outputs.grounding import ground_visual
from visual_output_fixtures import context


class FactCatalogTests(unittest.TestCase):
    def api(self):
        try: from aura_bio.visual_outputs import fact_catalog
        except ImportError: self.fail('Checked relation/procedure/comparison catalogues are not implemented.')
        return fact_catalog

    def test_diagram_keeps_three_source_relations_and_literal_modality(self):
        api=self.api();ctx=context();catalog=api.compile_fact_catalog('diagram',ctx)
        self.assertTrue(catalog.complete);self.assertEqual(len(catalog.facts),3)
        choice={'fact_ids':[f['id'] for f in catalog.facts],'orientation':'LR','layout':'pathway'}
        spec=api.expand_fact_selection(choice,catalog,ctx)
        result=ground_visual(parse_visual(json.dumps(spec),ctx),ctx)
        self.assertEqual(result.status,'ready')
        self.assertEqual([e['label'] for e in result.spec.payload['edges']],['activates','may inhibit','precedes'])
        self.assertEqual(result.spec.payload['edges'][1]['qualifiers'],['may'])
        self.assertEqual(result.spec.payload['groups'],[])

    def test_procedure_endpoints_come_from_ordering_not_adjacent_mechanisms(self):
        api=self.api();ctx=context();catalog=api.compile_fact_catalog('procedure',ctx)
        self.assertEqual(len(catalog.facts),1)
        spec=api.expand_fact_selection({'fact_ids':[catalog.facts[0]['id']]},catalog,ctx)
        result=ground_visual(parse_visual(json.dumps(spec),ctx),ctx)
        self.assertEqual(result.status,'ready')
        self.assertEqual([s['text'] for s in result.spec.payload['steps']],['ORION','VEGA'])
        self.assertEqual([s['claim_ids'] for s in result.spec.payload['steps']],[['c3'],['c3']])

    def test_comparison_builds_group_columns_and_observed_values(self):
        api=self.api();ctx=context();catalog=api.compile_fact_catalog('comparison',ctx)
        self.assertTrue(catalog.complete)
        spec=api.expand_fact_selection({'fact_ids':[f['id'] for f in catalog.facts]},catalog,ctx)
        result=ground_visual(parse_visual(json.dumps(spec),ctx),ctx)
        self.assertEqual(result.status,'ready')
        self.assertEqual([c['text'] for c in result.spec.payload['columns']],['Group A','Group B'])
        self.assertEqual([c['text'] for c in result.spec.payload['rows'][0]['cells']],['33 cells','38 cells'])

    def test_catalogue_cannot_upgrade_interpreted_edges_or_manufacture_return_edge(self):
        api=self.api();ctx=context('vlm');catalog=api.compile_fact_catalog('diagram',ctx)
        spec=api.expand_fact_selection({'fact_ids':[catalog.facts[0]['id']],'orientation':'LR','layout':'cycle'},catalog,ctx)
        result=ground_visual(parse_visual(json.dumps(spec),ctx),ctx)
        self.assertEqual(len(result.spec.payload['edges']),1)
        self.assertEqual(result.spec.payload['edges'][0]['support']['status'],'interpreted')

    def test_unknown_relationship_format_does_not_claim_complete_coverage(self):
        api=self.api();ctx=context();claim=StructuredClaim('c1','ORION activates VEGA; the condition is unclear.',(1,))
        ctx=replace(ctx,claims=(claim,),claims_by_id=MappingProxyType({'c1':claim}),
            basis_by_id=MappingProxyType({'c1':ctx.basis_by_id['c1']}),
            evidence=(replace(ctx.evidence[0],text='ORION activates VEGA.'),))
        self.assertFalse(api.compile_fact_catalog('diagram',ctx).complete)

    def test_foreign_duplicate_stale_ids_are_rejected(self):
        api=self.api();ctx=context();catalog=api.compile_fact_catalog('procedure',ctx)
        id=catalog.facts[0]['id']
        for ids in (['foreign'],[id,id]):
            with self.assertRaises(ValueError): api.expand_fact_selection({'fact_ids':ids},catalog,ctx)
        stale=replace(ctx,evidence=(replace(ctx.evidence[0],generation=101),))
        with self.assertRaises(ValueError): api.expand_fact_selection({'fact_ids':[id]},catalog,stale)

    def test_document_owned_entities_do_not_merge_through_identical_names(self):
        api=self.api();ctx=context()
        claims=(StructuredClaim('c1','A activates B.',(1,)),StructuredClaim('c2','B inhibits C.',(2,)))
        ctx=replace(ctx,claims=claims,claims_by_id=MappingProxyType({c.id:c for c in claims}),
            basis_by_id=MappingProxyType({c.id:ctx.basis_by_id[c.id] for c in claims}),
            evidence=(replace(ctx.evidence[0],text=claims[0].claim,document_id='a'*32),
                      replace(ctx.evidence[0],text=claims[1].claim,document_id='b'*32,chunk_id='chunk2')))
        catalog=api.compile_fact_catalog('diagram',ctx)
        spec=api.expand_fact_selection({'fact_ids':[f['id'] for f in catalog.facts],'orientation':'LR','layout':'pathway'},catalog,ctx)
        self.assertEqual(len(spec['payload']['nodes']),4)
        edges=spec['payload']['edges']
        self.assertNotEqual(edges[0]['to_id'],edges[1]['from_id'])

    def add_claim(self,text):
        ctx=context();claim=StructuredClaim('c6',text,(1,))
        return replace(ctx,claims=ctx.claims+(claim,),claims_by_id=MappingProxyType({**ctx.claims_by_id,'c6':claim}),
            basis_by_id=MappingProxyType({**ctx.basis_by_id,'c6':ctx.basis_by_id['c1']}),
            evidence=(replace(ctx.evidence[0],text=ctx.evidence[0].text+' '+text),))

    def test_unparsed_relation_prevents_id_only_catalog_from_hiding_it(self):
        self.assertFalse(self.api().compile_fact_catalog('diagram',self.add_claim('C belongs to D.')).complete)

    def test_categorical_comparison_facts_cannot_be_silently_replaced_by_numeric_subset(self):
        self.assertFalse(self.api().compile_fact_catalog('comparison',self.add_claim('Group A has red color.')).complete)

    def test_unparsed_instruction_prevents_complete_procedure_catalog(self):
        self.assertFalse(self.api().compile_fact_catalog('procedure',self.add_claim('Wash the sample.')).complete)


if __name__=='__main__': unittest.main()
