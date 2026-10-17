import unittest


class VisualOutputEvalTests(unittest.TestCase):
    def test_extension_requires_three_per_kind_and_manual_safe_controls(self):
        from aura_bio.visual_outputs import evaluation
        evaluate=getattr(evaluation,'evaluate_upgrade_results',None)
        self.assertTrue(callable(evaluate),'The frozen 30-case gate has no evaluator.')
        kinds=['source','diagram','comparison','procedure','plot']
        bank=[{'id':f'{kind}-{n}','kind':kind,'answerable':True,'evaluation_mode':'authored_contract'} for kind in kinds for n in range(4)]
        bank += [{'id':f'control-{n}','kind':'plot','answerable':False,'evaluation_mode':'live_unsupported'} for n in range(10)]
        rows=[{'id':c['id'],'status':'ready' if c['answerable'] else 'omitted'} for c in bank]
        reviews={c['id']:({'valid':True} if c['answerable'] and not c['id'].endswith('-3') else {'control_safe':True} if not c['answerable'] else {'valid':False}) for c in bank}
        self.assertTrue(evaluate(bank,rows,reviews)['release_passed'])
        reviews['plot-2']['valid']=False;reviews['source-3']['valid']=True
        result=evaluate(bank,rows,reviews)
        self.assertEqual(result['positive_valid'],15)
        self.assertFalse(result['release_passed']);self.assertIn('kind_plot',result['failed_gates'])
        result=evaluate(bank,rows,{})
        self.assertFalse(result['release_passed']);self.assertEqual(result['controls_correct'],0)
        self.assertEqual(result['positive_total'],20)

    def bank(self):
        kinds=['source','source','source','diagram','diagram','procedure','comparison','plot','plot']
        return [{'id':str(n),'kind':kind,'answerable':True} for n,kind in enumerate(kinds)]+[
            {'id':str(n),'kind':'plot','answerable':False} for n in range(9,12)]

    def summary(self, approved, missing=(), violations=0):
        try: from aura_bio.visual_outputs.evaluation import evaluate_visual_results
        except ImportError: self.fail('Frozen visual-output gate evaluator is not implemented')
        bank=self.bank()
        rows=[{'id':item['id'],'status':'ready' if item['answerable'] else 'omitted',
               'grounding_violations':violations if item['id']=='0' else 0} for item in bank if item['id'] not in missing]
        reviews={id:{'valid':True} for id in approved}
        return evaluate_visual_results(bank,rows,reviews)

    def test_six_of_nine_fails_even_when_all_controls_decline(self):
        report=self.summary({'0','3','5','6','7','8'})
        self.assertFalse(report['release_passed'])
        self.assertIn('positive_coverage',report['failed_gates'])
        self.assertEqual(report['positive_total'],9)

    def test_seven_requires_every_kind_controls_and_zero_violations(self):
        ids={'0','3','4','5','6','7','8'}
        self.assertTrue(self.summary(ids)['release_passed'])
        self.assertFalse(self.summary(ids,missing=('11',))['release_passed'])
        self.assertFalse(self.summary(ids,violations=1)['release_passed'])
        self.assertIn('kind_procedure',self.summary({'0','1','2','3','4','6','7'})['failed_gates'])

    def test_unattempted_and_unreviewed_positives_stay_in_denominator(self):
        report=self.summary(set(),missing=('1','2'))
        self.assertEqual(report['positive_valid'],0)
        self.assertEqual(report['positive_total'],9)
        self.assertEqual(report['manual_review_pending'],9)
        self.assertEqual(report['per_kind']['source']['total'],3)


if __name__=='__main__': unittest.main()
