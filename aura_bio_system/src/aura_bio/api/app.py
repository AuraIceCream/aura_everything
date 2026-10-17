"""FastAPI backend serving the AURA-Bio frontend against the real runtime.

Endpoints mirror the contract the React app already expects
(`frontend/src/lib/api.ts`). Runs execute the real pipeline synchronously and
are cached; the SSE endpoint replays the real trace and streams the real answer,
so the frontend's progressive experience is backed by genuine routing,
retrieval, and verification rather than mock data.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import ExitStack
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator
from .study_packs import router as study_router, study_lifespan, study_services, private_origin, study_http_error
from ..study.schema import StudyError

from .. import __version__
from . import mapping
from .state import benchmark_count, corpus_snapshot, get_runtime

app = FastAPI(title="AURA-Bio API", version=__version__, lifespan=study_lifespan)
app.include_router(study_router)
from .study_visual import router as study_visual_router
app.include_router(study_visual_router)
from .study_attachments import router as attachment_router
app.include_router(attachment_router)


@app.middleware('http')
async def private_study_cache(request,call_next):
    response=await call_next(request)
    if request.url.path.startswith(('/api/v1/study-packs','/api/v1/study-jobs','/api/v1/study-attachments','/api/v1/runs')):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
    return response


@app.exception_handler(StudyError)
async def study_error(request, exc):
    error = study_http_error(exc)
    return JSONResponse(status_code=error.status_code, content={'detail': error.detail}, headers={'Cache-Control': 'no-store'})


class PrivateUploadLimit:
    """Bound multipart bytes before Starlette spools an upload to disk."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        private = '/study-packs' in path or '/study-jobs' in path or '/study-attachments' in path
        if scope['type'] != 'http' or not private:
            return await self.app(scope, receive, send)
        try:
            private_origin(Request(scope))
        except HTTPException as exc:
            return await JSONResponse({'detail': exc.detail}, exc.status_code, headers={'Cache-Control': 'no-store'})(scope, receive, send)
        try:
            private_origin(Request(scope))
        except HTTPException as exc:
            return await JSONResponse({'detail': exc.detail}, exc.status_code, headers={'Cache-Control': 'no-store'})(scope, receive, send)
        from ..study.schema import Limits
        limit = Limits().max_upload_bytes + 1024 * 1024  # bounded multipart overhead
        headers = dict(scope.get('headers', []))
        try:
            too_large = int(headers.get(b'content-length', b'0')) > limit
        except ValueError:
            too_large = True
        if too_large:
            return await JSONResponse({'detail': 'Upload exceeds the file limit.'}, 413)(scope, receive, send)
        total = 0
        async def bounded_receive():
            nonlocal total
            message = await receive()
            total += len(message.get('body', b''))
            if total > limit:
                raise HTTPException(413, 'Upload exceeds the file limit.')
            return message
        async def private_send(message):
            if message['type'] == 'http.response.start':
                message['headers'] = [(key, value) for key, value in message.get('headers', []) if key.lower() != b'cache-control'] + [(b'cache-control', b'no-store')]
            await send(message)
        await self.app(scope, bounded_receive, private_send)


app.add_middleware(PrivateUploadLimit)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Completed runs, keyed by run_id. Bounded so a long-lived server does not grow
# without limit; this is a single-user local tool, not a multi-tenant service.
_RUNS: dict[str, dict[str, Any]] = {}
_RUN_ORDER: list[str] = []
_MAX_RUNS = 200


class RunRequestModel(BaseModel):
    query: str = Field(min_length=1)
    learner_level: str = "high_school"
    teaching_mode: str = "guided"
    response_length: str = "balanced"
    context_depth: str = "standard"
    source_types: list[str] = Field(default_factory=list)
    allow_external_critic: bool = False
    evidence_scope: Literal['core', 'pack_only'] = 'core'
    pack_id: str | None = None
    attachment_id: str | None = None
    context_pack_id: str | None = None
    think: bool = Field(default=False, strict=True)
    figure_ids: list[str] = Field(default_factory=list,max_length=8)
    answer_mode: Literal['tutor', 'strict'] = 'tutor'
    visual_output: Literal['none', 'auto', 'source', 'diagram', 'comparison', 'procedure', 'plot'] = 'none'

    @model_validator(mode='after')
    def coherent_scope(self):
        if (self.evidence_scope == 'pack_only') != bool(self.pack_id):
            raise ValueError('pack_only requires pack_id; core must not specify a pack.')
        if self.attachment_id and (self.evidence_scope != 'pack_only' or self.attachment_id != self.pack_id):
            raise ValueError('An image requires pack_only with its own pack_id.')
        if self.context_pack_id and (not self.attachment_id or self.context_pack_id == self.attachment_id):
            raise ValueError('Context requires an image and a different saved pack.')
        if self.attachment_id and len(self.query) > 4000:
            raise ValueError('Image questions are limited to 4000 characters.')
        if self.figure_ids and self.evidence_scope!='pack_only':
            raise ValueError('Figure sources must belong to selected study material.')
        if self.figure_ids and self.attachment_id:
            raise ValueError('Attached images use their bound image preparation, not document figure IDs.')
        return self


