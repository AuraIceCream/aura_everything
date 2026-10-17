import unittest
from aura_bio.study.visual.evaluation import evaluate_figure_run,validate_resume


class FigureEvaluationTests(unittest.TestCase):
    def test_denominators_unreviewed_null_and_label_hallucination(self):
        bank=[{'id':'one','figure_id':'f','split':'dev','category':'label','key':'A','question':'Read label'},
              {'id':'two','figure_id':'f','split':'dev','category':'relationship','key':'A','question':'Left item'},
              {'id':'three','figure_id':'g','split':'dev','category':'absent','key':None,'question':'Absent'}]
        records=[{'id':'one','state':'completed','labels':['A','Invented'],'gold_labels':['A'],'numeric_certified':True,'latency_ms':10,'tokens':30},
                 {'id':'two','state':'completed','answer':'A'}, {'id':'three','state':'error'}]
        result=evaluate_figure_run(records,bank)
        self.assertEqual(result['total'],3); self.assertEqual(result['errors'],1)
        self.assertEqual(result['label_recall'],1)
        self.assertEqual(result['unmatched_label_rate'],.5)
        self.assertIsNone(result['hallucinated_label_rate'])
        self.assertIsNone(result['relation_accuracy']); self.assertIsNone(result['unsupported_abstention'])
        self.assertEqual(result['numeric_certification_violations'],1)

    def test_resume_hashes_and_splits_fail_closed(self):
        with self.assertRaises(ValueError): validate_resume({'manifest_hash':'old'},{'manifest_hash':'new'})
        with self.assertRaises(ValueError): evaluate_figure_run([{'id':'foreign','state':'completed'}],[{'id':'one','split':'dev'}])
        with self.assertRaises(ValueError): evaluate_figure_run([], [{'id':'one','split':'dev'},{'id':'two','split':'holdout'}])

    def test_unsupported_control_requires_reviewed_abstention(self):
        bank=[{'id':'one','figure_id':'f','category':'absent','split':'holdout','key':None}]
        result=evaluate_figure_run([{'id':'one','state':'completed','review':{'abstained':False,'locator_correct':True}}],bank)
        self.assertEqual(result['unsupported_abstention'],0)
        self.assertEqual(result['manual_reviewed'],1)

    def test_missing_latency_stays_null(self):
        result=evaluate_figure_run([{'id':'one','state':'error','latency_ms':None}],[{'id':'one','split':'dev'}])
        self.assertIsNone(result['mean_latency_ms'])

    def test_local_eval_resume_pins_digest_and_score_only_never_preflights(self):
        from aura_bio.study.visual.evaluation import pin_evaluation_config
        from aura_bio.study.visual.schema import VisualJobConfig
        config=VisualJobConfig(model='local-vision')
        pinned=pin_evaluation_config(config,None,score_only=False,preflight=lambda _: 'digest-1')
        self.assertEqual(pinned.model_digest,'digest-1')
        frozen={'model_digest':pinned.model_digest}
        with self.assertRaises(ValueError):
            pin_evaluation_config(config,frozen,score_only=False,preflight=lambda _: 'digest-2')
        result=pin_evaluation_config(config,frozen,score_only=True,
            preflight=lambda _:self.fail('Scoring must not inspect/unload a GPU model'))
        self.assertEqual(result.model_digest,'digest-1')
