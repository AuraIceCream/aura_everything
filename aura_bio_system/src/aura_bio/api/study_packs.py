"""Local private study APIs. Intake never initialises the core model runtime."""
from contextlib import ExitStack, asynccontextmanager
from dataclasses import asdict
from pathlib import Path
import os
import threading
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ..study.schema import StudyError
from ..study.storage import StudyStore
from ..study.jobs import StudyJobs
from ..study.searcher import StudySearcher

_services = None
_attachments = None
_lock = threading.RLock()
_running = False


def study_services():
    global _services, _attachments
    root = Path(os.environ.get('AURA_STUDY_ROOT', '.local/study-packs')).resolve()
    with _lock:
        if _services is None or _services[0].root != root:
            shutdown_study()
            store = StudyStore(root)
            from ..study.attachments import AttachmentService
            def invalidate(pack_id):
                from .app import forget_pack_runs
                forget_pack_runs(pack_id)
            try:
                ttl = int(os.environ.get('AURA_ATTACHMENT_TTL_SECONDS', '3600'))
            except ValueError as exc:
                raise StudyError('invalid_config', 'Invalid attachment TTL setting.') from exc
            attachments = AttachmentService(store, ttl_seconds=ttl, invalidate=invalidate)
            _services = store, StudyJobs(store)
            _attachments = attachments
            _attachments.sweep()
            if _running:
                _attachments.start()
                _services[1].start()
        return _services


def attachment_services():
    study_services()
    return _attachments


def shutdown_study():
    global _services, _attachments
    with _lock:
        if _attachments is not None:
            _attachments.stop()
            _attachments = None
        from .study_visual import shutdown_visual
        shutdown_visual()
        if _services is not None:
            _services[1].stop()
            _services[0].close()
            _services = None


@asynccontextmanager
async def study_lifespan(app):
    global _running
    _running = True
    # Lazy: no model or even private storage is opened until first pack request.
    try:
        yield
    finally:
        shutdown_study()
        _running = False


def private_origin(request: Request):
    origin = request.headers.get('origin')
    if origin is None and request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Cross-site navigation cannot access private study data.')
    if origin is None and request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Cross-site navigation cannot access private study data.')
    default = ','.join(f'http://{host}:{port}' for host in ('localhost', '127.0.0.1') for port in (5173, 4173, 8000))
    allowed = {value.strip() for value in os.environ.get('AURA_STUDY_ALLOWED_ORIGINS', default).split(',')}
    if origin is not None and origin not in allowed:
        raise HTTPException(403, 'Private study data is available only to the configured local UI origins.')


def study_http_error(exc: StudyError):
    status = {'not_found': 404, 'not_ready': 409, 'limit': 413, 'unsupported_format': 415,
              'purge_failed': 409, 'attachment_expired': 410, 'saved_attachment': 409,
              'busy_gpu': 409, 'busy_memory': 409, 'model_unavailable': 503}.get(exc.code, 422)
    return HTTPException(status, {'code': exc.code, 'message': str(exc)})


router = APIRouter(prefix='/api/v1', dependencies=[Depends(private_origin)])


