"""Cross-page support must bind to every cited native source, never to pixels."""
import unittest
from unittest.mock import patch

from aura_bio.study.claims import StructuredClaim
from aura_bio.study.verification import StudyVerifier
from aura_bio.verification.schema import Claim, Certainty, Support
from test_study_pipeline import hit
from dataclasses import replace


class JointSupportTests(unittest.TestCase):
    def sources(self):
        return [hit(1, 'The proposed follow-up uses ORION profiling to test for the'),
                hit(2, 'presence of expanded VEGA clonotypes engaging in cell killing.')]

    def check(self, sources, contradiction=False):
        claim = StructuredClaim('c1', 'The proposed follow-up uses ORION profiling to test for expanded VEGA clonotypes engaging in cell killing.', (1, 2))
        seen = []
        def support(claims, passages, report):
            seen.append(passages)
            report.support_backend = 'nli'
            joined = next((p for p in passages if 'ORION' in p.text and 'VEGA' in p.text), None)
            verdict = Support.CONTRADICTORY if contradiction else Support.SUPPORTED if joined else Support.UNSUPPORTED
            return [Claim(0, claims[0], verdict, Certainty.ESTABLISHED,
                          .95 if joined else .1, (joined.chunk_id,) if joined else ())]
        with patch.object(StudyVerifier, '_support', side_effect=support):
            report = StudyVerifier().verify_claims([claim], sources)
        return report, seen

    def test_joint_native_support_maps_back_to_both_original_chunks(self):
        sources = self.sources()
        report, seen = self.check(sources)
        self.assertEqual(report.claims[0].support, Support.SUPPORTED)
        self.assertEqual(set(report.claims[0].evidence_chunk_ids), {p.chunk_id for p in sources})
        self.assertEqual({p['chunk_id'] for p in report.claim_basis[0].supporting_provenance},
                         {p.chunk_id for p in sources})
        self.assertEqual(report.claim_basis[0].verification_kind, 'native_verified')
        self.assertEqual(len(seen), 2)

    def test_joint_never_certifies_a_mixed_vlm_native_pair(self):
        sources = self.sources()
        sources[1] = replace(sources[1], provenance='vlm')
        report, seen = self.check(sources)
        self.assertNotEqual(report.claim_basis[0].verification_kind, 'native_verified')
        self.assertEqual(len(seen), 1)

    def test_individual_contradiction_remains_blocking_without_joint_retry(self):
        report, seen = self.check(self.sources(), contradiction=True)
        self.assertEqual(report.claims[0].support, Support.CONTRADICTORY)
        self.assertEqual(len(seen), 1)

    def test_different_document_fragments_are_not_stitched(self):
        sources = self.sources()
        sources[1] = replace(sources[1], document_id='other-document')
        report, seen = self.check(sources)
        self.assertNotEqual(report.claims[0].support, Support.SUPPORTED)
        self.assertEqual(len(seen), 1)


if __name__ == '__main__':
    unittest.main()
