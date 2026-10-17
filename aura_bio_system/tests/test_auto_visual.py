"""Auto is a semantic, single-call choice; all proposed facts still get checked."""
import copy
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from visual_output_fixtures import context, diagram, plot
from aura_bio.visual_outputs.planner import plan_visual


def selection(kind='diagram', reason='relationships', visual=None, source_id=None):
    return json.dumps({'selected_kind': kind, 'reason': reason, 'visual': visual,
                       'source_id': source_id})


class ResponseGenerator:
    model_name = 'fixture'
    def __init__(self, raw): self.raw, self.calls = raw, 0
    def propose_visual(self, kind, question, ctx):
        self.calls += 1
        if isinstance(self.raw, Exception): raise self.raw
        return self.raw


class AutoVisualTests(unittest.TestCase):
    def test_auto_can_choose_a_grounded_diagram_for_an_indirect_question(self):
        generator = ResponseGenerator(selection(visual=diagram()))
        result = plan_visual('auto', 'How do ORION and VEGA interact?', context(), generator, None)
        self.assertEqual(result.status, 'ready')
        self.assertEqual(result.spec.kind, 'diagram')
        self.assertEqual(result.metadata['selection_reason'], 'relationships')
        self.assertEqual(generator.calls, 1)

    def test_auto_can_choose_no_visual_without_a_false_failure(self):
        generator = ResponseGenerator(selection('none', 'simple_answer'))
        result = plan_visual('auto', 'What is ORION?', context(), generator, None)
        self.assertEqual(result.status, 'omitted')
        self.assertEqual(result.limitations, ())
        self.assertEqual(result.metadata['selected_kind'], 'none')
        self.assertEqual(generator.calls, 1)

    def test_auto_allows_comparison_procedure_and_native_plot_through_the_same_checks(self):
        bank = Path(__file__).parents[1] / 'benchmarks/data/visual_output_bank_v1.jsonl'
        cases = {row['id']: row for row in map(json.loads, bank.read_text(encoding='utf-8').splitlines())}
        for id, kind, reason in [('comparison-counts', 'comparison', 'comparison'),
                                 ('procedure-order', 'procedure', 'ordered_steps'),
                                 ('plot-counts', 'plot', 'numeric_pattern')]:
            with self.subTest(kind=kind):
                result = plan_visual('auto', cases[id]['question'], context(),
                    ResponseGenerator(selection(kind, reason, cases[id]['proposal'])), None)
                self.assertEqual(result.status, 'ready')
                self.assertEqual(result.spec.kind, kind)

    def test_source_choice_is_bound_to_a_candidate_not_model_paths_or_ids(self):
        result = plan_visual('auto', 'Explain this figure', context(),
                             ResponseGenerator(selection('source', 'source_inspection', source_id='s0')), None)
        self.assertEqual(result.status, 'ready')
        self.assertEqual(result.spec.kind, 'source')
        self.assertEqual(result.spec.payload['unit_id'], 'd' * 32)
        self.assertIsNone(result.spec.payload['asset_id'])
        self.assertIsNone(result.spec.payload['bbox'])
        foreign = plan_visual('auto', 'Explain this figure', context(),
                             ResponseGenerator(selection('source', 'source_inspection', source_id='foreign')), None)
        self.assertEqual(foreign.status, 'failed')

    def test_auto_rejects_invented_edges_without_another_proposal(self):
        value = diagram(); value['payload']['edges'][0].update(relation='causes', label='causes')
        generator = ResponseGenerator(selection(visual=value))
        result = plan_visual('auto', 'What follows from ORION?', context(), generator, None)
        self.assertEqual(result.status, 'omitted')
        self.assertEqual(generator.calls, 1)

    def test_auto_does_not_certify_pixel_numbers(self):
        generator = ResponseGenerator(selection('plot', 'numeric_pattern', plot()))
        result = plan_visual('auto', 'How do the counts differ?', context('vlm'), generator, None)
        self.assertEqual(result.status, 'omitted')
        self.assertEqual(generator.calls, 1)

    def test_off_and_empty_context_start_no_visual_model(self):
        generator = ResponseGenerator(AssertionError('must not start'))
        self.assertEqual(plan_visual('none', 'Draw a diagram', context(), generator, None).status, 'omitted')
        self.assertEqual(plan_visual('auto', 'Explain it visually', None, generator, None).status, 'omitted')
        self.assertEqual(generator.calls, 0)

    def test_no_source_candidates_prevents_source_selection(self):
        ctx = context(); ctx = replace(ctx, evidence=(replace(ctx.evidence[0], pack_id='', unit_ids=()),))
        result = plan_visual('auto', 'Explain this figure', ctx,
            ResponseGenerator(selection('source', 'source_inspection', source_id='s0')), None)
        self.assertEqual(result.status, 'failed')

    def test_invalid_decisions_and_timeouts_fail_safely_without_repair(self):
        cases = [selection('none', 'simple_answer', diagram()),
                 selection('diagram', 'relationships', plot()),
                 selection('source', 'source_inspection', source_id='s0', visual=diagram()),
                 selection('none', 'PRIVATE SOURCE SECRET'),
                 '{"selected_kind":"none","selected_kind":"source"}',
                 TimeoutError('PRIVATE SOURCE SECRET')]
        for raw in cases:
            with self.subTest(raw=str(raw)[:30]):
                generator = ResponseGenerator(raw)
                result = plan_visual('auto', 'Question', context(), generator, None)
                self.assertEqual(result.status, 'failed')
                self.assertEqual(generator.calls, 1)
                self.assertEqual(result.metadata.get('requested_mode'), 'auto')
                self.assertNotIn('SECRET', json.dumps(result.as_dict()))

    def test_local_call_keeps_same_model_thinking_and_original_claim_schema(self):
        from aura_bio.api.generation import OllamaGenerator
        generator = OllamaGenerator(model='local-fixture', think=True, response_schema={'original': True},visual_proposal_version=1)
        original = copy.deepcopy(generator.response_schema)
        sent = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({'done_reason': 'stop', 'message': {'content': selection(visual=diagram())}}).encode()
        def request(req, **kwargs):
            sent.append(json.loads(req.data))
            return Response()
        with patch('urllib.request.urlopen', side_effect=request), patch.object(OllamaGenerator, '_wait_for_unload', return_value=1):
            result = plan_visual('auto', 'How are they related?', context(), generator, None)
        self.assertEqual(result.status, 'ready')
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['model'], 'local-fixture')
        self.assertTrue(sent[0]['think'])
        self.assertIn('anyOf', sent[0]['format'])
        self.assertEqual(generator.response_schema, original)
        self.assertEqual(generator.last_metadata, {})

    def test_api_accepts_auto_and_keeps_off_for_omitted_option(self):
        from aura_bio.api.app import RunRequestModel
        try: request = RunRequestModel(query='Explain', visual_output='auto')
        except ValueError: self.fail('API does not accept automatic visual selection')
        self.assertEqual(request.visual_output, 'auto')
        self.assertEqual(RunRequestModel(query='Explain').visual_output, 'none')

    def test_local_layout_has_room_to_finish_without_changing_the_answer_budget(self):
        from aura_bio.api.generation import OllamaGenerator
        generator = OllamaGenerator(model='local-fixture', num_predict=768,visual_proposal_version=1)
        sent = []
        class Response:
            def __init__(self, complete): self.complete = complete
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({'done_reason': 'stop' if self.complete else 'length',
                    'message': {'content': selection(visual=diagram()) if self.complete else '{"selected_kind":'}}).encode()
        def request(req, **kwargs):
            payload = json.loads(req.data); sent.append((payload, kwargs['timeout']))
            return Response(payload['options']['num_predict'] >= 2048)
        with patch('urllib.request.urlopen', side_effect=request), patch.object(OllamaGenerator, '_wait_for_unload', return_value=1):
            result = plan_visual('auto', 'Compare the source-supported groups', context(), generator, None)
        self.assertEqual(result.status, 'ready')
        self.assertEqual(len(sent), 1)
        self.assertLessEqual(sent[0][0]['options']['num_predict'], 4096)
        self.assertGreaterEqual(sent[0][1], 180)
        self.assertLessEqual(sent[0][1], 300)
        self.assertEqual(generator.num_predict, 768)

    def test_larger_visual_budget_still_rejects_truncation_without_retry(self):
        from aura_bio.api.generation import OllamaGenerator
        calls = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return b'{"done_reason":"length","message":{"content":"{\\"selected_kind\\": "}}'
        def request(*args, **kwargs): calls.append(True); return Response()
        with patch('urllib.request.urlopen', side_effect=request):
            result = plan_visual('auto', 'Draw the relationship', context(), OllamaGenerator(model='fixture'), None)
        self.assertEqual(result.status, 'failed')
        self.assertIsNone(result.spec)
        self.assertEqual(len(calls), 1)

    def make_pipeline(self, raw, owned=False):
        from aura_bio.pipeline import AuraBioPipeline, AnswerPolicy
        from aura_bio.study.claims import parse_claims
        from aura_bio.study.routing import StudyRouter
        from aura_bio.study.verification import StudyVerifier
        from aura_bio.api.mapping import answer_payload
        from test_study_pipeline import hit
        class Generator(ResponseGenerator):
            last_metadata = {}
            def generate_claims(self, *args):
                return parse_claims('{"version":1,"claims":[{"claim":"ORION activates VEGA.","cite_ids":[1]}]}', 1)
        class Searcher:
            def search(self, *args, **kwargs):
                evidence = hit(1, 'ORION activates VEGA.')
                return [replace(evidence, document_id='b' * 32, unit_ids=('d' * 32,))] if owned else [evidence]
        return AuraBioPipeline(Generator(raw), searcher=Searcher(),
            router=StudyRouter(), verifier=StudyVerifier(use_entailment=False), draft_candidates=1,
            answer_policy=AnswerPolicy('pack_only', 'a' * 32))

    def test_auto_none_is_traced_but_does_not_render_an_unavailable_warning(self):
        from aura_bio.api.mapping import answer_payload
        pipeline = self.make_pipeline(selection('none', 'no_added_value'))
        before = answer_payload(pipeline.answer('What does ORION do?', use_critic=False), 'fixture')
        try: answer = pipeline.answer('What does ORION do?', use_critic=False, visual_output='auto')
        except ValueError: self.fail('Pipeline does not accept auto')
        after = answer_payload(answer, 'fixture')
        self.assertEqual(after.get('visuals', []), [])
        for field in ('markdown', 'confidence', 'verification_status', 'delivery', 'limitations'):
            self.assertEqual(after[field], before[field])
        self.assertEqual(answer.trace.final_record['visual']['metadata']['selected_kind'], 'none')

    def test_unavailable_selected_source_keeps_the_decision_and_does_not_substitute(self):
        pipeline = self.make_pipeline(selection('source', 'source_inspection', source_id='s0'), owned=True)
        try: answer = pipeline.answer('Explain this figure', use_critic=False, visual_output='auto')
        except ValueError: self.fail('Pipeline does not accept auto')
        visual = answer.trace.final_record['visual']
        self.assertEqual(visual['status'], 'omitted')
        self.assertEqual(visual['metadata']['selected_kind'], 'source')
        self.assertEqual(visual['metadata']['proposal_calls'], 1)
        self.assertIsNone(visual['spec'])


if __name__ == '__main__': unittest.main()
