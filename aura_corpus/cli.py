from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .catalogs import discover_catalog
from .books import audit_book_candidate, load_candidates
from .curation import CascadeCurator, GLMJudge, OllamaJudge
from .discovery import discover
from .download import DownloadBudget, download_one
from .env import load_dotenv
from .extract import decompress_single_file, extract_text_members, extract_zip_text_members
from .models import RemoteFile
from .pubmed_filter import filter_pubmed_file
from .registry import DEFAULT_REGISTRY, load_registry, select_sources
from .store import ManifestStore
from .validation import digest, validate


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = PROJECT_ROOT / ".env"


def _byte_count(value: str) -> int:
    match = __import__("re").fullmatch(r"(?i)(\d+(?:\.\d+)?)\s*([kmgt]?i?b)?", value.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"Invalid byte size: {value}")
    number = float(match.group(1))
    unit = (match.group(2) or "b").lower()
    factors = {
        "b": 1,
        "kb": 1000,
        "kib": 1024,
        "mb": 1000**2,
        "mib": 1024**2,
        "gb": 1000**3,
        "gib": 1024**3,
        "tb": 1000**4,
        "tib": 1024**4,
    }
    return int(number * factors[unit])


def _paths(args) -> tuple[Path, Path, Path]:
    root = Path(args.root).resolve()
    metadata = root / "05_Metadata"
    return root, metadata / "corpus.sqlite3", metadata / "manifests" / "files.jsonl"


def _discover_selected(args) -> tuple[list, list[RemoteFile]]:
    _, sources = load_registry(Path(args.registry))
    selected = select_sources(sources, args.source)
    items: list[RemoteFile] = []
    for source in selected:
        windows = _pmc_windows(args) if source.discovery == "pmc_efetch" else []
        variants = []
        if windows:
            for start, end in windows:
                variants.append(
                    replace(
                        source,
                        extra={**source.extra, "date_start": start, "date_end": end},
                    )
                )
        else:
            variants = [source]
        source_total = 0
        for variant in variants:
            found = discover(variant, limit=args.max_files)
            if args.max_files is not None:
                found = found[: args.max_files]
            items.extend(found)
            source_total += len(found)
        print(f"{source.id}: discovered {source_total} file(s)", file=sys.stderr)
    return selected, items


def _pmc_windows(args) -> list[tuple[str, str]]:
    values = list(getattr(args, "pmc_window", []) or [])
    windows: list[tuple[date, date]] = []
    for value in values:
        try:
            start_text, end_text = value.split(":", 1)
            start = date.fromisoformat(start_text)
            end = date.fromisoformat(end_text)
        except ValueError as exc:
            raise ValueError(f"Invalid --pmc-window {value!r}; use YYYY-MM-DD:YYYY-MM-DD") from exc
        if end < start:
            raise ValueError(f"Invalid --pmc-window {value!r}; end precedes start")
        windows.append((start, end))
    for year in getattr(args, "pmc_year", []) or []:
        start = date(year, 1, 1)
        last = date(year, 12, 31)
        while start <= last:
            end = min(start + timedelta(days=6), last)
            windows.append((start, end))
            start = end + timedelta(days=1)
    return [(start.isoformat(), end.isoformat()) for start, end in windows]


def _snapshot_sources(sources, metadata_root: Path) -> None:
    metadata_root.mkdir(parents=True, exist_ok=True)
    path = metadata_root / "sources_snapshot.json"
    existing: dict[str, dict] = {}
    if path.exists():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
            existing = {item["id"]: item for item in prior.get("sources", [])}
        except (OSError, json.JSONDecodeError, KeyError):
            existing = {}
    existing.update({source.id: asdict(source) for source in sources})
    snapshot = {
        "created_at": datetime.now(UTC).isoformat(),
        "sources": [existing[key] for key in sorted(existing)],
    }
    path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def command_sources(args) -> int:
    _, sources = load_registry(Path(args.registry))
    for source in sources:
        state = "enabled" if source.enabled else "disabled"
        print(f"{source.id:24} {source.risk:5} {state:8} {source.category}  {source.name}")
    return 0


