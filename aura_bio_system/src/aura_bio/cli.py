"""Command-line entry point for the AURA-Bio runtime.

`route` and `verify` run without any model or built index, so the routing and
verification layers can be exercised on their own. `search` needs the built
indexes; `answer` additionally needs a local model, which is loaded lazily.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .routing import QueryRouter
from .verification import BiologyVerifier, EvidencePassage


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aura-bio", description="AURA-Bio runtime")
    commands = parser.add_subparsers(dest="command", required=True)

    route = commands.add_parser("route", help="show the routing decision for a query")
    route.add_argument("query")
    route.add_argument("--level")
    route.add_argument("--mode")
    route.add_argument("--context-level", type=int)
    route.add_argument("--summary", action="store_true", help="print the compact SRS 8.1 shape")

    verify = commands.add_parser("verify", help="verify an answer against evidence files")
    verify.add_argument("query")
    verify.add_argument("--answer", required=True, help="answer text, or @path to read a file")
    verify.add_argument("--evidence", type=Path, help="JSONL of {chunk_id,text,...} passages")

    numeric = commands.add_parser("check-numeric", help="run only the SymPy numerical verifier")
    numeric.add_argument("query")
    numeric.add_argument("--answer", required=True)

    search = commands.add_parser("search", help="hybrid search against the built indexes")
    search.add_argument("query")
    search.add_argument("--index-root", type=Path, required=True)
    search.add_argument("--top-k", type=int, default=10)
    search.add_argument("--rerank", action="store_true")
    search.add_argument("--device")

    commands.add_parser("device", help="report which accelerator the ML components will use")

    critics = commands.add_parser(
        "compare-critics", help="compare external critics (GLM vs Gemini) on labelled cases"
    )
    critics.add_argument(
        "--critic", action="append", choices=("glm", "gemini"),
        help="repeatable; defaults to whichever provider keys are set",
    )
    critics.add_argument("--markdown", action="store_true", help="print the comparison table")
    return parser


def _read_answer(value: str) -> str:
    if value.startswith("@"):
        return Path(value[1:]).read_text(encoding="utf-8")
    return value


def _load_evidence(path: Path | None) -> list[EvidencePassage]:
    if path is None:
        return []
    passages: list[EvidencePassage] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        passages.append(
            EvidencePassage(
                chunk_id=str(row.get("chunk_id", len(passages))),
                text=row.get("text", ""),
                title=row.get("title", ""),
                source_id=row.get("source_id", ""),
            )
        )
    return passages


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)

    if args.command == "route":
        route = QueryRouter().route(args.query, args.level, args.mode, args.context_level)
        _print(route.summary() if args.summary else route.as_dict())
    elif args.command == "verify":
        report = BiologyVerifier().verify(
            _read_answer(args.answer), _load_evidence(args.evidence), question=args.query
        )
        _print(report.as_dict())
    elif args.command == "check-numeric":
        from .verification import verify_numerical

        checks = verify_numerical(args.query, _read_answer(args.answer))
        _print([check.as_dict() for check in checks])
    elif args.command == "search":
        from aura_bio_pipeline.retrieval import HybridSearcher

        from .retrieval import CrossEncoderReranker

        searcher = HybridSearcher(args.index_root, device=args.device)
        try:
            results = searcher.search(args.query, top_k=max(args.top_k, 30) if args.rerank else args.top_k)
            if args.rerank and results:
                results, _ = CrossEncoderReranker(device=args.device).rerank(
                    args.query, results, args.top_k
                )
            _print([item.as_dict() for item in results])
        finally:
            searcher.close()
    elif args.command == "device":
        from .device import device_report

        _print(device_report())
    elif args.command == "compare-critics":
        import os

        from .critique import GeminiCritic, GLMCritic, compare_critics, format_comparison_table

        wanted = args.critic or _default_critics()
        critics = []
        for name in wanted:
            if name == "glm":
                if not os.environ.get("ZAI_API_KEY"):
                    print("skipping glm: ZAI_API_KEY not set", file=sys.stderr)
                    continue
                critics.append(GLMCritic())
            elif name == "gemini":
                if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
                    print("skipping gemini: GEMINI_API_KEY/GOOGLE_API_KEY not set", file=sys.stderr)
                    continue
                critics.append(GeminiCritic())
        if not critics:
            raise SystemExit("No critic available: set ZAI_API_KEY and/or GEMINI_API_KEY")
        result = compare_critics(critics)
        if args.markdown:
            print(format_comparison_table(result))
            return 0
        _print(result)
    else:  # pragma: no cover - argparse guarantees a command
        raise AssertionError(args.command)
    return 0


def _default_critics() -> list[str]:
    import os

    names = []
    if os.environ.get("ZAI_API_KEY"):
        names.append("glm")
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        names.append("gemini")
    return names or ["glm", "gemini"]


if __name__ == "__main__":
    raise SystemExit(main())
