import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from aura_bio.study.schema import StudyError
from aura_bio.study.storage import StudyStore


def png():
    data = io.BytesIO()
    Image.new('RGB', (80, 80), 'white').save(data, 'PNG')
    return io.BytesIO(data.getvalue())


class AttachmentsTests(unittest.TestCase):
    def setUp(self):
        from aura_bio.study.attachments import AttachmentService
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1000
        self.store = StudyStore(Path(self.tmp.name), clock=lambda: self.now)
        self.service = AttachmentService(self.store)

    def tearDown(self):
        self.service.stop()
        self.tmp.cleanup()

    def test_image_upload_owns_hidden_pack_but_does_not_understand_it(self):
        item = self.service.upload('diagram.png', png())
        self.assertEqual(item['pack']['expires_at'], 4600)
        self.assertFalse(item['usable'])
        self.assertEqual(self.store.list_packs(), [])
        self.assertEqual(len(self.store.documents(item['attachment_id'])), 1)

    def test_failed_upload_leaves_no_pack_or_original(self):
        for name, data in [('diagram.png', b'not PNG'), ('lecture.txt', b'lecture')]:
            with self.assertRaises(StudyError):
                self.service.upload(name, io.BytesIO(data))
        self.assertEqual(self.store.list_packs(include_temporary=True), [])
        self.assertEqual(list(self.store.root.rglob('originals')), [])

    def test_promotion_survives_sweep_and_remove_cannot_delete_saved(self):
        item = self.service.upload('diagram.png', png())
        self.service.promote(item['attachment_id'], 'Keep this')
        self.now = 5000
        self.service.sweep()
        self.assertEqual(self.store.get_pack(item['attachment_id']).name, 'Keep this')
        with self.assertRaises(StudyError):
            self.service.delete(item['attachment_id'])

    def test_expiry_sweep_never_touches_context_and_retries_leases(self):
        item = self.service.upload('diagram.png', png())
        context = self.store.create_pack('Saved context')
        with self.store.lease(item['attachment_id'], require_ready=False):
            self.now = 4600
            self.service.sweep()
            self.assertTrue((self.store.root / item['attachment_id']).exists())
        self.service.sweep()
        self.assertFalse((self.store.root / item['attachment_id']).exists())
        self.assertEqual(self.store.get_pack(context.pack_id).name, 'Saved context')

    def test_quota_rejects_twenty_first_without_evicting(self):
        for _ in range(20):
            self.service.upload('diagram.png', png())
        with self.assertRaises(StudyError) as caught:
            self.service.upload('last.png', png())
        self.assertEqual(caught.exception.code, 'limit')
        self.assertEqual(len(self.store.list_packs(include_temporary=True)), 20)
