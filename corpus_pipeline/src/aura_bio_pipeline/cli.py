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

    sparse_parser = commands.add_parser(
        "build-sparse", help="build a source-scoped SQLite FTS/BM25 retrieval store"
    )
    sparse_parser.add_argument("--source", action="append", required=True)
    sparse_parser.add_argument("--index-path", type=Path, required=True)
    sparse_parser.add_argument("--max-chunks", type=int, help="benchmark-only chunk cap")
    sparse_parser.add_argument(
        "--compact",
        action="store_true",
        help="detail=none: identical BM25 ranking, ~23%% less disk, slower queries",
    )

    jobs_parser = commands.add_parser(
        "build-dense-jobs",
        help="build a memory-mapped FAISS index straight from extracted Kaggle job shards",
    )
    jobs_parser.add_argument("--job-root", type=Path, required=True)
    jobs_parser.add_argument("--index-root", type=Path, required=True)
    jobs_parser.add_argument(
        "--index-type", choices=("ivf-pq", "ivf-sq8", "sq8", "flat"), default="ivf-pq"
    )
    jobs_parser.add_argument("--batch-vectors", type=int, default=32_768)
    jobs_parser.add_argument("--training-vectors", type=int, default=300_000)
    jobs_parser.add_argument("--nlist", type=int, help="IVF clusters; default scales with corpus size")
    jobs_parser.add_argument("--nprobe", type=int, default=32, help="IVF clusters searched per query")

    manifest_parser = commands.add_parser(
        "write-retrieval-manifest", help="record the dense/core-BM25/PubMed-BM25 artifacts"
    )
    manifest_parser.add_argument("--index-root", type=Path, required=True)
    manifest_parser.add_argument("--dense-index", type=Path)
    manifest_parser.add_argument("--dense-map", type=Path)
    manifest_parser.add_argument("--core-sparse", type=Path)
    manifest_parser.add_argument("--pubmed-sparse", type=Path)

    hybrid_parser = commands.add_parser(
        "hybrid-search", help="RRF dense/core-BM25 plus separately weighted PubMed BM25"
    )
    hybrid_parser.add_argument("query")
    hybrid_parser.add_argument("--index-root", type=Path, required=True)
    hybrid_parser.add_argument("--top-k", type=int, default=10)
    hybrid_parser.add_argument("--candidate-k", type=int, default=50)
    hybrid_parser.add_argument("--pubmed-weight", type=float, default=0.85)
    hybrid_parser.add_argument("--device")

    sparse_benchmark = commands.add_parser(
        "benchmark-sparse", help="measure cached BM25/FTS query latency"
    )
    sparse_benchmark.add_argument("query")
    sparse_benchmark.add_argument("--index-path", type=Path, required=True)
    sparse_benchmark.add_argument("--repeats", type=int, default=5)
    sparse_benchmark.add_argument("--mode", choices=("auto", "and", "or"), default="auto")

    finetune_parser = commands.add_parser(
        "make-finetune-pack", help="create a deterministic 8-10 GiB clean chunk pack for fine-tuning"
    )
    finetune_parser.add_argument("--output", type=Path, required=True)
    finetune_parser.add_argument("--pubmed-gib", type=float, default=5.8)
    finetune_parser.add_argument("--copy", action="store_true", help="copy instead of NTFS hard-link")
    finetune_parser.add_argument("--exclude-qa", action="store_true")

    training_parser = commands.add_parser(
        "build-training-corpus",
        help="select quality-filtered prose from chunks for continued pretraining",
    )
    training_parser.add_argument("--output", type=Path, required=True)
    training_parser.add_argument(
        "--target-gib", type=float, default=1.0, help="text bytes to select (default 1.0)"
    )
    training_parser.add_argument(
        "--source", action="append", help="repeatable; defaults to the prose sources"
    )
    training_parser.add_argument("--minimum-score", type=float, default=0.45)
    training_parser.add_argument(
        "--qa-fraction", type=float, default=0.0,
        help="share of the budget filled with question-answer records (e.g. 0.30)",
    )
    training_parser.add_argument(
        "--gold", type=Path, help="gold_answers.jsonl to include as the best QA source"
    )
    training_parser.add_argument(
        "--include-structured",
        action="store_true",
        help="also draw from UniProt/GO/MeSH/Reactome record dumps (not recommended)",
    )

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
    elif args.command == "build-sparse":
        from .retrieval import build_sparse_index

        result = build_sparse_index(
            config.chunk_root, args.index_path, set(args.source), args.max_chunks, args.compact
        )
    elif args.command == "build-dense-jobs":
        from .retrieval import build_dense_index_from_jobs

        result = build_dense_index_from_jobs(
            args.job_root,
            config.chunk_root,
            args.index_root,
            args.index_type,
            training_vectors=args.training_vectors,
            batch_vectors=args.batch_vectors,
            nlist=args.nlist,
            nprobe=args.nprobe,
        )
    elif args.command == "write-retrieval-manifest":
        from .retrieval import write_retrieval_manifest

        result = write_retrieval_manifest(
            args.index_root,
            dense_index=args.dense_index,
            dense_map=args.dense_map,
            core_sparse=args.core_sparse,
            pubmed_sparse=args.pubmed_sparse,
        )
    elif args.command == "hybrid-search":
        from .retrieval import hybrid_search

        result = hybrid_search(
            args.index_root,
            args.query,
            args.top_k,
            args.candidate_k,
            args.pubmed_weight,
            args.device,
        )
    elif args.command == "benchmark-sparse":
        from .retrieval import benchmark_sparse

        result = benchmark_sparse(args.index_path, args.query, args.repeats, args.mode)
    elif args.command == "make-finetune-pack":
        from .finetune import make_finetune_pack

        result = make_finetune_pack(
            config.chunk_root,
            args.output,
            args.pubmed_gib,
            args.copy,
            not args.exclude_qa,
        )
    elif args.command == "build-training-corpus":
        from .training_data import PROSE_SOURCES, build_training_corpus

        result = build_training_corpus(
            config.chunk_root,
            args.output,
            int(args.target_gib * 1024**3),
            tuple(args.source) if args.source else PROSE_SOURCES,
            args.minimum_score,
            args.include_structured,
            qa_fraction=args.qa_fraction,
            gold_path=args.gold,
        )
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
