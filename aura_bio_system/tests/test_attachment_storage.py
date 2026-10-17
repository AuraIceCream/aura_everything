import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aura_bio.study.schema import StudyError
from aura_bio.study.storage import StudyStore


class AttachmentStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1000.0
        self.store = StudyStore(Path(self.tmp.name), clock=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def temporary(self):
        return self.store.create_pack('Image', retention='temporary', expires_at=4600.0)

    def test_hidden_pack_is_still_found_by_worker_job_lookup(self):
        pack = self.temporary()
        job = self.store.enqueue(pack.pack_id)
        self.assertEqual(self.store.list_packs(), [])
        self.assertEqual(self.store.list_packs(include_temporary=True)[0].pack_id, pack.pack_id)
        self.assertEqual(self.store.job(job.job_id).pack_id, pack.pack_id)

    def test_expiry_is_absolute_and_blocks_public_metadata(self):
        pack = self.temporary()
        self.now = 4599
        self.assertEqual(self.store.get_pack(pack.pack_id).expires_at, 4600)
        self.now = 4600
        with self.assertRaises(StudyError) as caught:
            self.store.get_pack(pack.pack_id)
        self.assertEqual(caught.exception.code, 'attachment_expired')
        with self.assertRaises(StudyError):
            self.store.enqueue(pack.pack_id)

    def test_promotion_cannot_be_undone_by_stale_index_update(self):
        old = self.temporary()
        saved = self.store.promote_pack(old.pack_id, 'Saved diagram')
        self.store.update_pack(replace(old, generation=2, state='sparse-ready'))
        actual = self.store.get_pack(old.pack_id)
        self.assertEqual((actual.retention, actual.expires_at, actual.name), ('saved', None, 'Saved diagram'))
        self.assertEqual(actual.generation, 2)
        self.now = 10000
        self.assertEqual(self.store.get_pack(saved.pack_id).retention, 'saved')

    def test_expired_reader_causes_pending_cleanup_then_safe_purge(self):
        pack = self.temporary()
        other = self.store.create_pack('Never delete')
        with self.store.lease(pack.pack_id, require_ready=False):
            self.now = 4601
            result = self.store.purge(pack.pack_id, confirmation=pack.pack_id, wait_seconds=0)
            self.assertFalse(result.deleted)
            self.assertTrue((self.store.root / pack.pack_id).exists())
            with self.assertRaises(StudyError):
                self.store.promote_pack(pack.pack_id, 'Too late')
        self.assertTrue(self.store.purge(pack.pack_id, confirmation=pack.pack_id, wait_seconds=0).deleted)
        self.assertFalse((self.store.root / pack.pack_id).exists())
        self.assertEqual(self.store.get_pack(other.pack_id).name, 'Never delete')

    def test_expiry_survives_restart_saved_legacy_records_do_not_expire(self):
        pack = self.temporary()
        saved = self.store.create_pack('Legacy')
        with self.store._catalog() as db:
            db.execute("UPDATE packs SET payload=json_remove(payload,'$.retention','$.expires_at','$.lifecycle_schema') WHERE pack_id=?", (saved.pack_id,))
        self.now = 5000
        restarted = StudyStore(self.store.root, clock=lambda: self.now)
        self.assertEqual(restarted.get_pack(saved.pack_id).retention, 'saved')
        with self.assertRaises(StudyError):
            restarted.get_pack(pack.pack_id)
