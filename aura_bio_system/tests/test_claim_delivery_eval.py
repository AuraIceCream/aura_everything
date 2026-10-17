import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


RUNNER = Path(__file__).resolve().parents[1] / 'benchmarks' / 'run_claim_delivery.py'


def runner():
    if not RUNNER.exists():
        return types.SimpleNamespace()
    spec = importlib.util.spec_from_file_location('claim_eval_runner', RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClaimDeliveryEvalTests(unittest.TestCase):
    def test_preflight_waits_for_own_model_to_release_between_questions(self):
        from aura_bio.study.schema import StudyError
        module = runner()
        class Backend:
            calls = 0
            def preflight(self, _config):
                self.calls += 1
                if self.calls < 3:
                    raise StudyError('busy_gpu', 'Insufficient free VRAM or GPU is busy')
                return 'installed-digest'
            def _request(self, method, path, **kwargs): return {'models':[]}
        backend = Backend()
        with patch.object(module.time, 'sleep') as sleep:
            self.assertEqual(module.preflight_after_release(backend, object()), 'installed-digest')
        self.assertEqual(backend.calls, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_preflight_can_release_only_its_own_resident_model(self):
        from aura_bio.study.schema import StudyError
        module = runner()
        class Backend:
            def __init__(self): self.loaded=True; self.releases=[]
            def preflight(self, _config):
                if self.loaded: raise StudyError('busy_gpu','Insufficient free VRAM or GPU is busy')
                return 'installed-digest'
            def _request(self, method, path, **kwargs):
                if path == '/api/ps': return {'models':[{'name':'qwen3.5:4b'}]}
                self.releases.append(kwargs['json'])
                self.loaded=False
                return {}
        backend=Backend()
        with patch.object(module.time,'sleep'), patch('aura_bio.study.visual.ollama.gpu_free_mb',return_value=(170,4096,0)):
            self.assertEqual(module.preflight_after_release(backend,types.SimpleNamespace(model='qwen3.5:4b')),'installed-digest')
        self.assertEqual(backend.releases,[{'model':'qwen3.5:4b','keep_alive':0}])

    def test_resume_rejects_changed_manifest_and_config(self):
        module = runner()
        self.assertTrue(callable(getattr(module, 'validate_checkpoint', None)), 'Checkpoint validation is not implemented')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'metadata.json'
            path.write_text(json.dumps({'config': {'manifest': 'old', 'model': 'qwen'}}))
            with self.assertRaises(ValueError):
                module.validate_checkpoint(path, {'manifest': 'new', 'model': 'qwen'})

    def test_completed_cases_are_retained_but_errors_are_retryable_explicitly(self):
        module = runner()
        self.assertTrue(callable(getattr(module, 'completed_ids', None)), 'Checkpoint resume is not implemented')
        self.assertEqual(module.completed_ids([{'id': 'a', 'decision': 'insufficient_evidence'},
                                               {'id': 'b', 'error': 'busy_gpu'}]), {'a'})

    def test_summary_uses_completed_denominator_and_no_semantic_score(self):
        module = runner()
        self.assertTrue(callable(getattr(module, 'summarize', None)), 'Evaluation summary is not implemented')
        bank = [{'id': 'a', 'answerable': True}, {'id': 'b', 'answerable': False}, {'id': 'c', 'answerable': True}]
        rows = [{'id': 'a', 'decision': 'insufficient_evidence', 'latency_ms': 100},
                {'id': 'b', 'decision': 'insufficient_evidence', 'latency_ms': 200}]
        summary = module.summarize(rows, bank)
        self.assertEqual(summary['completed'], 2)
        self.assertEqual(summary['missing'], 1)
        self.assertEqual(summary['answerable_refusal_rate'], 1.0)
        self.assertEqual(summary['unsupported_control_abstention'], 1.0)
        self.assertIsNone(summary['semantic_accuracy'])


if __name__ == '__main__':
    unittest.main()