class SearchRequestModel(BaseModel):
    query: str = Field(min_length=1)
    mode: str = "hybrid"
    source_type: str | None = None
    evidence_scope: Literal['core', 'pack_only'] = 'core'
    pack_id: str | None = None


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    runtime = get_runtime()
    if runtime.index_ready:
        status = "ready"
    elif runtime.sparse_ready or runtime.dense_ready:
        status = "partial"
    else:
        status = "offline"
    return {
        "status": status,
        "backend": True,
        "model": runtime.generator_kind != "extractive",
        "retrieval": runtime.searcher is not None,
        "index_ready": runtime.index_ready,
        "version": __version__,
    }


@app.get("/api/v1/capabilities")
def capabilities() -> dict[str, Any]:
    runtime = get_runtime()
    return {
        "local_models": [runtime.model_name],
        "teaching_modes": ["direct", "guided", "socratic", "exam", "revision", "research", "teach_back"],
        "retrieval_modes": ["bm25", "dense", "hybrid", "reranked"],
        "external_critic_available": runtime.critic_name is not None,
        "external_critic": runtime.critic_name,
        "benchmark_questions": benchmark_count(),
        "generator": runtime.generator_kind,
    }


@app.get("/api/v1/corpus/status")
def corpus_status() -> dict[str, Any]:
    return corpus_snapshot()


@app.post("/api/v1/runs", status_code=202)
def create_run(request: RunRequestModel, http: Request) -> dict[str, str]:
    if request.evidence_scope == 'pack_only':
        private_origin(http)
        store, _ = study_services()
        # Keep the run cache publication inside the same purge-protected lease.
        with ExitStack() as stack:
            for pack_id in sorted(_dependencies(request.model_dump())):
                stack.enter_context(store.lease(pack_id))
            if request.attachment_id:
                stack.enter_context(store.inference(request.attachment_id, 'answer', wait_for_visual=True))
                from .study_packs import attachment_services
                attachments = attachment_services()
                attachments._owned(request.attachment_id)
                if any(j.kind == 'visual' and j.state in {'queued', 'running'} for j in store.jobs(request.attachment_id)):
                    raise StudyError('not_ready', 'Visual processing is active; answering must wait for its explicit job to finish.')
                if not attachments.indexed_for(request.attachment_id, request.query):
                    raise StudyError('not_ready', 'Process this image for the bound question before answering; context alone is not sufficient.')
                if request.context_pack_id and store.get_pack(request.context_pack_id).retention != 'saved':
                    raise StudyError('invalid_config', 'Context must be saved study material.')
            if request.figure_ids:
                from ..study.visual.storage import VisualStore
                if not request.attachment_id:
                    stack.enter_context(store.inference(request.pack_id,'answer',wait_for_visual=True))
                visual=VisualStore(store,request.pack_id)
                visual.indexed_units(request.figure_ids,question=request.query)
            return _create_run(request)
    return _create_run(request)


