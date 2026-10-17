"""Private, explicitly started visual processing. No model code runs on GET/upload."""
import threading
import uuid
from dataclasses import asdict,replace
from fastapi import APIRouter,Depends,Response
from pydantic import BaseModel,Field,ConfigDict
from .study_packs import study_services,private_origin
from ..study.schema import StudyError
from ..study.visual.storage import VisualStore
from ..study.visual.jobs import VisualJobs
from ..study.visual.schema import NormalizedBox,VisualJobConfig,digest
from ..study.visual.assets import crop_bytes

router=APIRouter(prefix='/api/v1/study-packs',dependencies=[Depends(private_origin)])
_jobs=None
_lock=threading.RLock()


def visual_services():
    global _jobs
    store,_=study_services()
    with _lock:
        if _jobs is None or _jobs.store is not store:
            if _jobs: _jobs.stop()
            _jobs=VisualJobs(store); _jobs.recover()
        return _jobs


def shutdown_visual():
    global _jobs
    with _lock:
        if _jobs: _jobs.stop(); _jobs=None


class CropRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    figure_id: str
    bbox: dict[str,float]


class AnnotationRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text: str=Field(min_length=1,max_length=10000)


class StartRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    figure_ids: list[str]=Field(min_length=1,max_length=200)
    config: dict=Field(default_factory=dict)
    preview_hash: str | None=None


class PermissionRequest(BaseModel):
    allowed: bool


class VisualQuestionRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    question: str=Field(min_length=1,max_length=4000)


@router.post('/{pack_id}/visual-question')
def resolve_question(pack_id:str,body:VisualQuestionRequest):
    """Resolve only. Clicking Ask subsequently starts the ordinary visual job."""
    from ..study.questions import references,scoped_units
    store,_=study_services()
    with store.lease(pack_id,require_ready=False):
        refs=references(body.question)
        relevant=[ref for ref in refs if ref.kind in {'figure','table'}]
        import re
        visual_query=bool(re.search(r'\b(?:fig(?:ure)?|diagram|graph|plot|image|flowchart|micrograph|gel)\b',body.question,re.I))
        if not relevant and not visual_query:
            return {'figures':[], 'warnings':[]}
        units=scoped_units(store,pack_id,body.question)
        if units == []:
            raise StudyError('unresolved_reference','The requested figure/page is absent or lacks an identifiable caption. Specify a page or inspect the source; no substitute figure was selected.')
        if units is None:
            from ..study.searcher import StudySearcher
            with StudySearcher(store,pack_id) as searcher:
                hits=searcher.search(body.question,3,30)
            ids={id for hit in hits for id in hit.unit_ids}
            units=[u for doc in store.documents(pack_id) if doc.active for u in store.units(pack_id,doc.document_id) if u.unit_id in ids]
        visual=VisualStore(store,pack_id)
        by_id={u.unit_id:u for u in units if u.provenance=='native_text'}
        targets=[]
        for doc_id in dict.fromkeys(u.document_id for u in by_id.values()):
            candidates=visual.figures(doc_id)
            candidates=[f for f in candidates if f.unit_id in by_id and f.reason!='manual_crop']
            if relevant:
                matched=[]
                from ..study.questions import anchors
                for ref in relevant:
                    parents={u.unit_id for u in by_id.values() if any(a.get('kind','figure')==ref.kind and a['label']==ref.value for a in anchors(u))}
                    if not parents: continue
                    labelled=[f for f in candidates if f.unit_id in parents and f.figure_label==ref.value and f.reference_kind==ref.kind]
                    # An unlabeled FULL page can be inspected explicitly; an
                    # unrelated labelled crop or page union is never a substitute.
                    fallback=[f for f in candidates if f.unit_id in parents and not f.figure_label
                              and f.bbox==NormalizedBox() and f.reason!='caption_region']
                    if not labelled and not fallback:
                        raise StudyError('visual_unavailable',f'No identified crop or full-page view exists for {ref.kind} {ref.value}. Inspect the page and select a manual crop; no substitute figure was selected.')
                    matched.extend(labelled or fallback)
                candidates=matched
            candidates=[f for f in candidates if f.exclusion_reason not in {'tiny_image','repeated_logo','text_only'}]
            # Prefer current caption-owned candidates over historical page unions.
            candidates.sort(key=lambda f:(f.reason!='caption_region',not bool(f.figure_label)))
            seen=set()
            for f in candidates:
                key=(f.unit_id,f.figure_label,f.reference_kind)
                if key not in seen:
                    targets.append(f); seen.add(key)
        if not targets:
            raise StudyError('visual_unavailable','No usable rendered figure was found for this question. Inspect the page or re-ingest the PDF with rendering available.')
        if len(targets)>8:
            raise StudyError('limit','This question selects more than eight figure regions. Specify figures or pages for a bounded visual pass.')
        return {'figures':[asdict(f) for f in targets], 'warnings':visual.discovery_warnings}


