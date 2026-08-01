"""Prove every pipeline stage actually fired, rather than merely loading.

Written after the routing bug that motivates it. The trained task-type router
was loaded, reported healthy, and was *never consulted*, because the router only
asks a classifier where its own rules are unconfident and the rules were
confidently wrong. End-to-end accuracy was byte-identical with and without it.

That failure is invisible to tests (each component passed its own) and invisible
to the score (a component that never runs changes nothing). The only thing that
catches it is asking, of a real run, "did this stage leave a trace?".

So: read a results ``.jsonl`` and report, per stage, how often it fired and what
it did. A stage that never fires is the finding. Cheap enough to run after every
benchmark, and it needs no model loading.

    python benchmarks/check_liveness.py results/smoke_router_gate.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

#: Stages expected to leave a ``stage_ms`` entry when the pipeline runs with
#: ``--dense --rerank --critic``. Each maps to why its absence would matter.
EXPECTED_STAGES: dict[str, str] = {
    "routing": "questions are not being classified at all",
    "entity_check": "fabricated entities in questions are not being caught",
    "retrieval": "the corpus is not being consulted; this is the bare model",
    "rerank": "the cross-encoder is loaded but not reordering evidence",
    "evidence_selection": "retrieved passages are not being filtered",
    "generation": "no answer is being produced",
    "verification": "answers are not being checked",
}

#: Stages that are legitimately conditional -- absence is informative, not a bug.
CONDITIONAL_STAGES: dict[str, str] = {
    "critique": "the external critic (only runs when the verifier is unsure)",
}


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _pct(count: int, total: int) -> str:
    return f"{count:>3}/{total:<3} ({count / total * 100:5.1f}%)" if total else "  n/a"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=Path, help="a run's .jsonl")
    args = parser.parse_args(argv)

    rows = _rows(args.results)
    if not rows:
        print(f"{args.results} is empty")
        return 1

    errored = [r for r in rows if r.get("error")]
    live = [r for r in rows if not r.get("error")]
    print(f"{args.results.name}: {len(rows)} questions, {len(errored)} errored, {len(live)} usable\n")
    if errored:
        # An errored row has no trace, so it cannot testify to anything. Say so
        # loudly rather than reporting stages as dead when they never got to run.
        kinds = {str(r["error"])[:60] for r in errored}
        for kind in sorted(kinds):
            print(f"  ERROR x{sum(1 for r in errored if str(r['error'])[:60] == kind)}: {kind}")
        print()
    if not live:
        print("no usable rows -- every stage is untestable, fix the errors first")
        return 1

    dead: list[str] = []
    print(f"{'stage':<20} {'fired':>16}  {'median ms':>10}")
    print("-" * 52)
    for stage, consequence in {**EXPECTED_STAGES, **CONDITIONAL_STAGES}.items():
        timings = [
            float((r.get("trace") or {}).get("stage_ms", {})[stage])
            for r in live
            if stage in ((r.get("trace") or {}).get("stage_ms") or {})
        ]
        median = sorted(timings)[len(timings) // 2] if timings else 0.0
        marker = "" if timings else ("   <-- CONDITIONAL" if stage in CONDITIONAL_STAGES else "   <-- NEVER FIRED")
        print(f"{stage:<20} {_pct(len(timings), len(live)):>16}  {median:>10.1f}{marker}")
        if not timings and stage in EXPECTED_STAGES:
            dead.append(f"{stage}: {consequence}")

    # The router is the specific stage that failed silently before, so check it
    # by its effect rather than by whether it ran: a learned router that never
    # overrides a rule is indistinguishable from an absent one.
    sources: dict[str, int] = {}
    for row in live:
        for dimension in ("task_type", "subdomain", "learner_level"):
            entry = ((row.get("trace") or {}).get("route") or {}).get(dimension) or {}
            if entry.get("source"):
                sources[f"{dimension}:{entry['source']}"] = sources.get(f"{dimension}:{entry['source']}", 0) + 1
    if sources:
        print("\nrouting decisions by source (llm = the learned classifier was used):")
        for key in sorted(sources):
            print(f"  {key:<32} {sources[key]}")

    # The revision loop has no stage of its own -- a revised answer is generated
    # under "generation" -- so it is read from the attempt count instead. A
    # trace records 1 for a single pass, so anything above 1 is a revision that
    # actually happened.
    attempts = [int((r.get("trace") or {}).get("revisions") or 1) for r in live]
    revised = sum(1 for a in attempts if a > 1)
    print(f"\nrevision loop: fired on {_pct(revised, len(live))} "
          f"(max {max(attempts)} attempts on one question)")

    verdicts: dict[str, int] = {}
    for row in live:
        verdicts[str((row.get("trace") or {}).get("decision"))] = (
            verdicts.get(str((row.get("trace") or {}).get("decision")), 0) + 1
        )
    print("\nverifier decisions:", ", ".join(f"{k}={v}" for k, v in sorted(verdicts.items())))

    checkers: dict[str, int] = {}
    for row in live:
        for issue in (row.get("trace") or {}).get("issues") or []:
            checkers[str(issue.get("checker"))] = checkers.get(str(issue.get("checker")), 0) + 1
    print("issues raised by checker:", ", ".join(f"{k}={v}" for k, v in sorted(checkers.items())) or "none")

    if dead:
        print("\nDEAD STAGES -- each of these is a component that is not doing its job:")
        for line in dead:
            print(f"  {line}")
        return 1
    print("\nall expected stages fired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
