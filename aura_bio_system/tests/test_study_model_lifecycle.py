"""Generation and NLI must not retain each other's idle model allocation."""
import gc
import json
import threading
import unittest
import weakref
import itertools
from unittest.mock import patch

from aura_bio.pipeline import AnswerPolicy, AuraBioPipeline
from aura_bio.study.claim_generation import StudyClaimGenerator
from aura_bio.study.claims import parse_claims
from aura_bio.study.routing import StudyRouter
from aura_bio.study.verification import StudyVerifier
from aura_bio.verification.entailment import EntailmentScorer
from test_study_completion import hit


class ModelLifetimeTests(unittest.TestCase):
    def test_generation_waits_for_confirmed_unload_before_returning(self):
        events = []
        states = iter([[{'name': 'fixture'}], [{'name': 'fixture'}], []])
        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(self.body).encode()
        def transport(request, **kwargs):
            if request.full_url.endswith('/api/ps'):
                events.append('ps')
                return Response({'models': next(states)})
            events.append('chat')
            return Response({'message': {'content': '{"version":1,"claims":[]}'}, 'done_reason': 'stop'})
        generator = StudyClaimGenerator(model='fixture', retries=0)
        with patch('urllib.request.urlopen', transport), patch('time.sleep'):
            generator.generate_claims(StudyRouter().route('ORION?'), [])
        self.assertEqual(events, ['chat', 'ps', 'ps', 'ps'])

    def test_unload_timeout_does_not_repeat_successful_generation(self):
        calls = []
        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(self.body).encode()
        def transport(request, **kwargs):
            if request.full_url.endswith('/api/ps'):
                return Response({'models': [{'name': 'fixture'}]})
            calls.append('chat')
            return Response({'message': {'content': '{"version":1,"claims":[]}'}, 'done_reason': 'stop'})
        generator = StudyClaimGenerator(model='fixture', retries=2)
        ticks = itertools.count()
        with patch('urllib.request.urlopen', transport), patch('time.sleep'), \
                patch('time.monotonic', side_effect=lambda: next(ticks)):
            with self.assertRaisesRegex(RuntimeError, 'still resident'):
                generator.generate_claims(StudyRouter().route('ORION?'), [])
        self.assertEqual(calls, ['chat'])

    def test_other_request_cannot_load_nli_during_generation(self):
        scorer = EntailmentScorer()
        attempted, loaded = threading.Event(), threading.Event()
        def load():
            attempted.set()
            scorer._load()
            loaded.set()
        worker = threading.Thread(target=load)
        owner = self
        class Generator:
            last_metadata = {}
            def generate_claims(self, *args):
                worker.start()
                owner.assertTrue(attempted.wait(1))
                owner.assertFalse(loaded.wait(.05), 'Another request loaded NLI during generation')
                return parse_claims(json.dumps({'version': 1, 'claims': [
                    {'claim': 'ORION is the calibration label.', 'cite_ids': [1]}]}), 1)
        class Searcher:
            def search(self, *args, **kwargs):
                return [hit(1, 'ORION is the calibration label.')]
        pipeline = AuraBioPipeline(Generator(), searcher=Searcher(), router=StudyRouter(),
            verifier=StudyVerifier(use_entailment=False), accuracy_mode='robust', draft_candidates=1,
            answer_policy=AnswerPolicy('pack_only', 'a' * 32))
        with patch.object(scorer, '_load_locked', return_value=(None, None)):
            try:
                answer = pipeline.answer('What is ORION?', use_critic=False)
            finally:
                worker.join(2)
        self.assertTrue(loaded.is_set())
        self.assertIn('ORION', answer.text)

    def test_structured_generator_requests_unload_without_reducing_context_or_output(self):
        generator = StudyClaimGenerator(model='fixture', num_predict=768, num_ctx=8192)
        self.assertEqual(generator.keep_alive, 0)
        self.assertEqual(generator.num_predict, 768)
        self.assertEqual(generator.num_ctx, 8192)

    def test_idle_nli_weights_are_released_before_generation(self):
        class Weights:
            pass
        scorer = EntailmentScorer()
        weights = Weights()
        reference = weakref.ref(weights)
        scorer._pipe = (object(), weights)
        del weights
        verifier = StudyVerifier()
        prepare = getattr(verifier, 'before_generation', None)
        self.assertTrue(callable(prepare), 'Study verification needs a generation-phase handoff')
        with patch('aura_bio.verification.entailment._SCORER', scorer):
            result = prepare()
        gc.collect()
        self.assertIsNone(reference())
        self.assertTrue(result['nli_released'])
        self.assertTrue(verifier.use_entailment)

    def test_release_waits_for_active_scoring_lock(self):
        scorer = EntailmentScorer()
        self.assertTrue(hasattr(scorer, 'release'), 'NLI needs an inference-safe release operation')
        scorer._pipe = (object(), object())
        entered, finished = threading.Event(), threading.Event()
        def release():
            entered.set()
            scorer.release()
            finished.set()
        with scorer._lock:
            thread = threading.Thread(target=release)
            thread.start()
            self.assertTrue(entered.wait(1))
            self.assertFalse(finished.wait(.05))
            self.assertIsNotNone(scorer._pipe)
        thread.join(2)
        self.assertTrue(finished.is_set())
        self.assertIsNone(scorer._pipe)

    def test_each_structured_draft_hands_off_before_generating(self):
        class Weights:
            pass
        scorer = EntailmentScorer()
        references = []
        def allocate():
            weights = Weights()
            references.append(weakref.ref(weights))
            scorer._pipe = (object(), weights)
        allocate()
        class Verifier(StudyVerifier):
            def verify_claims(self, *args):
                report = StudyVerifier(use_entailment=False).verify_claims(*args)
                allocate()
                return report
        owner = self
        class Generator:
            last_metadata = {}
            def generate_claims(self, *args):
                owner.assertIsNone(references[-1](), 'Idle NLI model still held during generation')
                return parse_claims(json.dumps({'version': 1, 'claims': [
                    {'claim': 'ORION is the calibration label.', 'cite_ids': [1]}]}), 1)
        class Searcher:
            def search(self, *args, **kwargs):
                return [hit(1, 'ORION is the calibration label.')]
        pipeline = AuraBioPipeline(Generator(), searcher=Searcher(), router=StudyRouter(),
            verifier=Verifier(), accuracy_mode='robust', draft_candidates=2,
            answer_policy=AnswerPolicy('pack_only', 'a' * 32))
        with patch('aura_bio.verification.entailment._SCORER', scorer):
            answer = pipeline.answer('What is ORION?', use_critic=False)
        self.assertIn('ORION', answer.text)
        self.assertEqual(len(answer.trace.revisions), 2)
        self.assertEqual(len(answer.trace.retrieval['model_handoffs']), 2)