def config_from(value):
    try: return VisualJobConfig(**value)
    except (TypeError,ValueError) as exc: raise StudyError('invalid_config','Invalid visual configuration; only documented fields are accepted, never API keys.') from exc


def owned(visual,document_id,figure_id):
    figure=visual.figure(figure_id)
    if figure.document_id!=document_id: raise StudyError('not_found','Figure does not belong to this document.')
    return figure


@router.get('/{pack_id}/documents/{document_id}/figures')
def figures(pack_id:str,document_id:str):
    store,_=study_services()
    with store.lease(pack_id,require_ready=False):
        visual=VisualStore(store,pack_id)
        rows=visual.figures(document_id)
        return {'figures':[asdict(f) for f in rows],'external_allowed':visual.permission(),
                'warnings':visual.discovery_warnings,
                'warning':'Model descriptions and OCR are not independently verified evidence. Embedded PPTX images use asset coordinates, not a full-slide render.'}


@router.post('/{pack_id}/documents/{document_id}/figures/crops',status_code=201)
def crop(pack_id:str,document_id:str,body:CropRequest):
    store,_=study_services()
    with store.lock:
        visual=VisualStore(store,pack_id); owned(visual,document_id,body.figure_id)
        try: box=NormalizedBox(**body.bbox)
        except TypeError as exc: raise StudyError('invalid_crop','Use x0,y0,x1,y1 upright normalized crop coordinates.') from exc
        return asdict(visual.add_crop(body.figure_id,box))


