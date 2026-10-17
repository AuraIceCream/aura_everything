"""The AURA-Bio query pipeline (SRS 2.3).

Route -> retrieve -> fuse -> rerank -> select evidence -> draft -> verify ->
critique -> revise -> final answer, with the whole path recorded as one trace.

Generation and critique are injected as protocols. That keeps the pipeline
runnable and testable without a local model, and it is what lets SRS 25's
ablation switch individual components off and attribute the difference.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol, Sequence

from .critique import (
    Critique,
    RevisionRecord,
    combine_decision,
    revision_instructions,
)
from .retrieval.reranker import CrossEncoderReranker, select_evidence, select_diverse_evidence
from .retrieval.strategies import compress_evidence, retrieve_for_level, query_variants
from .routing import LearnerLevel, QueryRouter, Route, TeachingMode
from .tracing import Stopwatch, Trace, TraceStore, classify_failure
from .verification import BiologyVerifier, EvidencePassage


class Generator(Protocol):
    """The local biology LLM (SRS 15.1).

    ``coverage_pool`` is optional and carries the pre-rerank candidates, which
    only widen the prompt's vocabulary checklist. A generator that ignores it
    still satisfies this protocol.
    """

    def generate(
        self,
        route: Route,
        evidence: Sequence[Any],
        instructions: Sequence[str],
        coverage_pool: Sequence[Any] = (),
        unknown_entities: Sequence[str] = (),
        previous_answer: str = "",
    ) -> str:
        ...


class ChatModel(Protocol):
    """A local chat model that maps prompt messages to a completion."""

    def complete(self, messages: list[dict[str, str]]) -> str:
        ...


class PromptedGenerator:
    """Adapts a raw chat model into a Generator using the SRS 12 prompts."""

    def __init__(self, model: ChatModel, prompt_profile: str = "standard", prompt_builder: Any = None) -> None:
        self.model = model
        self.prompt_profile = prompt_profile
        self.prompt_builder = prompt_builder

    def generate(
        self,
        route: Route,
        evidence: Sequence[Any],
        instructions: Sequence[str],
        coverage_pool: Sequence[Any] = (),
        unknown_entities: Sequence[str] = (),
        previous_answer: str = "",
    ) -> str:
        from .generation import build_prompt

        if self.prompt_builder is not None:
            prompt = self.prompt_builder(route, evidence, instructions, coverage_pool, unknown_entities, previous_answer)
        else:
            prompt = build_prompt(route, evidence, instructions, coverage_pool, unknown_entities, previous_answer,
                                  profile=self.prompt_profile)
        return self.model.complete(prompt.as_messages())


class Critic(Protocol):
    """The optional development-time external critic (SRS 17)."""

    def review(self, route: Route, answer: str, evidence: Sequence[Any]) -> Critique:
        ...


class Searcher(Protocol):
    """Satisfied by aura_bio_pipeline.retrieval.HybridSearcher."""

    def search(self, query: str, top_k: int, candidate_k: int) -> list[Any]:
        ...


@dataclass(slots=True)
class Answer:
    """What the caller gets back, with its trace attached."""

    text: str
    decision: str
    confidence: float
    trace: Trace

    @property
    def sources(self) -> list[dict[str, Any]]:
        return self.trace.user_view()["sources"]


@dataclass(frozen=True)
class AnswerPolicy:
    evidence_scope: str = 'core'
    pack_id: str | None = None

    def __post_init__(self):
        if self.evidence_scope not in {'core', 'pack_only'} or (self.evidence_scope == 'pack_only' and not self.pack_id):
            raise ValueError('pack_only requires a pack_id; unknown evidence scope.')


class AuraBioPipeline:
    def __init__(
        self,
        generator: Generator,
        searcher: Searcher | None = None,
        router: QueryRouter | None = None,
        verifier: BiologyVerifier | None = None,
        reranker: CrossEncoderReranker | None = None,
        critic: Critic | None = None,
        store: TraceStore | None = None,
        model_name: str = "local",
        compress_deep_evidence: bool = True,
        revision_context: bool = False,
        accuracy_mode: str = "standard",
        draft_candidates: int = 2,
        answer_policy: AnswerPolicy | None = None,
    ) -> None:
        self.generator = generator
        self.searcher = searcher
        self.router = router or QueryRouter()
        self.verifier = verifier or BiologyVerifier()
        self.reranker = reranker
        self.critic = critic
        self.store = store
        self.model_name = model_name
        self.compress_deep_evidence = compress_deep_evidence
        # Robust repair edits the selected draft; standard keeps the existing
        # opt-in behaviour for backwards-compatible comparisons.
        self.revision_context = revision_context or accuracy_mode == "robust"
        if accuracy_mode not in ("standard", "robust"):
            raise ValueError("accuracy_mode must be standard or robust")
        if not 1 <= draft_candidates <= 5:
            raise ValueError("draft_candidates must be between 1 and 5")
        self.accuracy_mode = accuracy_mode
        self.draft_candidates = draft_candidates
        self.answer_policy = answer_policy or AnswerPolicy()

    def answer(
        self,
        query: str,
        learner_level: LearnerLevel | str | None = None,
        teaching_mode: TeachingMode | str | None = None,
        context_level: int | None = None,
        use_critic: bool = True,
        answer_mode: str = 'tutor',
        visual_output: str = 'none',
    ) -> Answer:
        if visual_output not in {'none', 'auto', 'source', 'diagram', 'comparison', 'procedure', 'plot'}:
            raise ValueError('Unknown visual output mode.')
        trace = Trace(query=query, model=self.model_name)

        with Stopwatch(trace, "routing"):
            route = self.router.route(query, learner_level, teaching_mode, context_level)
        trace.route = route.as_dict()

        # Does the question name something the corpus has never heard of? This
        # is a retrieval result about the *question*, computed before any
        # answer exists, and it is the one place the entity lexicon is precise:
        # it identifies all eight fabricated entities in the adversarial
        # benchmark with a 0.7% false-alarm rate over 433 real questions.
        unknown: tuple[str, ...] = ()
        with Stopwatch(trace, "entity_check"):
            try:
                if self.answer_policy.evidence_scope == 'core':
                    from .verification.ontology import unknown_entities as _unknown
                    unknown = tuple(_unknown(query))
            except Exception:
                unknown = ()
        if unknown:
            trace.unknown_entities = list(unknown)

        evidence: list[Any] = []
        # The full candidate set, kept for the prompt's vocabulary checklist
        # only. Reranking picks what is worth quoting; it should not also decide
        # which biology words the answer is allowed to know about.
        coverage_pool: list[Any] = []
        neighbor_errors = []
        neighbor_fetch = None
        if self.answer_policy.evidence_scope == 'pack_only' and hasattr(self.searcher, 'neighbors'):
            def neighbor_fetch(*args):
                try:
                    return self.searcher.neighbors(*args)
                except Exception as exc:
                    neighbor_errors.append(type(exc).__name__)
                    return []
        if route.needs_retrieval and self.searcher is not None:
            with Stopwatch(trace, "retrieval"):
                # Levels 3 and 4 use hierarchical / decomposed retrieval rather
                # than a deeper top-k (SRS 10.3-10.5).
                candidates = retrieve_for_level(
                    self.searcher,
                    getattr(self.searcher, "core", None),
                    query,
                    route.context_level,
                    route.retrieve_k,
                    expand_queries=self.accuracy_mode == "robust",
                    neighbor_fetch=neighbor_fetch,
                )
            coverage_pool = list(candidates)
            trace.retrieval = {
                "candidates": len(candidates),
                "requested": route.retrieve_k,
                "strategy": _STRATEGY_NAMES.get(route.context_level, "standard"),
                "channels": _channel_counts(candidates),
                "accuracy_mode": self.accuracy_mode,
                "queries": query_variants(query) if self.accuracy_mode == "robust" else [query],
                "evidence_scope": self.answer_policy.evidence_scope,
                "pack_id": self.answer_policy.pack_id,
                "generation": getattr(self.searcher, 'generation', None),
                "mode": getattr(self.searcher, 'mode', None),
                **({'neighbor_errors': neighbor_errors, 'external_private_excerpt_opt_in': bool(use_critic),
                    'warnings': list(getattr(self.searcher, 'runtime_warnings', [])),
                    'stages': getattr(self.searcher, 'pipeline_stages', {})} if self.answer_policy.evidence_scope == 'pack_only' else {}),
            }
            if self.reranker is not None and candidates:
                with Stopwatch(trace, "rerank"):
                    candidates, report = self.reranker.rerank(
                        query, candidates, len(candidates) if self.accuracy_mode == "robust" else route.rerank_k
                    )
                trace.rerank = report.as_dict()
            elif self.accuracy_mode != "robust":
                candidates = candidates[: route.rerank_k]
            with Stopwatch(trace, "evidence_selection"):
                if self.accuracy_mode == "robust":
                    evidence = select_diverse_evidence(query, candidates, max_passages=min(route.rerank_k, 6),
                        max_chars=14000 if self.answer_policy.evidence_scope == 'pack_only' else 9000,
                        per_source_cap=None if self.answer_policy.evidence_scope == 'pack_only' else 4,
                        per_document_cap=None if self.answer_policy.evidence_scope == 'pack_only' else 2)
                else:
                    evidence = select_evidence(candidates, max_passages=route.rerank_k,
                        per_source_cap=None if self.answer_policy.evidence_scope == 'pack_only' else 4)
                # Deep levels gather more passages than a prompt can hold, so
                # each is trimmed to the sentences that bear on the question.
                if self.compress_deep_evidence and route.context_level >= 3 and evidence and self.answer_policy.evidence_scope == 'core':
                    evidence = compress_evidence(query, evidence)
                    trace.retrieval["compressed"] = True
            trace.evidence = [_evidence_dict(item) for item in evidence]
            if self.answer_policy.evidence_scope == 'pack_only' and hasattr(self.searcher, 'finalize_evidence'):
                evidence = self.searcher.finalize_evidence(query, evidence, coverage_pool,
                    max_passages=max(min(route.rerank_k,6),min(12,len(getattr(self.searcher,'figure_ids',()))*2)), max_chars=14000)
                trace.retrieval['source_generations'] = self.searcher.generations
                trace.retrieval['source_modes'] = self.searcher.source_modes
                trace.retrieval['warnings'] = list(getattr(self.searcher,'runtime_warnings',[]))
                trace.evidence = [_evidence_dict(item) for item in evidence]

        passages = [
            EvidencePassage(
                chunk_id=str(getattr(item, "chunk_id", index)),
                text=getattr(item, "text", "") or "",
                title=getattr(item, "title", "") or "",
                source_id=getattr(item, "source_id", "") or "",
            )
            for index, item in enumerate(evidence)
        ]
        if self.answer_policy.evidence_scope == 'pack_only':
            # Private provenance is part of the verification contract, not just
            # a citation badge. Never turn interpreted pixels into native text.
            passages = list(evidence)

        if visual_output != 'none':
            trace.retrieval['visual_output'] = visual_output
        instructions: tuple[str, ...] = ()
        answer_text = ""
        decision = "accept"
        confidence = 0.5
        if self.answer_policy.evidence_scope == 'pack_only' and hasattr(self.generator, 'generate_claims'):
            return self._answer_structured(trace, route, evidence, passages, answer_mode)
        if self.accuracy_mode == "robust":
            return self._answer_candidates(trace, route, evidence, passages, coverage_pool, unknown, use_critic)
        # SRS 18.3 caps revisions; the loop runs draft plus at most that many.
        for iteration in range(route.max_revisions + 1):
            if iteration and self.answer_policy.evidence_scope == 'pack_only':
                from .study.prompts import study_repair_instructions
                instructions = study_repair_instructions(answer_text, report.as_dict(), instructions)
            from .resources import MODEL_PHASE_LOCK
            with MODEL_PHASE_LOCK:
                prepare = getattr(self.verifier, 'before_generation', None)
                if callable(prepare):
                    with Stopwatch(trace, 'model_handoff'):
                        trace.retrieval.setdefault('model_handoffs', []).append(prepare())
                with Stopwatch(trace, "generation"):
                    answer_text = self.generator.generate(
                        route, evidence, instructions, coverage_pool, unknown,
                        previous_answer=answer_text if iteration and self.revision_context else "",
                    )
            with Stopwatch(trace, "verification"):
                report = self.verifier.verify(answer_text, passages, route, query)
                if self.answer_policy.evidence_scope == 'pack_only':
                    from .verification.delivery import check_answer_delivery
                    report.issues.extend(check_answer_delivery(answer_text, passages,
                        dict(getattr(self.generator, 'last_metadata', {})), query))
            critique: Critique | None = None
            if self.critic is not None and use_critic:
                with Stopwatch(trace, "critique"):
                    try:
                        critique = self.critic.review(route, answer_text, evidence)
                    except Exception as exc:
                        # SRS 17.2: the critic is optional and must never be
                        # able to fail the request.
                        critique = Critique(False, decision="revise", trusted=False,
                                            failure_kind=type(exc).__name__)
            _record_critic_status(report, critique)
            decision = self._decision(report, critique)
            confidence = report.confidence()
            instructions = revision_instructions(report, critique)
            trace.revisions.append(
                RevisionRecord(
                    iteration=iteration,
                    answer=answer_text,
                    verification=report.as_dict(),
                    critique=critique.as_dict() if critique else None,
                    decision=decision,
                    instructions=instructions,
                ).as_dict()
            )
            if decision in ("accept", "degraded") or not instructions:
                break

        trace.final_answer = answer_text
        trace.decision = decision
        trace.confidence = confidence
        self._finalize_scope(trace)
        # Traceability of the answer that is actually returned. Recorded for
        # every request because it is the property the accuracy numbers cannot
        # show: the bare model reaches the same concept recall, but nothing it
        # says can be pointed at a source.
        with Stopwatch(trace, "provenance"):
            from .verification.provenance import measure_provenance

            trace.provenance = measure_provenance(trace.final_answer, passages).as_dict()
        self._attach_visual(trace, route, evidence)
        trace.failure_category = classify_failure(trace) if trace.decision != "accept" else None
        if self.store is not None:
            self.store.record(trace)
            if trace.failure_category:
                self.store.record_failure(trace, trace.failure_category)
        return Answer(trace.final_answer, trace.decision, trace.confidence, trace)

    def _answer_structured(self, trace, route, evidence, passages, answer_mode):
        """Keep model claims, checker findings, and final delivery separate."""
        from .study.claim_delivery import deliver_claims
        from .study.completion import assess_completion
        from .study.claims import merge_claims, MAX_CLAIMS, GENERATION_MAX_CLAIMS
        from dataclasses import replace
        from .verification.provenance import ProvenanceReport

        best = None
        best_key = None
        missing_parts = []
        attempts = self.draft_candidates if route.needs_retrieval else 1
        for iteration in range(attempts):
            instructions = ()
            enrichment = None
            supplement = getattr(self.generator, 'generate_supplement', None)
            augment = (iteration and best is not None and missing_parts
                       and best[2].delivered_ids and callable(supplement)
                       and len(best[2].delivered_ids) <= MAX_CLAIMS - GENERATION_MAX_CLAIMS)
            if iteration:
                instructions = ('Cover each requested part from the sources before adding other details.',)
                if missing_parts:
                    instructions += ('The previous draft may have omitted: ' + '; '.join(missing_parts)[:1200],)
                if best is not None:
                    instructions += ('Preserve these source-supported statements while filling the gaps; '
                        'check all citations again: ' + best[2].text[:1800],)
            from .resources import MODEL_PHASE_LOCK
            with MODEL_PHASE_LOCK:
                prepare = getattr(self.verifier, 'before_generation', None)
                if callable(prepare):
                    with Stopwatch(trace, 'model_handoff'):
                        trace.retrieval.setdefault('model_handoffs', []).append(prepare())
                with Stopwatch(trace, 'generation'):
                    if augment:
                        retained = tuple(item for item in best[0].claims if item.id in best[2].delivered_ids)
                        additions = supplement(route, evidence, missing_parts, retained)
                        draft = merge_claims(best[0], best[2].delivered_ids, additions)
                        enrichment = {'retained_ids': list(best[2].delivered_ids),
                                      'proposed_claims': [dict(id=item.id, claim=item.claim,
                                          cite_ids=list(item.cite_ids), depends_on=list(item.depends_on))
                                          for item in additions.claims]}
                    else:
                        draft = self.generator.generate_claims(route, evidence, instructions)
            with Stopwatch(trace, 'verification'):
                report = self.verifier.verify_claims(draft.claims, passages, route, route.query)
                delivered = deliver_claims(draft, report, mode=answer_mode)
                checked_text = [item.claim for item in draft.claims if item.id in delivered.delivered_ids]
                coverage = assess_completion(route.query, checked_text, passages)
                missing_parts = coverage['possible_omissions']
                if missing_parts and delivered.delivered_ids:
                    delivered = replace(delivered, decision='partial', status='partial',
                        text=delivered.text + '\n\nThis answer may not fully address: ' + '; '.join(missing_parts)[:500] + '.')
                    delivered.verification['delivery_status'] = 'partial'
            record = {
                'iteration': iteration, 'phase': 'enrichment' if enrichment is not None else 'draft', 'answer': delivered.text,
                'enrichment': enrichment,
                'decision': delivered.decision, 'verification': delivered.verification,
                'draft_verification': delivered.draft_verification,
                'delivery': {'status': delivered.status, 'delivered_ids': delivered.delivered_ids,
                             'question_coverage': coverage,
                             'delivered_cite_ids': sorted({n for item in draft.claims
                                 if item.id in delivered.delivered_ids for n in item.cite_ids}),
                             'omitted': delivered.omitted},
                'generation': dict(getattr(self.generator, 'last_metadata', {})),
            }
            trace.revisions.append(record)
            key = (coverage['addressed_parts'], len(delivered.delivered_ids), -len(delivered.omitted_ids),
                   sum(item.verification_kind == 'native_verified' for item in report.claim_basis))
            if best_key is None or key > best_key:
                best, best_key = (draft, report, delivered, iteration), key
            # Always target the selected answer, not omissions of a worse draft.
            missing_parts = trace.revisions[best[3]]['delivery']['question_coverage']['possible_omissions']
        draft, report, delivered, selected = best
        trace.selected_revision = selected
        trace.final_answer = delivered.text
        trace.decision = delivered.decision
        trace.confidence = round(len(delivered.delivered_ids) / len(draft.claims), 3) if draft.claims else 0.0
        trace.retrieval['answer_mode'] = answer_mode
        trace.retrieval['delivery_status'] = delivered.status
        trace.retrieval['delivered_claim_count'] = len(delivered.delivered_ids)
        trace.retrieval['omitted_claim_count'] = len(delivered.omitted_ids)
        accepted = {item.id: item for item in draft.claims if item.id in delivered.delivered_ids}
        citations = [n for item in accepted.values() for n in item.cite_ids]
        supporting = {record['chunk_id'] for basis in report.claim_basis for record in basis.supporting_provenance}
        valid = sum(1 for n in citations if 1 <= n <= len(passages) and passages[n - 1].chunk_id in supporting)
        sources = {passages[n - 1].source_id or passages[n - 1].chunk_id for n in citations if 1 <= n <= len(passages)}
        trace.provenance = ProvenanceReport(len(accepted), len(accepted), len(citations), valid, 0, len(sources)).as_dict()
        self._attach_visual(trace, route, evidence, draft, delivered)
        trace.failure_category = classify_failure(trace) if trace.decision not in {'accept', 'degraded'} else None
        if self.store is not None:
            self.store.record(trace)
            if trace.failure_category:
                self.store.record_failure(trace, trace.failure_category)
        return Answer(trace.final_answer, trace.decision, trace.confidence, trace)

    def _attach_visual(self, trace, route, evidence, draft=None, delivered=None):
        if trace.retrieval.get('visual_output', 'none') != 'none':
            from .visual_outputs.context import build_visual_context, build_core_visual_context
            from .visual_outputs.planner import plan_visual
            from .visual_outputs.schema import VisualResult
            from .resources import MODEL_PHASE_LOCK
            with Stopwatch(trace, 'visual_output'):
                try:
                    context = (build_core_visual_context(trace, evidence)
                               if self.answer_policy.evidence_scope == 'core'
                               else build_visual_context(draft, delivered, evidence))
                    with MODEL_PHASE_LOCK:
                        prepare = getattr(self.verifier, 'before_generation', None)
                        if context is not None and context.claims and trace.retrieval['visual_output'] != 'source':
                            if callable(prepare): prepare()
                            else:
                                from .verification.entailment import release_default_scorer
                                release_default_scorer()
                        visual_diagnostics = {}
                        visual = plan_visual(trace.retrieval['visual_output'], route.query,
                                             context, self.generator, self.verifier, diagnostics=visual_diagnostics)
                        if self.answer_policy.evidence_scope == 'pack_only':
                            trace.final_record['visual_diagnostics'] = visual_diagnostics
                    if visual.status == 'ready' and visual.spec.kind == 'source':
                        from .visual_outputs.source import resolve_source_visual
                        resolved = resolve_source_visual(visual.spec, context, getattr(self.searcher, 'store', None), question=route.query)
                        visual = replace(resolved, metadata=visual.metadata)
                    if self.answer_policy.evidence_scope == 'core':
                        # Core document/source IDs are not private pack IDs.
                        # Keep their stable identity for trace/JSON export without
                        # pretending they authorize an owned image/unit endpoint.
                        refs = []
                        for source in visual.spec.sources if visual.spec is not None else ():
                            citation = source['citation_id']
                            item = evidence[int(citation.removeprefix('cit-')) - 1]
                            refs.append({'citation_id': citation, 'chunk_id': item.chunk_id,
                                         'source_id': getattr(item, 'source_id', None),
                                         'document_id': getattr(item, 'document_id', None),
                                         'url': getattr(item, 'url', None)})
                        visual = replace(visual, metadata={**(visual.metadata or {}),
                                                          'evidence_scope': 'core', 'source_refs': refs})
                except Exception:
                    visual = VisualResult('failed', limitations=('The optional visual failed safely; the text answer is unchanged.',))
                trace.final_record['visual'] = visual.as_dict()

    def _decision(self, report, critique):
        decision = combine_decision(report, critique)
        if self.answer_policy.evidence_scope == 'pack_only' and decision == 'degraded' and critique is not None and critique.trusted:
            if (critique.decision in {'revise', 'reject'} or not critique.answer_supported
                    or critique.unsupported_claims or critique.terminology_errors or critique.process_errors):
                return 'revise'
        return decision

    def _finalize_scope(self, trace):
        if self.answer_policy.evidence_scope == 'pack_only' and trace.decision not in {'accept', 'degraded'}:
            from .study.prompts import INSUFFICIENT_SUPPORT
            trace.final_answer = INSUFFICIENT_SUPPORT
            trace.decision = 'insufficient_evidence'
            trace.confidence = 0.0

    def _answer_candidates(self, trace, route, evidence, passages, coverage_pool, unknown, use_critic):
        """Bounded independent drafts followed by targeted repair of the best.

        Every draft and revision is retained. Returning an earlier candidate
        also returns that candidate's decision, confidence and verification.
        """
        from .generation.selection import candidate_quality
        from .verification.provenance import measure_provenance
        from .verification.provenance import enforce_inline_support
        from .verification.delivery import check_answer_delivery
        from .verification.numerical import hardy_weinberg
        from .generation.calculations import render_validated_calculation
        from .generation.prompts import focus_revision_instructions

        # Feed recognised question-derived arithmetic into generation, rather
        # than merely rejecting a wrong number after it has been produced.
        # Start with the existing Hardy-Weinberg adapter; other solvers need
        # premise/unit validation before their output becomes generation input.
        with Stopwatch(trace, "calculation"):
            calculations = (hardy_weinberg(route.query, "")
                            if getattr(self.verifier, "check_numbers", False) and self.answer_policy.evidence_scope == 'core' else [])
        trace.retrieval["calculations"] = [check.as_dict() for check in calculations]
        trace.retrieval["revision_context"] = self.revision_context
        calculation_answer = (
            render_validated_calculation(route.query, calculations)
            if route.teaching_mode.label not in ("socratic", "teach_back") else None
        )
        trace.retrieval["calculation_rendered"] = calculation_answer is not None
        calculation_instructions = ()
        if calculations:
            requested = [check for check in calculations if check.verdict != "working"]
            working = [check for check in calculations if check.verdict == "working"]
            calculation_instructions = (
                "Calculation from the question's premises (not retrieved examples): "
                + "; ".join(f"{check.quantity} = {check.expected:.6g} ({check.working})"
                            for check in requested + working)
                + ". Use these values unchanged. Show brief working and the requested "
                "result; arithmetic from the question does not need a source citation.",
            )

        drafts = self.draft_candidates if route.needs_retrieval else 1
        best = None
        best_key = None
        for iteration in range(drafts + route.max_revisions):
            phase = "draft" if iteration < drafts else "revision"
            instructions = ()
            previous = ""
            revision_of = None
            if phase == "draft" and iteration:
                instructions = (
                    "Write an independent concise answer using the fixed calculation values. "
                    "Address every part. Avoid extra examples and repeated paragraphs."
                    if calculations else
                    "Write an independent concise answer. Address all subjects in the question, "
                    "use standard terms, and cite only passages that support the adjacent claim. "
                    "Avoid extra numerical examples and repeated paragraphs.",
                )
            elif phase == "revision":
                if best["decision"] in ("accept", "degraded"):
                    break
                instructions = focus_revision_instructions(best["instructions"])
                if not instructions:
                    break
                if self.answer_policy.evidence_scope == 'pack_only':
                    from .study.prompts import study_repair_instructions
                    instructions = study_repair_instructions(best['answer'], best['verification'], instructions)
                if self.revision_context:
                    previous = best["answer"]
                revision_of = best["iteration"]
            instructions = tuple(instructions) + calculation_instructions
            if evidence and not calculations:
                instructions += (
                    "Put inline [n] citations beside the factual claims that the "
                    "numbered passages support. A references list is not enough. "
                    "Never invent a citation or cite an unrelated passage.",
                )
            applied_instructions = tuple(instructions)
            from .resources import MODEL_PHASE_LOCK
            with MODEL_PHASE_LOCK:
                prepare = getattr(self.verifier, 'before_generation', None)
                if callable(prepare):
                    with Stopwatch(trace, 'model_handoff'):
                        trace.retrieval.setdefault('model_handoffs', []).append(prepare())
                with Stopwatch(trace, "generation"):
                    generated_text = self.generator.generate(
                        route, evidence, applied_instructions, coverage_pool, unknown,
                        previous_answer=previous)
                    # Do not append a correct result to incorrect model working.
                    # A recognised, validated calculation owns the complete worked
                    # answer. Keep the raw draft for audit; all checkers and the
                    # critic still assess the actual returned candidate.
                    text = calculation_answer if calculation_answer is not None else generated_text
            with Stopwatch(trace, "verification"):
                report = self.verifier.verify(text, passages, route, route.query)
                if calculations:
                    report.checker_status["inline_citations"] = "question_calculation"
                elif self.answer_policy.evidence_scope == 'core':
                    enforce_inline_support(text, passages, report)
                generation = dict(getattr(self.generator, "last_metadata", {}))
                if calculation_answer is None:
                    report.issues.extend(check_answer_delivery(text, passages, generation, route.query))
            critique = None
            if self.critic is not None and use_critic:
                with Stopwatch(trace, "critique"):
                    try:
                        critique = self.critic.review(route, text, evidence)
                    except Exception as exc:
                        trace.retrieval.setdefault("critic_errors", []).append(type(exc).__name__)
                        critique = Critique(False, decision="revise", trusted=False,
                                            failure_kind=type(exc).__name__)
            _record_critic_status(report, critique)
            decision = self._decision(report, critique)
            instructions = revision_instructions(report, critique, require_citations=not calculations)
            with Stopwatch(trace, "provenance"):
                provenance = measure_provenance(text, passages).as_dict()
            record = RevisionRecord(iteration, text, report.as_dict(),
                                    critique.as_dict() if critique else None, decision, instructions).as_dict()
            key, quality = candidate_quality(route.query, text, record["verification"], record["critique"], decision, provenance)
            record.update(phase=phase, quality=quality, provenance=provenance, generation=generation,
                          generated_answer=generated_text,
                          answer_origin="validated_calculation" if calculation_answer is not None else "model",
                          applied_instructions=list(applied_instructions), revision_of=revision_of)
            trace.revisions.append(record)
            if best_key is None or key > best_key:
                best, best_key = record, key
                trace.selected_revision = iteration

        trace.final_answer = best["answer"]
        trace.decision = best["decision"]
        trace.confidence = best["verification"]["confidence"]
        trace.provenance = best["provenance"]
        self._finalize_scope(trace)
        if trace.final_answer != best['answer']:
            trace.provenance = measure_provenance(trace.final_answer, passages).as_dict()
        self._attach_visual(trace, route, evidence)
        trace.failure_category = classify_failure(trace) if trace.decision != "accept" else None
        if self.store is not None:
            self.store.record(trace)
            if trace.failure_category:
                self.store.record_failure(trace, trace.failure_category)
        return Answer(trace.final_answer, trace.decision, trace.confidence, trace)


def _record_critic_status(report, critique):
    from .verification.schema import Issue

    if critique is None:
        report.checker_status["critic"] = "disabled"
    elif critique.trusted:
        report.checker_status["critic"] = "trusted"
    else:
        reason = critique.failure_kind or "untrusted_response"
        report.checker_status["critic"] = f"untrusted: {reason}"
        report.issues.insert(0, Issue(
            "critic", "critic_unavailable",
            f"The requested critic did not return a usable review ({reason}); "
            "this answer has not received critic approval.", "warning"))


_STRATEGY_NAMES = {3: "hierarchical", 4: "deep_decomposed"}


def _channel_counts(candidates: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in candidates:
        channel = getattr(item, "channel", "unknown")
        counts[channel] = counts.get(channel, 0) + 1
    return counts


def _evidence_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "as_dict"):
        return item.as_dict()
    return {
        "chunk_id": getattr(item, "chunk_id", None),
        "source_id": getattr(item, "source_id", None),
        "title": getattr(item, "title", None),
        "section": getattr(item, "section", None),
        "url": getattr(item, "url", None),
        "channel": getattr(item, "channel", None),
    }