def command_catalog(args) -> int:
    root, database, _ = _paths(args)
    _, sources = load_registry(Path(args.registry))
    catalogs = [source for source in sources if source.enabled and source.discovery == "catalog_review"]
    if args.source:
        requested = set(args.source)
        by_id = {source.id: source for source in catalogs}
        missing = sorted(requested - by_id.keys())
        if missing:
            raise ValueError(f"Unknown or non-catalog source(s): {', '.join(missing)}")
        catalogs = [by_id[source_id] for source_id in args.source]
    output_dir = root / "05_Metadata" / "catalog_candidates"
    output_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for source in catalogs:
        candidates = discover_catalog(
            source,
            max_candidates=args.max_candidates,
            max_pages=args.max_pages,
        )
        destination = output_dir / f"{source.id}.jsonl"
        temporary = destination.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for candidate in candidates:
                handle.write(json.dumps(candidate.as_record(source), ensure_ascii=False) + "\n")
        temporary.replace(destination)
        total += len(candidates)
        print(f"{source.id}: {len(candidates)} candidate(s) -> {destination}")
    _snapshot_sources(sources, database.parent)
    print(f"Catalog review queue complete: {total} candidate(s); no books were downloaded.")
    return 0


def command_audit_books(args) -> int:
    root, _, _ = _paths(args)
    candidate_root = root / "05_Metadata" / "catalog_candidates"
    output = root / "05_Metadata" / "book_audit.jsonl"
    source_ids = args.source or [
        "biolibretexts_catalog",
        "ebooksdirectory_biology_catalog",
        "freebookcentre_biology_catalog",
    ]
    if args.overwrite:
        output.unlink(missing_ok=True)
    latest: dict[str, dict] = {}
    if output.exists():
        for record in load_candidates(output):
            latest[str(record.get("candidate_id"))] = record
    with output.open("a", encoding="utf-8") as audit_handle:
        for source_id in source_ids:
            path = candidate_root / f"{source_id}.jsonl"
            if not path.exists():
                raise ValueError(f"Candidate catalog not found: {path}; run catalog first")
            candidates = load_candidates(path, limit=args.max_candidates)
            for index, candidate in enumerate(candidates, start=1):
                candidate_id = str(candidate.get("candidate_id"))
                prior = latest.get(candidate_id)
                if prior and prior.get("license_state") != "audit_error":
                    print(
                        f"{source_id} {index}/{len(candidates)}: cached - "
                        f"{candidate.get('title', '')}",
                        flush=True,
                    )
                    continue
                if source_id == "biolibretexts_catalog" and latest and args.delay > 0:
                    __import__("time").sleep(args.delay)
                try:
                    result = audit_book_candidate(candidate, delay_seconds=args.delay)
                except Exception as exc:
                    result = {
                        **candidate,
                        "use_scope": "research_noncommercial",
                        "audit_decision": "rejected",
                        "audit_reason": f"audit request failed: {exc}",
                        "license_state": "audit_error",
                    }
                latest[candidate_id] = result
                audit_handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                audit_handle.flush()
                print(
                    f"{source_id} {index}/{len(candidates)}: "
                    f"{result['audit_decision']} - {candidate.get('title', '')}",
                    flush=True,
                )
    counts = Counter(record["audit_decision"] for record in latest.values())
    print(f"Book audit: {dict(counts)} -> {output}")
    return 0


