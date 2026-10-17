"""Observed pack failures, plus controls against weakening grounding."""
import json
import unittest
from unittest.mock import patch

from aura_bio.study.prompts import build_study_prompt, study_repair_instructions
from aura_bio.study.routing import StudyRouter
from aura_bio.study.searcher import StudyEvidence
from aura_bio.study.verification import StudyVerifier, claim_pairs
from aura_bio.verification.schema import Claim, Certainty, Support
from aura_bio.pipeline import AnswerPolicy, AuraBioPipeline, PromptedGenerator


def source(text, method='native_text', chunk='a'):
    return StudyEvidence(chunk * 32, 'lesson', 'Lesson', None, text, None, None,
                         'pack_sparse', 1, pack_id='b' * 32, provenance=method)


def neutral(claims, passages, report):
    # External semantic model boundary: conservative, deterministic fixture.
    report.support_backend = 'nli'
    return [Claim(0, claims[0], Support.UNSUPPORTED, Certainty.ESTABLISHED, .1)]


class ClaimParsingTests(unittest.TestCase):
    def test_bold_numbered_list_marker_is_not_a_separate_claim(self):
        pairs=claim_pairs('**1. ORION uses seven samples.** [1]')
        self.assertEqual(len(pairs),1)
        self.assertNotIn('**1.',pairs[0][0])
        self.assertIn('ORION uses seven samples',pairs[0][0])
        self.assertIn('[1]',pairs[0][1])

    def test_bold_decimal_is_data_and_bold_factual_heading_is_not_exempt(self):
        self.assertIn('1.2 mg',claim_pairs('**1.2 mg** is the recorded mass. [1]')[0][0])
        pairs=claim_pairs('**1. ORION is always safe.**')
        self.assertEqual(len(pairs),1)
        self.assertIn('ORION is always safe',pairs[0][0])
        report=StudyVerifier(use_entailment=False).verify('**1. ORION is always safe.**',[source('ORION is unsafe.')])
        self.assertTrue(report.blocking)

    def test_trailing_citations_do_not_join_bullets(self):
        pairs = claim_pairs('- The recorded mass is 7 mg. [1]\n'
                            '- The units are milligrams, not grams. [2]')
        self.assertEqual([text for text, _ in pairs], [
            'The recorded mass is 7 mg.', 'The units are milligrams, not grams.'])
        self.assertIn('[1]', pairs[0][1])
        self.assertNotIn('[2]', pairs[0][1])
        self.assertIn('[2]', pairs[1][1])

    def test_inline_sentence_citations_remain_with_their_claim(self):
        pairs = claim_pairs('The record uses milligrams. [1] The caption is F. [2]')
        self.assertEqual(len(pairs), 2)
        self.assertIn('[1]', pairs[0][1])
        self.assertNotIn('[2]', pairs[0][1])

    def test_only_closed_introductory_boilerplate_is_ignored(self):
        pairs = claim_pairs('Based on the provided source material, here is the answer:\n'
                            '- The animation pauses at frame nine. [1]')
        self.assertEqual([text for text, _ in pairs], [
            'The animation pauses at frame nine.'])

    def test_factual_introductory_sentence_is_not_exempt(self):
        pairs = claim_pairs('Based on the source, the animation pauses at frame ten.')
        self.assertEqual(len(pairs), 1)
        self.assertIn('frame ten', pairs[0][0])

    def test_signed_numbers_and_decimals_are_not_list_markers(self):
        self.assertEqual([text for text, _ in claim_pairs('-7 mg is the recorded mass. [1]')],
                         ['-7 mg is the recorded mass.'])
        self.assertEqual([text for text, _ in claim_pairs('1.2 mg is the recorded mass. [1]')],
                         ['1.2 mg is the recorded mass.'])


