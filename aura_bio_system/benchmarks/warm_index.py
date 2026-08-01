"""Pull the retrieval indexes into the OS page cache before a benchmark run.

Every data partition on this machine (D:, E:, F:, G:) is a partition of one
SATA hard disk; only C: is the NVMe SSD. SQLite FTS queries against the 3.34 GB
sparse index are random reads, and random reads on that disk measured 7 MB/s —
which is why retrieval, not generation, was the largest stage in the first full
run at 209 s median per question.

A sequential pass over the same file runs at 108 MB/s, so faulting the whole
index in deliberately costs ~32 s once. Afterwards the file is served from
cache at ~4.2 GB/s and retrieval stops touching the disk at all. The pages sit
on the standby list, so this does not consume "free" memory in any way that
starves the model.

Worth re-running if a long gap or a memory-hungry process has evicted the cache.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

#: Only the files retrieval actually reads from. The dense index is skipped
#: unless asked for, since it is opt-in via AURA_DENSE and RAM is the binding
#: constraint here.
SPARSE_FILES = ("core-sparse.sqlite3",)
DENSE_FILES = ("core-dense.faiss", "core-dense-map.sqlite3")


def warm(path: Path, chunk: int = 8 << 20) -> tuple[float, float]:
    """Read a file end to end. Returns (gigabytes, seconds)."""

    total = 0
    started = time.perf_counter()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            total += len(block)
    elapsed = time.perf_counter() - started
    return total / (1 << 30), elapsed


def warm_index(index_root: Path, dense: bool = False, quiet: bool = False) -> None:
    names = SPARSE_FILES + (DENSE_FILES if dense else ())
    for name in names:
        path = index_root / name
        if not path.is_file():
            continue
        gib, seconds = warm(path)
        if not quiet:
            rate = gib * 1024 / seconds if seconds else 0
            print(f"warmed {name}: {gib:.2f} GiB in {seconds:.1f}s ({rate:.0f} MB/s)", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Warm the retrieval indexes into page cache")
    parser.add_argument("--index-root", type=Path, default=Path(r"G:\aura_data\AURA-Bio-Index"))
    parser.add_argument("--dense", action="store_true")
    args = parser.parse_args(argv)
    warm_index(args.index_root, dense=args.dense)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
