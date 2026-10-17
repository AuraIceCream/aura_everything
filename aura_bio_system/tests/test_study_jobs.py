import io
import tempfile
import threading
import time
import unittest
import os
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path

from aura_bio.study.jobs import StudyJobs
from aura_bio.study.schema import Limits, StudyError
from aura_bio.study.storage import StudyStore


def slow_extract(*args):
    time.sleep(2)


class StudyJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = StudyStore(self.root / 'packs')
        self.pack = self.store.create_pack('Class')
        self.document, self.job = self.store.add_document(self.pack.pack_id, 'lesson.txt', io.BytesIO(b'ORION calibration requires seven samples.'))
        self.jobs = StudyJobs(self.store)
        self.env = patch.dict(os.environ, {'AURA_STUDY_INDEX_MODE': 'sparse'})
        self.env.start()

    def tearDown(self):
        self.jobs.stop()
        self.env.stop()
        self.store.close()
        self.tmp.cleanup()

    def test_worker_extracts_and_publishes_sparse_without_models(self):
        self.jobs.run_once()
        self.assertEqual(self.store.job(self.job.job_id).state, 'sparse-ready')
        self.assertEqual(self.store.get_pack(self.pack.pack_id).state, 'sparse-ready')
        self.assertIn('seven samples', self.store.units(self.pack.pack_id, self.document.document_id)[0].text)

    def test_upload_automatically_builds_hybrid_and_reindex_keeps_it(self):
        from test_study_retrieval import FakeEncoder
        with patch.dict(os.environ, {'AURA_STUDY_INDEX_MODE': 'hybrid'}), \
                patch('aura_bio.study.jobs.cached_encoder', return_value=FakeEncoder()):
            self.jobs.run_once()
            self.assertEqual(self.store.get_pack(self.pack.pack_id).state, 'hybrid-ready')
            with patch.dict(os.environ, {'AURA_STUDY_INDEX_MODE': 'sparse'}):
                self.store.enqueue(self.pack.pack_id, kind='index')
                self.jobs.run_once()
            self.assertEqual(self.store.get_pack(self.pack.pack_id).state, 'hybrid-ready')
            self.assertIsNone(self.store.job(self.job.job_id).error)

    def test_missing_cached_encoder_is_explicit_sparse_fallback(self):
        with patch.dict(os.environ, {'AURA_STUDY_INDEX_MODE': 'hybrid'}), \
                patch('aura_bio.study.jobs.cached_encoder', side_effect=OSError('not cached')):
            self.jobs.run_once()
        job = self.store.job(self.job.job_id)
        self.assertEqual(job.state, 'sparse-ready')
        self.assertIn('embedding', job.error.lower())
        self.assertIn('sparse', job.error.lower())
        self.assertTrue(any('embedding' in warning.lower() for warning in
                            self.store.document(self.pack.pack_id, self.document.document_id).warnings))

    def test_timeout_is_retryable_not_ready(self):
        self.store.limits = Limits(timeout_seconds=0.1)
        jobs = StudyJobs(self.store, extractor=slow_extract)
        jobs.run_once()
        failed = self.store.job(self.job.job_id)
        self.assertEqual(failed.state, 'failed')
        self.assertIn('timeout', failed.error.lower())
        self.assertEqual(jobs.retry(failed.job_id).state, 'queued')
        self.assertEqual(self.store.get_pack(self.pack.pack_id).generation, 0)

    def test_interrupted_job_is_not_silently_ready(self):
        self.store.update_job(replace(self.job, state='extracting'))
        self.jobs.recover()
        result = self.store.job(self.job.job_id)
        self.assertEqual(result.state, 'failed')
        self.assertIn('interrupted', result.error.lower())

    def test_deactivation_retains_original_and_removes_search(self):
        self.jobs.run_once()
        original = self.store.original_path(self.pack.pack_id, self.document.document_id)
        job = self.store.deactivate(self.pack.pack_id, self.document.document_id)
        self.jobs.run_once()
        self.assertTrue(original.exists())
        self.assertEqual(self.store.job(job.job_id).state, 'empty')
        self.assertFalse(self.store.document(self.pack.pack_id, self.document.document_id).active)

    def test_purge_removes_originals_snapshots_and_private_traces(self):
        self.jobs.run_once()
        folder = self.store.root / self.pack.pack_id
        (folder / 'private-trace.jsonl').write_text('private answer')
        other = self.store.create_pack('Other')
        result = self.store.purge(self.pack.pack_id, confirmation=self.pack.pack_id)
        self.assertTrue(result.deleted)
        self.assertFalse(folder.exists())
        self.assertEqual(self.store.get_pack(other.pack_id).name, 'Other')

    def test_purge_requires_matching_confirmation(self):
        with self.assertRaises(StudyError):
            self.store.purge(self.pack.pack_id, confirmation='wrong')
        self.assertTrue(self.store.original_path(self.pack.pack_id, self.document.document_id).exists())

    def test_purge_waits_for_readers_and_blocks_new_readers(self):
        self.jobs.run_once()
        completed, started = threading.Event(), threading.Event()
        def purge():
            started.set()
            self.store.purge(self.pack.pack_id, confirmation=self.pack.pack_id)
            completed.set()
        with self.store.lease(self.pack.pack_id):
            thread = threading.Thread(target=purge)
            thread.start()
            self.assertTrue(started.wait(1))
            with self.store.condition:
                self.assertTrue(self.store.condition.wait_for(lambda: self.pack.pack_id in self.store.blocked, timeout=2))
            self.assertFalse(completed.is_set())
            with self.assertRaises(StudyError):
                with self.store.lease(self.pack.pack_id):
                    pass
        thread.join(5)
        self.assertTrue(completed.is_set())

    def test_document_purge_preserves_other_original(self):
        self.jobs.run_once()
        other, _ = self.store.add_document(self.pack.pack_id, 'other.txt', io.BytesIO(b'Another private lesson.'))
        self.jobs.run_once()
        path = self.store.original_path(self.pack.pack_id, other.document_id)
        self.store.purge(self.pack.pack_id, self.document.document_id, confirmation=self.document.document_id)
        self.assertEqual(path.read_bytes(), b'Another private lesson.')
        self.assertEqual(len(self.store.documents(self.pack.pack_id)), 1)
