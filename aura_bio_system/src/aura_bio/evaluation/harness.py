"""Run the four-system ablation over the benchmark (SRS 25).

A `SystemRunner` maps a question to an answer for one configuration. The four
the project cares about:

* baseline      — the raw local model, no retrieval;
* basic_rag     — hybrid retrieval stuffed into the prompt, nothing else;
* full_rag      — the complete AuraBioPipeline (routing, rerank, verify, revise);
* finetuned_rag — the same pipeline on a LoRA-adapted model.

The harness only orchestrates and scores; it does not know how any system
produces its answer, so a system that is not available yet (no model, no LoRA)
is simply skipped rather than faked.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from .schema import BenchmarkQuestion, System
from .scorer import QuestionScore, score_answer


class SystemRunner(Protocol):
    name: str

    def answer(self, question: BenchmarkQuestion) -> str:
        ...


@dataclass(slots=True)
class CallableRunner:
    """Adapt a plain function into a SystemRunner."""

    name: str
    fn: Callable[[BenchmarkQuestion], str]

    def answer(self, question: BenchmarkQuestion) -> str:
        return self.fn(question)


@dataclass(slots=True)
class SystemResult:
    system: str
    scores: list[QuestionScore]
    latencies_ms: list[float]
    errors: int = 0
    #: Question ids the baseline already answers perfectly. Scores over the
    #: complement ("discriminative subset") separate systems far better than the
    #: overall mean, which is compressed by questions nobody can improve.
    saturated_ids: frozenset[str] = field(default_factory=frozenset)

    def discriminative_mean(self) -> float | None:
        subset = [s.overall for s in self.scores if s.question_id not in self.saturated_ids]
        return round(statistics.fmean(subset), 4) if subset else None

    def aggregate(self) -> dict[str, Any]:
        if not self.scores:
            return {"system": self.system, "answered": 0, "errors": self.errors}
        overalls = [s.overall for s in self.scores]
        recalls = [s.concept_recall for s in self.scores]
        numeric = [s for s in self.scores if s.numeric_correct is not None]
        order = [s for s in self.scores if s.order_correct is not None]
        adversarial = [s for s in self.scores if s.hallucinated is not None]
        forbidden = [s for s in self.scores if not s.avoided_forbidden]
        summary = {
            "system": self.system,
            "answered": len(self.scores),
            "errors": self.errors,
            "overall_mean": round(statistics.fmean(overalls), 4),
            "concept_recall_mean": round(statistics.fmean(recalls), 4),
            "forbidden_rate": round(len(forbidden) / len(self.scores), 4),
            "median_latency_ms": round(statistics.median(self.latencies_ms), 1)
            if self.latencies_ms else None,
            "by_subdomain": self._by_subdomain(),
        }
        if self.saturated_ids:
            summary["discriminative_mean"] = self.discriminative_mean()
            summary["discriminative_n"] = len(
                [s for s in self.scores if s.question_id not in self.saturated_ids]
            )
        if numeric:
            summary["numeric_accuracy"] = round(
                sum(s.numeric_correct for s in numeric) / len(numeric), 4
            )
        if order:
            summary["process_order_accuracy"] = round(
                sum(s.order_correct for s in order) / len(order), 4
            )
        if adversarial:
            summary["hallucination_rate"] = round(
                sum(s.hallucinated for s in adversarial) / len(adversarial), 4
            )
        return summary

    def _by_subdomain(self) -> dict[str, float]:
        buckets: dict[str, list[float]] = {}
        for score in self.scores:
            buckets.setdefault(score.subdomain, []).append(score.overall)
        return {k: round(statistics.fmean(v), 4) for k, v in sorted(buckets.items())}


@dataclass(slots=True)
class BenchmarkReport:
    results: list[SystemResult] = field(default_factory=list)
    questions: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "questions": self.questions,
            "systems": [result.aggregate() for result in self.results],
            "ablation_table": self.table(),
        }

    def table(self) -> list[dict[str, Any]]:
        """The SRS 25 comparison table, one row per system."""

        rows = []
        for result in self.results:
            agg = result.aggregate()
            rows.append(
                {
                    "System": result.system,
                    "Overall": agg.get("overall_mean"),
                    "ConceptRecall": agg.get("concept_recall_mean"),
                    "Numeric": agg.get("numeric_accuracy"),
                    "ProcessOrder": agg.get("process_order_accuracy"),
                    "Hallucination": agg.get("hallucination_rate"),
                    "Forbidden": agg.get("forbidden_rate"),
                    "LatencyMs": agg.get("median_latency_ms"),
                }
            )
        return rows


def run_system(
    runner: SystemRunner,
    questions: Sequence[BenchmarkQuestion],
    progress_every: int = 50,
) -> SystemResult:
    scores: list[QuestionScore] = []
    latencies: list[float] = []
    errors = 0
    for index, question in enumerate(questions, 1):
        started = time.perf_counter()
        try:
            answer = runner.answer(question)
        except Exception as exc:  # a broken system must not abort the whole run
            errors += 1
            answer = f"[error: {exc}]"
        latencies.append((time.perf_counter() - started) * 1000)
        scores.append(score_answer(question, answer))
        if progress_every and index % progress_every == 0:
            print(f"{runner.name}: {index}/{len(questions)}", flush=True)
    return SystemResult(system=runner.name, scores=scores, latencies_ms=latencies, errors=errors)


def run_benchmark(
    runners: Sequence[SystemRunner], questions: Sequence[BenchmarkQuestion]
) -> BenchmarkReport:
    report = BenchmarkReport(questions=len(questions))
    for runner in runners:
        print(f"=== running {runner.name} over {len(questions)} questions ===", flush=True)
        report.results.append(run_system(runner, questions))
    return report


def format_markdown_table(report: BenchmarkReport) -> str:
    """Render the ablation as the SRS 25 markdown table."""

    header = (
        "| System | Overall | Concept recall | Numeric | Process order | "
        "Hallucination | Forbidden | Latency (ms) |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|"
    )
    lines = [header]

    def cell(value: Any) -> str:
        return "—" if value is None else (f"{value:.3f}" if isinstance(value, float) else str(value))

    for row in report.table():
        lines.append(
            f"| {row['System']} | {cell(row['Overall'])} | {cell(row['ConceptRecall'])} | "
            f"{cell(row['Numeric'])} | {cell(row['ProcessOrder'])} | {cell(row['Hallucination'])} | "
            f"{cell(row['Forbidden'])} | {cell(row['LatencyMs'])} |"
        )
    return "\n".join(lines)