def _create_run(request: RunRequestModel) -> dict[str, str]:
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    try:
        answer = _execute(request)
    except (HTTPException, StudyError):
        raise
    except Exception as exc:
        if request.evidence_scope == 'pack_only':
            # Private content and model errors must not escape to server logs.
            raise HTTPException(503, 'Private pipeline failed; check local component availability.') from exc
        # An exception escaping this handler is returned by Starlette's
        # outermost error middleware, which sits *outside* CORSMiddleware and
        # therefore emits a bare 500 with no Access-Control-Allow-Origin
        # header. A browser then reports it as a CORS failure, which sends
        # anyone debugging it after the wrong problem entirely. Convert it to
        # an ordinary HTTP error so the real reason reaches the caller.
        import traceback

        detail = f"{type(exc).__name__}: {exc}"
        print(f"[aura-api] run failed: {detail}", flush=True)
        traceback.print_exc()
        if isinstance(exc, (MemoryError, OSError)):
            # os error 1455 on Windows is "the paging file is too small",
            # which here means the machine ran out of room to load a model.
            raise HTTPException(
                status_code=503,
                detail=(
                    "Out of memory loading a model. Free RAM, or start the API "
                    "with fewer components: AURA_RERANK=0 drops the "
                    "cross-encoder, AURA_ROUTER=rules drops the router "
                    f"encoders, AURA_DENSE=0 drops the dense index. ({detail})"
                ),
            ) from exc
        raise HTTPException(status_code=500, detail=detail) from exc
    run = {
        "run_id": run_id,
        "status": "completed" if answer["decision"] != "error" else "failed",
        "query": request.query,
        "request": request.model_dump(),
        "answer": answer["answer_payload"],
        "trace": answer["events"],
        "markdown": answer["answer_payload"]["markdown"],
        "created_at": answer["created_at"],
        "summary": answer["summary"],
        "source_pack_ids": _dependencies(request.model_dump()),
    }
    if request.evidence_scope == 'pack_only':
        store, _ = study_services()
        with store.lock:
            _guard_run(run, store)
            _remember(run_id, run)
    else:
        _remember(run_id, run)
    return {"run_id": run_id, "status": "queued"}


@app.get("/api/v1/runs")
def list_runs(http: Request, limit: int = 25) -> dict[str, Any]:
    """Recent runs, newest first.

    The interface used to fill its "recent runs", teaching-quality and failure
    panels from bundled sample data. This endpoint is what lets those panels
    show what the system has actually done instead.
    """

    recent = []
    for run_id in reversed(_RUN_ORDER[-max(1, min(limit, _MAX_RUNS)):]):
        run = _RUNS.get(run_id)
        if run is None:
            continue
        if run.get('request', {}).get('evidence_scope') == 'pack_only':
            private_origin(http)
            try:
                _guard_run(run, study_services()[0])
            except StudyError:
                _forget(run_id)
                continue
        recent.append(
            {
                "run_id": run_id,
                "query": run["query"],
                "status": run["status"],
                "created_at": run["created_at"],
                "evidence_scope": run.get('request', {}).get('evidence_scope', 'core'),
                "pack_id": run.get('request', {}).get('pack_id'),
                "external_critic_used": bool(
                    run.get("request", {}).get("allow_external_critic")
                ),
                **(run.get("summary") or {}),
            }
        )
    return {"runs": recent, "total": len(_RUN_ORDER)}


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, http: Request) -> dict[str, Any]:
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.get('request', {}).get('evidence_scope') == 'pack_only':
        private_origin(http)
        store, _ = study_services()
        with ExitStack() as stack:
            for pack_id in sorted(_dependencies(run)):
                stack.enter_context(store.lease(pack_id))
            return {k: v for k, v in run.items() if k != 'markdown'}
    return {k: v for k, v in run.items() if k != "markdown"}


@app.get("/api/v1/runs/{run_id}/events")
async def run_events(run_id: str, http: Request) -> StreamingResponse:
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.get('request', {}).get('evidence_scope') == 'pack_only':
        private_origin(http)
        from starlette.background import BackgroundTask
        stack = ExitStack()
        store, _ = study_services()
        try:
            for pack_id in sorted(_dependencies(run)):
                stack.enter_context(store.lease(pack_id))
        except Exception:
            stack.close()
            raise
        async def leased_stream():
            try:
                async for item in _stream(run):
                    try:
                        _guard_run(run, store)
                    except StudyError as exc:
                        _forget(run_id)
                        yield _sse({'type': 'run.invalidated', 'code': exc.code, 'message': 'Private source expired or was removed; answer cleared.'})
                        return
                    yield item
            finally:
                stack.close()
        return StreamingResponse(leased_stream(), media_type='text/event-stream',
            headers={'Cache-Control': 'no-store'}, background=BackgroundTask(stack.close))
    return StreamingResponse(_stream(run), media_type="text/event-stream")


