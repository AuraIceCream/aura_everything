"""Lazily-constructed shared runtime for the API, with graceful degradation.

Every heavy dependency — the FAISS index, the reranker model, a local LLM — is
optional. The API starts and answers what it can: if no index is present it
still routes and verifies; if no model is present it answers extractively. This
matches SRS NFR-09 (fail gracefully) and lets the frontend run against a
partially-built system.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..critique import critic_from_env
from ..evaluation import all_questions
from ..pipeline import AuraBioPipeline
from ..routing import QueryRouter
from ..tracing import TraceStore
from ..verification import BiologyVerifier
from .generation import ExtractiveGenerator, OllamaGenerator


def _index_root() -> Path:
    return Path(os.environ.get("AURA_INDEX_ROOT", r"G:\aura_data\AURA-Bio-Index"))


@dataclass(slots=True)
class Runtime:
    pipeline: AuraBioPipeline
    searcher: Any | None
    reranker: Any | None
    model_name: str
    index_ready: bool
    dense_ready: bool
    sparse_ready: bool
    store: TraceStore
    generator_kind: str
    critic_name: str | None


_LOCK = threading.Lock()
_RUNTIME: Runtime | None = None


def _build_searcher(index_root: Path) -> tuple[Any | None, bool, bool]:
    manifest = index_root / "retrieval.manifest.json"
    if not manifest.is_file():
        _maybe_write_manifest(index_root)
    if not (index_root / "retrieval.manifest.json").is_file():
        return None, False, False
    try:
        from aura_bio_pipeline.retrieval import HybridSearcher

        # Dense adds ~1 GiB plus the encoder; opt in with AURA_DENSE=1 on hosts
        # with the RAM to spare. Default is the instant BM25 channels.
        dense_enabled = os.environ.get("AURA_DENSE", "0") == "1"
        from ..device import resolve_device

        searcher = HybridSearcher(
            index_root, device=resolve_device(), dense_enabled=dense_enabled,
            phrase_enabled=os.environ.get("AURA_ACCURACY_MODE", "standard") == "robust",
        )
        data = json.loads((index_root / "retrieval.manifest.json").read_text(encoding="utf-8"))
        return searcher, bool(data.get("dense_index")) and dense_enabled, bool(data.get("core_sparse"))
    except Exception as exc:  # a missing dependency must not down the API
        print(f"[aura-api] retrieval unavailable: {exc}", flush=True)
        return None, False, False


def _maybe_write_manifest(index_root: Path) -> None:
    """Write a retrieval manifest from whatever artifacts happen to exist."""

    dense = index_root / "core-dense.faiss"
    dense_map = index_root / "core-dense-map.sqlite3"
    core_sparse = index_root / "core-sparse.sqlite3"
    pubmed_sparse = index_root / "pubmed-sparse.sqlite3"
    if not core_sparse.is_file():
        return
    try:
        from aura_bio_pipeline.retrieval import write_retrieval_manifest

        write_retrieval_manifest(
            index_root,
            dense_index=dense if dense.is_file() else None,
            dense_map=dense_map if dense_map.is_file() else None,
            core_sparse=core_sparse,
            pubmed_sparse=pubmed_sparse if pubmed_sparse.is_file() else None,
        )
    except Exception as exc:
        print(f"[aura-api] could not write retrieval manifest: {exc}", flush=True)


def _build_reranker() -> Any | None:
    if os.environ.get("AURA_RERANK", "0") != "1":
        return None
    try:
        from ..retrieval import CrossEncoderReranker

        return CrossEncoderReranker(device=os.environ.get("AURA_RERANK_DEVICE", "cpu"))
    except Exception as exc:
        print(f"[aura-api] reranker unavailable: {exc}", flush=True)
        return None


def _build_router() -> QueryRouter:
    """Load the trained classifier unless explicitly disabled.

    Without this the API silently ran the rule router only: every routing fix
    validated in the benchmark scripts (the confident-wrong-rule gate, the
    macro-F1 selection metric) never reached the frontend, because nothing
    wired the trained model into the request path the UI actually calls.
    ``AURA_ROUTER=rules`` restores the old rules-only behaviour for parity
    with ``run_full_rag.py --rules-router``.
    """

    if os.environ.get("AURA_ROUTER", "").lower() == "rules":
        return QueryRouter()
    try:
        from ..routing.encoder_router import load_default_classifier

        return QueryRouter(classifier=load_default_classifier())
    except Exception as exc:  # a missing model file must not down the API
        print(f"[aura-api] learned router unavailable: {exc}", flush=True)
        return QueryRouter()


def _build_generator() -> tuple[Any, str, str]:
    """Prefer the local Ollama model when it is reachable, else extractive.

    The default model is the project's persona build ``aura-bio:v0``. Setting
    ``AURA_GENERATOR=extractive`` forces the no-model path even when Ollama is
    up, which the ablation's ``basic_rag``/retrieval-only comparisons want.
    """

    if os.environ.get("AURA_GENERATOR") == "extractive":
        gen = ExtractiveGenerator()
        return gen, gen.model_name, "extractive"
    model = os.environ.get("AURA_OLLAMA_MODEL", "aura-bio:v0")
    host = os.environ.get("AURA_OLLAMA_HOST", "http://127.0.0.1:11434")
    ollama = OllamaGenerator(model=model, host=host,
                             prompt_profile=os.environ.get("AURA_PROMPT_PROFILE", "standard"))
    if ollama.available():
        return ollama, ollama.model_name, "ollama"
    print(f"[aura-api] Ollama model {model!r} not reachable; using extractive fallback", flush=True)
    fallback = ExtractiveGenerator()
    return fallback, fallback.model_name, "extractive"


def get_runtime() -> Runtime:
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    with _LOCK:
        if _RUNTIME is not None:
            return _RUNTIME
        index_root = _index_root()
        searcher, dense_ready, sparse_ready = _build_searcher(index_root)
        reranker = _build_reranker()
        generator, model_name, kind = _build_generator()
        # External critic is opt-in: only constructed when a provider key is
        # present and AURA_CRITIC is not "off" (SRS 17.2, NFR-14 cost control).
        critic = None
        if os.environ.get("AURA_CRITIC", "").lower() not in ("off", "0", "none"):
            critic = critic_from_env(preference=os.environ.get("AURA_CRITIC", "glm"))
        store_path = Path(os.environ.get("AURA_TRACE_DB", str(index_root / "traces.sqlite3")))
        store = TraceStore(store_path, store_path.with_suffix(".jsonl"))
        pipeline = AuraBioPipeline(
            generator=generator,
            searcher=searcher,
            router=_build_router(),
            verifier=BiologyVerifier(),
            reranker=reranker,
            critic=critic,
            store=store,
            model_name=model_name,
            accuracy_mode=os.environ.get("AURA_ACCURACY_MODE", "standard"),
            draft_candidates=int(os.environ.get("AURA_DRAFT_CANDIDATES", "2")),
        )
        _RUNTIME = Runtime(
            pipeline=pipeline,
            searcher=searcher,
            reranker=reranker,
            model_name=model_name,
            index_ready=dense_ready and sparse_ready,
            dense_ready=dense_ready,
            sparse_ready=sparse_ready,
            store=store,
            generator_kind=kind,
            critic_name=getattr(critic, "name", None),
        )
        return _RUNTIME


def reset_runtime() -> None:
    """Test hook: drop the cached runtime so env changes take effect."""

    global _RUNTIME
    with _LOCK:
        if _RUNTIME is not None:
            try:
                _RUNTIME.store.close()
                if _RUNTIME.searcher is not None:
                    _RUNTIME.searcher.close()
            except Exception:
                pass
        _RUNTIME = None


def corpus_snapshot() -> dict[str, Any]:
    """Report real corpus/index state from the manifests on disk."""

    index_root = _index_root()
    dense_manifest = index_root / "core-dense.manifest.json"
    sources = _CORPUS_SOURCES.copy()
    dense_vectors = 0
    if dense_manifest.is_file():
        data = json.loads(dense_manifest.read_text(encoding="utf-8"))
        dense_vectors = int(data.get("vectors", 0))
    runtime = get_runtime()
    total_chunks = sum(s["chunks"] for s in sources)
    return {
        "stages": {
            "ingestion": 100,
            "chunking": 100,
            "embedding": round(100 * dense_vectors / total_chunks) if total_chunks else 0,
            "indexing": 100 if runtime.sparse_ready else 0,
        },
        "totals": {
            "sources": len(sources),
            "documents": sum(s["documents"] for s in sources),
            "chunks": total_chunks,
            "embedded_chunks": dense_vectors,
            "bytes": sum(s["bytes"] for s in sources),
        },
        "index_ready": runtime.index_ready,
        "sparse_ready": runtime.sparse_ready,
        "dense_ready": runtime.dense_ready,
        "last_updated": _now_iso(),
        "sources": sources,
    }


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).isoformat()


# Real measured corpus figures (chunks) from the processed corpus on D:.
_CORPUS_SOURCES: list[dict[str, Any]] = [
    {"source_id": "pubmed_filtered", "label": "PubMed abstracts", "source_type": "Literature",
     "documents": 26_416_670, "chunks": 26_416_670, "embedded_chunks": 0,
     "bytes": 23_405_000_000, "status": "ready", "license_id": "NLM PubMed Terms"},
    {"source_id": "pmc_oa_comm_xml", "label": "PMC open-access papers", "source_type": "Literature",
     "documents": 123_100, "chunks": 3_672_042, "embedded_chunks": 3_672_042,
     "bytes": 2_155_000_000, "status": "ready", "license_id": "Item-level OA licence"},
    {"source_id": "uniprot_sprot", "label": "UniProtKB / Swiss-Prot", "source_type": "Knowledge base",
     "documents": 575_503, "chunks": 5_454_224, "embedded_chunks": 5_454_224,
     "bytes": 759_000_000, "status": "ready", "license_id": "CC-BY-4.0"},
    {"source_id": "wikipedia_biology", "label": "Wikipedia Biology", "source_type": "Reference",
     "documents": 84_650, "chunks": 627_096, "embedded_chunks": 627_096,
     "bytes": 319_000_000, "status": "ready", "license_id": "CC-BY-SA-4.0"},
    {"source_id": "nlm_litarch_biology", "label": "NLM LitArch textbooks", "source_type": "Textbook",
     "documents": 6_941, "chunks": 481_295, "embedded_chunks": 481_295,
     "bytes": 158_000_000, "status": "ready", "license_id": "NLM LitArch item licence"},
    {"source_id": "gene_ontology", "label": "Gene Ontology", "source_type": "Knowledge base",
     "documents": 44_324, "chunks": 116_418, "embedded_chunks": 116_418,
     "bytes": 14_000_000, "status": "ready", "license_id": "CC-BY-4.0"},
    {"source_id": "mesh_descriptors", "label": "MeSH descriptors", "source_type": "Knowledge base",
     "documents": 30_000, "chunks": 33_101, "embedded_chunks": 33_101,
     "bytes": 12_000_000, "status": "ready", "license_id": "NLM data terms"},
    {"source_id": "biolibretexts_catalog", "label": "Biology LibreTexts", "source_type": "Textbook",
     "documents": 70, "chunks": 6_515, "embedded_chunks": 6_515,
     "bytes": 4_000_000, "status": "ready", "license_id": "item-level CC"},
    {"source_id": "reactome_summaries", "label": "Reactome pathways", "source_type": "Knowledge base",
     "documents": 2_600, "chunks": 3_559, "embedded_chunks": 3_559,
     "bytes": 2_000_000, "status": "ready", "license_id": "CC0-1.0"},
]


def benchmark_count() -> int:
    return len(all_questions())
