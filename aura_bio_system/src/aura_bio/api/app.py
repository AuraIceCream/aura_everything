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
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import __version__
from . import mapping
from .state import benchmark_count, corpus_snapshot, get_runtime

app = FastAPI(title="AURA-Bio API", version=__version__)

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


class SearchRequestModel(BaseModel):
    query: str = Field(min_length=1)
    mode: str = "hybrid"
    source_type: str | None = None


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
def create_run(request: RunRequestModel) -> dict[str, str]:
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    try:
        answer = _execute(request)
    except Exception as exc:
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
    }
    _remember(run_id, run)
    return {"run_id": run_id, "status": "queued"}


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {k: v for k, v in run.items() if k != "markdown"}


@app.get("/api/v1/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
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
def retrieval_search(request: SearchRequestModel) -> dict[str, Any]:
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
    runtime = get_runtime()
    answer = runtime.pipeline.answer(
        request.query,
        learner_level=mapping.learner_level(request.learner_level),
        teaching_mode=mapping.teaching_mode(request.teaching_mode),
        context_level=mapping.context_level(request.context_depth),
        use_critic=request.allow_external_critic,
    )
    return {
        "decision": answer.decision,
        "answer_payload": mapping.answer_payload(answer, runtime.model_name),
        "events": mapping.trace_to_events(answer.trace, runtime.model_name),
        "created_at": mapping._iso(answer.trace.created_at),
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
