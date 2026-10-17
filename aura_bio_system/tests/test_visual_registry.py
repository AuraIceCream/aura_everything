from dataclasses import replace
import json
import unittest
from visual_output_fixtures import context, plot


class VisualRegistryTests(unittest.TestCase):
    def module(self):
        try: from aura_bio.visual_outputs import registry
        except ImportError: self.fail('Immutable source registry is not implemented.')
        return registry

    def test_duplicate_cells_keep_distinct_offsets(self):
        api=self.module(); ctx=context()
        registry=api.build_registry(ctx,'Compare cell counts',prompt_byte_budget=50000)
        cells=[f for f in registry.fragments if f.text=='cells']
        self.assertEqual([f.start for f in cells],[79,98])
        self.assertNotEqual(cells[0].id,cells[1].id)
        for fragment in cells:
            self.assertEqual(api.resolve_fragment(registry,fragment.id,ctx),
                             {'cite_id':1,'start':fragment.start,'end':fragment.end})

    def test_foreign_or_stale_id_rejected(self):
        api=self.module(); ctx=context(); registry=api.build_registry(ctx,'Compare',prompt_byte_budget=50000)
        with self.assertRaises(ValueError): api.resolve_fragment(registry,'foreign',ctx)
        changed=replace(ctx,evidence=(replace(ctx.evidence[0],generation=2),))
        with self.assertRaises(ValueError): api.resolve_fragment(registry,registry.fragments[0].id,changed)

    def test_removed_claim_never_enters_registry(self):
        api=self.module(); registry=api.build_registry(context(removed=True),'Explain',prompt_byte_budget=50000)
        self.assertTrue(registry.fragments)
        self.assertTrue(all('c2' not in f.claim_ids for f in registry.fragments))

    def test_limit_reports_omitted_dependencies(self):
        api=self.module(); registry=api.build_registry(context(),'Explain',max_fragments=1,prompt_byte_budget=1)
        self.assertEqual(registry.fragments,())
        self.assertEqual(set(registry.omitted_claim_ids),{'c1','c2','c3','c4','c5'})

    def test_registry_does_not_upgrade_provenance(self):
        api=self.module(); registry=api.build_registry(context('vlm'),'Explain',prompt_byte_budget=50000)
        self.assertTrue(all(f.provenance=='vlm' for f in registry.fragments))

    def test_schema_and_resolution_use_ids_but_keep_original_offsets(self):
        api=self.module(); ctx=context(); registry=api.build_registry(ctx,'Compare counts',prompt_byte_budget=50000)
        from aura_bio.visual_outputs.schema import visual_schema,parse_visual
        proposal=plot()
        for point in proposal['payload']['series'][0]['points']:
            for role,binding in point['bindings'].items():
                fragment=next(f for f in registry.fragments if f.start==binding['start'] and f.end==binding['end'])
                point['bindings'][role]={'fragment_id':fragment.id}
        raw=api.resolve_registry_proposal(json.dumps(proposal),api.registry_schema(visual_schema('plot'),registry),registry,ctx)
        resolved=parse_visual(raw,ctx)
        self.assertEqual(resolved.payload['series'][0]['points'][1]['bindings']['value'],
                         {'cite_id':1,'start':95,'end':97})

    def test_fragment_and_candidate_bounds_are_explicit(self):
        api=self.module()
        registry=api.build_registry(context(),'Explain',max_fragments=2,prompt_byte_budget=1000)
        self.assertLessEqual(len(registry.fragments),2)
        self.assertTrue(registry.omitted_claim_ids)

    def test_small_prompt_keeps_numeric_group_value_and_unit_candidates(self):
        api=self.module(); registry=api.build_registry(context(),'Compare counts',prompt_byte_budget=3500)
        spans={(f.start,f.end) for f in registry.fragments}
        for binding in (plot()['payload']['series'][0]['points'][0]['bindings'].values()):
            self.assertIn((binding['start'],binding['end']),spans)

    def test_duplicate_unit_candidates_keep_their_statement_owner(self):
        registry=self.module().build_registry(context(),'Compare counts',prompt_byte_budget=50000)
        cells=[f for f in registry.fragments if f.text=='cells']
        self.assertEqual([f.claim_ids for f in cells],[('c4',),('c5',)])

    def test_numeric_units_survive_small_prompt_budget(self):
        registry=self.module().build_registry(context(),'Compare the counts',prompt_byte_budget=2300)
        units=[f for f in registry.fragments if f.text=='cells']
        self.assertEqual([f.claim_ids for f in units],[('c4',),('c5',)])

    def test_candidates_do_not_cross_sentence_boundaries(self):
        registry=self.module().build_registry(context(),'Explain',prompt_byte_budget=50000)
        self.assertFalse(any('. ' in f.text for f in registry.fragments))

    def test_short_budget_keeps_complete_relationship_bindings_not_only_entities(self):
        registry=self.module().build_registry(context(),'Draw the relationships',prompt_byte_budget=2300)
        texts={f.text for f in registry.fragments}
        self.assertIn('ORION activates VEGA.',texts)
        self.assertIn('VEGA may inhibit LUMEN.',texts)
