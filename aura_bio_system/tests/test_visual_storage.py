import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from PIL import Image
from aura_bio.study.storage import StudyStore
from aura_bio.study.extractors import extract_document
from aura_bio.study.schema import Unit,StudyError
from aura_bio.study.visual.storage import VisualStore


class VisualStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=StudyStore(Path(self.tmp.name)/'packs')
        self.pack=self.store.create_pack('Figures'); raw=io.BytesIO(); Image.new('RGB',(200,100),'white').save(raw,format='PNG')
        self.doc,_=self.store.add_document(self.pack.pack_id,'diagram.png',io.BytesIO(raw.getvalue()))
        self.store.publish_extraction(self.doc.document_id,extract_document(self.store.original_path(self.pack.pack_id,self.doc.document_id),self.doc,self.store.limits))
        self.visual=VisualStore(self.store,self.pack.pack_id); self.figure=self.visual.figures(self.doc.document_id)[0]

    def tearDown(self): self.tmp.cleanup()

    def revision(self,method='vlm',text='A activates B'):
        source=self.store.units(self.pack.pack_id,self.doc.document_id)[0]
        return replace(source,unit_id=__import__('uuid').uuid4().hex,role='figure_description',text=text,provenance=method,
                       provenance_details={'figure_id':self.figure.figure_id,'source_unit_id':source.unit_id})

    def test_annotation_revision_survives_redescribe(self):
        native=self.store.units(self.pack.pack_id,self.doc.document_id)[0]
        first=self.visual.publish_revision(self.revision(),expected_source_hash=self.figure.checksum)
        self.visual.activate_revision(self.figure.figure_id,first)
        annotation=self.visual.publish_revision(self.revision('user_annotation','User correction'),expected_source_hash=self.figure.checksum)
        self.visual.activate_revision(self.figure.figure_id,annotation)
        next_revision=self.visual.publish_revision(self.revision(text='New model output'),expected_source_hash=self.figure.checksum)
        self.visual.activate_revision(self.figure.figure_id,next_revision)
        self.assertIn(native.unit_id,{u.unit_id for u in self.store.units(self.pack.pack_id,self.doc.document_id)})
        self.assertIn(annotation,{u.unit_id for u in self.visual.active_units(self.doc.document_id)})
        self.assertNotIn(next_revision,{u.unit_id for u in self.visual.active_units(self.doc.document_id)})
        self.assertEqual(self.visual.revision(first).text,'A activates B')

    def test_wrong_source_and_cross_pack_rejected(self):
        with self.assertRaises(StudyError): self.visual.publish_revision(self.revision(),expected_source_hash='wrong')
        other=self.store.create_pack('Other')
        with self.assertRaises(StudyError): VisualStore(self.store,other.pack_id).figure(self.figure.figure_id)

    def test_purge_removes_visual_private_records(self):
        self.visual.publish_revision(self.revision(),expected_source_hash=self.figure.checksum)
        self.store.purge(self.pack.pack_id,self.doc.document_id,confirmation=self.doc.document_id)
        with self.assertRaises(StudyError): self.visual.figure(self.figure.figure_id)
