"""Optional core visuals consume selected checker findings, not model memory."""
import copy
import json
import unittest
from dataclasses import replace
from aura_bio.tracing import Trace
from visual_output_fixtures import context

FACT = 'ORION activates the VEGA receptor.'


def core_evidence():
    return [replace(context().evidence[0], pack_id='', document_id='', unit_ids=(), text=FACT)]


def core_trace():
    return Trace(final_answer=FACT + ' [1]', decision='accept', selected_revision=0,
        revisions=[{'answer': FACT + ' [1]', 'verification': {
            'support_backend': 'nli', 'checker_status': {}, 'issues': [],
            'claims': [{'index': 0, 'text': FACT, 'support': 'supported', 'score': .95,
                        'certainty': 'established', 'evidence_chunk_ids': ['chunk1']}]}}])


class CoreVisualTests(unittest.TestCase):
    def build(self, trace=None, evidence=None):
        try: from aura_bio.visual_outputs.context import build_core_visual_context
        except ImportError: self.fail('Core checked-claim visual adapter is not implemented')
        return build_core_visual_context(trace or core_trace(), evidence or core_evidence())

    def test_supported_inline_claim_keeps_original_evidence_number_and_native_basis(self):
        ctx = self.build()
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.claims[0].claim, FACT)
        self.assertEqual(ctx.claims[0].cite_ids, (1,))
        self.assertEqual(ctx.basis_by_id[ctx.claims[0].id]['verification_kind'], 'native_verified')

    def test_lexical_disabled_and_unavailable_checkers_cannot_certify_core_visuals(self):
        for backend in ('lexical', 'disabled'):
            trace = core_trace(); trace.revisions[0]['verification']['support_backend'] = backend
            self.assertIsNone(self.build(trace))
        trace = core_trace(); trace.revisions[0]['verification']['checker_status']['nli'] = 'unavailable: MemoryPressureError'
        self.assertIsNone(self.build(trace))

    def test_unverified_contradicted_uncited_and_wrongly_cited_facts_are_excluded(self):
        for support in ('unsupported', 'partially_supported', 'contradictory', 'unverifiable'):
            trace = core_trace(); trace.revisions[0]['verification']['claims'][0]['support'] = support
            self.assertIsNone(self.build(trace))
        for answer in (FACT, FACT + ' [2]'):
            trace = core_trace(); trace.final_answer = trace.revisions[0]['answer'] = answer
            self.assertIsNone(self.build(trace))
        evidence = core_evidence(); evidence[0] = replace(evidence[0], chunk_id='unrelated')
        self.assertIsNone(self.build(evidence=evidence))

    def test_stale_report_refusal_and_older_candidate_cannot_supply_visual_claims(self):
        trace = core_trace(); trace.final_answer = 'Insufficient support.'
        self.assertIsNone(self.build(trace))
        trace = core_trace(); trace.decision = 'insufficient_evidence'
        self.assertIsNone(self.build(trace))
        trace = core_trace(); rejected = copy.deepcopy(trace.revisions[0])
        rejected['verification']['claims'][0]['support'] = 'unsupported'
        trace.revisions.append(rejected); trace.selected_revision = 1
        self.assertIsNone(self.build(trace))

    def test_non_native_provenance_is_not_promoted_by_a_core_nli_label(self):
        for method in ('vlm', 'ocr', 'user_annotation'):
            self.assertIsNone(self.build(evidence=[replace(core_evidence()[0], provenance=method)]))

    def test_core_auto_is_optional_and_preserves_text_in_standard_and_robust_modes(self):
        from aura_bio.pipeline import AuraBioPipeline
        from aura_bio.api.mapping import answer_payload
        from aura_bio.study.routing import StudyRouter
        from aura_bio.verification.schema import Claim, Support, Certainty, VerificationReport
        class Generator:
            model_name = 'fixture'; last_metadata = {}
            def __init__(self): self.visual_calls = 0
            def generate(self, *args, **kwargs): return FACT + ' [1]'
            def propose_visual(self, *args):
                self.visual_calls += 1
                return json.dumps({'selected_kind': 'diagram', 'reason': 'relationships', 'source_id': None,
                    'visual': {'version': 1, 'id': 'core-diagram', 'kind': 'diagram', 'title': 'Test', 'description': '',
                        'payload': {'nodes': [{'id': 'a', 'label': 'ORION', 'claim_ids': ['core-c0']},
                                             {'id': 'b', 'label': 'the VEGA receptor', 'claim_ids': ['core-c0']}],
                                    'edges': [{'from_id': 'a', 'to_id': 'b', 'relation': 'activates',
                                               'label': 'activates', 'claim_ids': ['core-c0']}]}}})
        class Searcher:
            def search(self, *args, **kwargs): return core_evidence()
        class Verifier:
            def verify(self, *args, **kwargs):
                return VerificationReport(claims=[Claim(0, FACT, Support.SUPPORTED, Certainty.ESTABLISHED,
                    .95, ('chunk1',))], grounded_fraction=1, citation_coverage=1, support_backend='nli')
        for mode in ('standard', 'robust'):
            with self.subTest(mode=mode):
                generator = Generator()
                pipeline = AuraBioPipeline(generator, searcher=Searcher(), router=StudyRouter(),
                    verifier=Verifier(), accuracy_mode=mode, draft_candidates=1)
                before = answer_payload(pipeline.answer('How does ORION act?', use_critic=False), 'fixture')
                self.assertEqual(generator.visual_calls, 0)
                answer = pipeline.answer('How does ORION act?', use_critic=False, visual_output='auto')
                after = answer_payload(answer, 'fixture')
                self.assertEqual(after.get('visuals', [{}])[0].get('status'), 'ready')
                from aura_bio.visual_outputs.schema import _validate, public_visual_schema
                try: _validate(json.loads(json.dumps(after['visuals'][0]['spec'])), public_visual_schema('diagram'))
                except ValueError: self.fail('Core source identities violate the public visual response schema')
                self.assertEqual(after['visuals'][0]['metadata']['source_refs'][0]['chunk_id'], 'chunk1')
                self.assertEqual(generator.visual_calls, 1)
                for key in ('markdown', 'confidence', 'verification_status', 'citations'):
                    self.assertEqual(after[key], before[key])
                self.assertNotIn('delivery', answer.trace.final_record)


if __name__ == '__main__': unittest.main()