def command_fetch_books(args) -> int:
    if not args.yes:
        raise SystemExit("Refusing to download books without --yes")
    root, database, export = _paths(args)
    audit_path = root / "05_Metadata" / "book_audit.jsonl"
    if not audit_path.exists():
        raise ValueError(f"Book audit not found: {audit_path}; run audit-books first")
    approved = [
        record for record in load_candidates(audit_path, limit=args.max_files)
        if record.get("audit_decision") == "approved" and record.get("download_url")
    ]
    items = []
    for record in approved:
        candidate_id = str(record["candidate_id"])
        items.append(
            RemoteFile(
                source_id=str(record["source_id"]),
                category="02_Textbooks",
                url=str(record["download_url"]),
                filename=f"{candidate_id}.pdf",
                metadata={
                    "title": record.get("title"),
                    "page_url": record.get("url"),
                    "license_ids": record.get("license_ids", []),
                    "license_evidence_url": record.get("license_evidence_url"),
                    "license_state": "allowed_noncommercial",
                    "use_scope": "research_noncommercial",
                },
            )
        )
    store = ManifestStore(database)
    quarantine = root / "90_Quarantine"
    for item in items:
        store.plan(item, item.destination(root))
    existing_bytes = sum(
        path.stat().st_size for path in root.rglob("*")
        if path.is_file() and "05_Metadata" not in path.parts
    )
    source_ids = {item.source_id for item in items}
    existing_source_bytes = sum(
        path.stat().st_size for path in root.rglob("*")
        if path.is_file() and any(source_id in path.parts for source_id in source_ids)
    )
    budget = DownloadBudget(
        args.max_total_bytes,
        used=existing_bytes,
        source_limit=args.max_source_bytes,
        source_used=existing_source_bytes,
    )
    results = Counter()
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    download_one, item, item.destination(root), store, quarantine,
                    args.max_file_bytes, args.retries, budget,
                ): item
                for item in items
            }
            for future in as_completed(futures):
                item = futures[future]
                status, detail = future.result()
                results[status] += 1
                print(f"{status:11} {item.filename}: {detail}")
        store.export_jsonl(export)
    finally:
        store.close()
    print("Book summary: " + ", ".join(f"{k}={v}" for k, v in sorted(results.items())))
    return 1 if results["partial"] or results["quarantined"] else 0


def command_plan(args) -> int:
    root, database, export = _paths(args)
    selected, items = _discover_selected(args)
    _, registry_sources = load_registry(Path(args.registry))
    store = ManifestStore(database)
    try:
        for item in items:
            store.plan(item, item.destination(root))
        store.export_jsonl(export)
        _snapshot_sources(registry_sources, database.parent)
    finally:
        store.close()
    print(f"Planned {len(items)} file(s). Manifest: {export}")
    return 0


def command_fetch(args) -> int:
    if not args.yes:
        raise SystemExit("Refusing to download without --yes")
    root, database, export = _paths(args)
    if "wikipedia_biology" in args.source and args.max_files is None:
        raise SystemExit(
            "Wikipedia collection must be incremental. Add --max-files 1000 "
            "for the first 50,000-page stage, then increase it on later runs."
        )
    if (
        "pmc_oa_comm_xml" in args.source
        and not args.pmc_window
        and not args.pmc_year
    ):
        requested = max(1, min(args.max_files or 100, 10_000))
        expected_batches = (requested + 99) // 100
        pmc_root = root / "01_Literature" / "raw" / "pmc_oa_comm_xml"
        base_complete = all(
            (pmc_root / f"pmc-commercial-{number:05d}.xml").exists()
            for number in range(1, expected_batches + 1)
        )
        if base_complete:
            raise SystemExit(
                "The unwindowed PMC batches are already complete. Use --pmc-window "
                "YYYY-MM-DD:YYYY-MM-DD or --pmc-year YEAR to collect non-overlapping articles."
            )
    selected, items = _discover_selected(args)
    _, registry_sources = load_registry(Path(args.registry))
    bulk = [source.id for source in selected if source.risk == "bulk"]
    if bulk and not args.allow_bulk:
        raise SystemExit(
            "Bulk source selected; add --allow-bulk after reviewing the plan: " + ", ".join(bulk)
        )
    store = ManifestStore(database)
    quarantine = root / "90_Quarantine"
    for item in items:
        store.plan(item, item.destination(root))
    results: Counter[str] = Counter()
    existing_bytes = sum(
        path.stat().st_size
        for path in root.rglob("*")
        if path.is_file() and "05_Metadata" not in path.parts
    )
    selected_ids = {source.id for source in selected}
    existing_source_bytes = sum(
        path.stat().st_size
        for path in root.rglob("*")
        if path.is_file()
        and "05_Metadata" not in path.parts
        and any(source_id in path.parts for source_id in selected_ids)
    )
    budget = DownloadBudget(
        args.max_total_bytes,
        used=existing_bytes,
        source_limit=args.max_source_bytes,
        source_used=existing_source_bytes,
    )
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    download_one,
                    item,
                    item.destination(root),
                    store,
                    quarantine,
                    args.max_file_bytes,
                    args.retries,
                    budget,
                ): item
                for item in items
            }
            for future in as_completed(futures):
                item = futures[future]
                status, detail = future.result()
                results[status] += 1
                print(f"{status:11} {item.source_id}/{item.filename}: {detail}")
        store.export_jsonl(export)
        _snapshot_sources(registry_sources, database.parent)
    finally:
        store.close()
    print("Summary: " + ", ".join(f"{key}={value}" for key, value in sorted(results.items())))
    return 1 if results["quarantined"] or results["partial"] else 0


