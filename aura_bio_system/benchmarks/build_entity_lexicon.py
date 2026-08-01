"""Build the offline entity lexicon used by the ontology checkers.

Runs once against the sparse index and writes a compressed list of normalised
entity names drawn from the corpus's own naming authorities — Gene Ontology,
MeSH, Reactome and the encyclopaedia titles. Nothing at query time touches the
network or a model; the check is a set membership test.

    python aura_bio_system/benchmarks/build_entity_lexicon.py
"""

from __future__ import annotations

import argparse
import gzip
import time
from pathlib import Path

from aura_bio.env import load_env
from aura_bio.verification.ontology import (
    AUTHORITY_SOURCES,
    build_lexicon,
    default_lexicon_path,
    load_lexicon,
)


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Build the entity lexicon")
    parser.add_argument("--index", type=Path,
                        default=Path(r"G:\aura_data\AURA-Bio-Index\core-sparse.sqlite3"))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--sources", default=",".join(AUTHORITY_SOURCES))
    args = parser.parse_args(argv)

    out = args.out or default_lexicon_path()
    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    print(f"building from {args.index}\n  sources: {', '.join(sources)}", flush=True)

    started = time.perf_counter()
    path = build_lexicon(args.index, out, sources)
    elapsed = time.perf_counter() - started

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        count = sum(1 for _ in handle)
    print(f"wrote {count:,} entity names to {path} "
          f"({path.stat().st_size/1024:.0f} KB, {elapsed:.0f}s)", flush=True)

    # Spot-check the two things this exists to separate.
    lexicon = load_lexicon(path)
    real = ["Golgi apparatus", "mitochondrion", "photosynthesis", "Homo sapiens",
            "DNA replication", "acetylcholinesterase", "Escherichia coli"]
    fake = ["Golgi mitochondrial bridge organelle", "Hensen-Baxter law",
            "cortexamine", "Homo aquaticus marinus", "Krebs-Watson glucose bypass cycle"]
    print("\n  known real entities:")
    for name in real:
        print(f"    {'FOUND  ' if lexicon.known(name) else 'missing'} {name}")
    print("  fabricated entities (should all be missing):")
    for name in fake:
        print(f"    {'FOUND  ' if lexicon.known(name) else 'missing'} {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