@app.get("/api/v1/evaluation/summary")
def evaluation_summary() -> dict[str, Any]:
    """Benchmark composition and the SRS 25 four-system definitions."""

    from ..evaluation import all_questions
    import collections

    questions = all_questions()
    by_subdomain = collections.Counter(q.subdomain for q in questions)
    by_task = collections.Counter(q.task_type for q in questions)
    by_level = collections.Counter(q.level for q in questions)
    by_difficulty = collections.Counter(str(q.difficulty) for q in questions)
    return {
        "total": len(questions),
        "by_subdomain": dict(sorted(by_subdomain.items(), key=lambda kv: -kv[1])),
        "by_task_type": dict(by_task),
        "by_level": dict(by_level),
        "by_difficulty": dict(by_difficulty),
        "numeric_items": sum(1 for q in questions if q.answer_key.numeric is not None),
        "process_items": sum(1 for q in questions if q.answer_key.ordered_steps),
        "adversarial_items": sum(1 for q in questions if q.adversarial),
        "systems": [
            {"id": "baseline", "label": "Baseline model",
             "detail": "Raw local model, no retrieval", "srs_config": 1},
            {"id": "basic_rag", "label": "Basic RAG",
             "detail": "Hybrid retrieval only, no rerank or verification", "srs_config": 4},
            {"id": "full_rag", "label": "Full pipeline",
             "detail": "Routing, rerank, verification, critique, revision", "srs_config": 10},
            {"id": "finetuned_rag", "label": "Finetuned + RAG",
             "detail": "Full pipeline on a LoRA-adapted model", "srs_config": 11},
        ],
        "metrics": [
            "overall", "concept_recall", "numeric_accuracy",
            "process_order_accuracy", "hallucination_rate", "median_latency_ms",
        ],
    }


@app.post("/api/v1/retrieval/search")
def retrieval_search(request: SearchRequestModel, http: Request) -> dict[str, Any]:
    if request.evidence_scope == 'pack_only':
        private_origin(http)
        if not request.pack_id:
            raise HTTPException(422, 'pack_only requires pack_id.')
        from .study_packs import search, PackSearch
        return search(request.pack_id, PackSearch(query=request.query, mode=request.mode))
    if request.pack_id:
        raise HTTPException(422, 'Core search must not specify a pack.')
    runtime = get_runtime()
    if runtime.searcher is None:
        raise HTTPException(status_code=503, detail="retrieval index not available")
    import time

    use_dense = request.mode in ("dense", "hybrid", "reranked")
    started = time.perf_counter()
    results = runtime.searcher.search(
        request.query, top_k=30 if request.mode == "reranked" else 10, use_dense=use_dense
    )
    if request.mode == "reranked" and runtime.reranker is not None and results:
        results, _ = runtime.reranker.rerank(request.query, results, 10)
    latency = (time.perf_counter() - started) * 1000
    shaped = []
    for rank, item in enumerate(results, 1):
        if request.source_type and mapping.source_type(item.source_id) != request.source_type:
            continue
        citation = mapping.evidence_to_citation(item, rank)
        shaped.append(
            {
                **citation,
                "text": item.text,
                "mode": request.mode,
                "score": round(item.rerank_score if item.rerank_score is not None else item.rrf_score, 4),
                "bm25_rank": item.core_bm25_rank or item.pubmed_bm25_rank,
                "dense_rank": item.dense_rank,
                "hybrid_rank": rank,
                "reranked_rank": rank if request.mode == "reranked" else None,
            }
        )
    return {"query": request.query, "mode": request.mode, "latency_ms": round(latency, 1), "results": shaped}


# -- internals --------------------------------------------------------------


def _execute(request: RunRequestModel) -> dict[str, Any]:
    if request.evidence_scope == 'pack_only':
        from ..study.runtime import build_pack_pipeline
        store, _ = study_services()
        with store.lease(request.pack_id):
            pipeline = build_pack_pipeline(store, request.pack_id, use_critic=request.allow_external_critic,
                attachment=bool(request.attachment_id), context_pack_id=request.context_pack_id, question=request.query,
                think=request.think,require_model=bool(request.figure_ids))
            try:
                if request.figure_ids:
                    pipeline.searcher.bind_figures(request.figure_ids,request.query)
                answer = pipeline.answer(request.query,
                    learner_level=mapping.learner_level(request.learner_level),
                    teaching_mode=mapping.teaching_mode(request.teaching_mode),
                    context_level=mapping.context_level(request.context_depth), use_critic=request.allow_external_critic,
                    answer_mode=request.answer_mode, visual_output=request.visual_output)
                return {'decision': answer.decision,
                    'answer_payload': mapping.answer_payload(answer, pipeline.model_name),
                    'events': mapping.trace_to_events(answer.trace, pipeline.model_name),
                    'created_at': mapping._iso(answer.trace.created_at), 'summary': _summarise(answer)}
            finally:
                pipeline.searcher.close()
                pipeline.store.close()
    runtime = get_runtime()
    # Never mutate the shared generator when one request enables thinking.
    from copy import copy
    from .generation import OllamaGenerator
    pipeline = copy(runtime.pipeline)
    if isinstance(pipeline.generator, OllamaGenerator):
        pipeline.generator = copy(pipeline.generator)
        pipeline.generator.think = request.think
        if request.think:
            pipeline.generator.num_predict = max(pipeline.generator.num_predict,4096)
            pipeline.generator.timeout = max(pipeline.generator.timeout,600)
    answer = pipeline.answer(
        request.query,
        learner_level=mapping.learner_level(request.learner_level),
        teaching_mode=mapping.teaching_mode(request.teaching_mode),
        context_level=mapping.context_level(request.context_depth),
        use_critic=request.allow_external_critic,
        visual_output=request.visual_output,
    )
    return {
        "decision": answer.decision,
        "answer_payload": mapping.answer_payload(answer, runtime.model_name),
        "events": mapping.trace_to_events(answer.trace, runtime.model_name),
        "created_at": mapping._iso(answer.trace.created_at),
        "summary": _summarise(answer),
    }


