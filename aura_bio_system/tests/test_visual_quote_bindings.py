"""The local model quotes text; only the application counts source offsets."""
import json
import unittest
from unittest.mock import patch

from visual_output_fixtures import context, plot
from aura_bio.visual_outputs import planner
from aura_bio.visual_outputs.schema import _validate, visual_schema


class QuoteBindingTests(unittest.TestCase):
    def call(self, value, ctx=None):
        from aura_bio.api.generation import OllamaGenerator
        sent = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({'done_reason': 'stop', 'message': {'content': json.dumps(value)}}).encode()
        def request(req, **kwargs):
            sent.append(json.loads(req.data)); return Response()
        with patch('urllib.request.urlopen', side_effect=request), patch.object(OllamaGenerator, '_wait_for_unload', return_value=1):
            result = planner.plan_visual('plot', 'Compare the counts', ctx or context(),
                OllamaGenerator(model='fixture',visual_proposal_version=1), None)
        return result, sent

    def quoted_plot(self):
        value = plot()
        for point in value['payload']['series'][0]['points']:
            sentence = f"{point['group']}: {point['value']} cells"
            point['bindings'] = {key: {'cite_id': 1, 'quote': text, 'context': sentence}
                                 for key, text in [('group', point['group']), ('value', point['value']), ('unit', 'cells')]}
        return value

    def test_local_quotes_resolve_to_exact_original_offsets_and_public_contract(self):
        result, sent = self.call(self.quoted_plot())
        self.assertEqual(result.status, 'ready')
        points = result.spec.payload['series'][0]['points']
        self.assertEqual(points[0]['bindings']['value'], {'cite_id': 1, 'start': 76, 'end': 78})
        self.assertEqual(points[1]['bindings']['unit'], {'cite_id': 1, 'start': 98, 'end': 103})
        from aura_bio.visual_outputs.schema import public_visual_schema
        _validate(json.loads(json.dumps(result.spec.as_dict())), public_visual_schema('plot'))
        self.assertEqual(len(sent), 1)
        binding = sent[0]['format']['properties']['payload']['properties']['series']['items']['properties']['points']['items']['properties']['bindings']['properties']['value']
        self.assertIn('quote', binding['properties'])
        self.assertNotIn('start', binding['properties'])

    def test_ambiguous_missing_or_foreign_quotes_are_rejected_without_repair(self):
        for quote, surrounding, cite in [('cells', '', 1), ('38', 'Group A: 33 cells', 1),
                                          ('33', 'Group A: 33 cells', 9), ('333', '', 1)]:
            value = self.quoted_plot()
            value['payload']['series'][0]['points'][0]['bindings']['value'] = {'cite_id': cite, 'quote': quote, 'context': surrounding}
            result, sent = self.call(value)
            self.assertEqual(result.status, 'failed')
            self.assertEqual(len(sent), 1)

    def test_a_real_quote_does_not_permit_swapping_group_values(self):
        value = self.quoted_plot(); point = value['payload']['series'][0]['points'][0]
        point['value'] = '38'; point['bindings']['value'] = {'cite_id': 1, 'quote': '38', 'context': 'Group B: 38 cells'}
        self.assertEqual(self.call(value)[0].status, 'omitted')

    def test_comparison_decoding_disallows_content_in_an_absent_cell(self):
        from pathlib import Path
        bank = Path(__file__).parents[1] / 'benchmarks/data/visual_output_bank_v1.jsonl'
        value = next(row['proposal'] for row in map(json.loads, bank.read_text().splitlines()) if row['id'] == 'comparison-counts')
        value['payload']['rows'][0]['cells'][0]['status'] = 'not_stated'
        with self.assertRaises(ValueError): _validate(value, visual_schema('comparison'))

    def test_auto_selection_uses_the_same_quote_adapter(self):
        from aura_bio.visual_outputs.quotes import quote_schema, resolve_quotes
        from aura_bio.visual_outputs.schema import selection_schema, parse_selection, parse_visual
        value = {'selected_kind': 'plot', 'reason': 'numeric_pattern', 'visual': self.quoted_plot(), 'source_id': None}
        raw = resolve_quotes(json.dumps(value), quote_schema(selection_schema()), context())
        decision = parse_selection(raw)
        spec = parse_visual(json.dumps(decision['visual']), context())
        self.assertEqual(spec.payload['series'][0]['points'][1]['bindings']['value'],
                         {'cite_id': 1, 'start': 95, 'end': 97})


if __name__ == '__main__': unittest.main()
