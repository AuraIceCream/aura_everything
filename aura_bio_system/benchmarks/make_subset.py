"""Draw a reproducible, representative subset of the benchmark.

A 441-question run takes tens of hours on this hardware, which is too slow to
iterate against. This picks a fixed subset that keeps the shape of the whole
set, so a number measured on it predicts the number the full run would give,
and writes it as a plain id list. Every system under comparison then reads the
same file and answers exactly the same questions.

Sampling is stratified by task type and by the adversarial flag, and seeded, so
re-running this produces the identical subset.

    python aura_bio_system/benchmarks/make_subset.py --size 100 --out subset_100.txt
"""

from __future__ import annotations

import argparse
import random
from collections import Counter, defaultdict
from pathlib import Path

from aura_bio.evaluation import all_questions


def build_subset(
    size: int,
    seed: int,
    pool: list[str] | None = None,
    prefer: set[str] | None = None,
) -> list[str]:
    """Draw ``size`` ids, stratified by task type and adversarial flag.

    ``pool`` restricts the draw to an existing id list, so a smaller subset can
    be carved out of a larger one and stay comparable to it. ``prefer`` names
    ids to take first within each stratum — used to keep questions a run has
    already answered, so shrinking a run costs no repeated GPU time and does not
    bias the sample: preference operates inside a stratum, and the stratum sizes
    are fixed by the proportional allocation below.
    """

    questions = all_questions()
    if pool is not None:
        keep = set(pool)
        questions = [question for question in questions if question.id in keep]
    total = len(questions)
    strata: dict[tuple[str, bool], list[str]] = defaultdict(list)
    for question in questions:
        strata[(question.task_type, question.adversarial)].append(question.id)

    rng = random.Random(seed)
    # Largest-remainder allocation: proportional shares, with the leftover seats
    # going to the strata that lost the most to rounding. Plain rounding would
    # drop every stratum smaller than half a seat, which is where the adversarial
    # questions live.
    exact = {key: len(ids) * size / total for key, ids in strata.items()}
    counts = {key: int(value) for key, value in exact.items()}
    for key, _ in sorted(exact.items(), key=lambda item: item[1] - int(item[1]), reverse=True):
        if sum(counts.values()) >= size:
            break
        counts[key] += 1

    prefer = prefer or set()
    chosen: list[str] = []
    for key in sorted(strata):
        take = min(counts[key], len(strata[key]))
        members = sorted(strata[key])
        kept = [qid for qid in members if qid in prefer][:take]
        rest = [qid for qid in members if qid not in prefer]
        chosen.extend(kept)
        chosen.extend(rng.sample(rest, take - len(kept)))
    # Keep benchmark order so a partial run is still spread across the corpus.
    order = {question.id: index for index, question in enumerate(questions)}
    return sorted(chosen, key=lambda qid: order[qid])


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Draw a stratified benchmark subset")
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--out", type=Path, default=here / "subset_100.txt")
    parser.add_argument("--from-file", type=Path,
                        help="subsample this id list instead of the whole benchmark")
    parser.add_argument("--prefer-file", type=Path,
                        help="jsonl of an in-progress run; its answered ids are kept "
                             "where the strata allow, so shrinking a run reuses its work")
    args = parser.parse_args(argv)

    pool = None
    if args.from_file:
        pool = [line.strip() for line in args.from_file.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    prefer: set[str] = set()
    if args.prefer_file and args.prefer_file.is_file():
        import json as _json

        for line in args.prefer_file.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                prefer.add(_json.loads(line)["id"])

    ids = build_subset(args.size, args.seed, pool=pool, prefer=prefer)
    if prefer:
        print(f"reused {len(set(ids) & prefer)} of {len(prefer)} already-answered questions")
    args.out.write_text("\n".join(ids) + "\n", encoding="utf-8")

    by_id = {question.id: question for question in all_questions()}
    picked = [by_id[qid] for qid in ids]
    print(f"{len(ids)} questions -> {args.out}")
    print("task_type:", dict(Counter(q.task_type for q in picked)))
    print("adversarial:", dict(Counter(q.adversarial for q in picked)))
    print("level:", dict(Counter(q.level for q in picked)))
    print("subdomains:", len({q.subdomain for q in picked}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
