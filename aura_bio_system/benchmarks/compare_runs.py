"""Compare two runs on the questions they share, re-scored with one scorer.

Written for the learned-versus-rules router A/B, but general. The point it
exists to make: routing accuracy is a *proxy*. A router that classifies better
can still produce worse answers, because learner level selects the prompt's
length and register guidance -- routing a postgraduate question to
``high_school`` does not merely mislabel it, it asks for a shorter and simpler
answer. Only comparing the answers can settle that.

    python benchmarks/compare_runs.py results/a.jsonl results/b.jsonl

Reports the paired difference with a confidence interval, because on small
question counts these differences are usually not resolvable and saying so is
more useful than quoting a mean.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


def _rows(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        previous = out.get(row["id"])
        if previous is None or not row.get("error") or previous.get("error"):
            out[row["id"]] = row
    return {qid: r for qid, r in out.items() if not r.get("error") and r.get("answer")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    parser.add_argument("--quiet", action="store_true", help="skip the per-question table")
    args = parser.parse_args(argv)

    from aura_bio.evaluation import all_questions, score_answer

    questions = {q.id: q for q in all_questions()}
    left, right = _rows(args.a), _rows(args.b)
    shared = sorted(set(left) & set(right))
    if not shared:
        print("no successfully-answered questions in common")
        return 1

    name_a, name_b = args.a.stem, args.b.stem
    scores_a, scores_b, deltas = [], [], []
    if not args.quiet:
        print(f"{'id':<11} {name_a[:14]:>14} {name_b[:14]:>14} {'delta':>7} {'len a':>7} {'len b':>7}  level (a -> b)")
    for qid in shared:
        sa = score_answer(questions[qid], left[qid]["answer"]).overall
        sb = score_answer(questions[qid], right[qid]["answer"]).overall
        scores_a.append(sa)
        scores_b.append(sb)
        deltas.append(sb - sa)
        if not args.quiet:
            def level(row: dict[str, Any]) -> str:
                entry = ((row.get("trace") or {}).get("route") or {}).get("learner_level") or {}
                return str(entry.get("label", "?"))
            flag = "  <--" if abs(sb - sa) > 1e-9 else ""
            print(f"{qid:<11} {sa:>14.2f} {sb:>14.2f} {sb - sa:>+7.2f} "
                  f"{len(left[qid]['answer']):>7} {len(right[qid]['answer']):>7}  "
                  f"{level(left[qid])} -> {level(right[qid])}{flag}")

    mean_delta = statistics.mean(deltas)
    print(f"\nn={len(shared)}")
    print(f"  {name_a:<24} {statistics.mean(scores_a):.4f}")
    print(f"  {name_b:<24} {statistics.mean(scores_b):.4f}")
    print(f"  {'difference':<24} {mean_delta:+.4f}")
    better = sum(1 for d in deltas if d > 0)
    worse = sum(1 for d in deltas if d < 0)
    print(f"  {name_b} better on {better}, worse on {worse}, tied on {len(deltas) - better - worse}")

    if len(deltas) > 1:
        sd = statistics.stdev(deltas)
        se = sd / math.sqrt(len(deltas))
        lo, hi = mean_delta - 1.96 * se, mean_delta + 1.96 * se
        print(f"  paired SD {sd:.4f}, 95% CI [{lo:+.4f}, {hi:+.4f}]")
        if lo <= 0 <= hi:
            need = math.ceil((1.96 * sd / mean_delta) ** 2) if mean_delta else 0
            print(f"  NOT RESOLVED at this sample size"
                  + (f"; ~{need} questions would be needed for a difference this size" if need else ""))
        else:
            print("  the interval excludes zero")

    mean_len_a = statistics.mean(len(left[q]["answer"]) for q in shared)
    mean_len_b = statistics.mean(len(right[q]["answer"]) for q in shared)
    print(f"  mean answer length {mean_len_a:.0f} -> {mean_len_b:.0f} chars "
          f"({(mean_len_b / mean_len_a - 1) * 100:+.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
