"""Missing-detail enrichment retains checked facts, not rejected drafts."""
import json
import unittest
from unittest.mock import patch

from aura_bio.study.claims import parse_claims
from aura_bio.study.claim_generation import StudyClaimGenerator, build_claim_prompt
from aura_bio.study.routing import StudyRouter
from test_study_pipeline import hit


def draft(*rows):
    return parse_claims(json.dumps({'version': 1, 'claims': list(rows)}), 2)


class EnrichmentTests(unittest.TestCase):
    def test_merge_keeps_only_delivered_base_claims_and_rebases_new_dependencies(self):
        from aura_bio.study.claims import merge_claims
        base = draft({'id': 'c1', 'claim': 'ORION needs calibration.', 'cite_ids': [1]},
                     {'id': 'c2', 'claim': 'Unsupported assertion.', 'cite_ids': [1]})
        extra = draft({'id': 'c1', 'claim': 'VEGA tests vessel sealing.', 'cite_ids': [2]},
                      {'id': 'c2', 'claim': 'The sealing result remains proposed.',
                       'cite_ids': [2], 'depends_on': ['c1']})
        merged = merge_claims(base, ['c1'], extra)
        self.assertEqual([c.claim for c in merged.claims],
                         [base.claims[0].claim, extra.claims[0].claim, extra.claims[1].claim])
        self.assertEqual(len({c.id for c in merged.claims}), 3)
        self.assertEqual(merged.claims[2].depends_on, (merged.claims[1].id,))
        self.assertEqual(merged.claims[1].cite_ids, (2,))
        self.assertEqual([b.ref for b in merged.blocks], [c.id for c in merged.claims])

    def test_merge_exact_repeat_does_not_duplicate_a_displayed_fact(self):
        from aura_bio.study.claims import merge_claims
        base = draft({'claim': 'ORION needs calibration.', 'cite_ids': [1]})
        merged = merge_claims(base, ['c1'], base)
        self.assertEqual(merged, base)

    def test_removed_dependency_and_its_teaching_block_are_not_resurrected(self):
        from aura_bio.study.claims import merge_claims
        base = parse_claims(json.dumps({'version': 1, 'claims': [
            {'id': 'c1', 'claim': 'Unsupported assertion.', 'cite_ids': [1]},
            {'id': 'c2', 'claim': 'Dependent assertion.', 'cite_ids': [1], 'depends_on': ['c1']}],
            'blocks': [{'type': 'claim', 'ref': 'c1'}, {'type': 'claim', 'ref': 'c2'},
                       {'type': 'teaching', 'template': 'reflect', 'after': 'c2'}]}), 2)
        merged = merge_claims(base, ['c2'], draft())
        self.assertEqual(merged.claims, ())
        self.assertEqual(merged.blocks, ())

    def test_merge_limit_is_explicit_and_does_not_mutate_base(self):
        from aura_bio.study.claims import merge_claims, MAX_CLAIMS
        base = draft(*({'claim': f'Course fact {n}.', 'cite_ids': [1]} for n in range(MAX_CLAIMS)))
        with self.assertRaisesRegex(ValueError, 'claim limit'):
            merge_claims(base, [c.id for c in base.claims],
                         draft({'claim': 'An additional course fact.', 'cite_ids': [2]}))
        self.assertEqual(len(base.claims), MAX_CLAIMS)

    def test_supplement_prompt_does_not_ask_to_rewrite_retained_facts(self):
        generator = StudyClaimGenerator(model='fixture')
        self.assertTrue(callable(getattr(generator, 'generate_supplement', None)))
        route = StudyRouter().route('What experiment is proposed and what would it test?')
        base = draft({'claim': 'ORION needs calibration.', 'cite_ids': [1]})
        captured = []
        def generate(route, evidence, instructions, **kwargs):
            captured.append(build_claim_prompt(route, evidence, instructions,
                                               previous_answer=kwargs['previous_answer']))
            return '{"version":1,"claims":[]}'
        with patch.object(generator, 'generate', side_effect=generate):
            generator.generate_supplement(route, [hit(1, 'ORION needs calibration.')],
                                          ['what would it test'], base.claims)
        self.assertIn('only additional', captured[0].system.lower())
        self.assertIn('what would it test', captured[0].user)
        self.assertIn('ORION needs calibration.', captured[0].user)

    def test_pipeline_merges_then_rechecks_supplement_with_same_two_call_budget(self):
        from aura_bio.pipeline import AuraBioPipeline, AnswerPolicy
        from aura_bio.study.verification import StudyVerifier
        calls, checked = [], []
        base = draft({'claim': 'ORION proposes single-cell profiling.', 'cite_ids': [1]})
        extra = draft({'claim': 'The proposed study would test for expanded clonotypes engaging in cancer-cell killing.',
                       'cite_ids': [1]})
        class Generator:
            last_metadata = {}
            def generate_claims(self, *args):
                calls.append('draft')
                return base
            def generate_supplement(self, route, evidence, missing, retained):
                calls.append('supplement')
                self_retained = [c.claim for c in retained]
                if self_retained != [base.claims[0].claim]:
                    raise AssertionError('Wrong retained facts')
                return extra
        class Searcher:
            def search(self, *args, **kwargs):
                return [hit(1, 'ORION proposes single-cell profiling. The proposed study would test for '
                               'expanded clonotypes engaging in cancer-cell killing.')]
        class Verifier(StudyVerifier):
            def verify_claims(self, claims, *args):
                checked.append([c.claim for c in claims])
                return super().verify_claims(claims, *args)
        pipeline = AuraBioPipeline(Generator(), searcher=Searcher(), router=StudyRouter(),
            verifier=Verifier(use_entailment=False), accuracy_mode='robust', draft_candidates=2,
            answer_policy=AnswerPolicy('pack_only', 'a' * 32))
        answer = pipeline.answer('What follow-up experiment do the authors propose?', use_critic=False)
        self.assertEqual(calls, ['draft', 'supplement'])
        self.assertEqual(checked[1], [base.claims[0].claim, extra.claims[0].claim])
        self.assertIn('single-cell profiling', answer.text)
        self.assertIn('cancer-cell killing', answer.text)
        self.assertFalse(answer.trace.final_record['delivery']['question_coverage']['possible_omissions'])
        self.assertEqual(answer.trace.final_record['phase'], 'enrichment')


if __name__ == '__main__':
    unittest.main()
