"""Score the retrieval bank and check it against its pre-registered predictions.

The bank tags every question ``target`` (predicted: the pipeline gains) or
``control`` (predicted: no gain). Reporting both together is the point. A
pipeline that beats the baseline on the controls as well is not demonstrating
retrieval — it is demonstrating that the two systems differ in prompt or length
in some way that flatters one of them, and the target-set result cannot then be
attributed to retrieval either.

Three numbers decide whether the bank was well built:

* baseline on ``target`` should be **low**. If it is high, the selection
  hypothesis was wrong and no amount of pipeline work will show a gain here.
* baseline on ``control`` should be **high**, confirming the model really does
  know the basics and the questions are not simply badly worded.
* the gain on ``target`` minus the gain on ``control`` is the retrieval effect,
  net of anything that helps both.

    python aura_bio_system/benchmarks/report_bank.py
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from aura_bio.evaluation.schema import read_jsonl


def load(path: Path) -> dict[str, dict]:
    return {
        json.loads(line)["id"]: json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Report the retrieval bank comparison")
    parser.add_argument("--bank", type=Path, default=here / "retrieval_bank.jsonl")
    parser.add_argument("--baseline", type=Path, default=here / "results/bank_baseline.jsonl")
    parser.add_argument("--full", type=Path, default=here / "results/bank_full_rag.jsonl")
    args = parser.parse_args(argv)

    bank = {q.id: q for q in read_jsonl(args.bank)}
    base = load(args.baseline)
    full = load(args.full) if args.full.is_file() else {}
    ids = sorted(set(base) & (set(full) if full else set(base)))

    groups: dict[str, list[str]] = defaultdict(list)
    for qid in ids:
        groups[bank[qid].tags[0] if bank[qid].tags else "untagged"].append(qid)

    def mean(rows: dict[str, dict], group: list[str], key: str = "overall") -> float:
        vals = [rows[q]["score"][key] for q in group if q in rows]
        return statistics.mean(vals) if vals else float("nan")

    print(f"retrieval bank: {len(ids)} questions scored\n")
    header = f"{'group':<10}{'n':>4} {'baseline':>10} {'full_rag':>10} {'delta':>9}"
    print(header)
    print("-" * len(header))
    for tag in ("target", "control"):
        group = groups.get(tag, [])
        if not group:
            continue
        b = mean(base, group)
        if full:
            f = mean(full, group)
            print(f"{tag:<10}{len(group):>4} {b:>10.4f} {f:>10.4f} {f - b:>+9.4f}")
        else:
            print(f"{tag:<10}{len(group):>4} {b:>10.4f} {'-':>10} {'-':>9}")
    if full and groups.get("target") and groups.get("control"):
        eff = (mean(full, groups["target"]) - mean(base, groups["target"])) - (
            mean(full, groups["control"]) - mean(base, groups["control"])
        )
        print(f"\nretrieval effect (target gain - control gain): {eff:+.4f}")

    print("\nper-question")
    for tag in ("target", "control"):
        for qid in groups.get(tag, []):
            b = base[qid]["score"]["overall"]
            row = f"  [{tag[:4]}] {qid:<8} base={b:.2f}"
            if full and qid in full:
                f = full[qid]["score"]["overall"]
                mark = "  " if abs(f - b) < 1e-9 else (" +" if f > b else " -")
                row += f" full={f:.2f}{mark} missing={full[qid]['score']['detail'].get('missing_concepts')}"
            else:
                row += f" missing={base[qid]['score']['detail'].get('missing_concepts')}"
            print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
