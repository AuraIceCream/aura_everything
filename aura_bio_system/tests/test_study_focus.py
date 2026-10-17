"""Prompt focus is sourced from excerpts, never benchmark answer keys."""
import json
import unittest

from aura_bio.study.claim_generation import build_claim_prompt
from aura_bio.study.routing import StudyRouter
from test_study_completion import hit


class SourceFocusTests(unittest.TestCase):
    def test_background_purpose_cannot_displace_an_objective_continuation(self):
        sources = [hit(1, 'Guards evolved to detect intruders and protect the system.'),
                   hit(2, 'Studies highlighted the presence of authors and other background information.'),
                   hit(3, 'A follow-up study would use receptor profiling to test for the'),
                   hit(4, 'presence of expanded clonotypes engaging in target-cell killing.')]
        prompt = build_claim_prompt(StudyRouter().route(
            'What follow-up experiment is proposed to investigate that role?'), sources)
        focus = json.loads(prompt.user)['request_focus']
        self.assertEqual({item['citation'] for item in focus}, {3, 4})

    def test_experiment_objective_fragment_has_its_own_source_reference(self):
        sources = [hit(1, 'We propose receptor profiling, which may reveal the'),
                   hit(2, 'presence of expanded clonotypes engaging in target-cell killing.')]
        prompt = build_claim_prompt(StudyRouter().route(
            'What follow-up experiment is proposed to investigate that role?'), sources)
        body = json.loads(prompt.user)
        self.assertIn('request_focus', body)
        self.assertTrue(any(item['citation'] == 2 and 'target-cell killing' in item['quote']
                            for item in body['request_focus']))

    def test_classification_bias_quote_is_not_replaced_with_generic_background(self):
        sources = [hit(1, 'The groups are described in the introduction.'),
                   hit(2, 'The disadvantage is that highly invasive species may be understudied '
                          'where ecologists are less numerous.')]
        prompt = build_claim_prompt(StudyRouter().route(
            'What potential bias affects this classification?'), sources)
        body = json.loads(prompt.user)
        self.assertIn('request_focus', body)
        self.assertTrue(any(item['citation'] == 2 and 'understudied' in item['quote']
                            for item in body['request_focus']))

