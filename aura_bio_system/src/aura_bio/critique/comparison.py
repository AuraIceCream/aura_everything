"""Compare external critics (GLM vs Gemini) for the AURA-Bio use case.

The question the comparison answers is not "which model is smarter" but "which
critic best does the job the pipeline needs": catch a biology answer that should
be revised, leave a sound answer alone, and agree with the deterministic
verifier. It is graded against a small labelled set of answers with planted
errors, so the metric is decision accuracy, not vibes.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..routing import QueryRouter
from ..routing.schema import Route
from ..verification import BiologyVerifier, EvidencePassage
from .external import CriticResult
from .schema import combine_decision


@dataclass(frozen=True, slots=True)
class CriticCase:
    """One answer to review, with the correct verdict and why."""

    question: str
    answer: str
    evidence: tuple[EvidencePassage, ...]
    should_revise: bool
    label: str  # what is (or is not) wrong with the answer


def _passage(text: str, title: str = "source") -> EvidencePassage:
    return EvidencePassage(chunk_id="c", text=text, title=title, source_id="wikipedia_biology")


# A labelled set spanning the failure modes SRS 21.1 cares about. Half are sound
# answers the critic must leave alone; half contain a specific planted error.
CRITIC_CASES: list[CriticCase] = [
    CriticCase(
        "Explain how helicase works in DNA replication.",
        "Helicase unwinds the double helix at the origin of replication by breaking the hydrogen "
        "bonds between complementary base pairs, separating the two strands so polymerase can copy them. [1]",
        (_passage("Helicase unwinds the DNA double helix at the replication origin by breaking hydrogen "
                  "bonds between base pairs, separating the parental strands during replication."),),
        should_revise=False, label="sound: supported, correct",
    ),
    CriticCase(
        "What are the stages of mitosis?",
        "Mitosis proceeds through anaphase, then metaphase, then prophase, and finally telophase, "
        "before the cell divides. [1]",
        (_passage("Mitosis occurs in the order prophase, metaphase, anaphase, telophase, followed by cytokinesis."),),
        should_revise=True, label="process-order error (reversed)",
    ),
    CriticCase(
        "Where does glycolysis take place?",
        "Glycolysis takes place inside the mitochondria of the cell, where glucose is split into pyruvate. [1]",
        (_passage("Glycolysis occurs in the cytoplasm (cytosol) of the cell, where glucose is broken down to pyruvate."),),
        should_revise=True, label="wrong location (mitochondria vs cytoplasm)",
    ),
    CriticCase(
        "How many chromosomes are in a human somatic cell?",
        "A human somatic cell contains 46 chromosomes, arranged in 23 homologous pairs. [1]",
        (_passage("Human somatic (body) cells are diploid and contain 46 chromosomes in 23 pairs."),),
        should_revise=False, label="sound: correct fact",
    ),
    CriticCase(
        "How many chromosomes are in a human somatic cell?",
        "A human somatic cell contains 92 chromosomes in 46 pairs. [1]",
        (_passage("Human somatic (body) cells are diploid and contain 46 chromosomes in 23 pairs."),),
        should_revise=True, label="wrong number, contradicts evidence",
    ),
    CriticCase(
        "What is the role of ATP synthase?",
        "ATP synthase lets protons flow down their electrochemical gradient across the inner "
        "mitochondrial membrane and couples that flow to the synthesis of ATP from ADP and phosphate. [1]",
        (_passage("ATP synthase allows protons to move down their electrochemical gradient and uses that "
                  "energy to phosphorylate ADP to ATP across the inner mitochondrial membrane."),),
        should_revise=False, label="sound: supported mechanism",
    ),
    CriticCase(
        "Explain the function of the Golgi mitochondrial bridge organelle.",
        "The Golgi mitochondrial bridge organelle shuttles lipids directly between the Golgi and "
        "mitochondria, coordinating membrane synthesis in the cell. [1]",
        (_passage("The Golgi apparatus modifies, sorts, and packages proteins and lipids for transport."),),
        should_revise=True, label="hallucinated non-existent organelle",
    ),
    CriticCase(
        "Define an enzyme.",
        "An enzyme is a biological catalyst, usually a protein, that speeds up a reaction by lowering "
        "its activation energy without being consumed. [1]",
        (_passage("Enzymes are biological catalysts, typically proteins, that lower activation energy and "
                  "increase reaction rates without being used up."),),
        should_revise=False, label="sound: correct definition",
    ),
    CriticCase(
        "Is it true that we only use 10% of our brains?",
        "Yes, humans only use about 10% of their brains, and the other 90% is dormant and unused. [1]",
        (_passage("The claim that humans use only 10% of their brains is a myth; brain imaging shows "
                  "virtually all regions are active."),),
        should_revise=True, label="endorses a myth the evidence refutes",
    ),
    CriticCase(
        "Explain photosynthesis for a Class 6 student.",
        "Photosynthesis is the light-dependent reduction of NADP+ coupled to non-cyclic photophosphorylation "
        "in the thylakoid, feeding the Calvin-Benson cycle's carboxylation of ribulose-1,5-bisphosphate. [1]",
        (_passage("Plants make their own food using sunlight, water, and carbon dioxide, producing glucose "
                  "and oxygen. This process is called photosynthesis."),),
        should_revise=True, label="level mismatch: far too advanced for Class 6",
    ),
    CriticCase(
        "What does DNA polymerase do?",
        "DNA polymerase synthesises a new DNA strand by adding nucleotides complementary to the template, "
        "working in the 5' to 3' direction. [1]",
        (_passage("DNA polymerase adds nucleotides to a growing strand in the 5' to 3' direction, using the "
                  "template strand to determine the complementary base."),),
        should_revise=False, label="sound: correct and supported",
    ),
    CriticCase(
        "Compare arteries and veins.",
        "Arteries carry blood towards the heart under low pressure, while veins carry blood away from the "
        "heart under high pressure. [1]",
        (_passage("Arteries carry blood away from the heart under high pressure; veins return blood to the "
                  "heart under lower pressure and contain valves."),),
        should_revise=True, label="reversed artery/vein direction",
    ),
]


def _levels_for(question: str) -> Route:
    router = QueryRouter()
    if "Class 6" in question:
        return router.route(question, learner_level="middle_school")
    return router.route(question)


@dataclass(slots=True)
class CriticScore:
    name: str
    decisions_correct: int
    total: int
    false_accepts: int      # should_revise but critic accepted (dangerous)
    false_revises: int      # sound answer but critic flagged
    parse_failures: int
    latencies_ms: list[float]
    tokens: list[int]
    agree_with_verifier: int
    per_case: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "critic": self.name,
            "decision_accuracy": round(self.decisions_correct / self.total, 3) if self.total else 0.0,
            "false_accept_rate": round(self.false_accepts / self.total, 3) if self.total else 0.0,
            "false_revise_rate": round(self.false_revises / self.total, 3) if self.total else 0.0,
            "verifier_agreement": round(self.agree_with_verifier / self.total, 3) if self.total else 0.0,
            "parse_failures": self.parse_failures,
            "median_latency_ms": round(statistics.median(self.latencies_ms), 1) if self.latencies_ms else None,
            "total_completion_tokens": sum(self.tokens) if self.tokens else None,
            "cases": self.total,
        }


def compare_critics(
    critics: Sequence[Any],
    cases: Sequence[CriticCase] = tuple(CRITIC_CASES),
    verifier: BiologyVerifier | None = None,
    pause_seconds: float = 1.0,
) -> dict[str, Any]:
    """Run each critic over the labelled cases and score decision quality.

    Each critic must expose ``review_detailed(route, answer, evidence) ->
    CriticResult``. The verifier's own decision is computed too, so the table
    shows how a deterministic-only pipeline would have done on the same cases.
    """

    verifier = verifier or BiologyVerifier()
    routes = [(_levels_for(case.question), case) for case in cases]

    verifier_correct = 0
    for route, case in routes:
        report = verifier.verify(case.answer, list(case.evidence), route, case.question)
        revised = report.decision() != "accept"
        verifier_correct += int(revised == case.should_revise)

    scores: list[CriticScore] = []
    for critic in critics:
        score = CriticScore(getattr(critic, "name", type(critic).__name__), 0, 0, 0, 0, 0, [], [], 0)
        for index, (route, case) in enumerate(routes):
            # Free provider tiers rate-limit bursts; a short gap between calls
            # avoids most 429s, and the client retries the rest.
            if index and pause_seconds:
                time.sleep(pause_seconds)
            result: CriticResult = critic.review_detailed(route, case.answer, case.evidence)
            report = verifier.verify(case.answer, list(case.evidence), route, case.question)
            combined = combine_decision(report, result.critique)
            critic_revises = result.critique.decision in ("revise", "reject")
            score.total += 1
            if result.error:
                score.parse_failures += 1
            elif not result.critique.trusted:
                score.parse_failures += 1
            score.decisions_correct += int(critic_revises == case.should_revise)
            if case.should_revise and not critic_revises:
                score.false_accepts += 1
            if not case.should_revise and critic_revises:
                score.false_revises += 1
            if result.latency_ms:
                score.latencies_ms.append(result.latency_ms)
            if result.completion_tokens:
                score.tokens.append(result.completion_tokens)
            score.agree_with_verifier += int(critic_revises == (report.decision() != "accept"))
            score.per_case.append(
                {
                    "label": case.label,
                    "should_revise": case.should_revise,
                    "critic_decision": result.critique.decision,
                    "combined_decision": combined,
                    "correct": critic_revises == case.should_revise,
                    "latency_ms": round(result.latency_ms, 1),
                    "error": result.error,
                }
            )
        scores.append(score)

    return {
        "cases": len(cases),
        "verifier_only_accuracy": round(verifier_correct / len(cases), 3) if cases else 0.0,
        "critics": [score.summary() for score in scores],
        "detail": {score.name: score.per_case for score in scores},
    }


def format_comparison_table(result: dict[str, Any]) -> str:
    header = (
        "| Critic | Decision acc. | False-accept | False-revise | Verifier agree | "
        "Parse fails | Median ms | Tokens |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|"
    )
    lines = [header]

    def cell(value: Any) -> str:
        return "—" if value is None else (f"{value:.3f}" if isinstance(value, float) else str(value))

    for critic in result["critics"]:
        lines.append(
            f"| {critic['critic']} | {cell(critic['decision_accuracy'])} | "
            f"{cell(critic['false_accept_rate'])} | {cell(critic['false_revise_rate'])} | "
            f"{cell(critic['verifier_agreement'])} | {cell(critic['parse_failures'])} | "
            f"{cell(critic['median_latency_ms'])} | {cell(critic['total_completion_tokens'])} |"
        )
    lines.append("")
    lines.append(f"Deterministic verifier alone: {result['verifier_only_accuracy']:.3f} decision accuracy "
                 f"over {result['cases']} cases.")
    return "\n".join(lines)