@router.get('/{pack_id}/documents/{document_id}/figures/{figure_id}/preview')
def preview(pack_id:str,document_id:str,figure_id:str):
    store,_=study_services()
    with store.lease(pack_id,require_ready=False):
        visual=VisualStore(store,pack_id); figure=owned(visual,document_id,figure_id)
        asset=visual.rendered_asset(document_id,figure.asset_id)
        return Response(crop_bytes(asset.content,figure.bbox),media_type='image/png',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.get('/{pack_id}/documents/{document_id}/figures/{figure_id}/revisions')
def revisions(pack_id:str,document_id:str,figure_id:str):
    store,_=study_services()
    with store.lease(pack_id,require_ready=False):
        visual=VisualStore(store,pack_id); owned(visual,document_id,figure_id)
        return {'revisions':visual.revisions(figure_id)}


@router.post('/{pack_id}/documents/{document_id}/figures/{figure_id}/annotations',status_code=201)
def annotate(pack_id:str,document_id:str,figure_id:str,body:AnnotationRequest):
    store,_=study_services()
    with store.lock:
        visual=VisualStore(store,pack_id); figure=owned(visual,document_id,figure_id)
        parent=next(u for u in store.units(pack_id,document_id) if u.unit_id==figure.unit_id)
        unit=replace(parent,unit_id=uuid.uuid4().hex,role='user_annotation',text=body.text,provenance='user_annotation',
                     asset_ids=(figure.asset_id,),metadata={},provenance_details={'figure_id':figure_id,'source_unit_id':parent.unit_id,'numbers_verified':False})
        revision=visual.publish_revision(unit,expected_source_hash=figure.checksum); visual.activate_revision(figure_id,revision)
        store.enqueue(pack_id,kind='index')
        return asdict(visual.revision(revision))


@router.put('/{pack_id}/visual-permission')
def permission(pack_id:str,body:PermissionRequest):
    store,_=study_services(); visual=VisualStore(store,pack_id)
    return {'external_allowed':visual.permission(body.allowed)}


def payload_preview(pack_id,body):
    store,_=study_services(); visual=VisualStore(store,pack_id); config=config_from(body.config)
    rows=[]
    for fid in body.figure_ids:
        f=visual.figure(fid); asset=visual.rendered_asset(f.document_id,f.asset_id)
        parent=next(u for u in store.units(pack_id,f.document_id) if u.unit_id==f.unit_id)
        ocr=visual.ocr_hint(f)
        raw=crop_bytes(asset.content,f.bbox,max_pixels=config.max_pixels)
        from ..study.visual.selection import figure_context
        rows.append({'figure_id':fid,'document_id':f.document_id,'bbox':asdict(f.bbox),'frame':f.frame,'image_bytes':len(raw),'crop_sha256':digest(raw),
                     'ocr_hint':ocr[:4000],'caption_hint':figure_context(parent,f),'source_snapshot':visual.snapshot_hash(f)})
    payload={'provider':config.provider,'model':config.model,'figures':rows,'prompt_version':config.prompt_version,'config':asdict(config),
             'disclosure':'Groq receives exactly these owned crops and untrusted hints plus the figure prompt. Local deletion cannot delete hosted logs/retention.'}
    return {**payload,'preview_hash':digest(payload)}


@router.post('/{pack_id}/visual-jobs/preview')
def job_preview(pack_id:str,body:StartRequest): return payload_preview(pack_id,body)


@router.get('/{pack_id}/visual-jobs')
def job_history(pack_id:str,document_id:str):
    jobs=visual_services(); visual=VisualStore(jobs.store,pack_id)
    jobs.store.document(pack_id,document_id)  # Validate ownership, including historical inactive sources.
    with jobs.store.lease(pack_id,require_ready=False),jobs.store.db(pack_id) as db:
        ids={row[0] for row in db.execute('SELECT DISTINCT job_id FROM visual_checkpoints WHERE document_id=?',(document_id,))}
        return {'jobs':[asdict(job) for job in reversed(jobs.store.jobs(pack_id)) if job.kind=='visual' and job.job_id in ids]}


@router.post('/{pack_id}/visual-jobs',status_code=202)
def start_job(pack_id:str,body:StartRequest):
    config=config_from(body.config)
    jobs=visual_services()
    with jobs.store.lock:
        if config.provider=='groq':
            preview=payload_preview(pack_id,body)
            if not body.preview_hash or preview['preview_hash']!=body.preview_hash: raise StudyError('consent_required','Preview and approve this exact hosted payload before starting. Crop/hint/config changes require a new preview.')
        result=jobs.start(pack_id,body.figure_ids,config)
    jobs.launch()
    return asdict(result)


def owned_job(pack_id,job_id):
    jobs=visual_services(); job=jobs.store.job(job_id)
    if job.pack_id!=pack_id or job.kind!='visual': raise StudyError('not_found','Visual job not found in this pack.')
    return jobs,job


@router.get('/{pack_id}/visual-jobs/{job_id}')
def job_status(pack_id:str,job_id:str):
    jobs,job=owned_job(pack_id,job_id); visual=VisualStore(jobs.store,pack_id)
    config,ids,usage=visual.job_data(job_id)
    checkpoints=visual.checkpoints(job_id)
    indexed=False
    if job.state=='completed':
        try:
            visual.indexed_units(ids,question=config.get('question') or None)
            indexed=True
        except StudyError as exc:
            if exc.code not in {'not_ready'}: raise
    pending=[j for j in jobs.store.jobs(pack_id) if j.kind!='visual']
    index_error=pending[-1].error if pending and pending[-1].state=='failed' else None
    return {**asdict(job),'config':config,'tokens_used':usage,'checkpoints':[asdict(c) for c in checkpoints],
            'indexed':indexed,'index_error':index_error}


@router.post('/{pack_id}/visual-jobs/{job_id}/pause')
def pause(pack_id:str,job_id:str): return asdict(owned_job(pack_id,job_id)[0].pause(job_id))


@router.post('/{pack_id}/visual-jobs/{job_id}/cancel')
def cancel(pack_id:str,job_id:str): return asdict(owned_job(pack_id,job_id)[0].cancel(job_id))


@router.post('/{pack_id}/visual-jobs/{job_id}/resume',status_code=202)
def resume(pack_id:str,job_id:str):
    jobs,job=owned_job(pack_id,job_id); visual=VisualStore(jobs.store,pack_id)
    config,_,_=visual.job_data(job_id); result=jobs.resume(job_id,config_from(config)); jobs.launch()
    return asdict(result)