def command_verify(args) -> int:
    root, database, export = _paths(args)
    store = ManifestStore(database)
    failed = 0
    try:
        for row in store.rows():
            path = Path(row["local_path"])
            if not path.exists():
                if row["status"] == "complete":
                    store.update(row["source_id"], row["filename"], "missing", error="file missing")
                    failed += 1
                continue
            valid, reason = validate(path)
            if not valid:
                store.update(row["source_id"], row["filename"], "invalid", error=reason)
                failed += 1
                print(f"invalid {path}: {reason}")
                continue
            sha256 = digest(path)
            store.update(
                row["source_id"], row["filename"], "complete",
                actual_bytes=path.stat().st_size, sha256=sha256, error=None,
            )
            print(f"ok      {path}")
        store.export_jsonl(export)
    finally:
        store.close()
    return 1 if failed else 0


def command_status(args) -> int:
    _, database, _ = _paths(args)
    store = ManifestStore(database)
    try:
        rows = store.rows()
    finally:
        store.close()
    counts = Counter(row["status"] for row in rows)
    bytes_complete = sum(row["actual_bytes"] or 0 for row in rows if row["status"] == "complete")
    print(f"files={len(rows)} complete_bytes={bytes_complete}")
    for status, count in sorted(counts.items()):
        print(f"{status:12} {count}")
    return 0


def command_extract(args) -> int:
    root, database, _ = _paths(args)
    store = ManifestStore(database)
    extracted = skipped = 0
    try:
        rows = store.rows("complete")
    finally:
        store.close()
    if args.source:
        requested = set(args.source)
        rows = [row for row in rows if row["source_id"] in requested]
    if args.max_files is not None:
        rows = rows[: args.max_files]
    update_store = ManifestStore(database) if args.delete_raw else None

    def remove_raw(row, path: Path, output: Path) -> None:
        if not args.delete_raw or not path.exists():
            return
        path.unlink()
        if update_store is not None:
            update_store.update(
                row["source_id"],
                row["filename"],
                "normalized",
                error=f"normalized to {output}",
            )

    for row in rows:
        path = Path(row["local_path"])
        lower = path.name.lower()
        if row["source_id"] == "pubmed_baseline":
            continue
        output_root = root / row["category"] / "normalized" / row["source_id"]
        if lower.endswith((".tar.gz", ".tgz")):
            output = output_root / path.stem.replace(".tar", "")
            marker = output / ".aura-extract-complete"
            if marker.exists():
                remove_raw(row, path, output)
                print(f"{path.name}: already normalized", flush=True)
                skipped += 1
                continue
            done, ignored = extract_text_members(path, output)
            marker.write_text("complete\n", encoding="ascii")
            remove_raw(row, path, output)
        elif lower.endswith(".zip"):
            output = output_root / path.stem
            marker = output / ".aura-extract-complete"
            if marker.exists():
                remove_raw(row, path, output)
                print(f"{path.name}: already normalized", flush=True)
                skipped += 1
                continue
            done, ignored = extract_zip_text_members(path, output)
            marker.write_text("complete\n", encoding="ascii")
            remove_raw(row, path, output)
        elif lower.endswith((".gz", ".bz2")):
            suffix = ".bz2" if lower.endswith(".bz2") else ".gz"
            output = output_root / path.name[: -len(suffix)]
            if output.exists():
                remove_raw(row, path, output)
                print(f"{path.name}: already normalized")
                skipped += 1
                continue
            decompress_single_file(path, output)
            done, ignored = 1, 0
            remove_raw(row, path, output)
        else:
            continue
        extracted += done
        skipped += ignored
        print(f"{path.name}: extracted={done} skipped={ignored}", flush=True)
    print(f"Total: extracted={extracted} skipped={skipped}")
    if update_store is not None:
        update_store.close()
    return 0


