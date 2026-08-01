"""Re-grade a stored benchmark run with the current scorer.

Answers are recorded verbatim, so grading them again costs nothing and needs no
model. That matters whenever the scorer changes: runs graded by different
versions of the answer key logic are not comparable, and re-running a system to
pick up a scoring fix would waste hours of GPU time for no new information.

Writes ``<name>.rescored.jsonl`` next to the input unless told otherwise.

    python aura_bio_system/benchmarks/rescore.py results/baseline_aura-bio_v0.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from aura_bio.evaluation import all_questions, score_answer


def rescore(path: Path, out: Path | None = None, suffix: str = ".rescored.jsonl") -> Path:
    questions = {question.id: question for question in all_questions()}
    out = out or path.with_name(path.name.replace(".jsonl", "") + suffix)

    before: list[float] = []
    after: list[float] = []
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        question = questions.get(row["id"])
        if question is None:
            continue
        before.append(row["score"]["overall"])
        row["score"] = score_answer(question, row["answer"]).as_dict()
        after.append(row["score"]["overall"])
        lines.append(json.dumps(row, ensure_ascii=False))

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"{path.name}: n={len(after)} "
        f"before={statistics.mean(before):.4f} after={statistics.mean(after):.4f} "
        f"delta={statistics.mean(after) - statistics.mean(before):+.4f} -> {out.name}"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-grade stored runs with the current scorer")
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--suffix", default=".rescored.jsonl",
                        help="output suffix; use a distinct one per scorer mode so the "
                             "strict and number-agreeing gradings sit side by side")
    args = parser.parse_args(argv)
    for path in args.runs:
        rescore(path, suffix=args.suffix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
