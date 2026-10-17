"""Temporary pack ownership; expiry never deletes a selected context pack."""
import hashlib
import json
import sqlite3
import threading
from dataclasses import asdict

from .schema import StudyError
from .validation import validate_filename, validate_id


def question_hash(question):
    return hashlib.sha256(question.strip().encode('utf-8')).hexdigest() if question.strip() else ''


class AttachmentService:
    def __init__(self, store, *, clock=None, ttl_seconds=3600, invalidate=None):
        if type(ttl_seconds) is not int or not 300 <= ttl_seconds <= 86400:
            raise StudyError('invalid_config', 'Attachment TTL must be 300–86400 seconds.')
        self.store, self.clock = store, clock or store.clock
        self.ttl_seconds, self.invalidate = ttl_seconds, invalidate or (lambda _: None)
        self.stopping = threading.Event()
        self.thread = None
        with store._catalog() as db:
            db.execute('CREATE TABLE IF NOT EXISTS image_attachments(pack_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, cleanup_error TEXT)')

    def _owned(self, attachment_id):
        validate_id(attachment_id)
        with self.store._catalog() as db:
            row = db.execute('SELECT document_id,cleanup_error FROM image_attachments WHERE pack_id=?', (attachment_id,)).fetchone()
        if not row:
            raise StudyError('not_found', 'Image attachment not found.')
        return row

    def upload(self, filename, stream):
        if validate_filename(filename) not in {'png', 'jpg', 'jpeg'}:
            raise StudyError('unsupported_format', 'Attach a single-frame PNG or JPEG; documents belong in Study material.')
        with self.store.lock:
            self.sweep()
            if sum(p.retention == 'temporary' for p in self.store.list_packs(include_temporary=True)) >= 20:
                raise StudyError('limit', 'Twenty temporary images are already retained; remove one or save it first.')
            pack = self.store.create_pack('Temporary image', retention='temporary', expires_at=self.clock() + self.ttl_seconds)
            try:
                doc, job = self.store.add_document(pack.pack_id, filename, stream)
                with self.store._catalog() as db:
                    db.execute('INSERT INTO image_attachments VALUES (?,?,NULL)', (pack.pack_id, doc.document_id))
                return self.status(pack.pack_id)
            except Exception:
                self.store.purge(pack.pack_id, confirmation=pack.pack_id, wait_seconds=0)
                raise

    def indexed_for(self, attachment_id, question=None):
        pack = self.store.assert_available(attachment_id)
        if any(j.kind != 'visual' and j.state in {'queued','extracting','extracted','indexing'} for j in self.store.jobs(attachment_id)):
            return False
        if pack.state not in {'sparse-ready', 'hybrid-ready'}:
            return False
        from .searcher import StudySearcher
        expected = question_hash(question) if question is not None else None
        with StudySearcher(self.store, attachment_id) as searcher:
            for row in searcher.connection.execute('SELECT payload FROM chunks'):
                chunk = json.loads(row[0])
                if not chunk['text'].strip() or chunk.get('provenance') not in {'ocr', 'vlm', 'user_annotation'}:
                    continue
                active = {u.unit_id for u in self.store.units(attachment_id, chunk['document_id'])}
                if not set(chunk['unit_ids']).issubset(active):
                    continue
                if expected is not None and chunk.get('provenance') == 'vlm':
                    units = [u for u in self.store.units(attachment_id, chunk['document_id']) if u.unit_id in chunk['unit_ids']]
                    if any(u.provenance_details.get('question_hash', '') not in {'', expected} for u in units):
                        continue
                return True
        return False

    def status(self, attachment_id):
        doc_id, error = self._owned(attachment_id)
        with self.store.lease(attachment_id, require_ready=False):
            pack = self.store.get_pack(attachment_id)
            jobs = self.store.jobs(attachment_id)
            visual = [j for j in jobs if j.kind == 'visual']
            indexing = [j for j in jobs if j.kind != 'visual']
            units = self.store.units(attachment_id, doc_id)
            return {'attachment_id': attachment_id, 'pack': asdict(pack),
                    'document': asdict(self.store.document(attachment_id, doc_id)),
                    'preview_asset_id': next((asset for u in units if u.provenance == 'native_text' for asset in u.asset_ids), None),
                    'job': asdict(indexing[-1]) if indexing else None,
                    'visual_jobs': [asdict(j) for j in visual],
                    'processing': any(j.state in {'queued', 'running'} for j in visual),
                    'usable': self.indexed_for(attachment_id),
                    'pending_cleanup': bool(self.store.pending_purge(attachment_id)), 'cleanup_error': error}

    def promote(self, attachment_id, name):
        with self.store.lock:
            self._owned(attachment_id)
            return self.store.promote_pack(attachment_id, name)

    def _purge(self, attachment_id):
        self.invalidate(attachment_id)
        try:
            result = self.store.purge(attachment_id, confirmation=attachment_id, wait_seconds=0)
            if result.deleted:
                with self.store._catalog() as db:
                    db.execute('DELETE FROM image_attachments WHERE pack_id=?', (attachment_id,))
            return result
        except StudyError:
            with self.store._catalog() as db:
                db.execute('UPDATE image_attachments SET cleanup_error=? WHERE pack_id=?',
                           ('Cleanup pending/failed; close local source viewers and retry removal.', attachment_id))
            raise

    def delete(self, attachment_id):
        with self.store.lock:
            self._owned(attachment_id)
            if self.store._pack_record(attachment_id).retention != 'temporary':
                raise StudyError('saved_attachment', 'This image is saved material; detach it without deleting its pack.')
            return self._purge(attachment_id)

    def sweep(self):
        results = []
        with self.store.lock:
            for pack in self.store.list_packs(include_temporary=True):
                if pack.retention != 'temporary' or not (self.store.expired(pack) or pack.state == 'purge-pending'):
                    continue
                try:
                    results.append(asdict(self._purge(pack.pack_id)))
                except StudyError:
                    results.append({'pack_id': pack.pack_id, 'deleted': False, 'cleanup_error': 'Cleanup requires retry.'})
        return results

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.sweep()
        self.stopping.clear()
        self.thread = threading.Thread(target=self._loop, name='aura-image-expiry', daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stopping.wait(60):
            self.sweep()

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=2)
