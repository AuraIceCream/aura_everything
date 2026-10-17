import json
import unittest
from unittest.mock import patch

from aura_bio.study.visual.ollama import OllamaVisionBackend
from aura_bio.study.visual.schema import ProviderResponse
from aura_bio.study.visual.description import FigureDescriber
from aura_bio.study.schema import StudyError
from test_figure_description import figure_input, FIELDS


class VisualOutputContractTests(unittest.TestCase):
    def test_default_figure_budget_can_finish_a_dense_structured_description(self):
        backend = OllamaVisionBackend(http=object())
        def request(method, path, **kwargs):
            budget = kwargs['json']['options']['num_predict']
            return {'model':'qwen3.5:4b', 'done_reason':'stop' if budget >= 2048 else 'length',
                    'message':{'content':json.dumps(FIELDS) if budget >= 2048 else '{"kind":"mixed"'}}
        with patch.object(backend, 'preflight', return_value='digest'), patch.object(backend, '_request', side_effect=request):
            try: result = FigureDescriber(backend).describe(figure_input())
            except StudyError: self.fail('The default budget cuts off a complete dense figure description.')
        self.assertEqual(result.fields, FIELDS)
        self.assertEqual(len(result.responses), 1)

    def test_structural_repair_decoding_limits_endpoints_to_prior_declared_labels(self):
        backend = OllamaVisionBackend(http=object())
        raw = json.dumps({**FIELDS, 'relations':[{'from':'A','to':'Invisible','relation':'arrow'}]})
        sent = []
        def request(method, path, **kwargs):
            sent.append(kwargs['json'])
            return {'model':'qwen3.5:4b', 'done_reason':'stop', 'message':{'content':raw if len(sent)==1 else json.dumps(FIELDS)}}
        with patch.object(backend, 'preflight', return_value='digest'), patch.object(backend, '_request', side_effect=request):
            result = FigureDescriber(backend).describe(figure_input())
        self.assertEqual(result.fields, FIELDS)
        schema = sent[1]['format']
        if 'anyOf' in schema: schema = next(s for s in schema['anyOf'] if 'pathway' in s['properties']['kind']['enum'])
        endpoints = schema['properties']['relations']['items']['properties']
        self.assertIn('enum', endpoints['from'], 'Repair must constrain, not merely request, existing endpoints.')
        self.assertEqual(endpoints['from']['enum'], ['A','B'])
        self.assertEqual(endpoints['to']['enum'], ['A','B'])
        self.assertEqual(endpoints['relation']['enum'], ['arrow','line','inhibitory_arrow'])
        self.assertEqual(len(sent), 2)

    def test_table_decoding_and_live_validation_reject_arrow_semantics(self):
        from aura_bio.study.visual.description import description_schema, validate_live_description
        from aura_bio.visual_outputs.schema import _validate
        table = {**FIELDS, 'kind':'table_image', 'summary':'Column A and column B.'}
        with self.assertRaises(ValueError): _validate(table, description_schema())
        with self.assertRaises(StudyError): validate_live_description(json.dumps(table))
        table['relations'] = []
        _validate(table, description_schema())
        self.assertEqual(validate_live_description(json.dumps(table)), table)

    def test_structural_repair_cannot_add_labels_to_justify_an_invalid_connection(self):
        from aura_bio.study.visual.description import description_schema
        from aura_bio.visual_outputs.schema import _validate
        invalid = {**FIELDS, 'relations':[{'from':'A','to':'Invisible','relation':'arrow'}]}
        invented = {**FIELDS, 'labels':['A','B','Invisible']}
        with self.assertRaises(ValueError): _validate(invented, description_schema(json.dumps(invalid)))

    def test_repair_preserves_recognizable_fields_in_malformed_envelope(self):
        from aura_bio.study.visual.description import description_schema, validate_live_description
        from aura_bio.visual_outputs.schema import _validate
        prior = {**FIELDS, 'kind':'table_image', 'labels':['A'], 'relations':[]}
        missing = {k:v for k,v in prior.items() if k != 'axes'}
        oversized = {**prior, 'summary':'x'*1501}
        invented = {**FIELDS, 'labels':['A','B','Invented']}
        for broken in (missing, oversized):
            with self.subTest(broken=broken):
                raw = json.dumps(broken)
                with self.assertRaises(ValueError): _validate(invented, description_schema(raw))
                with self.assertRaises(StudyError): validate_live_description(json.dumps(invented), raw)
                self.assertEqual(validate_live_description(json.dumps(prior), raw), prior)

    def test_local_request_allows_a_complete_bounded_pathway(self):
        backend = OllamaVisionBackend(http=object())
        sent = []

        def request(method, path, **kwargs):
            sent.append(kwargs['json'])
            return {'model':'qwen3.5:4b', 'message':{'content':json.dumps(FIELDS)}, 'done_reason':'stop'}

        with patch.object(backend, 'preflight', return_value='digest'), patch.object(backend, '_request', side_effect=request):
            result = backend.complete(figure_input())
        self.assertEqual(json.loads(result.raw), FIELDS)
        payload = sent[0]
        self.assertIsInstance(payload['format'], dict)
        schema=payload['format']
        if 'anyOf' in schema: schema=next(s for s in schema['anyOf'] if 'pathway' in s['properties']['kind']['enum'])
        self.assertEqual(schema['additionalProperties'], False)
        self.assertGreaterEqual(schema['properties']['relations']['maxItems'], 16)
        self.assertLessEqual(schema['properties']['relations']['maxItems'], 32)
        self.assertGreaterEqual(schema['properties']['labels']['maxItems'], 24)
        self.assertLessEqual(payload['options']['num_predict'], 2048)
        self.assertEqual(payload['model'], 'qwen3.5:4b')

    def test_optional_thinking_reaches_local_transport_and_changes_cache_identity(self):
        from dataclasses import replace
        from aura_bio.study.visual.schema import VisualJobConfig
        original = figure_input()
        config = VisualJobConfig(think=True, num_predict=4096, timeout_seconds=600)
        focused = replace(original, config=config)
        backend = OllamaVisionBackend(http=object())
        with patch.object(backend, 'preflight', return_value='digest'), patch.object(backend, '_request', return_value={
            'model':config.model, 'message':{'content':json.dumps(FIELDS)}, 'done_reason':'stop',
        }) as transport:
            backend.complete(focused)
        payload = transport.call_args.kwargs['json']
        self.assertTrue(payload['think'])
        self.assertEqual(payload['options']['num_predict'], 4096)
        self.assertNotEqual(original.config.checksum, config.checksum)

    def test_new_live_description_rejects_inferred_or_dangling_edges(self):
        from test_figure_description import Backend
        for relation in ({'from':'A','to':'B','relation':'activates'},
                         {'from':'A','to':'Invisible','relation':'arrow'}):
            backend = Backend([json.dumps({**FIELDS, 'relations':[relation]})] * 2)
            with self.subTest(relation=relation), self.assertRaises(StudyError):
                FigureDescriber(backend).describe(figure_input())
            self.assertEqual(backend.calls, 2)

    def test_truncated_output_keeps_diagnostics_and_is_never_repaired_as_complete(self):
        backend = OllamaVisionBackend(http=object())
        with patch.object(backend, 'preflight', return_value='digest'), patch.object(backend, '_request', return_value={
            'model':'qwen3.5:4b', 'message':{'content':'{"kind":"mixed"'},
            'done_reason':'length', 'eval_count':1024, 'prompt_eval_count':800,
        }):
            with self.assertRaises(StudyError) as caught:
                FigureDescriber(backend).describe(figure_input())
        self.assertEqual(caught.exception.attempts, 1)
        self.assertEqual(caught.exception.code, 'output_truncated')
        self.assertEqual(caught.exception.responses[0].raw, '{"kind":"mixed"')
        self.assertEqual(caught.exception.responses[0].usage['completion_tokens'], 1024)
