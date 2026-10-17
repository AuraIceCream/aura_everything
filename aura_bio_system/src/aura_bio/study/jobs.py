"""Persistent single-worker jobs; parsing runs in a bounded spawned process."""
import multiprocessing
import threading
import time
import os
import json
from functools import lru_cache
from dataclasses import asdict,replace

from .extractors import extract_document
from .indexing import StudyIndexer
from .schema import StudyError,Asset,Extraction,unit_from_dict
from .validation import contained


def _extract_child(connection, extractor, path, document, limits):
    try:
        connection.send(('ok', extractor(path, document, limits)))
    except StudyError as exc:
        connection.send(('error', exc.code, str(exc)))
    except Exception as exc:
        connection.send(('error', 'extraction_failed', f'Parser failed ({type(exc).__name__}).'))
    finally:
        connection.close()


def _pdf_count(path, document, limits):
    from pypdf import PdfReader
    with path.open('rb') as handle:
        reader=PdfReader(handle)
        if reader.is_encrypted: raise StudyError('encrypted','Upload a decrypted PDF.')
        count=len(reader.pages)
        if count>limits.max_pages_or_slides: raise StudyError('limit','PDF page count exceeds the safety limit.')
        return count


def _pdf_page_step(path,document,limits):
    # The page number is frozen in a per-step Limits-compatible record tuple.
    limits,number=limits
    from .extractors_pdf import extract_pdf_page
    from .visual.assets import render_pdf_page
    unit=extract_pdf_page(path,document,number,limits)
    try: image=render_pdf_page(path,number,limits)
    except StudyError as exc:
        if exc.code!='missing_dependency': raise
        return Extraction([unit],[],[f'Page {number}: missing_dependency — install the visual extra for previews; native text retained.'],{'units':1},'pdf-page-native-v1')
    image=replace(image,asset_id=__import__('hashlib').sha256(f'{unit.unit_id}:{image.checksum}'.encode()).hexdigest()[:32])
    unit=replace(unit,asset_ids=(image.asset_id,))
    asset=Asset(image.asset_id,unit.unit_id,'image/png',image.content,{'width':image.width,'height':image.height,'frame':'page_normalized','transform':asdict(image.transform)})
    return Extraction([unit],[asset],[],{'units':1},'pdf-page-v1')


def _load_encoder():
    from ..resources import guard_cpu_model_load
    guard_cpu_model_load('study embedding model')
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('BAAI/bge-base-en-v1.5', device='cpu', local_files_only=True)
    model.model_name = 'BAAI/bge-base-en-v1.5'
    return model


@lru_cache(maxsize=1)
def cached_encoder():
    """Reuse an exact-model owner; idle weights may be released for generation."""
    from .model_lifecycle import RetrievalModel
    return RetrievalModel(_load_encoder, 'BAAI/bge-base-en-v1.5').load()


