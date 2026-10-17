import io
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from aura_bio.study.storage import StudyStore
from aura_bio.study.jobs import StudyJobs
from study_fixtures import pdf_fixture
from aura_bio.study.schema import StudyError


class PdfPageJobsTests(unittest.TestCase):
    def test_missing_optional_renderer_preserves_native_pdf_ingestion(self):
        from aura_bio.study import jobs as module
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/'text.pdf'; pdf_fixture(path,('Native chapter remains readable.',))
            store=StudyStore(root/'packs'); pack=store.create_pack('Native')
            doc,_=store.add_document(pack.pack_id,'text.pdf',io.BytesIO(path.read_bytes()))
            jobs=StudyJobs(store)
            # Exercise parent integration/fallback without pretending the patched
            # renderer is inherited by a Windows spawn.
            jobs._step=lambda document,extractor,limits,timeout:extractor(store.original_path(pack.pack_id,doc.document_id),document,limits)
            with patch('aura_bio.study.visual.assets.render_pdf_page',side_effect=StudyError('missing_dependency','Renderer absent')):
                result=jobs._parse_pdf(doc)
            self.assertIn('Native chapter',result.units[0].text)
            self.assertEqual(result.assets,[])
            self.assertTrue(any('missing_dependency' in warning for warning in result.warnings))

    def test_pdf_uses_page_timeout_and_keeps_visual_only_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/'scan.pdf'; pdf_fixture(path,('',''))
            store=StudyStore(root/'packs'); pack=store.create_pack('Scans')
            doc,job=store.add_document(pack.pack_id,'scan.pdf',io.BytesIO(path.read_bytes()))
            jobs=StudyJobs(store); jobs.run_once()
            self.assertEqual(store.document(pack.pack_id,doc.document_id).state,'visual-only')
            self.assertEqual(len(store.units(pack.pack_id,doc.document_id)),2)
            self.assertEqual(len(store.units(pack.pack_id,doc.document_id)[0].asset_ids),1)
            self.assertNotEqual(store.job(job.job_id).state,'failed')
