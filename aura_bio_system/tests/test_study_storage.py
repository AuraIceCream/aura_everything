from __future__ import annotations

import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from aura_bio.study.schema import Limits, StudyError
from aura_bio.study.storage import StudyStore


class StudyStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = StudyStore(self.root / 'packs', Limits(max_upload_bytes=1024))
        self.pack = self.store.create_pack('Course')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_duplicates_are_bytes_not_filenames(self):
        first, job = self.store.add_document(self.pack.pack_id, 'lecture.txt', io.BytesIO(b'Lecture'))
        second, duplicate_job = self.store.add_document(self.pack.pack_id, 'copy.txt', io.BytesIO(b'Lecture'))
        self.assertEqual(first.document_id, second.document_id)
        self.assertIsNone(duplicate_job)
        self.assertEqual(self.store.job(job.job_id).state, 'queued')
        self.assertEqual(self.store.original_path(self.pack.pack_id, first.document_id).read_bytes(), b'Lecture')

    def test_oversized_stream_is_not_promoted(self):
        with self.assertRaises(StudyError) as error:
            self.store.add_document(self.pack.pack_id, 'large.txt', io.BytesIO(b'x' * 1025))
        self.assertEqual(error.exception.code, 'limit')
        self.assertEqual(self.store.documents(self.pack.pack_id), [])
        self.assertFalse(list(self.store.root.rglob('*.part')))

    def test_unsafe_display_names_and_ids_are_rejected(self):
        for name in ('../lesson.txt', 'CON.txt', 'nested\\lesson.txt', 'a:stream.txt'):
            with self.subTest(name=name), self.assertRaises(StudyError):
                self.store.add_document(self.pack.pack_id, name, io.BytesIO(b'Text'))
        with self.assertRaises(StudyError):
            self.store.get_pack('../')

    def test_cross_pack_document_lookup_fails(self):
        document, _ = self.store.add_document(self.pack.pack_id, 'x.txt', io.BytesIO(b'Private'))
        other = self.store.create_pack('Other')
        with self.assertRaises(StudyError):
            self.store.original_path(other.pack_id, document.document_id)

    def test_original_core_root_is_not_a_study_root(self):
        core = self.root / 'core'
        core.mkdir()
        (core / 'sentinel').write_bytes(b'unchanged')
        with patch.dict(os.environ, {'AURA_INDEX_ROOT': str(core)}):
            with self.assertRaises(StudyError):
                StudyStore(core / 'private')
        self.assertEqual((core / 'sentinel').read_bytes(), b'unchanged')

    def test_signature_mismatch_and_unsupported_format(self):
        for name, content in [('bad.pdf', b'Text'), ('macro.xlsm', b'PK'), ('bad.xlsx', b'Text')]:
            with self.subTest(name=name), self.assertRaises(StudyError):
                self.store.add_document(self.pack.pack_id, name, io.BytesIO(content))

    def test_archive_entities_are_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('[Content_Types].xml', '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///secret">]><x/>')
            archive.writestr('xl/workbook.xml', '<x/>')
        stream.seek(0)
        with self.assertRaises(StudyError):
            self.store.add_document(self.pack.pack_id, 'unsafe.xlsx', stream)

    def test_reopen_preserves_jobs(self):
        _, job = self.store.add_document(self.pack.pack_id, 'a.txt', io.BytesIO(b'A'))
        self.store.close()
        self.store = StudyStore(self.root / 'packs')
        self.assertEqual(self.store.job(job.job_id).state, 'queued')
