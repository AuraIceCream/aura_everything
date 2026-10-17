"""Regressions from the October document-question review."""
import unittest
from unittest.mock import patch

from aura_bio.study.claims import ClaimBlock, ClaimDraft, StructuredClaim
from aura_bio.study.claim_delivery import deliver_claims
from aura_bio.study.searcher import StudyEvidence
from aura_bio.study.verification import StudyVerifier
from aura_bio.verification.schema import Claim, Certainty, Support
from aura_bio.api.mapping import answer_payload
from aura_bio.pipeline import Answer
from aura_bio.tracing import Trace
from aura_bio.study.claim_generation import build_claim_prompt
from aura_bio.study.routing import StudyRouter


def passage(text, number=1):
    return StudyEvidence(f'{number:032x}', 'source', 'Lesson', None, text, None,
                         None, 'pack_sparse', 1, pack_id='a' * 32)


class StudyGroundingRegressions(unittest.TestCase):
    def test_table_crossreferences_do_not_distract_numeric_entailment(self):
        from aura_bio.study.verification import _verification_windows
        evidence = passage('There were 33 species in Group I (Table 1), 38 plants in Group II '
                           'and 104 plants in Group III (Table 2).')
        windows = _verification_windows('Group I had 33 species and Group II had 38 plants.', [evidence])
        self.assertNotIn('(Table 1)', windows[0].text)
        self.assertIn('(Table 1)', evidence.text)

    def test_table_identity_claim_retains_table_crossreference(self):
        from aura_bio.study.verification import _verification_windows
        windows = _verification_windows('The counts are in Table 2.',
            [passage('There were 104 plants in Group III (Table 2).')])
        self.assertIn('Table 2', windows[0].text)

    def test_count_window_does_not_require_unrelated_numeric_sentences(self):
        from aura_bio.study.verification import _verification_windows
        evidence = passage('There were 33 species in Group I, 38 plants in Group II and 104 plants in Group III. '
                           'Of the 33 species, 12 were Asteraceae and 4 were Poaceae. '
                           'The analysis used 8 controls.')
        windows = _verification_windows('Group I contained 33 species, Group II contained 38 species, '
                                        'and Group III contained 104 species.', [evidence])
        self.assertIn('38 plants', windows[0].text)
        self.assertNotIn('12 were Asteraceae', windows[0].text)

    def test_late_numeric_fact_reaches_semantic_checker_in_short_cited_window(self):
        lead = 'Unrelated background and citations. ' * 90
        fact = ('After 12–15 population doublings, the entire culture of blind mole rat '
                'cells dies within 3–4 days via necrotic and apoptotic processes.')
        seen = []

        def checking(claims, evidence, report):
            seen.extend(evidence)
            report.support_backend = 'nli'
            return [Claim(0, claims[0], Support.SUPPORTED, Certainty.ESTABLISHED, .99,
                          (evidence[0].chunk_id,))]

        verifier = StudyVerifier()
        with patch.object(verifier, '_support', side_effect=checking):
            result = verifier.verify(fact + ' [1]', [passage(lead + fact)])
        self.assertEqual(result.claim_basis[0].verification_kind, 'native_verified')
        self.assertTrue(seen)
        self.assertTrue(all(len(item.text) <= 900 for item in seen))
        self.assertIn('12–15 population doublings', ' '.join(item.text for item in seen))
        self.assertEqual({item.chunk_id for item in seen}, {f'{1:032x}'})

    def test_late_fact_survives_an_unpunctuated_extraction(self):
        from aura_bio.study.verification import _verification_windows
        text = ('background text without reliable sentence boundaries ' * 55 +
                'the blind mole rat culture dies after 12–15 doublings over 3–4 days')
        windows = _verification_windows('blind mole rat 12–15 doublings 3–4 days',
                                        [passage(text)])
        self.assertTrue(windows)
        self.assertTrue(all(len(item.text) <= 800 for item in windows))
        self.assertTrue(any('12–15 doublings' in item.text for item in windows))

    def test_explicit_via_activation_direction_cannot_be_reversed(self):
        text = ('HMM-HA interacts with CD44 and triggers early contact inhibition (ECI) '
                'via activation of p16INK4A or pALT. ECI prevents hyperplasia.')
        verifier = StudyVerifier(use_entailment=False)
        wrong = StructuredClaim('c1', 'ECI activates p16INK4A.', (1,))
        with patch.object(verifier, '_support', return_value=[
                Claim(0, wrong.claim, Support.SUPPORTED, Certainty.ESTABLISHED, .99)]):
            report = verifier.verify_claims((wrong,), [passage(text)])
        draft = ClaimDraft(1, (wrong,), (ClaimBlock('claim', ref='c1'),))
        delivered = deliver_claims(draft, report)
        self.assertNotIn('ECI activates', delivered.text)
        self.assertEqual(delivered.delivered_ids, [])

    def test_correct_direction_is_not_blocked_by_guard(self):
        text = ('HMM-HA triggers early contact inhibition (ECI) via activation of p16INK4A.')
        claim = StructuredClaim('c1', 'p16INK4A activation triggers ECI.', (1,))
        verifier = StudyVerifier(use_entailment=False)
        with patch.object(verifier, '_support', return_value=[
                Claim(0, claim.claim, Support.SUPPORTED, Certainty.ESTABLISHED, .99)]):
            report = verifier.verify_claims((claim,), [passage(text)])
        self.assertFalse(any(issue.kind == 'reversed_causal_direction' for issue in report.issues))

    def test_semantic_checker_sees_cited_paraphrase_below_lexical_gate(self):
        verifier = StudyVerifier()
        text = 'Water must be added before the powder can be stirred.'
        claim = 'The procedure starts by introducing liquid.'
        seen = []

        def checking(claims, evidence, report):
            seen.extend(evidence)
            report.support_backend = 'nli'
            return [Claim(0, claims[0], Support.SUPPORTED, Certainty.ESTABLISHED,
                          .95, (evidence[0].chunk_id,))]

        with patch.object(verifier, '_support', side_effect=checking):
            result = verifier.verify(claim + ' [1]', [passage(text)])
        self.assertTrue(seen)
        self.assertEqual(result.claim_basis[0].supporting_provenance[0]['chunk_id'], f'{1:032x}')
        self.assertEqual(result.claim_basis[0].verification_kind, 'native_verified')

    def test_answer_payload_shows_only_citations_in_delivered_claims(self):
        trace = Trace(evidence=[{'chunk_id': f'{n:032x}', 'text': f'Source {n}',
                                 'source_id': 'source', 'title': 'Lesson'} for n in range(1, 4)],
                      revisions=[{'verification': {}, 'delivery': {
                          'status': 'partial', 'delivered_ids': ['c1'],
                          'delivered_cite_ids': [2], 'omitted': [{'id': 'c2'}]}}])
        answer = Answer('Supported fact. [2]', 'partial', .5, trace)
        citations = answer_payload(answer, 'fixture')['citations']
        self.assertEqual([item['citation_id'] for item in citations], ['cit-2'])
        self.assertEqual([item['chunk_id'] for item in citations], [f'{2:032x}'])

    def test_claim_prompt_asks_for_qualification_in_the_substantive_claim(self):
        prompt = build_claim_prompt(StudyRouter().route('What may HMM-HA do?'),
                                    [passage('HMM-HA may protect against metastasis.')])
        self.assertIn('Do not add a separate claim merely explaining that another claim is qualified',
                      prompt.system)
