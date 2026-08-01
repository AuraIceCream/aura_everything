"""Query router: task, subdomain, learner level, teaching mode, context depth.

Every router returns a :class:`Classification` carrying the patterns it matched,
because SRS 21.1 requires a wrong answer to be attributable to "wrong routing"
and a routing benchmark cannot improve tables it cannot inspect.

An optional LLM classifier fills in only where the rules are not confident.
The rules stay authoritative when they are confident, so routing remains
reproducible and testable without a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from .rules import (
    ADVANCED_VOCABULARY,
    DEEP_REASONING_MARKERS,
    LEVEL_PATTERNS,
    ORDERED_PROCESSES,
    SIMPLE_REQUEST_MARKERS,
    SUBDOMAIN_TERMS,
    TASK_BASE_CONTEXT,
    TASK_DEFAULT_MODE,
    TASK_PATTERNS,
    TEACHING_PATTERNS,
)
from .schema import (
    CONTEXT_LEVEL_POLICY,
    Classification,
    LearnerLevel,
    Route,
    Subdomain,
    TaskType,
    TeachingMode,
)

#: Below this the rule decision is treated as a guess worth overriding.
LOW_CONFIDENCE = 0.35


def _never(_dimension: str) -> bool:
    """Default for classifiers that do not report measured accuracy.

    The LLM classifier has never been scored against the rules, so it keeps the
    conservative rules-first contract it was written under.
    """

    return False


class LLMClassifier(Protocol):
    """A local model that returns JSON for one routing question.

    Kept as a protocol so the pipeline never imports a model to run the rules,
    and so the ablation study can measure rules-only against rules-plus-LLM.
    """

    def classify(self, query: str, question: str, labels: list[str]) -> dict[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class _Scored:
    label: str
    score: float
    matched: tuple[str, ...]
    scores: dict[str, float]


def _score_patterns(text: str, table: dict[Any, tuple[tuple[str, float], ...]]) -> _Scored | None:
    """Sum pattern weights per label and report which patterns fired."""

    totals: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for label, patterns in table.items():
        for pattern, weight in patterns:
            if re.search(pattern, text):
                key = str(label)
                totals[key] = totals.get(key, 0.0) + weight
                hits.setdefault(key, []).append(pattern)
    if not totals:
        return None
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    best, best_score = ranked[0]
    return _Scored(best, best_score, tuple(hits[best]), totals)


def _confidence(scored: _Scored | None, saturation: float = 5.0) -> float:
    """Blend absolute evidence with the margin over the runner-up.

    A label that wins 6.0 to 5.5 is a genuinely ambiguous query and should not
    report the same confidence as one that wins 6.0 to 0.
    """

    if scored is None:
        return 0.0
    ranked = sorted(scored.scores.values(), reverse=True)
    runner_up = ranked[1] if len(ranked) > 1 else 0.0
    strength = min(1.0, scored.score / saturation)
    margin = (scored.score - runner_up) / scored.score if scored.score else 0.0
    return round(0.5 * strength + 0.5 * strength * margin, 4)


def _weight_sum(text: str, patterns: tuple[tuple[str, float], ...]) -> tuple[float, list[str]]:
    total = 0.0
    matched: list[str] = []
    for pattern, weight in patterns:
        if re.search(pattern, text):
            total += weight
            matched.append(pattern)
    return total, matched


class QueryRouter:
    """Composes the five SRS routers into one reproducible decision."""

    def __init__(self, classifier: LLMClassifier | None = None) -> None:
        self.classifier = classifier

    # -- individual routers ---------------------------------------------------

    def route_task(self, text: str) -> Classification:
        scored = _score_patterns(text, TASK_PATTERNS)
        if scored is None:
            # A bare noun phrase with no interrogative is nearly always a
            # request to explain the topic, not small talk.
            return Classification(
                TaskType.CONCEPT_EXPLANATION, 0.2, source="fallback", scores={}
            )
        return Classification(scored.label, _confidence(scored), scored.matched, "rules", scored.scores)

    def route_subdomain(self, text: str) -> tuple[Classification, tuple[str, ...]]:
        scored = _score_patterns(text, SUBDOMAIN_TERMS)
        if scored is None:
            return (
                Classification(Subdomain.GENERAL_BIOLOGY, 0.15, source="fallback"),
                (),
            )
        confidence = _confidence(scored, saturation=4.0)
        # SRS 8.3 allows more than one subdomain; anything within 60% of the
        # winner is worth carrying into retrieval filters and verifier policy.
        threshold = scored.score * 0.6
        secondary = tuple(
            label
            for label, value in sorted(scored.scores.items(), key=lambda item: item[1], reverse=True)
            if label != scored.label and value >= threshold
        )
        if len(secondary) >= 2:
            return (
                Classification(
                    Subdomain.INTERDISCIPLINARY,
                    confidence,
                    scored.matched,
                    "rules",
                    scored.scores,
                ),
                (scored.label,) + secondary,
            )
        return (
            Classification(scored.label, confidence, scored.matched, "rules", scored.scores),
            secondary,
        )

    def route_learner_level(self, text: str, declared: LearnerLevel | None = None) -> Classification:
        if declared is not None:
            return Classification(declared, 1.0, ("explicit",), "user")
        scored = _score_patterns(text, LEVEL_PATTERNS)
        if scored is not None and scored.score >= 2.5:
            return Classification(
                scored.label, _confidence(scored, saturation=3.0), scored.matched, "rules", scored.scores
            )
        # No stated level: infer from the vocabulary the asker chose to use.
        advanced, advanced_hits = _weight_sum(text, ADVANCED_VOCABULARY)
        simple, simple_hits = _weight_sum(text, SIMPLE_REQUEST_MARKERS)
        if advanced >= 4.0:
            return Classification(
                LearnerLevel.RESEARCH, min(0.75, advanced / 8), tuple(advanced_hits), "vocabulary"
            )
        if advanced >= 2.0:
            return Classification(
                LearnerLevel.UNDERGRADUATE, min(0.6, advanced / 6), tuple(advanced_hits), "vocabulary"
            )
        if simple >= 1.5:
            return Classification(
                LearnerLevel.GENERAL_PUBLIC, min(0.5, simple / 4), tuple(simple_hits), "vocabulary"
            )
        if scored is not None:
            return Classification(
                scored.label, _confidence(scored, saturation=3.0), scored.matched, "rules", scored.scores
            )
        # SRS 6.1 puts school students first, so an unmarked query defaults to
        # the level that needs the most scaffolding without being childish.
        return Classification(LearnerLevel.HIGH_SCHOOL, 0.2, source="default")

    def route_teaching_mode(
        self, text: str, task: TaskType, level: LearnerLevel, declared: TeachingMode | None = None
    ) -> Classification:
        if declared is not None:
            return Classification(declared, 1.0, ("explicit",), "user")
        scored = _score_patterns(text, TEACHING_PATTERNS)
        if scored is not None and scored.score >= 2.5:
            return Classification(
                scored.label, _confidence(scored, saturation=4.0), scored.matched, "rules", scored.scores
            )
        mode = TASK_DEFAULT_MODE.get(task, TeachingMode.GUIDED_EXPLANATION)
        if level in (LearnerLevel.RESEARCH, LearnerLevel.POSTGRADUATE) and mode in (
            TeachingMode.GUIDED_EXPLANATION,
            TeachingMode.DIRECT_ANSWER,
        ):
            mode = TeachingMode.RESEARCH
        return Classification(mode, 0.45, (f"task:{task}",), "task_default")

    def route_context_level(
        self, text: str, task: TaskType, level: LearnerLevel, declared: int | None = None
    ) -> int:
        if declared is not None:
            return max(0, min(4, declared))
        context = TASK_BASE_CONTEXT.get(task, 2)
        depth, _ = _weight_sum(text, DEEP_REASONING_MARKERS)
        if depth >= 2.0:
            context = max(context, 4)
        elif depth >= 1.0:
            context = max(context, 3)
        if level in (LearnerLevel.RESEARCH, LearnerLevel.POSTGRADUATE):
            context = max(context, 3)
        if level in (LearnerLevel.ELEMENTARY, LearnerLevel.MIDDLE_SCHOOL) and context > 2:
            # Depth here buys evidence the answer will not be allowed to use.
            context = 2
        if len(text.split()) > 45:
            context = max(context, 3)
        return max(0, min(4, context))

    # -- composition ----------------------------------------------------------

    def route(
        self,
        query: str,
        learner_level: LearnerLevel | str | None = None,
        teaching_mode: TeachingMode | str | None = None,
        context_level: int | None = None,
    ) -> Route:
        text = query.lower().strip()
        overrides = tuple(
            name
            for name, value in (
                ("learner_level", learner_level),
                ("teaching_mode", teaching_mode),
                ("context_level", context_level),
            )
            if value is not None
        )
        declared_level = LearnerLevel(learner_level) if learner_level is not None else None
        declared_mode = TeachingMode(teaching_mode) if teaching_mode is not None else None

        task = self._consult(query, "task type", list(TaskType), self.route_task(text))
        subdomain, secondary = self.route_subdomain(text)
        subdomain = self._consult(query, "biology subdomain", list(Subdomain), subdomain)
        # route_subdomain builds `secondary` by excluding whichever label the
        # rules chose. If the classifier then picks a different primary, the
        # rules' pick becomes a legitimate secondary and the classifier's must
        # not be listed as its own secondary.
        secondary = tuple(label for label in secondary if label != str(subdomain.label))
        level = self.route_learner_level(text, declared_level)
        # Level was the one routed dimension with no classifier fallback, and
        # the one that needed it most: the rules answer "high_school" at
        # confidence 0.2 for 439 of 441 benchmark questions because real
        # questions rarely state a level. An explicitly declared level is
        # returned at confidence 1.0 by route_learner_level and so survives
        # _consult's superseding branch too — see the guard there.
        level = self._consult(query, "learner level", list(LearnerLevel), level)
        mode = self.route_teaching_mode(text, TaskType(task.label), LearnerLevel(level.label), declared_mode)
        depth = self.route_context_level(text, TaskType(task.label), LearnerLevel(level.label), context_level)

        policy = CONTEXT_LEVEL_POLICY[depth]
        return Route(
            query=query,
            task_type=task,
            subdomain=subdomain,
            secondary_subdomains=secondary,
            learner_level=level,
            teaching_mode=mode,
            context_level=depth,
            needs_retrieval=depth > 0,
            needs_process_verification=mentions_ordered_process(text)
            or task.label == TaskType.PROCESS_EXPLANATION,
            needs_numerical_verification=task.label == TaskType.NUMERICAL,
            retrieve_k=policy["retrieve"],
            rerank_k=policy["rerank"],
            max_revisions=policy["max_revisions"],
            explicit_overrides=overrides,
        )

    def _consult(
        self, query: str, question: str, labels: list[Any], fallback: Classification
    ) -> Classification:
        """Decide whether to ask the classifier about one dimension, and obey it.

        Two ways in. The original one is a low-confidence rule: the rules admit
        they are guessing, so anything is an improvement. The second is for a
        classifier that reports, from its own training run, that it beat the
        rules on this dimension by a wide margin — see
        :meth:`EncoderClassifier.supersedes`. Without it a *confidently wrong*
        rule is unreachable, which is exactly what happened to ``task type``.

        A level the user stated explicitly is never touched by either path.
        """

        if self.classifier is None or fallback.source == "user":
            return fallback
        supersede = bool(getattr(self.classifier, "supersedes", _never)(question))
        if fallback.confidence >= LOW_CONFIDENCE and not supersede:
            return fallback
        return self._ask_llm(query, question, labels, fallback, supersede=supersede)

    def _ask_llm(
        self,
        query: str,
        question: str,
        labels: list[Any],
        fallback: Classification,
        supersede: bool = False,
    ) -> Classification:
        assert self.classifier is not None
        allowed = [str(label) for label in labels]
        try:
            result = self.classifier.classify(query, question, allowed)
        except Exception:
            # A router must never take the whole request down with it.
            return fallback
        label = str(result.get("label", "")).strip()
        if label not in allowed:
            return fallback
        confidence = float(result.get("confidence", 0.5))
        # The confidence comparison is a proxy for "which of these two is more
        # likely right", and it is only meaningful when the two numbers are on
        # the same scale. A classifier that has *measured* itself against these
        # rules has a better answer than the proxy, so it is not second-guessed.
        if confidence <= fallback.confidence and not supersede:
            return fallback
        return Classification(label, min(confidence, 0.95), ("llm",), "llm")


def mentions_ordered_process(text: str) -> tuple[str, ...] | bool:
    """Report which SRS 16.3 ordered processes a query is about."""

    found = tuple(name for name in ORDERED_PROCESSES if name in text)
    return bool(found)


def ordered_processes_in(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(name for name in ORDERED_PROCESSES if name in lowered)
