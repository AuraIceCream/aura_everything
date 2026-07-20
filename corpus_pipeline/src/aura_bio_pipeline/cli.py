from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .config import load_config
from .dedup import compact_state
from .pipeline import chunk, create_inventory, ingest, pipeline_status, probe_sources


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "pipeline.toml"


def _sources(args: argparse.Namespace) -> set[str] | None:
    return set(args.source) if getattr(args, "source", None) else None


def _add_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", action="append", help="repeatable configured source ID")
    parser.add_argument("--max-files", type=int, help="bounded input-shard limit for a pilot")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aura-process",
        description="Prepare and index AURA-Bio without modifying its verified source corpus.",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="pipeline TOML configuration")
    commands = parser.add_subparsers(dest="command", required=True)

    inventory = commands.add_parser("inventory", help="write the selected source-file inventory")
    _add_selection(inventory)

    probe = commands.add_parser("probe", help="parse one real document from every source")
    probe.add_argument("--source", action="append", help="repeatable configured source ID")

    ingest_parser = commands.add_parser(
        "ingest", help="parse, clean, and exactly deduplicate canonical documents"
    )
    _add_selection(ingest_parser)
    ingest_parser.add_argument("--workers", type=int, default=4)

    chunk_parser = commands.add_parser("chunk", help="create source-aware BGE-safe chunk shards")
    _add_selection(chunk_parser)
    chunk_parser.add_argument("--tokenizer", help="override the configured Hugging Face tokenizer")
    chunk_parser.add_argument("--workers", type=int, default=4)
    chunk_parser.add_argument(
        "--delete-documents-after-success",
        action="store_true",
        help="reclaim canonical-shard space only after its chunk output is committed",
    )

    embed_parser = commands.add_parser("embed", help="create resumable float16 BGE embedding shards")
    _add_selection(embed_parser)
    embed_parser.add_argument("--model", help="override the configured SentenceTransformer model")
    embed_parser.add_argument("--batch-size", type=int)
    embed_parser.add_argument(
        "--max-chunks", type=int, help="pilot-only cap per selected chunk shard"
    )
    embed_parser.add_argument("--device", help="for example cpu, cuda, or cuda:0")

    index_parser = commands.add_parser("index", help="build FAISS dense and SQLite FTS5 indexes")
    index_parser.add_argument(
        "--index-type", choices=("sq8", "flat"), default="sq8", help="sq8 is the compact default"
    )

    search_parser = commands.add_parser("search", help="test hybrid dense+sparse retrieval")
    search_parser.add_argument("query")
    search_parser.add_argument("--top-k", type=int, default=10)
    search_parser.add_argument("--candidate-k", type=int, default=50)
    search_parser.add_argument("--device")

    status_parser = commands.add_parser("status", help="show generated artifact counts")
    status_parser.set_defaults(command="status")

    commands.add_parser(
        "compact-state",
        help="preserve resume markers while rebuilding the exact-deduplication cache",
    )

    reset_parser = commands.add_parser(
        "reset", help="delete only generated AURA-Bio-Processed artifacts"
    )
    reset_parser.add_argument("--yes", action="store_true", help="confirm deletion of generated outputs")

    run_parser = commands.add_parser("run", help="run inventory through indexing")
    _add_selection(run_parser)
    run_parser.add_argument("--device")
    run_parser.add_argument("--batch-size", type=int)
    run_parser.add_argument("--workers", type=int, default=4)
    run_parser.add_argument("--index-type", choices=("sq8", "flat"), default="sq8")
    run_parser.add_argument(
        "--yes",
        action="store_true",
        help="required for an unbounded full-corpus embedding run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    source_ids = _sources(args)

    if args.command == "inventory":
        result = create_inventory(config, source_ids, args.max_files)
    elif args.command == "probe":
        result = probe_sources(config, source_ids)
    elif args.command == "ingest":
        result = ingest(config, source_ids, args.max_files, args.workers)
    elif args.command == "chunk":
        result = chunk(
            config,
            source_ids,
            args.max_files,
            args.tokenizer,
            args.workers,
            args.delete_documents_after_success,
        )
    elif args.command == "embed":
        from .embedding import embed

        result = embed(
            config,
            source_ids,
            args.max_files,
            args.device,
            args.model,
            args.batch_size,
            args.max_chunks,
        )
    elif args.command == "index":
        from .embedding import build_indexes

        result = build_indexes(config, args.index_type)
    elif args.command == "search":
        from .embedding import hybrid_search

        result = hybrid_search(config, args.query, args.top_k, args.candidate_k, args.device)
    elif args.command == "status":
        result = pipeline_status(config)
    elif args.command == "compact-state":
        result = compact_state(config.output_root / "state" / "pipeline.sqlite3")
    elif args.command == "reset":
        if not args.yes:
            raise SystemExit("reset requires --yes")
        targets = {config.output_root.resolve(), config.chunk_root.resolve()}
        if config.corpus_root.resolve() in targets:
            raise SystemExit("Refusing to reset because a generated root equals corpus_root")
        for target in sorted(targets, key=lambda item: len(item.parts), reverse=True):
            if target.exists() and not any(target.is_relative_to(parent) for parent in targets if parent != target):
                shutil.rmtree(target)
        result = {
            "reset": [str(item) for item in sorted(targets)],
            "source_corpus_untouched": str(config.corpus_root),
        }
    elif args.command == "run":
        from .embedding import build_indexes, embed

        if args.max_files is None and not args.yes:
            raise SystemExit(
                "Refusing an unbounded embedding run without --yes. "
                "Start with --max-files 2 to measure throughput and disk use."
            )
        result = {
            "inventory": create_inventory(config, source_ids, args.max_files),
            "ingest": ingest(config, source_ids, args.max_files, args.workers),
            "chunk": chunk(config, source_ids, args.max_files, workers=args.workers),
            "embed": embed(
                config,
                source_ids,
                args.max_files,
                args.device,
                None,
                args.batch_size,
                None,
            ),
            "index": build_indexes(config, args.index_type),
        }
    else:  # pragma: no cover - argparse guarantees a command
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
