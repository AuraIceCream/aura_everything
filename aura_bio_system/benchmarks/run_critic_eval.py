"""Measure the external critic against labelled answers (SRS 17, 21.1).

The critic has never been measured in situ. It is implemented, it has a working
key, and until ``load_env`` existed nothing ever put that key where
``critic_from_env`` could see it, so every benchmark run in the project's
history executed with ``critic=None``.

``critique/comparison.py`` already carries the apparatus: twelve labelled cases
spanning the SRS 21.1 failure modes — half sound answers the critic must leave
alone, half with a specific planted error — and :func:`compare_critics`, which
also computes what the deterministic verifier alone would have decided on the
same cases. That last number is the one that matters: an external critic is
only worth its latency and quota if it decides better than the free checkers.

    python aura_bio_system/benchmarks/run_critic_eval.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aura_bio.critique import critic_from_env
from aura_bio.critique.comparison import CRITIC_CASES, compare_critics, format_comparison_table
from aura_bio.env import load_env


def main(argv: list[str] | None = None) -> int:
    load_env()
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Score the external critic on labelled cases")
    parser.add_argument("--provider", default="glm", choices=("glm", "gemini"))
    parser.add_argument("--pause", type=float, default=1.5,
                        help="seconds between calls; free tiers rate-limit bursts")
    parser.add_argument("--out", type=Path, default=here / "results/critic_eval.json")
    args = parser.parse_args(argv)

    critic = critic_from_env(args.provider)
    if critic is None:
        raise SystemExit(
            f"no critic available for provider {args.provider!r}. "
            "Expected ZAI_API_KEY (glm) or GEMINI_API_KEY / GOOGLE_API_KEY (gemini) "
            "in the environment or the repository .env."
        )
    print(f"critic: {getattr(critic, 'name', type(critic).__name__)} over {len(CRITIC_CASES)} cases",
          flush=True)

    result = compare_critics([critic], pause_seconds=args.pause)
    print()
    print(format_comparison_table(result))

    print("\nper-case:")
    for name, cases in result["detail"].items():
        for case in cases:
            mark = "ok " if case["correct"] else "MISS"
            print(f"  {mark} [{case['critic_decision']:<7}] {case['label']}"
                  + (f"  error={case['error']}" if case.get("error") else ""))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
