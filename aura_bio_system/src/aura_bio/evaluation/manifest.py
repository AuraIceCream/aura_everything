"""Prevent resumable benchmarks from combining different code or inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def ensure_run_manifest(
    settings_path: Path,
    results_path: Path,
    settings: dict[str, Any],
    source_paths: Iterable[Path],
    input_paths: Iterable[Path] = (),
) -> None:
    """Fingerprint Python source and explicit inputs; never rewrite a saved run.

    Does not fingerprint model weights, large indexes, or installed dependencies.
    Those must be held fixed separately. No environment or credentials are read.
    """
    hashes: dict[str, str] = {}
    for group, roots in (("source", source_paths), ("input", input_paths)):
        for index, root in enumerate(roots):
            if not root.exists():
                raise FileNotFoundError(root)
            files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
            for path in files:
                name = path.relative_to(root).as_posix() if root.is_dir() else root.name
                hashes[f"{group}/{index}/{name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"schema_version": 1, "settings": settings, "sha256": hashes}
    if settings_path.is_file():
        previous = json.loads(settings_path.read_text(encoding="utf-8"))
        if previous != manifest:
            raise SystemExit(
                "Run settings, code, inputs, or manifest format changed. "
                "Use a new --tag; existing results were not modified."
            )
    else:
        if results_path.exists() and results_path.stat().st_size:
            raise SystemExit(
                "Existing results have no provenance manifest. "
                "Use a new --tag; existing results were not modified."
            )
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        with settings_path.open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)
