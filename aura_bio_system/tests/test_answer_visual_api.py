import json
import unittest
from visual_output_fixtures import context, diagram


class VisualPlannerTests(unittest.TestCase):
    def test_none_never_calls_a_model(self):
        try: from aura_bio.visual_outputs.planner import plan_visual
        except ImportError: self.fail('Optional visual planning is not implemented')
        class Generator:
            def propose_visual(self, *args): raise AssertionError('none started generation')
        self.assertEqual(plan_visual('none', 'ORION?', context(), Generator(), None).status, 'omitted')

    def test_one_proposal_and_no_repair_or_private_error_disclosure(self):
        try: from aura_bio.visual_outputs.planner import plan_visual
        except ImportError: self.fail('Optional visual planning is not implemented')
        class Generator:
            def __init__(self, raw=None): self.calls=0; self.raw=raw
            def propose_visual(self, *args):
                self.calls += 1
                if self.raw is None: raise TimeoutError('PRIVATE SOURCE SECRET')
                return self.raw
        for raw in (None, '{broken', json.dumps(diagram())):
            generator = Generator(raw)
            result = plan_visual('diagram', 'ORION?', context(), generator, None)
            self.assertEqual(generator.calls, 1)
            self.assertNotIn('SECRET', str(result.as_dict()))
            self.assertEqual(result.status, 'ready' if raw and raw.startswith('{"version"') else 'failed')

    def test_request_defaults_off_and_rejects_arbitrary_code_mode(self):
        from aura_bio.api.app import RunRequestModel
        from pydantic import ValidationError
        request = RunRequestModel(query='ORION?')
        self.assertTrue(hasattr(request, 'visual_output'), 'Visual request option is missing')
        self.assertEqual(request.visual_output, 'none')
        with self.assertRaises(ValidationError): RunRequestModel(query='ORION?', visual_output='python')

    def test_visual_failure_preserves_mapped_answer_and_selected_claims(self):
        from aura_bio.pipeline import AuraBioPipeline, AnswerPolicy
        from aura_bio.study.claims import parse_claims
        from aura_bio.study.routing import StudyRouter
        from aura_bio.study.verification import StudyVerifier
        from aura_bio.api.mapping import answer_payload
        from test_study_pipeline import hit
        class Generator:
            model_name = 'fixture'; last_metadata = {}
            def generate_claims(self, *args):
                return parse_claims('{"version":1,"claims":[{"claim":"ORION activates VEGA.","cite_ids":[1]}]}', 1)
            def propose_visual(self, *args): raise TimeoutError('PRIVATE SOURCE SECRET')
        class Searcher:
            def search(self, *args, **kwargs): return [hit(1, 'ORION activates VEGA.')]
        pipeline = AuraBioPipeline(Generator(), searcher=Searcher(), router=StudyRouter(),
            verifier=StudyVerifier(use_entailment=False), draft_candidates=1,
            answer_policy=AnswerPolicy('pack_only', 'a'*32))
        before = answer_payload(pipeline.answer('What does ORION do?', use_critic=False), 'fixture')
        try: result = pipeline.answer('What does ORION do?', use_critic=False, visual_output='diagram')
        except TypeError: self.fail('Visual request is not integrated into structured delivery')
        after = answer_payload(result, 'fixture')
        for field in ('markdown', 'confidence', 'verification_status', 'delivery'):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after['visuals'][0]['status'], 'failed')
        self.assertNotIn('SECRET', json.dumps(after))
        self.assertIn('visual_output', result.trace.stage_ms)


if __name__ == '__main__': unittest.main()