class NativeSpanTests(unittest.TestCase):
    def test_exact_native_sentence_survives_semantic_false_negative(self):
        verifier = StudyVerifier()
        with patch.object(verifier, '_support', side_effect=neutral):
            report = verifier.verify('The recorded mass is **7 mg**. [1]',
                [source('# Mass\nThe recorded mass is 7 mg.')])
        self.assertFalse(report.blocking)
        self.assertEqual(report.decision(), 'degraded')
        self.assertEqual(report.support_backend, 'native_text_span')
        self.assertEqual(report.claim_basis[0].verification_kind, 'native_unverified')
        self.assertFalse(report.claim_basis[0].inputs_verified)

    def test_substrings_cannot_drop_negation_or_other_context(self):
        verifier = StudyVerifier()
        examples = [
            ('ORION requires seven samples.', 'It is false that ORION requires seven samples.'),
            ('ORION requires seven samples.', 'ORION requires seven samples only if the gate is open.'),
            ('The recorded mass is 7 mg.', 'The recorded mass is 7 Mg.'),
            ('The recorded mass is 8 mg.', 'The recorded mass is 7 mg.'),
        ]
        for answer, text in examples:
            with self.subTest(answer=answer, text=text), patch.object(verifier, '_support', side_effect=neutral):
                report = verifier.verify(answer + ' [1]', [source(text)])
                self.assertTrue(report.blocking)

    def test_soft_wrapped_qualifiers_cannot_be_removed(self):
        verifier = StudyVerifier()
        with patch.object(verifier, '_support', side_effect=neutral):
            report = verifier.verify('ORION requires seven samples. [1]',
                [source('ORION requires seven samples\nonly if the gate is open.')])
        self.assertTrue(report.blocking)

    def test_source_numeric_sign_and_decimal_must_survive_matching(self):
        verifier = StudyVerifier()
        for answer, text in [('7 mg is the recorded mass.', '-7 mg is the recorded mass.'),
                             ('2 mg is the recorded mass.', '1.2 mg is the recorded mass.')]:
            with self.subTest(text=text), patch.object(verifier, '_support', side_effect=neutral):
                report = verifier.verify(answer + ' [1]', [source(text)])
                self.assertTrue(report.blocking)

    def test_matching_text_in_uncited_source_is_not_support(self):
        verifier = StudyVerifier()
        with patch.object(verifier, '_support', side_effect=neutral):
            report = verifier.verify('The recorded mass is 7 mg. [2]', [
                source('The recorded mass is 7 mg.'), source('A chart lists colours.', chunk='c')])
        self.assertTrue(report.blocking)

    def test_exact_derived_sentence_never_promoted_to_native_support(self):
        for method, expected in [('vlm', 'interpreted'), ('ocr', 'ocr_transcribed'),
                                 ('user_annotation', 'user_annotated')]:
            with self.subTest(method=method):
                report = StudyVerifier(use_entailment=False).verify(
                    'The recorded mass is 7 mg. [1]', [source('The recorded mass is 7 mg.', method)])
                self.assertEqual(report.claim_basis[0].verification_kind, expected)
                self.assertFalse(report.claim_basis[0].inputs_verified)


class SourceAwarePromptTests(unittest.TestCase):
    def test_prose_contract_avoids_uncited_factual_headings_and_preserves_qualifiers(self):
        prompt=self.prompt(['native_text'])
        self.assertIn('uncited headings',prompt.system)
        self.assertIn('may',prompt.system)
    def test_prompt_calculation_format_is_accepted_by_the_real_source_checker(self):
        evidence = [source('The worksheet calculation is 5 * 4.')]
        prompt = build_study_prompt(StudyRouter().route('What total follows?'), evidence, [])
        payload = json.loads(prompt.user)
        self.assertIn('derived_calculation_format', payload)
        answer = payload['derived_calculation_format'].format(
            expression='5 * 4', result='20', citations='[1]')
        report = StudyVerifier(use_entailment=False).verify(answer, evidence)
        self.assertFalse(report.blocking)
        self.assertEqual(report.numerical[0]['expected'], 20)

    def prompt(self, methods):
        return build_study_prompt(StudyRouter().route('What does the record say?'),
            [source('The recorded mass is 7 mg.', method) for method in methods], [])

    def test_native_only_request_does_not_ask_for_visual_or_ocr_disclaimers(self):
        prompt = self.prompt(['native_text'])
        self.assertNotIn('model-described figure', prompt.system)
        self.assertNotIn('OCR', prompt.system)
        self.assertEqual(json.loads(prompt.user)['untrusted_numbered_sources'][0]['provenance'], 'native_text')

    def test_mixed_provenance_keeps_specific_visual_and_ocr_safety_rules(self):
        prompt = self.prompt(['native_text', 'vlm', 'ocr'])
        self.assertIn('model-described figure', prompt.system)
        self.assertIn('OCR', prompt.system)
        self.assertIn('unverified', prompt.system)
        self.assertEqual([item['provenance'] for item in json.loads(prompt.user)['untrusted_numbered_sources']],
                         ['native_text', 'vlm', 'ocr'])


