import copy
import json
import unittest
from dataclasses import replace
from visual_output_fixtures import context, diagram, plot


class VisualGroundingTests(unittest.TestCase):
    def ground(self, value, ctx=None):
        try:
            from aura_bio.visual_outputs.schema import parse_visual
            from aura_bio.visual_outputs.grounding import ground_visual
        except ImportError: self.fail('Visual grounding is not implemented')
        return ground_visual(parse_visual(json.dumps(value), ctx or context()), ctx or context(), None)

    def test_exact_retained_relationship_has_original_citations_and_support(self):
        result = self.ground(diagram())
        self.assertEqual(result.status, 'ready')
        edge = result.spec.payload['edges'][0]
        self.assertEqual(edge['support']['cite_ids'], ['cit-1'])
        self.assertEqual(edge['support']['status'], 'native_verified')

    def test_two_entities_do_not_establish_causality_or_reverse_direction(self):
        for relation, label, reverse in [('causes', 'causes', False), ('activates', 'activates', True)]:
            value = diagram(); edge = value['payload']['edges'][0]
            edge.update(relation=relation, label=label)
            if reverse: edge['from_id'], edge['to_id'] = edge['to_id'], edge['from_id']
            self.assertEqual(self.ground(value).status, 'omitted')

    def test_qualified_relationship_cannot_be_strengthened(self):
        value = diagram(); value['payload']['nodes'][0].update(label='VEGA', claim_ids=['c2'])
        value['payload']['nodes'][1].update(label='LUMEN', claim_ids=['c2'])
        value['payload']['edges'][0].update(relation='inhibits', label='inhibits', claim_ids=['c2'])
        self.assertEqual(self.ground(value).status, 'omitted')
        value['payload']['edges'][0]['label'] = 'may inhibit'
        self.assertEqual(self.ground(value).status, 'ready')

    def test_interpreted_relationship_is_not_promoted(self):
        edge = self.ground(diagram(), context('vlm')).spec.payload['edges'][0]
        self.assertEqual(edge['support']['status'], 'interpreted')
        self.assertEqual(edge['support']['provenance'], ['vlm'])

    def test_correct_plot_bindings_pass_but_swapped_group_numbers_fail(self):
        self.assertEqual(self.ground(plot()).status, 'ready')
        value = copy.deepcopy(plot()); points = value['payload']['series'][0]['points']
        points[0]['value'], points[1]['value'] = points[1]['value'], points[0]['value']
        points[0]['bindings']['value'], points[1]['bindings']['value'] = points[1]['bindings']['value'], points[0]['bindings']['value']
        self.assertEqual(self.ground(value).status, 'omitted')

    def test_pixel_and_ocr_numbers_are_not_certified_plot_inputs(self):
        for method in ('vlm', 'ocr', 'user_annotation'):
            self.assertEqual(self.ground(plot(), context(method)).status, 'omitted')

    def test_unit_population_and_denominator_cannot_be_invented(self):
        value = plot(); value['payload']['series'][0]['unit'] = 'mg'
        self.assertEqual(self.ground(value).status, 'omitted')
        value = plot(); value['payload']['unit'] = '%'
        value['payload']['series'][0]['unit'] = '%'
        self.assertEqual(self.ground(value).status, 'omitted')

    def test_optional_x_cannot_smuggle_an_unbound_value_into_a_bar_export(self):
        value=plot();value['payload']['series'][0]['points'][0]['x']='99'
        self.assertEqual(self.ground(value).status,'omitted')

    def custom_context(self, text):
        from aura_bio.study.claims import StructuredClaim
        ctx = context()
        claims = tuple(StructuredClaim(c.id, text, c.cite_ids) for c in ctx.claims)
        return replace(ctx, claims=claims, claims_by_id={c.id: c for c in claims},
                       evidence=(replace(ctx.evidence[0], text=text),))

    def span(self, text, value):
        start = text.index(value)
        return {'cite_id': 1, 'start': start, 'end': start + len(value)}

    def test_plot_number_must_attach_to_its_group_and_quantity_not_just_sentence(self):
        for text in ('Group A has 33 cells after 38 days.',
                     'Group A has 33 cells and Group B has 38 cells.'):
            with self.subTest(text=text):
                value = plot(); series = value['payload']['series'][0]
                series['points'] = [series['points'][0]]
                point = series['points'][0]; point['value'] = '38'
                point['bindings'] = {key: self.span(text, word) for key, word in
                                     [('group', 'Group A'), ('value', '38'), ('unit', 'cells')]}
                self.assertEqual(self.ground(value, self.custom_context(text)).status, 'omitted')

    def test_plot_uses_neutral_labels_not_model_assertions(self):
        value = plot(); payload = value['payload']
        payload['x_label'] = payload['y_label'] = payload['series'][0]['label'] = 'Cells proven to cause cancer'
        result = self.ground(value)
        self.assertEqual(result.status, 'ready')
        self.assertNotIn('proven to cause', json.dumps(result.spec.as_dict()))

    def test_procedure_does_not_strip_a_negative_instruction(self):
        value = {'version': 1, 'id': 'steps', 'kind': 'procedure', 'title': 'Procedure', 'description': '',
                 'payload': {'steps': [{'id': 's1', 'text': 'heat the sample', 'claim_ids': ['c1']}], 'precedes': []}}
        ctx = self.custom_context('Do not heat the sample.')
        self.assertEqual(self.ground(value, ctx).status, 'omitted')
        value['payload']['steps'][0]['text'] = 'Do not heat the sample.'
        self.assertEqual(self.ground(value, ctx).status, 'ready')

    def comparison(self, text, criterion, cell):
        return {'version': 1, 'id': 'table', 'kind': 'comparison', 'title': 'Table', 'description': '',
                'payload': {'columns': [{'id': 'a', 'text': 'Group A', 'claim_ids': ['c1'],
                                        'bindings': [self.span(text, 'Group A')]}],
                            'rows': [{'id': 'r1', 'criterion': {'text': criterion, 'claim_ids': ['c1'],
                                         'bindings': [self.span(text, criterion)]},
                                      'cells': [{'column_id': 'a', 'text': cell, 'status': 'stated',
                                                 'claim_ids': ['c1'], 'bindings': [self.span(text, cell)]}]}]}}

    def test_comparison_preserves_qualifiers_and_binds_the_row_criterion(self):
        for text, criterion, cell in [('Group A is not active.', 'active', 'active'),
                                     ('Group A has length 5 mm and width 2 mm.', 'length', '2 mm')]:
            with self.subTest(text=text):
                self.assertEqual(self.ground(self.comparison(text, criterion, cell),
                                             self.custom_context(text)).status, 'omitted')
        text = 'Group A has length 5 mm.'
        self.assertEqual(self.ground(self.comparison(text, 'length', '5 mm'),
                                     self.custom_context(text)).status, 'ready')

    def test_comparison_cannot_hide_a_retained_value_as_not_stated(self):
        text = 'Group A has length 5 mm.'
        value = self.comparison(text, 'length', '5 mm')
        value['payload']['rows'][0]['cells'][0].update(status='not_stated', text='', claim_ids=[], bindings=[])
        self.assertEqual(self.ground(value, self.custom_context(text)).status, 'omitted')

    def test_contains_cannot_be_a_forward_part_of_edge(self):
        text = 'ORION contains VEGA.'
        value = diagram(); value['payload']['edges'][0].update(relation='part_of', label='contains')
        self.assertEqual(self.ground(value, self.custom_context(text)).status, 'omitted')


if __name__ == '__main__': unittest.main()
