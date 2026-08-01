"""Score two or more benchmark runs over exactly the same questions.

A mean taken over whichever questions a run happened to finish is not
comparable to one taken over a different set. This restricts every run to the
intersection (or to an explicit id list) before averaging, and breaks the
result down by the dimensions that turned out to matter: the pipeline's own
accept/revise decision, task type, and the adversarial subset.

    python aura_bio_system/benchmarks/compare_subset.py \
        --ids-file subset_100.txt results/baseline_aura-bio_v0.jsonl results/full_rag_subset100.jsonl
"""

from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from pathlib import Path

import json


def load(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["id"]] = row
    return rows


def _mean(rows: dict[str, dict], ids: list[str], key: str = "overall") -> float:
    values = [rows[qid]["score"][key] for qid in ids if qid in rows]
    return statistics.mean(values) if values else float("nan")


#: Provenance fields averaged across a run, or ``{}`` for a run that recorded
#: none — the baseline has no pipeline and so no trace at all.
_PROVENANCE_FIELDS = (
    "claim_citation_rate", "citation_validity", "unsupported_assertion_rate",
    "distinct_sources", "dangling_citations",
)


def _provenance(rows: dict[str, dict], ids: list[str]) -> dict[str, float]:
    records = [
        rows[qid].get("trace", {}).get("provenance") or {}
        for qid in ids
        if qid in rows
    ]
    records = [record for record in records if record]
    if not records:
        return {}
    return {
        field: statistics.mean(float(record.get(field, 0.0)) for record in records)
        for field in _PROVENANCE_FIELDS
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare benchmark runs on a shared question set")
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--ids-file", type=Path, help="restrict to these ids")
    args = parser.parse_args(argv)

    runs = {path.stem: load(path) for path in args.runs}
    ids = set.intersection(*(set(rows) for rows in runs.values()))
    if args.ids_file:
        wanted = {line.strip() for line in args.ids_file.read_text(encoding="utf-8").splitlines() if line.strip()}
        ids &= wanted
    ids = sorted(ids)
    print(f"comparing {len(ids)} questions across {len(runs)} runs\n")

    width = max(len(name) for name in runs)
    print(f"{'run':<{width}}  {'overall':>8} {'recall':>8} {'halluc':>8} {'errors':>7} {'median s':>9}")
    for name, rows in runs.items():
        adv = [q for q in ids if rows[q].get("adversarial")]
        halluc = (
            statistics.mean(bool(rows[q]["score"]["hallucinated"]) for q in adv) if adv else float("nan")
        )
        errors = sum(1 for q in ids if rows[q].get("error"))
        median_s = statistics.median(rows[q].get("latency_ms", 0) for q in ids) / 1000
        print(
            f"{name:<{width}}  {_mean(rows, ids):>8.4f} {_mean(rows, ids, 'concept_recall'):>8.4f} "
            f"{halluc:>8.3f} {errors:>7d} {median_s:>9.1f}"
        )

    # Traceability. The bare model structurally scores zero here whatever its
    # accuracy, which is the point: it cannot attribute anything it says.
    if any(_provenance(rows, ids) for rows in runs.values()):
        print("\nprovenance (claims traceable to a named source)")
        print(f"{'run':<{width}}  {'cited':>8} {'valid':>8} {'unsourced':>10} {'sources':>8} {'dangling':>9}")
        for name, rows in runs.items():
            stats = _provenance(rows, ids)
            if not stats:
                print(f"{name:<{width}}  {'-':>8} {'-':>8} {'-':>10} {'-':>8} {'-':>9}   (no trace recorded)")
                continue
            print(
                f"{name:<{width}}  {stats['claim_citation_rate']:>8.3f} "
                f"{stats['citation_validity']:>8.3f} {stats['unsupported_assertion_rate']:>10.3f} "
                f"{stats['distinct_sources']:>8.2f} {stats['dangling_citations']:>9.2f}"
            )

    print("\nby task_type")
    by_type: dict[str, list[str]] = defaultdict(list)
    first = next(iter(runs.values()))
    for qid in ids:
        by_type[first[qid]["task_type"]].append(qid)
    print(f"{'task_type':<26}{'n':>4}  " + "  ".join(f"{name:>16}" for name in runs))
    for task, group in sorted(by_type.items(), key=lambda item: -len(item[1])):
        cells = "  ".join(f"{_mean(rows, group):>16.3f}" for rows in runs.values())
        print(f"{task:<26}{len(group):>4}  {cells}")

    print("\npipeline decisions (last run)")
    last = runs[list(runs)[-1]]
    counts: dict[str, list[str]] = defaultdict(list)
    for qid in ids:
        counts[last[qid].get("trace", {}).get("decision") or "error"].append(qid)
    for decision, group in sorted(counts.items(), key=lambda item: -len(item[1])):
        revs = statistics.mean(last[q].get("trace", {}).get("revisions", 0) for q in group)
        print(f"  {decision:<22} n={len(group):>4}  score={_mean(last, group):.3f}  passes={revs:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