def command_filter_pubmed(args) -> int:
    root, database, _ = _paths(args)
    source_dir = root / "01_Literature" / "raw" / "pubmed_baseline"
    output_dir = root / "01_Literature" / "normalized" / "pubmed_filtered"
    manifest_path = root / "05_Metadata" / "manifests" / "pubmed_filter.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    inputs = sorted(source_dir.glob("*.xml.gz"))
    if args.max_files is not None:
        inputs = inputs[: args.max_files]
    if not inputs:
        raise ValueError(f"No complete PubMed XML files found under {source_dir}")
    totals = Counter()
    store = ManifestStore(database)
    with manifest_path.open("a", encoding="utf-8") as manifest:
        for index, source in enumerate(inputs, start=1):
            destination = output_dir / source.name.replace(".xml.gz", ".jsonl.gz")
            if destination.exists() and not args.overwrite:
                valid, reason = validate(destination)
                if not valid:
                    store.close()
                    raise ValueError(f"Existing filtered shard is invalid: {destination}: {reason}")
                if args.delete_raw:
                    source.unlink()
                    store.update(
                        "pubmed_baseline",
                        source.name,
                        "filtered",
                        error=f"normalized to {destination}",
                    )
                    print(f"removed  {index}/{len(inputs)} {source.name} (verified shard exists)")
                else:
                    print(f"skipped  {index}/{len(inputs)} {destination.name}")
                continue
            stats = filter_pubmed_file(
                source,
                destination,
                min_abstract_chars=args.min_abstract_chars,
            )
            totals.update(stats)
            record = {
                "source": str(source),
                "destination": str(destination),
                "created_at": datetime.now(UTC).isoformat(),
                **stats,
            }
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
            manifest.flush()
            if args.delete_raw:
                source.unlink()
                store.update(
                    "pubmed_baseline",
                    source.name,
                    "filtered",
                    error=f"normalized to {destination}",
                )
            ratio = stats["output_bytes"] / max(1, stats["input_bytes"])
            print(
                f"complete {index}/{len(inputs)} {destination.name}: "
                f"accepted={stats['accepted']}/{stats['input']} ratio={ratio:.1%}"
            )
    print(
        f"PubMed filter total: accepted={totals['accepted']}/{totals['input']} "
        f"input_bytes={totals['input_bytes']} output_bytes={totals['output_bytes']}"
    )
    store.close()
    return 0


