import hashlib
import json
from pathlib import Path
import tempfile
import unittest


class VisualUpgradeRunnerTests(unittest.TestCase):
    def runner(self):
        try:
            from aura_bio_system.benchmarks import run_visual_upgrade
        except ImportError:
            self.fail('The checkpointed visual-upgrade runner is not implemented.')
        return run_visual_upgrade

    def test_hash_change_refuses_before_inference(self):
        runner = self.runner()
        with self.assertRaises(ValueError):
            runner.validate_manifest({'bank_sha256':'0'*64}, b'{"id":"a"}\n')

    def test_gold_and_proposals_never_enter_model_inputs(self):
        runner = self.runner(); captured = []
        def runtime(case):
            captured.append(case)
            return {'status':'ready'}
        with tempfile.TemporaryDirectory() as directory:
            result = runner.run_case({'id':'a','kind':'diagram','question':'Explain the cycle',
                'gold':'secret','criteria':['secret'],'proposal':{'answer':'secret'}}, runtime, Path(directory))
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(captured, [{'id':'a','kind':'diagram','question':'Explain the cycle'}])

    def test_independent_failure_continues(self):
        runner = self.runner()
        def runtime(case):
            if case['id']=='a': raise ValueError('Bad provider output')
            return {'status':'ready'}
        with tempfile.TemporaryDirectory() as directory:
            records = runner.run_cases([{'id':id,'kind':'diagram','question':'Explain'} for id in ('a','b')],
                                       runtime, Path(directory), identity={'model':'fixed'})
        self.assertEqual([r['status'] for r in records], ['failed','ready'])

    def test_unknown_completion_is_not_resubmitted(self):
        runner = self.runner(); calls = []
        def runtime(case):
            calls.append(case); raise TimeoutError('Unknown completion')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory); cases=[{'id':'a','kind':'source','question':'Explain'}]
            runner.run_cases(cases, runtime, output, identity={'model':'fixed'})
            records=runner.run_cases(cases, runtime, output, identity={'model':'fixed'}, resume=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(records[0]['status'], 'unknown_completion')

    def test_resource_deferred_is_not_pass(self):
        runner=self.runner()
        from aura_bio.study.schema import StudyError
        def runtime(case): raise StudyError('busy_gpu','Resource guard')
        with tempfile.TemporaryDirectory() as directory:
            row=runner.run_case({'id':'a','question':'Explain','kind':'source'},runtime,Path(directory))
        self.assertEqual(row['status'],'deferred')
        self.assertEqual(row['reason_code'],'busy_gpu')

    def test_resume_rejects_changed_identity(self):
        runner=self.runner()
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory); cases=[{'id':'a','kind':'source','question':'Explain'}]
            runner.run_cases(cases,lambda case:{'status':'ready'},output,identity={'model':'first'})
            with self.assertRaises(ValueError):
                runner.run_cases(cases,lambda case:{'status':'ready'},output,identity={'model':'second'},resume=True)

    def test_production_adapter_reaches_actual_ask_boundary(self):
        from unittest.mock import patch
        runner=self.runner()
        answer={'markdown':'Checked answer','visuals':[{'status':'ready','spec':{'kind':'diagram'}}]}
        with patch('aura_bio.api.app._execute',return_value={'answer_payload':answer,'decision':'accept'}) as execute:
            result=runner.ProductionRuntime('qwen3.5:4b',require_full_stages=False)({'id':'a','kind':'diagram',
                'question':'Explain','pack_id':'a'*32})
        self.assertEqual(result['answer']['markdown'],'Checked answer')
        self.assertEqual(execute.call_args.args[0].visual_output,'diagram')

    def test_sparse_or_missing_checker_runtime_cannot_be_reported_as_complete(self):
        from types import SimpleNamespace
        runner=self.runner()
        checker=getattr(runner,'check_pipeline_stages',None)
        self.assertTrue(callable(checker),'No strict production-stage admission exists.')
        pipeline=SimpleNamespace(searcher=SimpleNamespace(mode='sparse'),reranker=None,
            verifier=SimpleNamespace(use_entailment=False),generator=SimpleNamespace(model_name='extractive'))
        with self.assertRaises(Exception): checker(pipeline,'qwen3.5:4b')

    def test_model_eval_preparation_uses_same_v2_focus_as_ask(self):
        runner=self.runner()
        factory=getattr(runner,'question_config',None)
        self.assertTrue(callable(factory),'Benchmark preparation is still using the legacy vision path.')
        config=factory('qwen3.5:4b','Explain Fig. 5',False)
        self.assertEqual(config['description_version'],2)
        self.assertTrue(config['focus']);self.assertEqual(config['timeout_seconds'],300)
