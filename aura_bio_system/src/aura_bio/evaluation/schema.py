"""Benchmark question schema and the four systems under comparison (SRS 25).

The benchmark exists to compare, on the same questions:

* `baseline` — the raw local model, no retrieval (SRS 25 config 1);
* `basic_rag` — hybrid retrieval only, no rerank/verify/critique (config 4);
* `full_rag` — the complete pipeline: routing, rerank, verification, critique,
  revision (config 10);
* `finetuned_rag` — the full pipeline on a LoRA-adapted model (config 11).

Each question carries a machine-checkable answer key so scoring does not depend
on an LLM judge alone, which SRS 31 Risk 4 warns against.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator


class System(StrEnum):
    BASELINE = "baseline"
    BASIC_RAG = "basic_rag"
    FULL_RAG = "full_rag"
    FINETUNED_RAG = "finetuned_rag"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass(frozen=True, slots=True)
class AnswerKey:
    """Machine-checkable expectations for one question.

    Every field is optional so a question only declares the checks that apply
    to it. A factual question uses ``must_include``; a numerical question uses
    ``numeric``; a process question uses ``ordered_steps``.
    """

    must_include: tuple[str, ...] = ()
    must_avoid: tuple[str, ...] = ()
    ordered_steps: tuple[str, ...] = ()
    numeric: float | None = None
    numeric_tolerance: float = 0.02
    reference_answer: str = ""
    acceptable_answers: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.must_include:
            payload["must_include"] = list(self.must_include)
        if self.must_avoid:
            payload["must_avoid"] = list(self.must_avoid)
        if self.ordered_steps:
            payload["ordered_steps"] = list(self.ordered_steps)
        if self.numeric is not None:
            payload["numeric"] = self.numeric
            payload["numeric_tolerance"] = self.numeric_tolerance
        if self.reference_answer:
            payload["reference_answer"] = self.reference_answer
        if self.acceptable_answers:
            payload["acceptable_answers"] = list(self.acceptable_answers)
        return payload


@dataclass(frozen=True, slots=True)
class BenchmarkQuestion:
    id: str
    question: str
    subdomain: str
    task_type: str
    level: str
    difficulty: Difficulty
    answer_key: AnswerKey
    adversarial: bool = False
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "subdomain": self.subdomain,
            "task_type": self.task_type,
            "level": self.level,
            "difficulty": str(self.difficulty),
            "adversarial": self.adversarial,
            "tags": list(self.tags),
            "answer_key": self.answer_key.as_dict(),
        }


def write_jsonl(questions: list[BenchmarkQuestion], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for question in questions:
            handle.write(json.dumps(question.as_dict(), ensure_ascii=False) + "\n")
    return len(questions)


def read_jsonl(path: Path) -> Iterator[BenchmarkQuestion]:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        key = row.get("answer_key", {})
        yield BenchmarkQuestion(
            id=row["id"],
            question=row["question"],
            subdomain=row["subdomain"],
            task_type=row["task_type"],
            level=row["level"],
            difficulty=Difficulty(row["difficulty"]),
            adversarial=row.get("adversarial", False),
            tags=tuple(row.get("tags", ())),
            answer_key=AnswerKey(
                must_include=tuple(key.get("must_include", ())),
                must_avoid=tuple(key.get("must_avoid", ())),
                ordered_steps=tuple(key.get("ordered_steps", ())),
                numeric=key.get("numeric"),
                numeric_tolerance=key.get("numeric_tolerance", 0.02),
                reference_answer=key.get("reference_answer", ""),
                acceptable_answers=tuple(key.get("acceptable_answers", ())),
            ),
        )