def command_curate(args) -> int:
    curator = CascadeCurator(
        local=OllamaJudge(model=args.local_model, endpoint=args.ollama_endpoint),
        external=(
            GLMJudge(model=args.glm_model, endpoint=args.glm_endpoint)
            if args.use_glm
            else None
        ),
        local_accept_threshold=args.threshold,
    )
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open(encoding="utf-8") as source, output_path.open("w", encoding="utf-8") as target:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            try:
                result = curator.classify(record)
            except Exception as exc:
                result = {
                    "decision": "quarantine",
                    "confidence": 1.0,
                    "reason": f"curator error: {exc}",
                    "judge": "pipeline",
                }
            target.write(json.dumps({**record, "curation": result}, ensure_ascii=False) + "\n")
            print(f"{line_number}: {result['decision']} ({result.get('judge')})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aura-corpus")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--root", default=os.environ.get("AURA_CORPUS_ROOT", "AURA-Bio-Corpus"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sources").set_defaults(handler=command_sources)

    catalog = subparsers.add_parser(
        "catalog", help="build licence-review queues from directory sites; downloads no books"
    )
    catalog.add_argument("--source", action="append", default=[], help="repeatable catalog ID")
    catalog.add_argument("--max-candidates", type=int)
    catalog.add_argument("--max-pages", type=int)
    catalog.set_defaults(handler=command_catalog)

    audit_books = subparsers.add_parser("audit-books")
    audit_books.add_argument("--source", action="append", default=[])
    audit_books.add_argument("--max-candidates", type=int)
    audit_books.add_argument("--delay", type=float, default=5.0)
    audit_books.add_argument("--overwrite", action="store_true")
    audit_books.set_defaults(handler=command_audit_books)

    fetch_books = subparsers.add_parser("fetch-books")
    fetch_books.add_argument("--yes", action="store_true")
    fetch_books.add_argument("--max-files", type=int)
    fetch_books.add_argument("--workers", type=int, default=2)
    fetch_books.add_argument("--retries", type=int, default=3)
    fetch_books.add_argument("--max-file-bytes", type=_byte_count, default=_byte_count("500MB"))
    fetch_books.add_argument("--max-source-bytes", type=_byte_count, default=_byte_count("5GB"))
    fetch_books.add_argument(
        "--max-total-bytes", type=_byte_count,
        default=_byte_count(os.environ.get("AURA_MAX_TOTAL_BYTES", "50GB")),
    )
    fetch_books.set_defaults(handler=command_fetch_books)

    for name, handler in (("plan", command_plan), ("fetch", command_fetch)):
        child = subparsers.add_parser(name)
        child.add_argument("--source", action="append", default=[], help="repeatable source ID")
        child.add_argument("--max-files", type=int)
        child.add_argument(
            "--pmc-window",
            action="append",
            default=[],
            help="repeatable PMC release-date window YYYY-MM-DD:YYYY-MM-DD",
        )
        child.add_argument(
            "--pmc-year",
            action="append",
            type=int,
            default=[],
            help="repeatable PMC year, automatically split into non-overlapping 7-day windows",
        )
        child.set_defaults(handler=handler)
        if name == "fetch":
            child.add_argument("--yes", action="store_true")
            child.add_argument("--allow-bulk", action="store_true")
            child.add_argument("--workers", type=int, default=3)
            child.add_argument("--retries", type=int, default=3)
            child.add_argument("--max-file-bytes", type=_byte_count)
            child.add_argument(
                "--max-source-bytes",
                type=_byte_count,
                help="cap stored bytes for the selected source(s), including existing files",
            )
            child.add_argument(
                "--max-total-bytes",
                type=_byte_count,
                default=_byte_count(os.environ.get("AURA_MAX_TOTAL_BYTES", "50GB")),
                help="hard corpus cap including existing raw/quarantine files (default: 50GB)",
            )

    subparsers.add_parser("verify").set_defaults(handler=command_verify)
    subparsers.add_parser("status").set_defaults(handler=command_status)
    extract = subparsers.add_parser("extract")
    extract.add_argument("--source", action="append", default=[], help="repeatable source ID")
    extract.add_argument("--max-files", type=int)
    extract.add_argument(
        "--delete-raw",
        action="store_true",
        help="remove each archive only after its normalized output completes",
    )
    extract.set_defaults(handler=command_extract)

    pubmed_filter = subparsers.add_parser(
        "filter-pubmed", help="stream PubMed XML into compact English abstract JSONL.gz shards"
    )
    pubmed_filter.add_argument("--max-files", type=int)
    pubmed_filter.add_argument("--min-abstract-chars", type=int, default=300)
    pubmed_filter.add_argument("--overwrite", action="store_true")
    pubmed_filter.add_argument(
        "--delete-raw",
        action="store_true",
        help="delete each raw XML.gz only after its filtered shard passes gzip verification",
    )
    pubmed_filter.set_defaults(handler=command_filter_pubmed)

    curate = subparsers.add_parser("curate")
    curate.add_argument("--input", required=True)
    curate.add_argument("--output", required=True)
    curate.add_argument("--local-model", default=os.environ.get("OLLAMA_MODEL", "qwen3.5:4b"))
    curate.add_argument(
        "--ollama-endpoint",
        default=os.environ.get("OLLAMA_ENDPOINT", "http://127.0.0.1:11434/api/chat"),
    )
    curate.add_argument("--use-glm", action="store_true")
    curate.add_argument("--glm-model", default=os.environ.get("ZAI_MODEL", "glm-4.5-flash"))
    curate.add_argument(
        "--glm-endpoint",
        default=os.environ.get(
            "ZAI_ENDPOINT", "https://api.z.ai/api/paas/v4/chat/completions"
        ),
    )
    curate.add_argument("--threshold", type=float, default=0.85)
    curate.set_defaults(handler=command_curate)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    env_path = Path(os.environ.get("AURA_ENV_FILE", str(DEFAULT_ENV)))
    load_dotenv(env_path)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
        return 2
