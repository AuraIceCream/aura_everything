"""Graded delivery of source-checked study claims."""
import json
import unittest

from test_study_claims import document, evidence
from aura_bio.study.verification import StudyVerifier
from aura_bio.study.routing import StudyRouter


class ClaimDeliveryTests(unittest.TestCase):
    def deliver(self, value, mode='tutor'):
        try:
            from aura_bio.study.claims import parse_claims
            from aura_bio.study.claim_delivery import deliver_claims
        except ImportError:
            self.fail('Graded structured claim delivery is not implemented')
        draft = parse_claims(json.dumps(value), 1)
        verifier = StudyVerifier(use_entailment=False)
        report = verifier.verify_claims(draft.claims, [evidence('ORION is the calibration label.')],
                                        StudyRouter().route('ORION?'), 'ORION?')
        return deliver_claims(draft, report, mode=mode)

    def test_tutor_retains_supported_claim_and_discloses_omission(self):
        value = document()
        value['claims'].append({'id':'c2','claim':'The capital of France is Paris.','cite_ids':[1],'depends_on':[]})
        value['blocks'].append({'type':'claim','ref':'c2'})
        result = self.deliver(value)
        self.assertIn('ORION', result.text)
        self.assertNotIn('Paris', result.text)
        self.assertEqual(result.decision, 'partial')
        self.assertEqual(result.omitted_ids, ['c2'])
        self.assertEqual(result.delivered_ids, ['c1'])
        self.assertEqual(len(result.verification['claims']), 1)

    def test_strict_refuses_same_mixed_draft(self):
        value = document()
        value['claims'].append({'id':'c2','claim':'The capital of France is Paris.','cite_ids':[1],'depends_on':[]})
        value['blocks'].append({'type':'claim','ref':'c2'})
        result = self.deliver(value, 'strict')
        self.assertEqual(result.decision, 'insufficient_evidence')
        self.assertNotIn('ORION', result.text)

    def test_transitive_dependency_pruning_includes_teaching_blocks(self):
        value = document('The capital of France is Paris.')
        value['claims'].extend([
            {'id':'c2','claim':'ORION is the calibration label.','cite_ids':[1],'depends_on':['c1']},
            {'id':'c3','claim':'ORION is the calibration label.','cite_ids':[1],'depends_on':['c2']}])
        value['blocks'].extend([{'type':'claim','ref':'c2'}, {'type':'claim','ref':'c3'}])
        result = self.deliver(value)
        self.assertEqual(result.delivered_ids, [])
        self.assertEqual(result.omitted_ids, ['c1', 'c2', 'c3'])
        self.assertNotIn('own words', result.text)

    def test_safe_teaching_is_rendered_beside_its_surviving_claim(self):
        result = self.deliver(document())
        self.assertIn('own words', result.text)
        self.assertIn('[1]', result.text)
        self.assertEqual(result.verification['citation_coverage'], 1.0)


if __name__ == '__main__':
    unittest.main()
