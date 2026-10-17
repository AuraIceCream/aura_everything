import io
import json
from pathlib import Path
from dataclasses import replace
import tempfile
import time
import unittest
from types import SimpleNamespace
from aura_bio.study.schema import Asset, Extraction, Locator, Unit
from aura_bio.study.storage import StudyStore
from aura_bio.study.claims import StructuredClaim, ClaimDraft, ClaimBlock
from aura_bio.study.searcher import StudyEvidence


class SourceVisualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StudyStore(Path(self.tmp.name) / 'packs')
        self.pack = self.store.create_pack('Source trial',retention='temporary',expires_at=time.time()+60)
        self.doc, _ = self.store.add_document(self.pack.pack_id, 'lesson.txt', io.BytesIO(b'ORION activates VEGA.'))
        from PIL import Image
        stream=io.BytesIO(); Image.new('RGB', (40, 60), 'white').save(stream, format='PNG')
        self.unit = Unit('d'*32, self.doc.document_id, 0, 'body', 'Lesson', '', 'ORION activates VEGA.',
                         (Locator('image'),), asset_ids=('e'*32,),
                         provenance_details={'bbox': {'x0': .1, 'y0': .2, 'x1': .8, 'y1': .9}})
        self.store.publish_extraction(self.doc.document_id, Extraction([self.unit],
            [Asset('e'*32, self.unit.unit_id, 'image/png', stream.getvalue(), {'width': 40, 'height': 60})], [], {}, 'fixture'))

    def tearDown(self): self.store.close(); self.tmp.cleanup()

    def resolve(self, question='', extra_evidence=(), **changes):
        try:
            from aura_bio.visual_outputs.context import build_visual_context
            from aura_bio.visual_outputs.schema import parse_visual
            from aura_bio.visual_outputs.source import resolve_source_visual
        except ImportError: self.fail('Owned source visual resolution is not implemented')
        claim = StructuredClaim('c1', 'ORION activates VEGA.', (1,))
        draft = ClaimDraft(1, (claim,), (ClaimBlock('claim', ref='c1'),))
        delivery = SimpleNamespace(delivered_ids=['c1'], verification={'claim_basis': [
            {'verification_kind': 'native_verified', 'supporting_provenance': []}]})
        evidence = StudyEvidence('chunk1','doc','Lesson',None,self.unit.text,None,None,'pack_sparse',1.,
            pack_id=self.pack.pack_id, document_id=self.doc.document_id, unit_ids=(self.unit.unit_id,), generation=1)
        ctx=build_visual_context(draft,delivery,[evidence,*extra_evidence])
        payload={'claim_ids':['c1'],'pack_id':self.pack.pack_id,'document_id':self.doc.document_id,
                 'unit_id':self.unit.unit_id,'asset_id':None,'bbox':None,**changes}
        try:
            spec=parse_visual(json.dumps({'version':1,'id':'source','kind':'source','title':'Source',
                                         'description':'', 'payload':payload}),ctx)
        except ValueError:
            return SimpleNamespace(status='omitted')
        return resolve_source_visual(spec,ctx,self.store,None,question=question)

    def test_focused_source_highlight_is_question_bound_not_model_bbox(self):
        from dataclasses import asdict
        from aura_bio.study.visual.schema import digest
        from aura_bio.study.attachments import question_hash
        asset_hash=self.store.asset(self.pack.pack_id,self.doc.document_id,'e'*32)['checksum']
        question='Where is Plant A from?'
        region={'id':'r1','figure_id':'f'*32,'bbox':{'x0':.1,'y0':.2,'x1':.8,'y1':.6},
                'frame':'asset_normalized','context_refs':['header'],'source_hash':asset_hash,
                'question_hash':digest(question),'precision':'table_row'}
        self.unit=replace(self.unit,provenance_details={**self.unit.provenance_details,
            'question_hash':question_hash(question),'focus_regions':[region]})
        with self.store.db(self.pack.pack_id) as db:
            db.execute('UPDATE units SET payload=? WHERE unit_id=?',(json.dumps(asdict(self.unit)),self.unit.unit_id))
        result=self.resolve(question=question)
        self.assertEqual(result.status,'ready')
        self.assertEqual(result.spec.version,2)
        self.assertEqual(result.spec.payload['highlight_precision'],'table_row')
        self.assertEqual(result.spec.payload['highlights'][0]['bbox']['y1'],.6)
        self.assertEqual(self.resolve(question='Explain a different image').status,'omitted')

    def test_native_caption_can_show_frozen_question_focus_without_certifying_pixels(self):
        import uuid
        from aura_bio.study.visual.storage import VisualStore
        from aura_bio.study.visual.schema import digest
        from aura_bio.study.attachments import question_hash
        visual=VisualStore(self.store,self.pack.pack_id);figure=visual.figures(self.doc.document_id)[0]
        question='Inspect the row in this source.'
        region={'id':'row1','figure_id':figure.figure_id,'bbox':{'x0':.1,'y0':.2,'x1':.8,'y1':.6},
            'frame':figure.frame,'context_refs':[],'source_hash':figure.checksum,'question_hash':digest(question),'precision':'table_row'}
        revision=replace(self.unit,unit_id=uuid.uuid4().hex,provenance='vlm',text='A model interpretation, not verification.',
            provenance_details={'source_unit_id':self.unit.unit_id,'figure_id':figure.figure_id,
                'question_hash':question_hash(question),'focus_regions':[region]})
        uid=visual.publish_revision(revision,expected_source_hash=figure.checksum)
        evidence=StudyEvidence('figure-chunk','figure','Figure',None,revision.text,None,None,'pack_sparse',1.,
            pack_id=self.pack.pack_id,document_id=self.doc.document_id,unit_ids=(uid,),generation=1,provenance='vlm')
        result=self.resolve(question=question,extra_evidence=(evidence,))
        self.assertEqual(result.status,'ready')
        self.assertEqual(result.spec.version,2)
        self.assertEqual(result.spec.payload['highlight_precision'],'table_row')
        self.assertEqual(result.spec.payload['support']['provenance'],['native_text'])
        # A later active revision outside the frozen answer evidence is ignored.
        self.assertEqual(self.resolve(question=question).spec.version,1)

    def test_source_uses_immutable_owned_asset_and_upright_region(self):
        result=self.resolve()
        self.assertEqual(result.status,'ready')
        self.assertEqual(result.spec.payload['bbox'], {'x0':.1,'y0':.2,'x1':.8,'y1':.9})
        self.assertEqual(result.spec.payload['revision_id'],self.unit.unit_id)
        self.assertEqual(result.spec.payload['asset_id'],'e'*32)
        self.assertEqual(result.spec.payload['coordinates'],'upright_normalized')

    def test_foreign_asset_or_invented_bbox_is_not_substituted(self):
        for changes in ({'asset_id':'f'*32}, {'pack_id':'f'*32},
                        {'bbox':{'x0':.3,'y0':.4,'x1':.5,'y1':.6}}):
            self.assertEqual(self.resolve(**changes).status,'omitted')

    def test_expired_attachment_source_is_unavailable(self):
        self.store.clock=lambda:self.pack.expires_at+1
        self.assertEqual(self.resolve().status,'omitted')

    def test_rotated_render_does_not_double_transform_an_upright_region(self):
        from aura_bio.study.visual.schema import SourceTransform
        from dataclasses import asdict
        transform=SourceTransform(60,40,40,60,90)
        # Original rectangle (12,8)-(54,36) rotates to (.1,.2)-(.8,.9).
        self.unit=replace(self.unit,provenance_details={**self.unit.provenance_details,'source_transform':asdict(transform)})
        with self.store.db(self.pack.pack_id) as db:
            db.execute('UPDATE units SET payload=? WHERE unit_id=?',(json.dumps(asdict(self.unit)),self.unit.unit_id))
        result=self.resolve()
        self.assertEqual(result.spec.payload['bbox'],{'x0':.1,'y0':.2,'x1':.8,'y1':.9})

    def test_page_without_region_does_not_claim_precise_highlight(self):
        self.unit=replace(self.unit, provenance_details={})
        self.store.publish_extraction(self.doc.document_id,Extraction([self.unit],[],[],{},'fixture'))
        # Asset-less text units remain usable and explicitly do not claim pixels.
        self.unit=replace(self.unit,asset_ids=())
        self.store.publish_extraction(self.doc.document_id,Extraction([self.unit],[],[],{},'fixture'))
        result=self.resolve()
        self.assertEqual(result.status,'ready')
        self.assertIsNone(result.spec.payload['bbox'])
        self.assertEqual(result.spec.payload['highlight_precision'],'unit_only')

    def test_deactivated_or_purged_source_fails_visibly(self):
        self.store.update_document(replace(self.store.document(self.pack.pack_id,self.doc.document_id),active=False))
        self.assertEqual(self.resolve().status,'omitted')
        self.store.purge(self.pack.pack_id, self.doc.document_id, confirmation=self.doc.document_id)
        self.assertEqual(self.resolve().status,'omitted')


if __name__ == '__main__': unittest.main()
