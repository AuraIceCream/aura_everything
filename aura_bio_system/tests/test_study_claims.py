"""Structured claim parsing and direct verification contracts."""
import json
import unittest
from unittest.mock import patch

from aura_bio.study.verification import StudyVerifier
from aura_bio.study.searcher import StudyEvidence
from aura_bio.study.routing import StudyRouter


def document(claim='ORION is the calibration label.', **changes):
    value = {'version': 1, 'claims': [{'id': 'c1', 'claim': claim, 'cite_ids': [1], 'depends_on': []}],
             'blocks': [{'type': 'claim', 'ref': 'c1'}, {'type': 'teaching', 'template': 'reflect', 'after': 'c1'}]}
    value.update(changes)
    return value


def evidence(text, method='native_text'):
    return StudyEvidence('chunk1', 'doc', 'Lesson', None, text, None, None, 'pack_sparse', 1.0,
                         pack_id='a' * 32, document_id='b' * 32, provenance=method)


class StudyClaimsTests(unittest.TestCase):
    def test_claim_prompt_keeps_numbered_sources_and_closed_teaching_templates(self):
        from aura_bio.study.claim_generation import build_claim_prompt
        prompt = build_claim_prompt(StudyRouter().route('What is ORION?'),
                                    [evidence('ORION is the calibration label.')], ())
        self.assertIn('ORION is the calibration label.', prompt.user)
        self.assertIn('"citation": 1', prompt.user)
        self.assertIn('fixed non-factual teaching prompts', prompt.system)
        self.assertNotIn('free-form teaching', prompt.system)

    def test_generation_budget_is_shorter_than_parser_safety_cap(self):
        from aura_bio.study.claim_generation import build_claim_prompt
        from aura_bio.study.claims import claim_schema, MAX_CLAIMS
        prompt = build_claim_prompt(StudyRouter().route('What is ORION?'), [evidence('ORION is the calibration label.')])
        schema = claim_schema()
        self.assertLess(schema['properties']['claims']['maxItems'], MAX_CLAIMS)
        self.assertLessEqual(schema['properties']['claims']['items']['properties']['claim']['maxLength'], 400)
        self.assertIn('no more than six', prompt.system.lower())

    def test_model_schema_only_requests_claims_and_local_renderer_orders_blocks(self):
        from aura_bio.study.claims import claim_schema
        schema = claim_schema()
        self.assertEqual(schema['required'], ['version', 'claims'])
        self.assertNotIn('blocks', schema['properties'])
        from aura_bio.study.claims import parse_claims
        value = document()
        del value['blocks']
        draft = parse_claims(json.dumps(value), 1)
        self.assertEqual([(block.type, block.ref) for block in draft.blocks], [('claim', 'c1')])

    def test_model_schema_assigns_claim_ids_locally(self):
        from aura_bio.study.claims import claim_schema, parse_claims
        schema = claim_schema()
        claim = schema['properties']['claims']['items']
        self.assertEqual(claim['required'], ['claim', 'cite_ids'])
        self.assertNotIn('id', claim['properties'])
        self.assertNotIn('depends_on', claim['properties'])
        draft = parse_claims(json.dumps({'version': 1, 'claims': [
            {'claim': 'First fact.', 'cite_ids': [1]},
            {'claim': 'Second fact.', 'cite_ids': [2]},
        ]}), 2)
        self.assertEqual([item.id for item in draft.claims], ['c1', 'c2'])
        self.assertEqual([block.ref for block in draft.blocks], ['c1', 'c2'])

    def parser(self):
        try:
            from aura_bio.study.claims import parse_claims
        except ImportError:
            self.fail('Structured study claims have not been implemented')
        return parse_claims

    def test_local_schema_rejects_bad_citations_and_duplicate_ids(self):
        parse = self.parser()
        for value in (document(claims=[{'id':'c1', 'claim':'ORION.', 'cite_ids':[2], 'depends_on':[]}]),
                      document(claims=document()['claims'] * 2)):
            with self.assertRaises(ValueError):
                parse(json.dumps(value), 1)

    def test_dependency_must_reference_an_earlier_claim(self):
        parse = self.parser()
        value = document()
        value['claims'][0]['depends_on'] = ['c2']
        with self.assertRaises(ValueError):
            parse(json.dumps(value), 1)

    def test_teaching_cannot_smuggle_a_fact_without_new_names_or_numbers(self):
        parse = self.parser()
        value = document()
        value['blocks'][1] = {'type': 'teaching', 'text': 'It always prevents cancer.'}
        with self.assertRaises(ValueError):
            parse(json.dumps(value), 1)

    def test_duplicate_json_fields_and_model_status_are_rejected(self):
        parse = self.parser()
        with self.assertRaises(ValueError):
            parse('{"version":1,"version":1,"claims":[],"blocks":[]}', 0)
        value = document()
        value['claims'][0]['status'] = 'verified'
        with self.assertRaises(ValueError):
            parse(json.dumps(value), 1)

    def test_claims_are_verified_without_markdown_segmentation(self):
        parse = self.parser()
        draft = parse(json.dumps(document('ORION is the calibration label. It is used before sealing.')), 1)
        verifier = StudyVerifier(use_entailment=False)
        self.assertTrue(callable(getattr(verifier, 'verify_claims', None)), 'Direct claim verification is absent')
        report = verifier.verify_claims(draft.claims,
            [evidence('ORION is the calibration label. It is used before sealing.')], StudyRouter().route('ORION?'), 'ORION?')
        self.assertEqual(len(report.claims), 1)
        self.assertEqual(report.claims[0].text, 'ORION is the calibration label. It is used before sealing.')

    def test_figure_claim_never_becomes_native_verified(self):
        parse = self.parser()
        draft = parse(json.dumps(document('ORION is the calibration label.')), 1)
        verifier = StudyVerifier(use_entailment=False)
        self.assertTrue(callable(getattr(verifier, 'verify_claims', None)), 'Direct claim verification is absent')
        report = verifier.verify_claims(draft.claims, [evidence('ORION is the calibration label.', 'vlm')],
                                        StudyRouter().route('ORION?'), 'ORION?')
        self.assertNotEqual(report.claim_basis[0].verification_kind, 'native_verified')
        self.assertFalse(report.claim_basis[0].inputs_verified)

    def test_ollama_receives_schema_not_only_json_mode(self):
        from aura_bio.api.generation import OllamaGenerator
        import inspect
        self.assertIn('response_schema', inspect.signature(OllamaGenerator).parameters,
                      'Ollama claim generation cannot request schema-constrained decoding')
        captured = []
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({'message': {'content': json.dumps(document())}, 'done_reason': 'stop'}).encode()
        def transport(request, **kwargs):
            captured.append(json.loads(request.data))
            return Response()
        schema = {'type': 'object', 'properties': {'claims': {'type': 'array'}}}
        generator = OllamaGenerator(response_schema=schema, retries=0)
        with patch('urllib.request.urlopen', transport):
            generator.generate(StudyRouter().route('ORION?'), [evidence('ORION is the calibration label.')], [])
        self.assertEqual(captured[0]['format'], schema)


if __name__ == '__main__':
    unittest.main()
