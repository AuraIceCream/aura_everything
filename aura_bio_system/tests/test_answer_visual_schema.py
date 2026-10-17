import copy
import json
import unittest
from visual_output_fixtures import context, diagram, plot


class VisualSchemaTests(unittest.TestCase):
    def parse(self, value, ctx=None):
        try: from aura_bio.visual_outputs.schema import parse_visual
        except ImportError: self.fail('Visual schema is not implemented')
        return parse_visual(json.dumps(value), ctx or context())

    def test_context_contains_only_selected_delivered_claims(self):
        ctx = context(removed=True)
        self.assertEqual(set(ctx.claims_by_id), {'c1', 'c3', 'c4', 'c5'})
        self.assertNotIn('c2', ctx.basis_by_id)

    def test_valid_versioned_diagram(self):
        self.assertEqual(self.parse(diagram()).version, 1)

    def test_public_contract_includes_assigned_support_but_model_cannot_supply_it(self):
        try: from aura_bio.visual_outputs.schema import public_visual_schema, _validate
        except ImportError: self.fail('Public grounded visual schema is missing')
        from aura_bio.visual_outputs.grounding import ground_visual
        result=ground_visual(self.parse(diagram()),context())
        _validate(json.loads(json.dumps(result.spec.as_dict())),public_visual_schema('diagram'))
        value=diagram();value['payload']['nodes'][0]['support']={'status':'native_verified'}
        with self.assertRaises(ValueError):self.parse(value)

    def test_removed_claim_is_not_permitted_to_return_as_visual(self):
        value = diagram(); value['payload']['edges'][0]['claim_ids'] = ['c2']
        with self.assertRaises(ValueError): self.parse(value, context(removed=True))

    def test_limits_and_closed_fields_are_authoritative(self):
        try: from aura_bio.visual_outputs.schema import parse_visual
        except ImportError: self.fail('Visual schema is not implemented')
        cases = []
        for key, value in [('version', 2), ('kind', 'html'), ('unexpected', True)]:
            bad = diagram(); bad[key] = value; cases.append(bad)
        bad = diagram(); bad['payload']['nodes'] *= 11; cases.append(bad)
        bad = diagram(); bad['payload']['edges'] *= 31; cases.append(bad)
        bad = diagram(); bad['payload']['nodes'][1]['id'] = 'n1'; cases.append(bad)
        bad = diagram(); bad['payload']['edges'][0]['to_id'] = 'absent'; cases.append(bad)
        bad = plot(); bad['payload']['series'][0]['points'] *= 51; cases.append(bad)
        for value in (True, float('nan'), 'NaN', 'Infinity'):
            bad = copy.deepcopy(plot()); bad['payload']['series'][0]['points'][0]['value'] = value; cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.parse(bad)
        with self.assertRaises(ValueError): parse_visual(' ' * 65537, context())

    def test_unsupported_context_is_explicit_not_markdown_reconstruction(self):
        try: from aura_bio.visual_outputs.planner import plan_visual
        except ImportError: self.fail('Visual planner is not implemented')
        self.assertEqual(plan_visual('diagram', 'ORION?', None, None, None).status, 'omitted')


if __name__ == '__main__': unittest.main()
