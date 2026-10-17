"""Windows commit exhaustion must fail before native model loading."""
import unittest
import os
from unittest.mock import patch


class ModelMemoryTests(unittest.TestCase):
    def resources(self):
        try:
            from aura_bio import resources
        except ImportError:
            self.fail('Cold model loading needs a Windows committed-memory guard.')
        return resources

    def test_free_physical_ram_does_not_override_exhausted_commit(self):
        resources = self.resources()
        with patch.object(resources, 'available_memory_mb', return_value={'physical': 6000, 'commit': 500}):
            with self.assertRaisesRegex(resources.MemoryPressureError, 'committed-memory'):
                resources.guard_cpu_model_load('reranker', 2048)

    def test_sufficient_commit_allows_normal_model_loading(self):
        resources = self.resources()
        with patch.object(resources, 'available_memory_mb', return_value={'physical': 800, 'commit': 6000}):
            resources.guard_cpu_model_load('reranker', 2048)

    def test_unknown_memory_status_does_not_disable_non_windows_hosts(self):
        resources = self.resources()
        with patch.object(resources, 'available_memory_mb', return_value=None):
            resources.guard_cpu_model_load('reranker', 2048)

    def test_cold_reranker_stops_before_entering_native_loader(self):
        resources = self.resources()
        from aura_bio.study.reranking import cached_scorer
        with patch.object(resources, 'available_memory_mb', return_value={'physical': 6000, 'commit': 500}):
            with self.assertRaises(resources.MemoryPressureError):
                cached_scorer.__wrapped__()

    def test_nli_memory_pressure_remains_a_visible_unavailable_checker(self):
        resources = self.resources()
        from aura_bio.verification.entailment import EntailmentScorer
        with patch.object(resources, 'available_memory_mb', return_value={'physical': 6000, 'commit': 500}), patch.dict(os.environ, {'AURA_NLI': 'on'}):
            with self.assertRaises(resources.MemoryPressureError):
                EntailmentScorer()._load()

    def test_nli_memory_fallback_is_disclosed_in_delivered_answer(self):
        resources = self.resources()
        from aura_bio.study.verification import StudyVerifier
        from aura_bio.study.claims import parse_claims
        from aura_bio.study.claim_delivery import deliver_claims
        from aura_bio.verification.entailment import EntailmentScorer
        from test_study_claims import evidence
        draft = parse_claims('{"version":1,"claims":[{"claim":"ORION is the calibration label.","cite_ids":[1]}]}', 1)
        with patch.object(resources, 'available_memory_mb', return_value={'physical': 6000, 'commit': 500}), \
                patch.dict(os.environ, {'AURA_NLI': 'on'}), \
                patch('aura_bio.verification.entailment._SCORER', EntailmentScorer()):
            report = StudyVerifier().verify_claims(draft.claims, [evidence('ORION is the calibration label.')])
        delivered = deliver_claims(draft, report)
        self.assertTrue(any(issue['kind'] == 'memory_pressure' for issue in delivered.verification['issues']))
        self.assertFalse(delivered.verification['claim_basis'][0]['inputs_verified'])

    def test_study_runtime_does_not_silently_downgrade_on_memory_pressure(self):
        from types import SimpleNamespace
        resources = self.resources()
        from aura_bio.study.runtime import build_pack_pipeline
        from aura_bio.study.schema import StudyError
        store = SimpleNamespace(assert_available=lambda _: SimpleNamespace(state='hybrid-ready'))
        with patch('aura_bio.study.runtime.cached_encoder', side_effect=resources.MemoryPressureError('low commit')):
            with self.assertRaises(StudyError) as failure:
                build_pack_pipeline(store, 'a' * 32)
        self.assertEqual(failure.exception.code, 'busy_memory')

    def test_resource_pressure_maps_to_temporary_api_conflict(self):
        from aura_bio.api.study_packs import study_http_error
        from aura_bio.study.schema import StudyError
        error = study_http_error(StudyError('busy_memory', 'low commit'))
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.detail['code'], 'busy_memory')