class RepairTests(unittest.TestCase):
    def test_repair_covers_late_rejections_after_multiple_bad_headings(self):
        instructions=study_repair_instructions('',{'claims':[
            {'index':n,'text':f'Rejected item {n}.','support':'unsupported'} for n in range(14)]},[])
        self.assertIn('Rejected item 11.',instructions[0])
        self.assertNotIn('Rejected item 12.',instructions[0])
    def test_repair_identifies_rejected_claims_without_suggesting_new_facts(self):
        answer = 'The drawing has two compartments. [1]\nNorth contains orange tokens. [1]'
        instructions = study_repair_instructions(answer, {'claims': [
            {'index': 0, 'text': 'The drawing has two compartments.', 'support': 'contradictory'},
            {'index': 1, 'text': 'North contains orange tokens.', 'support': 'supported'}]},
            ['Correct the contradicted compartment count.'])
        self.assertIn('North contains orange tokens. [1]', instructions[0])
        self.assertTrue(any('Remove rejected statements' in item and
                            'The drawing has two compartments.' in item for item in instructions))
        self.assertFalse(any('three compartments' in item for item in instructions))

    def test_duplicate_text_does_not_launder_an_unsupported_citation(self):
        text = 'The recorded mass is 7 mg.'
        instructions = study_repair_instructions(text + ' [1]\n' + text + ' [2]',
            {'claims': [{'index': 0, 'text': text, 'support': 'supported'},
                        {'index': 1, 'text': text, 'support': 'unsupported'}]}, ['Fix the second citation.'])
        self.assertIn(text + ' [1]', instructions[0])
        self.assertNotIn('[2]', instructions[0])

    def test_repair_preserves_supported_cited_facts_not_the_uncited_addition(self):
        good = 'The recorded mass is 7 mg. [1]'
        bad = 'Mars is made of cheese.'

        class Model:
            def __init__(self):
                self.prompts = []
            def complete(self, messages):
                self.prompts.append(json.loads(messages[-1]['content']))
                return good + '\n' + bad if len(self.prompts) <= 2 else good

        class Search:
            def search(self, *args, **kwargs):
                return [source('The recorded mass is 7 mg.')]

        model = Model()
        pipeline = AuraBioPipeline(PromptedGenerator(model, prompt_builder=build_study_prompt),
            searcher=Search(), router=StudyRouter(), verifier=StudyVerifier(use_entailment=False),
            accuracy_mode='robust', draft_candidates=2, answer_policy=AnswerPolicy('pack_only', 'b' * 32))
        answer = pipeline.answer('What mass is recorded?', use_critic=False)
        repair = model.prompts[-1]
        self.assertIn(good, repair['repair_instructions'][0])
        self.assertNotIn(bad, repair['repair_instructions'][0])
        self.assertEqual(answer.text, good)
        self.assertEqual(answer.decision, 'degraded')
        self.assertEqual(answer.trace.selected_revision, 2)


if __name__ == '__main__':
    unittest.main()
