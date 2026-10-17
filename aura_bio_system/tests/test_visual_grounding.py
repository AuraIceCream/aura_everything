import unittest
import io
import tempfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from aura_bio.study.schema import Unit,Locator
from aura_bio.study.chunking import chunk_units
from aura_bio.study.searcher import StudyEvidence
from aura_bio.study.verification import StudyVerifier
from aura_bio.verification.schema import Claim,Support,Certainty
from aura_bio.api.mapping import evidence_to_citation


def passage(method='vlm',text='A activates B in the pathway.'):
    return StudyEvidence('a'*32,'study:pack','Diagram',None,text,None,None,'pack_sparse',1,
                         pack_id='b'*32,document_id='c'*32,unit_ids=('d'*32,),locators=(Locator('pdf',page=2),),provenance=method)


class VisualGroundingTests(unittest.TestCase):
    def test_full_pipeline_preserves_derived_provenance_at_verifier_boundary(self):
        from aura_bio.pipeline import AuraBioPipeline,AnswerPolicy
        from aura_bio.study.routing import StudyRouter
        for mode in ('standard','robust'):
            for method in ('vlm','ocr'):
                hit=passage(method,'The worksheet asks for 7 * 3.')
                class Search:
                    def search(self,*args,**kwargs):return [hit]
                class Generator:
                    def generate(self,*args,**kwargs):return 'Derived: 7 * 3 = 21 [1]'
                pipeline=AuraBioPipeline(Generator(),Search(),router=StudyRouter(),verifier=StudyVerifier(use_entailment=False),accuracy_mode=mode,draft_candidates=1,answer_policy=AnswerPolicy('pack_only',hit.pack_id))
                result=pipeline.answer('Calculate the worksheet expression',context_level=2,use_critic=False)
                report=result.trace.final_verification
                self.assertFalse(report['numerical'][0]['inputs_verified'])
                self.assertTrue(report['numerical'][0]['conditional'])
                basis=report['claim_basis'][0]
                self.assertIn(basis['verification_kind'],{'interpreted','ocr_transcribed'})
                self.assertEqual(basis['supporting_provenance'][0]['pack_id'],hit.pack_id)

    def test_provenance_survives_real_index_search_roundtrip(self):
        from aura_bio.study.storage import StudyStore
        from aura_bio.study.indexing import StudyIndexer
        from aura_bio.study.searcher import StudySearcher
        from aura_bio.study.schema import Extraction
        with tempfile.TemporaryDirectory() as tmp:
            store=StudyStore(Path(tmp)/'packs'); pack=store.create_pack('Course')
            doc,_=store.add_document(pack.pack_id,'lesson.txt',io.BytesIO(b'Notes'))
            base=Unit('a'*32,doc.document_id,0,'body','Title','','Calibration sample',(Locator('pdf',page=1),))
            units=[replace(base,unit_id=f'{n:032x}',provenance=method,text=f'Calibration sample method {method}') for n,method in enumerate(('native_text','ocr','vlm','user_annotation'))]
            store.publish_extraction(doc.document_id,Extraction(units,[],[],{},'fixture'))
            StudyIndexer(store).build(pack.pack_id)
            with StudySearcher(store,pack.pack_id) as searcher:
                hits=searcher.search('Calibration sample',10,10)
                self.assertEqual({h.provenance for h in hits},{'native_text','ocr','vlm','user_annotation'})

    def test_chunks_do_not_merge_methods(self):
        base=Unit('a'*32,'b'*32,0,'body','T','','same text',(Locator('pdf',page=1),))
        chunks=chunk_units([base,replace(base,unit_id='c'*32,provenance='ocr')])
        self.assertEqual(len(chunks),2)
        self.assertEqual([c.provenance for c in chunks],['native_text','ocr'])
        self.assertEqual(chunks[1].spans[0]['provenance'],'ocr')

    def test_provenance_survives_citation(self):
        citation=evidence_to_citation(passage(),1)
        self.assertEqual(citation['provenance'],'vlm')

    def test_vlm_passage_never_verifies_itself(self):
        verifier=StudyVerifier()
        with patch.object(verifier,'_support',side_effect=AssertionError('NLI self-verification')):
            report=verifier.verify('A activates B in the pathway. [1]',[passage()])
        self.assertEqual(report.claims[0].support,Support.UNVERIFIABLE)
        self.assertEqual(report.decision(),'degraded')
        self.assertEqual(report.grounded_fraction,0)
        self.assertEqual(report.claim_basis[0].verification_kind,'interpreted')

    def test_unrelated_native_passage_does_not_launder_figure_claim(self):
        report=StudyVerifier(use_entailment=False).verify('A activates B in the pathway. [1][2]',[passage(),passage('native_text','A book discusses ocean tides and wind.')])
        self.assertEqual(report.claims[0].support,Support.UNVERIFIABLE)
        self.assertEqual(report.claim_basis[0].verification_kind,'interpreted')

    def test_independent_native_support_can_verify(self):
        verifier=StudyVerifier()
        def nli(claims,evidence,report):
            self.assertTrue(all(e.provenance=='native_text' for e in evidence)); report.support_backend='nli'
            return [Claim(0,claims[0],Support.SUPPORTED,Certainty.ESTABLISHED,1,('a'*32,))]
        with patch.object(verifier,'_support',side_effect=nli):
            report=verifier.verify('A activates B in the pathway. [1][2]',[passage(),passage('native_text')])
        self.assertEqual(report.claim_basis[0].verification_kind,'native_verified')

    def test_ocr_number_not_certified_and_gene_label_not_measurement(self):
        report=StudyVerifier(use_entailment=False).verify('IL6 has a printed value of 7 units. [1]',[passage('ocr','IL6 has a printed value of 7 units.')])
        self.assertEqual(report.claim_basis[0].verification_kind,'ocr_transcribed')
        self.assertFalse(report.claim_basis[0].inputs_verified)
        self.assertNotIn('6',report.claims[0].numeric_tokens)

    def test_calculation_preserves_unverified_inputs(self):
        report=StudyVerifier(use_entailment=False).verify('Derived: 7 * 3 = 21 [1]',[passage('ocr','The worksheet asks for 7 * 3.')])
        self.assertEqual(report.numerical[0]['verdict'],'correct')
        self.assertFalse(report.numerical[0]['inputs_verified'])
        self.assertEqual(report.claims[0].support,Support.UNVERIFIABLE)

    def test_question_inputs_not_certified_by_unrelated_native_citation(self):
        report=StudyVerifier(use_entailment=False).verify('Derived: 7 * 3 = 21 [1]',
            [passage('native_text','The chapter describes arithmetic.')],question='Calculate 7 * 3')
        self.assertFalse(report.numerical[0]['inputs_verified'])
        self.assertTrue(report.numerical[0]['conditional'])
        self.assertEqual(report.claims[0].support,Support.UNVERIFIABLE)

    def test_native_lexical_fallback_and_user_edit_not_certified(self):
        for method,kind in [('native_text','native_unverified'),('user_annotation','user_annotated')]:
            report=StudyVerifier(use_entailment=False).verify('A activates B in the pathway. [1]',[passage(method)])
            self.assertEqual(report.claim_basis[0].verification_kind,kind)
            self.assertEqual(report.decision(),'degraded')
