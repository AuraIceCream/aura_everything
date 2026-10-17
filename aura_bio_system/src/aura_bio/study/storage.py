"""Pack-owned SQLite and generated paths; no access to core corpus stores."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import closing, contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import BinaryIO

from .schema import Document, Job, Limits, Pack, PurgeResult, StudyError, unit_from_dict
from .validation import contained, validate_container, validate_filename, validate_id

_TABLES = '''
CREATE TABLE IF NOT EXISTS documents (
 document_id TEXT PRIMARY KEY, checksum TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS documents_checksum ON documents(checksum);
CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS units (unit_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS units_document ON units(document_id, ordinal);
CREATE TABLE IF NOT EXISTS assets (asset_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, payload TEXT NOT NULL);
'''


class StudyStore:
    def __init__(self, root: Path, limits: Limits | None = None, *, clock=time.time):
        self.root = root.resolve()
        self.clock = clock
        self.limits = limits or Limits()
        protected = [Path(os.environ.get('AURA_INDEX_ROOT', r'G:\aura_data\AURA-Bio-Index'))]
        protected += [Path(os.environ[name]) for name in ('AURA_CORPUS_ROOT', 'AURA_PROCESSED_ROOT') if name in os.environ]
        protected += [Path(r'G:\aura_data') / name for name in ('AURA-Bio-Corpus', 'AURA-Bio-Processed')]
        if any(self.root.is_relative_to(p.resolve()) or p.resolve().is_relative_to(self.root) for p in protected):
            raise StudyError('unsafe_root', 'Study storage must be separate from core corpus/index roots.')
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.readers: dict[str, int] = {}
        self.blocked: set[str] = set()
        self.inference_owner = None
        with self._catalog() as db:
            db.execute('CREATE TABLE IF NOT EXISTS packs(pack_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS purges(pack_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    @contextmanager
    def _catalog(self):
        db = sqlite3.connect(contained(self.root, 'catalog.sqlite3'), timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def db(self, pack_id: str):
        self.get_pack(pack_id)
        db = sqlite3.connect(contained(self.root, pack_id, 'metadata.sqlite3'), timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_pack(self, name: str, domain: str = 'general', *, retention='saved', expires_at=None) -> Pack:
        if not name.strip() or len(name) > 160 or domain not in {'general', 'biology'}:
            raise StudyError('invalid_pack', 'Choose a short name and general or biology domain.')
        if retention not in {'saved', 'temporary'} or (retention == 'saved' and expires_at is not None) or (retention == 'temporary' and (not isinstance(expires_at, (int, float)) or not math.isfinite(expires_at) or expires_at <= self.clock())):
            raise StudyError('invalid_pack', 'Invalid temporary retention deadline.')
        with self.lock:
            pack = Pack(uuid.uuid4().hex, name.strip(), domain, self.clock(), retention=retention, expires_at=expires_at)
            folder = contained(self.root, pack.pack_id)
            folder.mkdir()
            with self._catalog() as db:
                db.execute('INSERT INTO packs VALUES (?,?)', (pack.pack_id, json.dumps(asdict(pack))))
            with self.db(pack.pack_id) as db:
                db.executescript(_TABLES)
            return pack

    def list_packs(self, *, include_temporary=False) -> list[Pack]:
        with self._catalog() as db:
            packs = [Pack(**json.loads(row[0])) for row in db.execute('SELECT payload FROM packs ORDER BY rowid DESC')]
            return [p for p in packs if include_temporary or p.retention == 'saved']

    def worker_packs(self):
        return [p for p in self.list_packs(include_temporary=True) if p.state != 'purge-pending' and p.pack_id not in self.blocked and not self.expired(p)]

    @contextmanager
    def inference(self, pack_id, kind, *, wait_for_visual=False):
        """Reserve, without holding the catalog lock over provider work."""
        token = (kind, pack_id, uuid.uuid4().hex)
        with self.lock:
            self.assert_available(pack_id)
            if self.inference_owner is not None or (wait_for_visual and any(
                j.kind == 'visual' and j.state in {'queued', 'running'}
                for p in self.worker_packs() for j in self.jobs(p.pack_id))):
                raise StudyError('busy_gpu', 'Visual/answer work is already active; wait and resume explicitly. No model was switched.')
            self.inference_owner = token
        try:
            yield
        finally:
            with self.lock:
                if self.inference_owner == token:
                    self.inference_owner = None

    def expired(self, pack):
        return pack.retention == 'temporary' and pack.expires_at is not None and self.clock() >= pack.expires_at

    def get_pack(self, pack_id: str) -> Pack:
        pack = self._pack_record(pack_id)
        if self.expired(pack):
            raise StudyError('attachment_expired', 'Temporary image expired; upload it again or use saved material.')
        return pack

    def _pack_record(self, pack_id: str) -> Pack:
        validate_id(pack_id)
        with self._catalog() as db:
            row = db.execute('SELECT payload FROM packs WHERE pack_id=?', (pack_id,)).fetchone()
        if row is None:
            raise StudyError('not_found', 'Study pack not found.')
        return Pack(**json.loads(row[0]))

    def update_pack(self, pack: Pack) -> None:
        with self.lock:
            current = self._pack_record(pack.pack_id)
            if pack.state != 'purge-pending':
                self.assert_available(pack.pack_id)
            pack = replace(pack, retention=current.retention, expires_at=current.expires_at,
                           lifecycle_schema=current.lifecycle_schema, name=current.name)
            with self._catalog() as db:
                db.execute('UPDATE packs SET payload=? WHERE pack_id=?', (json.dumps(asdict(pack)), pack.pack_id))

    def promote_pack(self, pack_id, name):
        if not name.strip() or len(name) > 160:
            raise StudyError('invalid_pack', 'Choose a short name for saved material.')
        with self.lock:
            pack = self.assert_available(pack_id)
            pack = replace(pack, name=name.strip(), retention='saved', expires_at=None)
            with self._catalog() as db:
                db.execute('UPDATE packs SET payload=? WHERE pack_id=?', (json.dumps(asdict(pack)), pack_id))
            return pack

    def pending_purge(self, pack_id: str) -> dict | None:
        """Catalog-only cleanup target: pack metadata may already have been removed."""
        self._pack_record(pack_id)
        with self._catalog() as db:
            row = db.execute('SELECT payload FROM purges WHERE pack_id=?', (pack_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def documents(self, pack_id: str) -> list[Document]:
        with self.db(pack_id) as db:
            return [Document(**json.loads(row[0])) for row in db.execute('SELECT payload FROM documents ORDER BY rowid')]

    def document(self, pack_id: str, document_id: str) -> Document:
        validate_id(document_id)
        with self.db(pack_id) as db:
            row = db.execute('SELECT payload FROM documents WHERE document_id=?', (document_id,)).fetchone()
        if row is None:
            raise StudyError('not_found', 'Document not found in this pack.')
        return Document(**json.loads(row[0]))

    def update_document(self, document: Document) -> None:
        with self.db(document.pack_id) as db:
            db.execute('UPDATE documents SET payload=? WHERE document_id=?', (json.dumps(asdict(document)), document.document_id))

    def original_path(self, pack_id: str, document_id: str) -> Path:
        document = self.document(pack_id, document_id)
        return contained(self.root, pack_id, 'originals', f'{document_id}.{document.kind}')

    def add_document(self, pack_id: str, filename: str, stream: BinaryIO) -> tuple[Document, Job | None]:
        with self.lock:
            pack = self.assert_available(pack_id)
            if pack.retention == 'temporary' and self.documents(pack_id):
                raise StudyError('not_ready', 'A temporary attachment owns exactly one image; save material before adding documents.')
            kind = validate_filename(filename)
            document_id = uuid.uuid4().hex
            folder = contained(self.root, pack_id, 'originals')
            folder.mkdir(exist_ok=True)
            temporary = contained(folder, f'{document_id}.part')
            digest, size = hashlib.sha256(), 0
            try:
                with temporary.open('xb') as handle:
                    while data := stream.read(65536):
                        size += len(data)
                        if size > self.limits.max_upload_bytes:
                            raise StudyError('limit', 'Upload exceeds the configured file limit.')
                        digest.update(data)
                        handle.write(data)
                if not size:
                    raise StudyError('invalid_container', 'The uploaded file is empty.')
                validate_container(temporary, kind, self.limits)
                checksum = digest.hexdigest()
                for old in self.documents(pack_id):
                    if old.checksum == checksum and old.active:
                        return old, None
                document = Document(document_id, pack_id, filename, checksum, kind)
                target = contained(folder, f'{document_id}.{kind}')
                os.replace(temporary, target)
                try:
                    with self.db(pack_id) as db:
                        db.execute('INSERT INTO documents VALUES (?,?,?)', (document_id, checksum, json.dumps(asdict(document))))
                    return document, self.enqueue(pack_id, document_id)
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
            finally:
                temporary.unlink(missing_ok=True)

    def enqueue(self, pack_id: str, document_id: str | None = None, kind: str = 'extract') -> Job:
        job = Job(uuid.uuid4().hex, pack_id, document_id, 'queued', kind=kind)
        with self.db(pack_id) as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?)', (job.job_id, json.dumps(asdict(job)), time.time()))
        return job

    def jobs(self, pack_id: str) -> list[Job]:
        with self.db(pack_id) as db:
            return [Job(**json.loads(row[0])) for row in db.execute('SELECT payload FROM jobs ORDER BY created_at')]

    def job(self, job_id: str) -> Job:
        validate_id(job_id)
        for pack in self.list_packs(include_temporary=True):
            if pack.state == 'purge-pending':
                continue
            path = contained(self.root, pack.pack_id, 'metadata.sqlite3')
            with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as db:
                row = db.execute('SELECT payload FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if row:
                self.assert_available(pack.pack_id)
                return Job(**json.loads(row[0]))
        raise StudyError('not_found', 'Study job not found.')

    def update_job(self, job: Job) -> None:
        with self.db(job.pack_id) as db:
            db.execute('UPDATE jobs SET payload=? WHERE job_id=?', (json.dumps(asdict(job)), job.job_id))

    def assert_available(self, pack_id: str) -> Pack:
        pack = self.get_pack(pack_id)
        if pack_id in self.blocked or pack.state == 'purge-pending':
            raise StudyError('not_ready', 'Pack is being removed; retry cleanup before using it.')
        return pack

    def publish_extraction(self, document_id, extraction) -> None:
        with self.lock:
            document = next((doc for pack in self.worker_packs() if pack.state != 'purge-pending'
                             for doc in self.documents(pack.pack_id)
                             if doc.document_id == document_id), None)
            if document is None:
                raise StudyError('not_found', 'Extraction document no longer exists.')
            self.assert_available(document.pack_id)
            if any(unit.document_id != document_id for unit in extraction.units):
                raise StudyError('invalid_extraction', 'Source units do not belong to this document.')
            with self.db(document.pack_id) as db:
                db.execute('DELETE FROM units WHERE document_id=?', (document_id,))
                db.execute('DELETE FROM assets WHERE document_id=?', (document_id,))
                db.executemany('INSERT INTO units VALUES (?,?,?,?)',
                               [(u.unit_id, document_id, u.ordinal, json.dumps(asdict(u))) for u in extraction.units])
                for asset in extraction.assets:
                    validate_id(asset.asset_id)
                    if asset.unit_id not in {u.unit_id for u in extraction.units}:
                        raise StudyError('invalid_extraction', 'Asset does not belong to an extracted unit.')
                    folder = contained(self.root, document.pack_id, 'assets', document_id)
                    folder.mkdir(parents=True, exist_ok=True)
                    target = contained(folder, asset.asset_id)
                    target.write_bytes(asset.content)
                    metadata = {'asset_id': asset.asset_id, 'unit_id': asset.unit_id,
                                'mime_type': asset.mime_type, 'coordinates': asset.coordinates,
                                'checksum': hashlib.sha256(asset.content).hexdigest()}
                    db.execute('INSERT INTO assets VALUES (?,?,?)', (asset.asset_id, document_id, json.dumps(metadata)))
            from dataclasses import replace
            self.update_document(replace(document, state='extracted', warnings=extraction.warnings,
                                         coverage=extraction.coverage, parser_version=extraction.parser_version))

    def units(self, pack_id: str, document_id: str):
        self.document(pack_id, document_id)
        with self.db(pack_id) as db:
            units = [unit_from_dict(json.loads(row[0])) for row in db.execute(
                'SELECT payload FROM units WHERE document_id=? ORDER BY ordinal', (document_id,))]
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='visual_revisions'").fetchone():
                units += [unit_from_dict(json.loads(row[0])) for row in db.execute('SELECT payload FROM visual_revisions WHERE document_id=? AND active=1 ORDER BY rowid',(document_id,))]
            return units

    def asset(self, pack_id: str, document_id: str, asset_id: str):
        validate_id(asset_id)
        self.document(pack_id, document_id)
        with self.db(pack_id) as db:
            row = db.execute('SELECT payload FROM assets WHERE document_id=? AND asset_id=?',
                             (document_id, asset_id)).fetchone()
        if row is None:
            raise StudyError('not_found', 'Asset not found in this document.')
        return json.loads(row[0])

    def asset_path(self, pack_id: str, document_id: str, asset_id: str) -> Path:
        self.asset(pack_id, document_id, asset_id)
        return contained(self.root, pack_id, 'assets', document_id, asset_id)

    @contextmanager
    def lease(self, pack_id: str, *, require_ready: bool = True):
        with self.condition:
            pack = self.assert_available(pack_id)
            if require_ready and pack.state not in {'sparse-ready', 'hybrid-ready'}:
                raise StudyError('not_ready', 'Wait for this pack to finish indexing.')
            self.readers[pack_id] = self.readers.get(pack_id, 0) + 1
        try:
            yield pack.generation
        finally:
            with self.condition:
                self.readers[pack_id] -= 1
                self.condition.notify_all()

    def deactivate(self, pack_id: str, document_id: str) -> Job:
        with self.lock:
            self.assert_available(pack_id)
            document = self.document(pack_id, document_id)
            self.update_document(replace(document, active=False))
            from .visual.storage import VisualStore
            visual=VisualStore(self,pack_id)
            with self.db(pack_id) as db:
                affected={r[0] for r in db.execute('SELECT job_id FROM visual_checkpoints WHERE document_id=?',(document_id,))}
            for job in self.jobs(pack_id):
                if (job.document_id == document_id or job.job_id in affected) and job.state in {'queued','running','paused','partial'}:
                    self.update_job(replace(job, state='failed', error='Document deactivated.'))
            return self.enqueue(pack_id, kind='index')

    def purge(self, pack_id: str, document_id: str | None = None, *, confirmation: str, wait_seconds=None) -> PurgeResult:
        validate_id(pack_id)
        if document_id is not None:
            validate_id(document_id)
        if confirmation != (document_id or pack_id):
            raise StudyError('confirmation_required', 'Confirm the exact document or pack ID to permanently delete it.')
        with self.condition:
            pack = self._pack_record(pack_id)
            with self._catalog() as db:
                pending = db.execute('SELECT payload FROM purges WHERE pack_id=?', (pack_id,)).fetchone()
            journal = json.loads(pending[0]) if pending else None
            if journal and document_id and journal['document_id'] != document_id:
                raise StudyError('not_ready', 'Retry the pending target purge, or confirm deletion of the whole pack.')
            if journal is None:
                doc = self.document(pack_id, document_id) if document_id else None
                journal = {'document_id': document_id, 'kind': doc.kind if doc else None}
                with self._catalog() as db:
                    db.execute('INSERT INTO purges VALUES (?,?)', (pack_id, json.dumps(journal)))
            self.blocked.add(pack_id)
            self.update_pack(replace(pack, state='purge-pending'))
            self.condition.notify_all()
            if not self.condition.wait_for(lambda: not self.readers.get(pack_id, 0), timeout=wait_seconds):
                return PurgeResult(pack_id, document_id, False)
            # No reader/worker holds an index/file/trace handle at this point.
            folder = contained(self.root, pack_id)
            if folder.resolve() == self.root or not folder.resolve().is_relative_to(self.root):
                raise StudyError('unsafe_path', 'Refusing an unsafe purge target.')
            try:
                if document_id is None:
                    if folder.exists():
                        shutil.rmtree(folder)
                    with self._catalog() as db:
                        db.execute('DELETE FROM packs WHERE pack_id=?', (pack_id,))
                        db.execute('DELETE FROM purges WHERE pack_id=?', (pack_id,))
                else:
                    # Journal survives deletion of the document row and server restart.
                    original = contained(folder, 'originals', f'{document_id}.{journal["kind"]}')
                    with self.db(pack_id) as db:
                        original.unlink(missing_ok=True)
                        db.execute('DELETE FROM units WHERE document_id=?', (document_id,))
                        db.execute('DELETE FROM assets WHERE document_id=?', (document_id,))
                        from .visual.storage import remove_document_visual
                        remove_document_visual(db,document_id)
                        db.execute('DELETE FROM documents WHERE document_id=?', (document_id,))
                        # Whole-pack history is invalidated, as disclosed by PurgeResult/UI.
                        db.execute('DELETE FROM jobs')
                    for parts in (('assets', document_id), ('visual', document_id), ('generations',), ('traces',)):
                        target = contained(folder, *parts)
                        if target.exists():
                            shutil.rmtree(target)
                    with self.db(pack_id) as db:
                        db.execute('VACUUM')
                    self.blocked.remove(pack_id)
                    # This transition is owned by purge, not an ordinary worker write.
                    with self._catalog() as db:
                        db.execute('UPDATE packs SET payload=? WHERE pack_id=?',
                                   (json.dumps(asdict(replace(pack, generation=0, state='empty'))), pack_id))
                    from .indexing import StudyIndexer
                    StudyIndexer(self).build(pack_id)
                    # Removal is immediate and model-free. Rebuild dense features
                    # in the normal worker, outside this purge lock. The interim
                    # sparse state is exposed accurately while that job runs.
                    if self.get_pack(pack_id).state == 'sparse-ready':
                        self.enqueue(pack_id, kind='index')
                    with self._catalog() as db:
                        db.execute('DELETE FROM purges WHERE pack_id=?', (pack_id,))
                self.blocked.discard(pack_id)
                self.condition.notify_all()
                return PurgeResult(pack_id, document_id, True)
            except Exception as exc:
                self.blocked.add(pack_id)
                self.update_pack(replace(pack, state='purge-pending'))
                raise StudyError('purge_failed', 'Cleanup failed; the pack is blocked. Close local file viewers and retry purge.') from exc

    def close(self) -> None:
        # Connections are short-lived/context-owned, including on worker threads.
        pass
