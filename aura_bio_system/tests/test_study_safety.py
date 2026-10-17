"""Review findings: recoverability, isolation, and private output boundaries."""
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from dataclasses import replace

from aura_bio.study.storage import StudyStore
from aura_bio.study.jobs import StudyJobs
from aura_bio.study.indexing import StudyIndexer
from aura_bio.study.schema import StudyError
from aura_bio.study.validation import contained


class StudySafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StudyStore(Path(self.tmp.name) / 'packs')
        self.pack = self.store.create_pack('Class')
        self.doc, self.job = self.store.add_document(self.pack.pack_id, 'lesson.txt', io.BytesIO(b'ORION requires seven samples.'))
        StudyJobs(self.store).run_once()

    def tearDown(self):
        self.tmp.cleanup()

    def test_partial_document_purge_is_retryable_after_metadata_removed(self):
        folder = self.store.root / self.pack.pack_id
        with patch('aura_bio.study.storage.shutil.rmtree', side_effect=PermissionError('viewer')):
            with self.assertRaises(StudyError):
                self.store.purge(self.pack.pack_id, self.doc.document_id, confirmation=self.doc.document_id)
        self.assertEqual(self.store.get_pack(self.pack.pack_id).state, 'purge-pending')
        result = self.store.purge(self.pack.pack_id, self.doc.document_id, confirmation=self.doc.document_id)
        self.assertTrue(result.deleted)
        self.assertFalse(list((folder / 'originals').glob('*')))
        self.assertEqual(self.store.documents(self.pack.pack_id), [])

    def test_orphan_generation_from_catalog_failure_does_not_block_retry(self):
        old = self.store.get_pack(self.pack.pack_id).generation
        with patch.object(self.store, 'update_pack', side_effect=OSError('catalog failure')):
            with self.assertRaises(OSError):
                StudyIndexer(self.store).build(self.pack.pack_id)
        self.assertEqual(self.store.get_pack(self.pack.pack_id).generation, old)
        new = StudyIndexer(self.store).build(self.pack.pack_id)
        self.assertGreater(new, old)

    def test_failed_retry_keeps_previous_units_on_subsequent_reindex(self):
        self.store.update_document(replace(self.doc, state='failed'))
        StudyIndexer(self.store).build(self.pack.pack_id)
        self.assertEqual(self.store.get_pack(self.pack.pack_id).state, 'sparse-ready')

    def test_in_root_reparse_alias_cannot_cross_pack_ownership(self):
        # Real symlinks may need Windows privileges; mock only OS reparse detection,
        # while exercising the path validator, including in-root targets.
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaises(StudyError):
                contained(self.store.root, self.pack.pack_id, 'originals')

    def test_purge_cancels_an_active_extraction_worker(self):
        from test_study_jobs import slow_extract
        doc, _ = self.store.add_document(self.pack.pack_id, 'slow.txt', io.BytesIO(b'Private slow material.'))
        jobs = StudyJobs(self.store, extractor=slow_extract)
        thread = threading.Thread(target=jobs.run_once)
        thread.start()
        with self.store.condition:
            self.assertTrue(self.store.condition.wait_for(lambda: self.store.readers.get(self.pack.pack_id, 0) > 0, timeout=2))
        self.store.purge(self.pack.pack_id, confirmation=self.pack.pack_id)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertFalse((self.store.root / self.pack.pack_id).exists())

    def test_partial_pack_purge_survives_restart_with_missing_metadata(self):
        folder = self.store.root / self.pack.pack_id
        def partial_remove(path):
            (folder / 'metadata.sqlite3').unlink()
            raise PermissionError('original viewer is still open')
        with patch('aura_bio.study.storage.shutil.rmtree', side_effect=partial_remove):
            with self.assertRaises(StudyError):
                self.store.purge(self.pack.pack_id, confirmation=self.pack.pack_id)
        restarted = StudyStore(self.store.root)
        StudyJobs(restarted).recover()
        self.assertEqual(restarted.pending_purge(self.pack.pack_id)['document_id'], None)
        self.assertTrue(restarted.purge(self.pack.pack_id, confirmation=self.pack.pack_id).deleted)
