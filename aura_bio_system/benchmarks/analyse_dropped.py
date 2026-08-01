"""Which concepts does the pipeline lose that the bare model already had?

The ceiling analysis says the pipeline adds 5.9% of required concepts from
retrieved evidence and loses 4.8% that the bare model names unaided, and that
these nearly cancel -- which is why the baseline, basic RAG and the full
pipeline all land on 0.878 concept coverage. The aggregate is established. What
it does not say is *which* concepts are being dropped, and that is the only form
of the number that suggests a fix.

So: pair a baseline run against a pipeline run on the same questions and split
the required concepts four ways.

    python benchmarks/analyse_dropped.py results/baseline_aura-bio_v0.jsonl \\
        results/full_rag_subset50.jsonl

Both sides are re-scored from their stored answers with the current scorer, so
files written months and several scorer fixes apart stay comparable.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _rows(path: Path) -> dict[str, dict[str, Any]]:
    """Latest non-errored row per question id."""

    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        previous = out.get(row["id"])
        if previous is None or not row.get("error") or previous.get("error"):
            out[row["id"]] = row
    return {qid: row for qid, row in out.items() if not row.get("error")}


def _missing(row: dict[str, Any], questions: dict[str, Any]) -> set[str]:
    """Concepts absent from this answer, re-scored with the *current* scorer.

    Deliberately not the ``missing_concepts`` stored in the row. Those were
    written by whichever scorer version produced the file, and the two runs
    being compared were generally scored months and several scorer fixes apart.
    Re-deriving both sides from the stored answers is the only way the
    comparison measures the systems rather than the scorer.
    """

    from aura_bio.evaluation import score_answer

    question = questions.get(row["id"])
    if question is None:
        detail = (row.get("score") or {}).get("detail") or {}
        return {str(c).lower() for c in detail.get("missing_concepts") or []}
    detail = score_answer(question, row.get("answer") or "").detail
    return {str(c).lower() for c in detail.get("missing_concepts") or []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baseline", type=Path, help="bare-model results .jsonl")
    parser.add_argument("pipeline", type=Path, help="pipeline results .jsonl")
    parser.add_argument("--top", type=int, default=25, help="how many dropped concepts to list")
    args = parser.parse_args(argv)

    from aura_bio.evaluation import all_questions

    questions = {q.id: q for q in all_questions()}
    base, pipe = _rows(args.baseline), _rows(args.pipeline)
    shared = sorted(set(base) & set(pipe))
    if not shared:
        print("the two runs share no successfully-answered questions")
        return 1

    dropped: Counter[str] = Counter()   # model had it, pipeline lost it
    gained: Counter[str] = Counter()    # pipeline found it, model lacked it
    dropped_by_question: list[tuple[str, int, list[str]]] = []
    both_missing = 0
    total_concepts = 0

    for qid in shared:
        bm, pm = _missing(base[qid], questions), _missing(pipe[qid], questions)
        # A concept missing from the pipeline but not the baseline is one the
        # model demonstrably knew and the pipeline talked it out of.
        lost = sorted(pm - bm)
        found = sorted(bm - pm)
        dropped.update(lost)
        gained.update(found)
        both_missing += len(pm & bm)
        # The required-concept count is not in the row, but every missing set is
        # a subset of it, so the union bounds what this question was scored on.
        total_concepts += len(pm | bm)
        if lost:
            dropped_by_question.append((qid, len(lost), lost))

    n_dropped, n_gained = sum(dropped.values()), sum(gained.values())
    print(f"questions compared            : {len(shared)}")
    print(f"concepts one system missed    : {total_concepts}")
    print(f"  gained by the pipeline      : {n_gained:>4}  (in evidence, not in the model)")
    print(f"  DROPPED by the pipeline     : {n_dropped:>4}  (model knew it, pipeline lost it)")
    print(f"  missed by both              : {both_missing:>4}")
    print(f"  net                         : {n_gained - n_dropped:+d}\n")

    if n_dropped:
        print(f"most-dropped concepts (top {args.top}):")
        for concept, count in dropped.most_common(args.top):
            print(f"  {count:>3}x  {concept}")
        print()
        worst = sorted(dropped_by_question, key=lambda item: item[1], reverse=True)[:10]
        print("questions losing the most:")
        for qid, count, lost in worst:
            print(f"  {qid}  -{count}: {', '.join(lost[:6])}{' ...' if len(lost) > 6 else ''}")

    if n_gained:
        print(f"\nmost-gained concepts (top {args.top}):")
        for concept, count in gained.most_common(args.top):
            print(f"  {count:>3}x  {concept}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
