"""Biology benchmark and the SRS 25 four-system ablation harness."""

from .harness import (
    BenchmarkReport,
    CallableRunner,
    SystemResult,
    SystemRunner,
    format_markdown_table,
    run_benchmark,
    run_system,
)
from .questions import all_questions
from .schema import AnswerKey, BenchmarkQuestion, Difficulty, System, read_jsonl, write_jsonl
from .scorer import QuestionScore, score_answer

__all__ = [
    "AnswerKey",
    "BenchmarkQuestion",
    "BenchmarkReport",
    "CallableRunner",
    "Difficulty",
    "QuestionScore",
    "System",
    "SystemResult",
    "SystemRunner",
    "all_questions",
    "format_markdown_table",
    "read_jsonl",
    "run_benchmark",
    "run_system",
    "score_answer",
    "write_jsonl",
]
