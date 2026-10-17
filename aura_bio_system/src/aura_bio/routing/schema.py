"""Label spaces and the routing decision record.

The label sets are fixed here rather than in each router so that the routers,
the prompt templates, the evaluation sets, and the trace schema cannot drift
apart from one another.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskType(StrEnum):
    """SRS 8.2 request categories."""

    FACTUAL_RECALL = "factual_recall"
    DEFINITION = "definition"
    CONCEPT_EXPLANATION = "concept_explanation"
    PROCESS_EXPLANATION = "process_explanation"
    COMPARISON = "comparison"
    NUMERICAL = "numerical"
    MISCONCEPTION_CORRECTION = "misconception_correction"
    RESEARCH_PAPER = "research_paper"
    EXAM_ANSWER = "exam_answer"
    QUIZ_GENERATION = "quiz_generation"
    REVISION = "revision"
    SUMMARY = "summary"
    CONVERSATIONAL = "conversational"


class Subdomain(StrEnum):
    """SRS 8.3 biology subdomains."""

    GENERAL_BIOLOGY = "general_biology"
    CELL_BIOLOGY = "cell_biology"
    MOLECULAR_BIOLOGY = "molecular_biology"
    GENETICS = "genetics"
    MICROBIOLOGY = "microbiology"
    BOTANY = "botany"
    ZOOLOGY = "zoology"
    ECOLOGY = "ecology"
    EVOLUTION = "evolution"
    PHYSIOLOGY = "physiology"
    ANATOMY = "anatomy"
    IMMUNOLOGY = "immunology"
    BIOCHEMISTRY = "biochemistry"
    BIOTECHNOLOGY = "biotechnology"
    NEUROSCIENCE = "neuroscience"
    DEVELOPMENTAL_BIOLOGY = "developmental_biology"
    BIOINFORMATICS = "bioinformatics"
    INTERDISCIPLINARY = "interdisciplinary"


class LearnerLevel(StrEnum):
    """SRS 8.4 academic levels, ordered from least to most advanced."""

    ELEMENTARY = "elementary"
    MIDDLE_SCHOOL = "middle_school"
    HIGH_SCHOOL = "high_school"
    SENIOR_SECONDARY = "senior_secondary"
    UNDERGRADUATE = "undergraduate"
    POSTGRADUATE = "postgraduate"
    RESEARCH = "research"
    GENERAL_PUBLIC = "general_public"


LEVEL_ORDER: tuple[LearnerLevel, ...] = (
    LearnerLevel.ELEMENTARY,
    LearnerLevel.MIDDLE_SCHOOL,
    LearnerLevel.HIGH_SCHOOL,
    LearnerLevel.SENIOR_SECONDARY,
    LearnerLevel.UNDERGRADUATE,
    LearnerLevel.POSTGRADUATE,
    LearnerLevel.RESEARCH,
)


class TeachingMode(StrEnum):
    """SRS 9.1 teaching styles."""

    DIRECT_ANSWER = "direct_answer"
    GUIDED_EXPLANATION = "guided_explanation"
    SOCRATIC = "socratic"
    EXAM = "exam"
    HOMEWORK_SUPPORT = "homework_support"
    REVISION = "revision"
    MISCONCEPTION_REPAIR = "misconception_repair"
    RESEARCH = "research"
    TEACH_BACK = "teach_back"


CONTEXT_LEVEL_POLICY: dict[int, dict[str, int]] = {
    # SRS 10.1-10.5. retrieve/rerank are candidate and final evidence counts.
    0: {"retrieve": 0, "rerank": 0, "max_revisions": 0},
    1: {"retrieve": 10, "rerank": 5, "max_revisions": 1},
    2: {"retrieve": 30, "rerank": 10, "max_revisions": 1},
    3: {"retrieve": 60, "rerank": 12, "max_revisions": 1},
    4: {"retrieve": 100, "rerank": 16, "max_revisions": 2},
}


@dataclass(frozen=True, slots=True)
class Classification:
    """One router's answer plus the evidence it used, for the trace log."""

    label: str
    confidence: float
    matched: tuple[str, ...] = ()
    source: str = "rules"
    scores: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "matched": list(self.matched),
            "source": self.source,
            "scores": {key: round(value, 3) for key, value in sorted(
                self.scores.items(), key=lambda item: item[1], reverse=True
            )[:5]},
        }


@dataclass(frozen=True, slots=True)
class Route:
    """The complete pre-retrieval plan for one query."""

    query: str
    task_type: Classification
    subdomain: Classification
    secondary_subdomains: tuple[str, ...]
    learner_level: Classification
    teaching_mode: Classification
    context_level: int
    needs_retrieval: bool
    needs_process_verification: bool
    needs_numerical_verification: bool
    retrieve_k: int
    rerank_k: int
    max_revisions: int
    explicit_overrides: tuple[str, ...] = ()
    domain: str = 'biology'
    evidence_scope: str = 'core'

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "domain": self.domain,
            "evidence_scope": self.evidence_scope,
            "task_type": self.task_type.as_dict(),
            "subdomain": self.subdomain.as_dict(),
            "secondary_subdomains": list(self.secondary_subdomains),
            "learner_level": self.learner_level.as_dict(),
            "teaching_mode": self.teaching_mode.as_dict(),
            "context_level": self.context_level,
            "needs_retrieval": self.needs_retrieval,
            "needs_process_verification": self.needs_process_verification,
            "needs_numerical_verification": self.needs_numerical_verification,
            "retrieve_k": self.retrieve_k,
            "rerank_k": self.rerank_k,
            "max_revisions": self.max_revisions,
            "explicit_overrides": list(self.explicit_overrides),
        }

    def summary(self) -> dict[str, Any]:
        """The compact SRS 8.1 shape, for prompts and user-facing traces."""

        return {
            "domain": self.domain,
            **({'evidence_scope': self.evidence_scope} if self.evidence_scope != 'core' else {}),
            "subdomain": self.subdomain.label,
            "task_type": self.task_type.label,
            "learner_level": self.learner_level.label,
            "teaching_mode": self.teaching_mode.label,
            "context_level": self.context_level,
            "needs_retrieval": self.needs_retrieval,
            "needs_process_verification": self.needs_process_verification,
        }