class NewPack(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    domain: Literal['general', 'biology'] = 'general'


class Confirmation(BaseModel):
    confirmation: str


class PackSearch(BaseModel):
    query: str = Field(min_length=1, max_length=10000)
    mode: str = 'hybrid'


class IndexRequest(BaseModel):
    dense: bool = False


@router.post('/study-packs', status_code=201)
def create_pack(body: NewPack):
    return asdict(study_services()[0].create_pack(body.name, body.domain))


@router.get('/study-packs')
def list_packs():
    return {'packs': [asdict(pack) for pack in study_services()[0].list_packs()]}


@router.get('/study-packs/{pack_id}')
def pack_detail(pack_id: str):
    store, _ = study_services()
    with store.lock:
        pack = store.get_pack(pack_id)
        # Recovery must remain reachable when cleanup removed the metadata file.
        docs = [] if pack.state == 'purge-pending' else [asdict(doc) for doc in store.documents(pack_id)]
        return {**asdict(pack), 'documents': docs, 'pending_purge': store.pending_purge(pack_id)}


@router.post('/study-packs/{pack_id}/documents', status_code=202)
def upload(pack_id: str, file: UploadFile):
    store, _ = study_services()
    try:
        document, job = store.add_document(pack_id, file.filename or '', file.file)
        return {'document': asdict(document), 'job': asdict(job) if job else None, 'deduplicated': job is None}
    finally:
        file.file.close()


@router.get('/study-packs/{pack_id}/documents')
def documents(pack_id: str):
    store, _ = study_services()
    with store.lease(pack_id, require_ready=False):
        return {'documents': [asdict(doc) for doc in store.documents(pack_id)]}


@router.get('/study-packs/{pack_id}/documents/{document_id}')
def document(pack_id: str, document_id: str):
    store, _ = study_services()
    with store.lease(pack_id, require_ready=False):
        return asdict(store.document(pack_id, document_id))


@router.get('/study-packs/{pack_id}/documents/{document_id}/units')
def units(pack_id: str, document_id: str, offset: int = 0, limit: int = 100):
    store, _ = study_services()
    with store.lease(pack_id, require_ready=False):
        rows = store.units(pack_id, document_id)
        return {'units': [asdict(unit) for unit in rows[max(0, offset):max(0, offset) + min(100, max(1, limit))]], 'total': len(rows)}


@router.get('/study-packs/{pack_id}/documents/{document_id}/units/{unit_id}')
def unit(pack_id: str, document_id: str, unit_id: str):
    from ..study.validation import validate_id
    validate_id(unit_id)
    store, _ = study_services()
    with store.lease(pack_id, require_ready=False):
        result = next((row for row in store.units(pack_id, document_id) if row.unit_id == unit_id), None)
        if result is None:
            from ..study.visual.storage import VisualStore
            result=VisualStore(store,pack_id).revision(unit_id)
            if result.document_id!=document_id: raise StudyError('not_found','Source revision belongs to another document.')
        return asdict(result)


def _private_file(store, pack_id, path_fn, mime, filename=None):
    stack = ExitStack()
    try:
        stack.enter_context(store.lease(pack_id, require_ready=False))
        handle = stack.enter_context(path_fn().open('rb'))
    except Exception:
        stack.close()
        raise
    def chunks():
        try:
            while data := handle.read(65536):
                yield data
        finally:
            stack.close()
    headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
    if filename:
        headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
    return StreamingResponse(chunks(), media_type=mime, headers=headers, background=BackgroundTask(stack.close))


@router.get('/study-packs/{pack_id}/documents/{document_id}/original')
def original(pack_id: str, document_id: str):
    store, _ = study_services()
    doc = store.document(pack_id, document_id)
    return _private_file(store, pack_id, lambda: store.original_path(pack_id, document_id), 'application/octet-stream', doc.filename)


@router.get('/study-packs/{pack_id}/documents/{document_id}/assets/{asset_id}')
def asset(pack_id: str, document_id: str, asset_id: str):
    store, _ = study_services()
    info = store.asset(pack_id, document_id, asset_id)
    if info['mime_type'] not in {'image/png', 'image/jpeg', 'image/gif'}:
        raise HTTPException(415, 'This asset is not a previewable raster image.')
    return _private_file(store, pack_id, lambda: store.asset_path(pack_id, document_id, asset_id), info['mime_type'])


@router.post('/study-packs/{pack_id}/documents/{document_id}/deactivate', status_code=202)
def deactivate(pack_id: str, document_id: str):
    return asdict(study_services()[0].deactivate(pack_id, document_id))


def purge_pack(pack_id, document_id, confirmation):
    # Marking pending and cache invalidation are atomic wrt request execution leases.
    from .app import forget_pack_runs
    store, _ = study_services()
    result = store.purge(pack_id, document_id, confirmation=confirmation)
    forget_pack_runs(pack_id)
    return asdict(result)


@router.delete('/study-packs/{pack_id}')
def purge(pack_id: str, body: Confirmation):
    return purge_pack(pack_id, None, body.confirmation)


@router.delete('/study-packs/{pack_id}/documents/{document_id}')
def purge_document(pack_id: str, document_id: str, body: Confirmation):
    return purge_pack(pack_id, document_id, body.confirmation)


@router.post('/study-packs/{pack_id}/search')
def search(pack_id: str, body: PackSearch):
    from .mapping import evidence_to_citation
    store, _ = study_services()
    with store.lease(pack_id):
        # Never initialise the core corpus or fetch a missing model.
        encoder = None
        warnings = []
        if body.mode != 'bm25' and store.get_pack(pack_id).state == 'hybrid-ready':
            from ..study.jobs import cached_encoder
            try:
                encoder = cached_encoder()
            except Exception as exc:
                warnings.append(f'Cached embedding unavailable ({type(exc).__name__}); sparse-only query.')
        with StudySearcher(store, pack_id, dense_encoder=encoder) as searcher:
            hits = searcher.search(body.query, top_k=100, candidate_k=100)
            report = None
            if body.mode != 'bm25':
                from ..study.reranking import configured_reranker
                try:
                    reranker = configured_reranker()
                except Exception as exc:
                    reranker = None
                    warnings.append(f'Cached CPU reranker unavailable ({type(exc).__name__}); reranking skipped.')
                if reranker is not None:
                    hits, report = reranker.rerank(body.query, hits, 10)
                elif not warnings:
                    warnings.append('Study reranking is disabled.')
            hits = hits[:10]
            return {'query': body.query, 'mode': searcher.mode, 'generation': searcher.generation,
                    'embedding_model': getattr(encoder, 'model_name', None),
                    'rerank': report.as_dict() if report is not None else None,
                    'warnings': searcher.runtime_warnings + warnings,
                    'results': [{**evidence_to_citation(hit, rank), 'text': hit.text} for rank, hit in enumerate(hits, 1)]}


@router.post('/study-packs/{pack_id}/index', status_code=202)
def index(pack_id: str, body: IndexRequest):
    store, jobs = study_services()
    with store.lock:
        store.assert_available(pack_id)
        job = jobs.request_dense_index(pack_id) if body.dense else store.enqueue(pack_id, kind='index')
        return asdict(job)


@router.get('/study-jobs/{job_id}')
def job(job_id: str):
    return asdict(study_services()[0].job(job_id))


@router.post('/study-jobs/{job_id}/retry', status_code=202)
def retry(job_id: str):
    return asdict(study_services()[1].retry(job_id))