class StudyJobs:
    def __init__(self, store, *, extractor=extract_document):
        self.store, self.extractor = store, extractor
        self.stopping = threading.Event()
        self.run_lock = threading.Lock()
        self.thread = None

    def recover(self):
        with self.store.lock:
            for pack in self.store.worker_packs():
                if pack.state == 'purge-pending':
                    continue  # Partial deletion may have removed its metadata DB.
                for job in self.store.jobs(pack.pack_id):
                    if job.state in {'extracting', 'extracted', 'indexing'}:
                        self.store.update_job(replace(job, state='failed', error='Interrupted by server restart; retry explicitly.'))
                        if job.document_id:
                            doc = self.store.document(job.pack_id, job.document_id)
                            self.store.update_document(replace(doc, state='failed', warnings=doc.warnings + ['Extraction/indexing interrupted; retry required.']))

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.recover()
        self.stopping.clear()
        self.thread = threading.Thread(target=self._loop, name='aura-study-worker', daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stopping.is_set():
            if not self.run_once():
                self.stopping.wait(0.25)

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=self.store.limits.timeout_seconds + 2)

    def retry(self, job_id):
        with self.store.lock:
            job = self.store.job(job_id)
            self.store.assert_available(job.pack_id)
            if job.state != 'failed':
                raise StudyError('not_ready', 'Only failed/interrupted jobs can be retried.')
            if job.document_id and not self.store.document(job.pack_id, job.document_id).active:
                raise StudyError('not_ready', 'Deactivated documents cannot be retried.')
            job = replace(job, state='queued', error=None)
            self.store.update_job(job)
            return job

    def request_dense_index(self, pack_id):
        self.store.assert_available(pack_id)
        return self.store.enqueue(pack_id, kind='dense')

    def _parse(self, document):
        if document.kind=='pdf' and self.extractor is extract_document:
            return self._parse_pdf(document)
        return self._step(document,self.extractor,self.store.limits,self.store.limits.timeout_seconds)

    def _step(self,document,extractor,limits,timeout_seconds):
        context = multiprocessing.get_context('spawn')
        receive, send = context.Pipe(duplex=False)
        process = context.Process(target=_extract_child, args=(send, extractor,
            self.store.original_path(document.pack_id, document.document_id), document, limits))
        deadline = time.monotonic() + timeout_seconds
        process.start()
        send.close()
        try:
            while True:
                if self.stopping.is_set() or document.pack_id in self.store.blocked:
                    raise StudyError('cancelled', 'Extraction cancelled for shutdown or purge.')
                if time.monotonic() >= deadline:
                    raise StudyError('timeout', 'This parser/page exceeded its deadline; completed page checkpoints are retained. Retry explicitly.')
                if receive.poll(0.05):
                    try:
                        result = receive.recv()
                    except EOFError as exc:
                        raise StudyError('extraction_failed', 'Extraction worker exited without a result.') from exc
                    if result[0] != 'ok':
                        raise StudyError(result[1], result[2])
                    return result[1]
                if not process.is_alive():
                    raise StudyError('extraction_failed', 'Extraction worker exited without a result.')
        finally:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            receive.close()
            process.close()

    def _parse_pdf(self,document):
        from .visual.storage import VisualStore
        from .visual.schema import digest
        VisualStore(self.store,document.pack_id)
        count=self._step(document,_pdf_count,self.store.limits,self.store.limits.page_timeout_seconds)
        units,assets,warnings,total,size=[],[],[],0,0
        for number in range(1,count+1):
            with self.store.lease(document.pack_id,require_ready=False):
                if not self.store.document(document.pack_id,document.document_id).active: raise StudyError('cancelled','Document deactivated.')
                with self.store.db(document.pack_id) as db:
                    row=db.execute('SELECT payload FROM visual_pages WHERE document_id=? AND page=?',(document.document_id,number)).fetchone()
                folder=contained(self.store.root,document.pack_id,'visual',document.document_id,'pages'); folder.mkdir(parents=True,exist_ok=True)
                if row:
                    data=json.loads(row[0]); unit=unit_from_dict(data['unit'])
                    asset=None
                    if data.get('asset'):
                        info=data['asset']; content=contained(folder,info['asset_id']).read_bytes()
                        if digest(content)!=info['checksum']: raise StudyError('source_changed','Checkpoint render changed; re-ingest PDF.')
                        asset=Asset(info['asset_id'],unit.unit_id,'image/png',content,info['coordinates'])
                else:
                    extracted=self._step(document,_pdf_page_step,(self.store.limits,number),self.store.limits.page_timeout_seconds)
                    warnings.extend(extracted.warnings)
                    unit=extracted.units[0]; asset=extracted.assets[0] if extracted.assets else None
                    if asset and size+len(asset.content)>self.store.limits.max_visual_bytes:
                        unit=replace(unit,asset_ids=()); asset=None
                        warnings.append(f'Page {number}: visual asset budget exhausted; text retained, preview unavailable.')
                    data={'unit':asdict(unit),'asset':None}
                    if asset:
                        contained(folder,asset.asset_id).write_bytes(asset.content)
                        data['asset']={'asset_id':asset.asset_id,'coordinates':asset.coordinates,'checksum':digest(asset.content)}
                    with self.store.lock,self.store.db(document.pack_id) as db:
                        self.store.assert_available(document.pack_id)
                        db.execute('INSERT OR REPLACE INTO visual_pages VALUES (?,?,?)',(document.document_id,number,json.dumps(data)))
                units.append(unit)
                total+=max(len(unit.text),len(unit.metadata.get('raw_text','')))
                if total>10_000_000: raise StudyError('limit','PDF extracted text exceeds safety limit.')
                if asset: assets.append(asset); size+=len(asset.content)
                if not unit.text: warnings.append(f'Page {number}: no native text; retained preview is uninterpreted. Start OCR/vision explicitly.')
        if not assets and not any(unit.text.strip() for unit in units):
            raise StudyError('ocr_required','PDF has no native text or usable previews. Install the visual extra, re-ingest, then start OCR explicitly.')
        return Extraction(units,assets,warnings,{'units':len(units),'text_units':sum(bool(u.text) for u in units),'visual_units':len(assets),'visual_bytes':size},'pdf-page-v1')

    def run_once(self):
        with self.run_lock:
            job = next((job for pack in self.store.worker_packs()
                        if pack.state != 'purge-pending' and pack.pack_id not in self.store.blocked
                        for job in self.store.jobs(pack.pack_id) if job.state == 'queued' and job.kind != 'visual'), None)
            if job is None:
                return False
            try:
                prepared=None
                if job.kind=='extract':
                    doc=self.store.document(job.pack_id,job.document_id)
                    if doc.kind=='pdf' and self.extractor is extract_document:
                        self.store.update_job(replace(job,state='extracting'))
                        self.store.update_document(replace(doc,state='extracting'))
                        try:
                            prepared=self._parse(doc)  # Per-page leases/deadlines, never a document-wide 180s lease.
                        except Exception as exc:
                            detail=f'{exc.code}: {exc}' if isinstance(exc,StudyError) else f'PDF processing failed ({type(exc).__name__}).'
                            self.store.update_job(replace(job,state='failed',error=detail))
                            self.store.update_document(replace(doc,state='failed',warnings=doc.warnings+[detail]))
                            return True
                with self.store.lease(job.pack_id, require_ready=False):
                    try:
                        if job.kind == 'extract':
                            doc = self.store.document(job.pack_id, job.document_id)
                            if not doc.active:
                                raise StudyError('cancelled', 'Document deactivated.')
                            self.store.update_job(replace(job, state='extracting'))
                            self.store.update_document(replace(doc, state='extracting'))
                            extraction = prepared if prepared is not None else self._parse(doc)
                            self.store.publish_extraction(doc.document_id, extraction)
                            self.store.update_job(replace(job, state='extracted'))
                        self.store.update_job(replace(job, state='indexing'))
                        wants_dense = (job.kind == 'dense' or self.store.get_pack(job.pack_id).state == 'hybrid-ready'
                                       or os.environ.get('AURA_STUDY_INDEX_MODE', 'hybrid') != 'sparse')
                        encoder, warning = None, None
                        if wants_dense:
                            try:
                                encoder = cached_encoder()
                            except Exception as exc:
                                if job.kind == 'dense':
                                    raise  # Explicit dense retries must not falsely succeed.
                                warning = f'Cached CPU embedding unavailable ({type(exc).__name__}); sparse-only fallback. Retry dense indexing after configuring the local cache.'
                        StudyIndexer(self.store).build(job.pack_id, dense_encoder=encoder)
                        ready = self.store.get_pack(job.pack_id).state
                        self.store.update_job(replace(job, state=ready, error=warning))
                        if warning and job.document_id:
                            doc = self.store.document(job.pack_id, job.document_id)
                            self.store.update_document(replace(doc, warnings=doc.warnings + [warning]))
                    except Exception as exc:
                        detail = f'{exc.code}: {exc}' if isinstance(exc, StudyError) else f'Indexing failed ({type(exc).__name__}); previous snapshot retained.'
                        self.store.update_job(replace(job, state='failed', error=detail))
                        if job.document_id:
                            doc = self.store.document(job.pack_id, job.document_id)
                            self.store.update_document(replace(doc, state='failed', warnings=doc.warnings + [detail]))
            except StudyError:
                return False  # Pack was removed/blocked before the worker acquired its lease.
            return True
