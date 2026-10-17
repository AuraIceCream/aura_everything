"""Build a private request-scoped pipeline without opening any core index."""
import os

from ..api.generation import ExtractiveGenerator, OllamaGenerator
from ..critique import critic_from_env
from ..pipeline import AnswerPolicy, AuraBioPipeline
from ..tracing import TraceStore
from .jobs import cached_encoder
from .prompts import build_study_prompt
from .claim_generation import StudyClaimGenerator
from .routing import StudyRouter
from .searcher import StudySearcher
from .verification import StudyVerifier
from .reranking import configured_reranker
from ..resources import MemoryPressureError
from .schema import StudyError


class StudyExtractiveGenerator(ExtractiveGenerator):
    """Quoted snippets only; no uncited factual boilerplate or memory answer."""
    def generate(self, route, evidence, *args, **kwargs):
        from .prompts import INSUFFICIENT_SUPPORT
        if not evidence:
            return INSUFFICIENT_SUPPORT
        # Cite each sentence/line, including short labels. These are excerpts, not an inferred answer.
        import re
        snippets = []
        for n, item in enumerate(evidence, 1):
            for line in item.text.splitlines():
                for sentence in re.split(r'(?<=[.!?])\s+', line.strip()):
                    if sentence:
                        snippets.append(f'- {sentence} [{n}]')
        return 'Sources\n\n' + '\n'.join(snippets)


class PrivateTraceStore(TraceStore):
    def __init__(self, study_store, dependencies, *args):
        self.study_store, self.dependencies = study_store, dependencies
        super().__init__(*args)

    def record(self, trace):
        with self.study_store.lock:
            for id in self.dependencies:
                self.study_store.assert_available(id)
            super().record(trace)

    def record_failure(self, *args, **kwargs):
        with self.study_store.lock:
            for id in self.dependencies:
                self.study_store.assert_available(id)
            super().record_failure(*args, **kwargs)


def build_pack_pipeline(store, pack_id, *, use_critic=False, context_pack_id=None, attachment=False, question=None, think=False, require_model=False):
    # All study encoders/checkers here use PyTorch; do not discover TensorFlow
    # opportunistically unless the host explicitly opts into it.
    os.environ.setdefault('USE_TF', '0')
    pack = store.assert_available(pack_id)
    encoder = None
    warnings = []
    if pack.state == 'hybrid-ready' or (context_pack_id and store.assert_available(context_pack_id).state == 'hybrid-ready'):
        try:
            encoder = cached_encoder()
        except MemoryPressureError as exc:
            raise StudyError('busy_memory', str(exc)) from exc
        except Exception as exc:
            warnings.append(f'Cached embedding unavailable ({type(exc).__name__}); query uses sparse-only retrieval.')
    if attachment or context_pack_id:
        from .composite import CompositeStudySearcher
        searcher = CompositeStudySearcher(store, pack_id, context_pack_id, dense_encoder=encoder, question=question)
    else:
        searcher = StudySearcher(store, pack_id, dense_encoder=encoder, question=question)
    try:
        generator = StudyExtractiveGenerator()
        if os.environ.get('AURA_GENERATOR') != 'extractive':
            generator_type = StudyClaimGenerator if os.environ.get('AURA_STUDY_CLAIM_FIRST', '1') != '0' else OllamaGenerator
            local = generator_type(model=os.environ.get('AURA_OLLAMA_MODEL', 'aura-bio:v0'),
                                    host=os.environ.get('AURA_OLLAMA_HOST', 'http://127.0.0.1:11434'),
                                    num_predict=int(os.environ.get('AURA_STUDY_THINK_NUM_PREDICT', '4096') if think else os.environ.get('AURA_STUDY_NUM_PREDICT', '768')),
                                    think=think, timeout=600 if think else 300,
                                    keep_alive=0 if attachment or require_model or generator_type is StudyClaimGenerator else None,
                                    seed=int(os.environ.get('AURA_STUDY_SEED', '42')),
                                    use_mmap=(os.environ['AURA_OLLAMA_USE_MMAP'].lower() in {'1', 'true'}
                                              if 'AURA_OLLAMA_USE_MMAP' in os.environ else None),
                                    retries=0 if attachment or require_model else 2,
                                    num_batch=64 if attachment or require_model or generator_type is StudyClaimGenerator else None,
                                    **({'prompt_builder': build_study_prompt} if generator_type is OllamaGenerator else {}))
            if attachment or require_model:
                from .visual.ollama import OllamaVisionBackend, gpu_free_mb
                backend = OllamaVisionBackend(url=local.host)
                tags = backend._request('get', '/api/tags', timeout=5).get('models', [])
                if not any(m.get('name') == local.model_name or m.get('model') == local.model_name for m in tags):
                    raise StudyError('model_unavailable', 'The exact configured answer model is not installed; no fallback attempted.')
                loaded = backend._request('get', '/api/ps', timeout=5).get('models', [])
                target_loaded = any(m.get('name') == local.model_name or m.get('model') == local.model_name for m in loaded)
                if any(m.get('name') != local.model_name and m.get('model') != local.model_name for m in loaded):
                    raise StudyError('busy_gpu', 'Another Ollama model is loaded; visual answering paused.')
                free, total, utilization = gpu_free_mb()
                if utilization > 15 or free < (64 if target_loaded else 384):
                    raise StudyError('busy_gpu', f'GPU is occupied ({free:.0f} MiB free, {utilization:.0f}% utilization); visual answering paused. Resume explicitly when free.')
                local.strict_no_fallback = True
                generator = local
            elif local.available():
                generator = local
        reranker = None
        try:
            reranker = configured_reranker()
            if reranker is None:
                warnings.append('Study reranking is explicitly disabled.')
        except MemoryPressureError as exc:
            raise StudyError('busy_memory', str(exc)) from exc
        except Exception as exc:
            warnings.append(f'Cached CPU reranker unavailable ({type(exc).__name__}); candidates are not reranked.')
        searcher.runtime_warnings.extend(warnings)
        searcher.pipeline_stages = {'embedding_model': getattr(encoder, 'model_name', None),
                                   'reranker_model': getattr(reranker, 'model_name', None),
                                   'generator': generator.model_name}
        preference = os.environ.get('AURA_CRITIC', 'glm')
        critic = critic_from_env(preference=preference) if use_critic and preference not in {'off', 'none', '0'} else None
        trace_root = store.root / pack_id / 'traces'
        trace_store = PrivateTraceStore(store, [id for id in (pack_id, context_pack_id) if id], trace_root / 'traces.sqlite3', trace_root / 'traces.jsonl')
        return AuraBioPipeline(generator, searcher=searcher, router=StudyRouter(pack.domain),
            verifier=StudyVerifier(pack.domain, use_entailment=os.environ.get('AURA_NLI', '').lower() not in {'off', '0', 'false'}), reranker=reranker, critic=critic, store=trace_store,
            model_name=generator.model_name, accuracy_mode=os.environ.get('AURA_ACCURACY_MODE', 'robust'),
            draft_candidates=int(os.environ.get('AURA_DRAFT_CANDIDATES', '2')),
            answer_policy=AnswerPolicy('pack_only', pack_id))
    except Exception:
        searcher.close()
        raise
