"""Negative layout fixtures test the guard, not an ambiguous positive prompt."""
import importlib.util
import json
from pathlib import Path
import unittest
from visual_output_fixtures import context, diagram

ROOT = Path(__file__).parents[1] / 'benchmarks'


class VisualRunnerTests(unittest.TestCase):
    def test_model_grounding_omission_retains_private_failure_cause(self):
        spec=importlib.util.spec_from_file_location('visual_runner_diagnostics',ROOT/'run_visual_output_eval.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        value=diagram();value['payload']['edges'][0]['label']='ORION activates VEGA'
        class Generator:
            def propose_visual(self,*args): return json.dumps(value)
        details={}
        result,mode=runner.evaluate_case({'answerable':True,'kind':'diagram','question':'Draw the pathway'},
            context(),value,Generator(),diagnostics=details)
        self.assertEqual(result.status,'omitted')
        self.assertIn('complete retained proposition',details['grounding_error'])
        self.assertNotIn('grounding_error',result.metadata)

    def test_model_mode_keeps_adversarial_guard_controls_distinct(self):
        spec = importlib.util.spec_from_file_location('visual_runner', ROOT / 'run_visual_output_eval.py')
        runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
        evaluate = getattr(runner, 'evaluate_case', None)
        self.assertTrue(callable(evaluate), 'The runner must distinguish proposal generation from guard controls.')
        bank = [json.loads(line) for line in (ROOT / 'data/visual_output_bank_v1.jsonl').read_text().splitlines()]
        class Generator:
            def propose_visual(self, *args): raise AssertionError('A frozen bad-layout control must not become a positive model request.')
        case = next(c for c in bank if c['id'] == 'control-causality')
        result, mode = evaluate(case, context(), case['proposal'], Generator())
        self.assertEqual(result.status, 'omitted')
        self.assertEqual(mode, 'guard_fixture')
        class PositiveGenerator:
            def propose_visual(self, *args): return json.dumps(diagram())
        result, mode = evaluate(next(c for c in bank if c['id'] == 'diagram-interpreted'),
                                context('vlm'), diagram(), PositiveGenerator())
        self.assertEqual(result.status, 'ready')
        self.assertEqual(mode, 'model')


if __name__ == '__main__': unittest.main()
