"""The AURA-Bio query pipeline (SRS 2.3).

Route -> retrieve -> fuse -> rerank -> select evidence -> draft -> verify ->
critique -> revise -> final answer, with the whole path recorded as one trace.

Generation and critique are injected as protocols. That keeps the pipeline
runnable and testable without a local model, and it is what lets SRS 25's
ablation switch individual components off and attribute the difference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from .critique import (
    Critique,
    RevisionRecord,
    combine_decision,
    revision_instructions,
)
from .retrieval.reranker import CrossEncoderReranker, select_evidence
from .retrieval.strategies import compress_evidence, retrieve_for_level
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
    ) -> str:
        ...


class ChatModel(Protocol):
    """A local chat model that maps prompt messages to a completion."""

    def complete(self, messages: list[dict[str, str]]) -> str:
        ...


class PromptedGenerator:
    """Adapts a raw chat model into a Generator using the SRS 12 prompts."""

    def __init__(self, model: ChatModel) -> None:
        self.model = model

    def generate(
        self,
        route: Route,
        evidence: Sequence[Any],
        instructions: Sequence[str],
        coverage_pool: Sequence[Any] = (),
        unknown_entities: Sequence[str] = (),
    ) -> str:
        from .generation import build_prompt

        prompt = build_prompt(route, evidence, instructions, coverage_pool, unknown_entities)
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
    ) -> None:
        self.generator = generator
        self.searcher = searcher
        self.router = router or QueryRouter()
        self.verifier = verifier or BiologyVerifier()
        self.reranker = reranker
        self.critic = critic
        self.store = store
        self.model_name = model_name

    def answer(
        self,
        query: str,
        learner_level: LearnerLevel | str | None = None,
        teaching_mode: TeachingMode | str | None = None,
        context_level: int | None = None,
        use_critic: bool = True,
    ) -> Answer:
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
                )
            coverage_pool = list(candidates)
            trace.retrieval = {
                "candidates": len(candidates),
                "requested": route.retrieve_k,
                "strategy": _STRATEGY_NAMES.get(route.context_level, "standard"),
                "channels": _channel_counts(candidates),
            }
            if self.reranker is not None and candidates:
                with Stopwatch(trace, "rerank"):
                    candidates, report = self.reranker.rerank(query, candidates, route.rerank_k)
                trace.rerank = report.as_dict()
            else:
                candidates = candidates[: route.rerank_k]
            with Stopwatch(trace, "evidence_selection"):
                evidence = select_evidence(candidates, max_passages=route.rerank_k)
                # Deep levels gather more passages than a prompt can hold, so
                # each is trimmed to the sentences that bear on the question.
                if route.context_level >= 3 and evidence:
                    evidence = compress_evidence(query, evidence)
                    trace.retrieval["compressed"] = True
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

        instructions: tuple[str, ...] = ()
        answer_text = ""
        decision = "accept"
        confidence = 0.5
        # SRS 18.3 caps revisions; the loop runs draft plus at most that many.
        for iteration in range(route.max_revisions + 1):
            with Stopwatch(trace, "generation"):
                answer_text = self.generator.generate(
                    route, evidence, instructions, coverage_pool, unknown
                )
            with Stopwatch(trace, "verification"):
                report = self.verifier.verify(answer_text, passages, route, query)
            critique: Critique | None = None
            if self.critic is not None and use_critic:
                with Stopwatch(trace, "critique"):
                    try:
                        critique = self.critic.review(route, answer_text, evidence)
                    except Exception:
                        # SRS 17.2: the critic is optional and must never be
                        # able to fail the request.
                        critique = None
            decision = combine_decision(report, critique)
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
            if decision == "accept" or not instructions:
                break

        trace.final_answer = answer_text
        trace.decision = decision
        trace.confidence = confidence
        # Traceability of the answer that is actually returned. Recorded for
        # every request because it is the property the accuracy numbers cannot
        # show: the bare model reaches the same concept recall, but nothing it
        # says can be pointed at a source.
        with Stopwatch(trace, "provenance"):
            from .verification.provenance import measure_provenance

            trace.provenance = measure_provenance(answer_text, passages).as_dict()
        trace.failure_category = classify_failure(trace) if decision != "accept" else None
        if self.store is not None:
            self.store.record(trace)
            if trace.failure_category:
                self.store.record_failure(trace, trace.failure_category)
        return Answer(answer_text, decision, confidence, trace)


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
