"""Idle retrieval weights must not overlap local generation allocations."""
import gc
import threading
import unittest
import weakref


class WeightHandoffTests(unittest.TestCase):
    def module(self):
        from aura_bio.study import model_lifecycle
        return model_lifecycle

    def test_cached_owners_do_not_keep_released_weights_alive_and_reload_is_identical(self):
        try: lifecycle = self.module()
        except ImportError: self.fail('A reloadable retrieval-weight owner is required.')
        refs = []
        class Weights:
            def encode(self, texts, **kwargs): return [[len(t)] for t in texts]
            def predict(self, pairs, **kwargs): return [.75] * len(pairs)
        def load():
            model = Weights(); refs.append(weakref.ref(model)); return model
        owner = lifecycle.RetrievalModel(load, 'same-model')
        owners = [owner, owner]  # Searcher and cache both hold the live owner.
        self.assertEqual(owner.encode(['DNA']), [[3]])
        self.assertIsNotNone(refs[0]())
        lifecycle.release_retrieval_weights(); gc.collect()
        self.assertIsNone(refs[0]())
        self.assertEqual(owners[1].predict([('q', 'p')], batch_size=2), [.75])
        self.assertEqual(owner.model_name, 'same-model')
        self.assertEqual(len(refs), 2)

    def test_generation_handoff_releases_both_retrieval_owners_without_reloading_them(self):
        try: lifecycle = self.module()
        except ImportError: self.fail('Generation must release retained retrieval weights.')
        from aura_bio.study.verification import StudyVerifier
        class Weights:
            def encode(self, *args, **kwargs): return [1]
            def predict(self, *args, **kwargs): return [2]
        refs = []
        def load():
            weights = Weights(); refs.append(weakref.ref(weights)); return weights
        encoder = lifecycle.RetrievalModel(load, 'encoder')
        scorer = lifecycle.RetrievalModel(load, 'reranker')
        encoder.encode(['q']); scorer.predict([('q', 'p')])
        report = StudyVerifier(use_entailment=False).before_generation()
        self.assertEqual(report['retrieval_models_released'], 2)
        self.assertTrue(all(ref() is None for ref in refs))
        self.assertEqual(len(refs), 2)

    def test_eviction_waits_for_an_active_inference(self):
        try: lifecycle = self.module()
        except ImportError: self.fail('Retrieval inference and weight eviction require shared locking.')
        entered, finish, released = threading.Event(), threading.Event(), threading.Event()
        class Weights:
            def encode(self, *args):
                entered.set(); finish.wait(3); return [1]
        owner = lifecycle.RetrievalModel(Weights, 'encoder')
        inference = threading.Thread(target=lambda: owner.encode(['q']))
        eviction = threading.Thread(target=lambda: (lifecycle.release_retrieval_weights(), released.set()))
        inference.start()
        self.assertTrue(entered.wait(2))
        eviction.start()
        try: self.assertFalse(released.wait(.1))
        finally:
            finish.set(); inference.join(3); eviction.join(3)
        self.assertTrue(released.is_set())

    def test_production_generation_entry_releases_weights_in_all_study_paths(self):
        lifecycle = self.module()
        from aura_bio.pipeline import AuraBioPipeline, AnswerPolicy
        from aura_bio.study.routing import StudyRouter
        from aura_bio.study.verification import StudyVerifier
        from aura_bio.study.claims import parse_claims
        from test_study_pipeline import hit
        for structured in (False, True):
            for mode in ('standard', 'robust'):
                with self.subTest(structured=structured, mode=mode):
                    refs = []; called = []
                    class Weights:
                        def encode(self, *args, **kwargs): return [1]
                    def load():
                        weights = Weights(); refs.append(weakref.ref(weights)); return weights
                    owner = lifecycle.RetrievalModel(load, 'encoder')
                    class Searcher:
                        def search(self, *args, **kwargs):
                            owner.encode(['q'])
                            return [hit(1, 'ORION is a calibration label.')]
                    test = self
                    class Generator:
                        model_name = 'fixture'; last_metadata = {}
                        def generate(self, *args, **kwargs):
                            test.assertTrue(refs)
                            test.assertTrue(all(ref() is None for ref in refs), 'Retrieval weights survived into generation')
                            called.append(True)
                            return 'ORION is a calibration label. [1]'
                    class StructuredGenerator(Generator):
                        def generate_claims(self, *args, **kwargs):
                            self.generate()
                            return parse_claims('{"version":1,"claims":[{"claim":"ORION is a calibration label.","cite_ids":[1]}]}', 1)
                    pipeline = AuraBioPipeline(StructuredGenerator() if structured else Generator(),
                        searcher=Searcher(), router=StudyRouter(), verifier=StudyVerifier(use_entailment=False),
                        accuracy_mode=mode, draft_candidates=1,
                        answer_policy=AnswerPolicy('pack_only', 'a' * 32))
                    pipeline.answer('What is ORION?', use_critic=False)
                    self.assertTrue(called)


if __name__ == '__main__': unittest.main()