def _summarise(answer: Any) -> dict[str, Any]:
    """The per-run facts the teaching-quality and failure panels aggregate.

    Kept alongside the run rather than recomputed, because the trace it comes
    from is discarded once the run is evicted from the cache.
    """

    trace = answer.trace
    route = trace.route or {}

    def label(dimension: str) -> str | None:
        entry = route.get(dimension)
        return str(entry.get("label")) if isinstance(entry, dict) else None

    issues: list[dict[str, str]] = []
    for record in trace.revisions:
        for issue in (record.get("verification") or {}).get("issues", []):
            issues.append(
                {
                    "checker": str(issue.get("checker")),
                    "kind": str(issue.get("kind")),
                    "severity": str(issue.get("severity")),
                }
            )

    return {
        "decision": trace.decision,
        "confidence": round(float(trace.confidence), 3),
        "provenance": trace.provenance,
        "task_type": label("task_type"),
        "subdomain": label("subdomain"),
        "learner_level": label("learner_level"),
        "teaching_mode": label("teaching_mode"),
        "passes": len(trace.revisions),
        "revised": trace.revision_count > 0,
        "selected_revision": trace.selected_revision,
        "failure_category": trace.failure_category,
        "evidence_count": len(trace.evidence),
        "stage_ms": {k: round(v, 1) for k, v in trace.stage_ms.items()},
        "latency_ms": round(trace.latency_ms, 1),
    }


async def _stream(run: dict[str, Any]):
    events = run["trace"]
    answer = run["answer"]
    # Trace stages before generation, then stream the answer text, then the
    # remaining stages — the shape the frontend's mock stream used.
    pre = [e for e in events if e["stage"] not in ("verification", "critique", "revision", "complete")]
    post = [e for e in events if e["stage"] in ("verification", "critique", "revision", "complete")]
    for event in pre:
        yield _sse({"type": "trace", "event": event})
        await asyncio.sleep(0.12)
    markdown = answer["markdown"]
    step = max(1, len(markdown) // 60)
    for start in range(0, len(markdown), step):
        yield _sse({"type": "answer.delta", "delta": markdown[start : start + step]})
        await asyncio.sleep(0.02)
    for event in post:
        yield _sse({"type": "trace", "event": event})
        await asyncio.sleep(0.1)
    yield _sse({"type": "answer.completed", "answer": answer})


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _remember(run_id: str, run: dict[str, Any]) -> None:
    _RUNS[run_id] = run
    _RUN_ORDER.append(run_id)
    while len(_RUN_ORDER) > _MAX_RUNS:
        evicted = _RUN_ORDER.pop(0)
        _RUNS.pop(evicted, None)


def forget_pack_runs(pack_id):
    for run_id in list(_RUN_ORDER):
        if pack_id in _dependencies(_RUNS.get(run_id, {})):
            _forget(run_id)


def _dependencies(value):
    if 'source_pack_ids' in value:
        return value['source_pack_ids']
    request = value.get('request', value)
    return list(dict.fromkeys(p for p in (request.get('pack_id'), request.get('context_pack_id')) if p))


def _guard_run(run, store):
    for pack_id in _dependencies(run):
        store.assert_available(pack_id)


def _forget(run_id):
    _RUNS.pop(run_id, None)
    if run_id in _RUN_ORDER:
        _RUN_ORDER.remove(run_id)
