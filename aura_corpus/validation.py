from __future__ import annotations

import bz2
import gzip
import hashlib
import json
import tarfile
import zipfile
from pathlib import Path


def digest(path: Path, algorithm: str = "sha256") -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _consume(handle) -> None:
    for _ in iter(lambda: handle.read(1024 * 1024), b""):
        pass


def validate(path: Path) -> tuple[bool, str]:
    if not path.is_file() or path.stat().st_size == 0:
        return False, "missing or empty file"
    name = path.name.lower()
    try:
        if name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(path, "r:gz") as archive:
                members = archive.getmembers()
                if not members:
                    return False, "empty tar archive"
                for member in members:
                    parts = Path(member.name).parts
                    if member.name.startswith(("/", "\\")) or ".." in parts:
                        return False, f"unsafe tar member: {member.name}"
                    extracted = archive.extractfile(member) if member.isfile() else None
                    if extracted:
                        _consume(extracted)
        elif name.endswith(".gz"):
            with gzip.open(path, "rb") as handle:
                _consume(handle)
        elif name.endswith(".bz2"):
            with bz2.open(path, "rb") as handle:
                _consume(handle)
        elif name.endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                bad = archive.testzip()
                if bad:
                    return False, f"corrupt zip member: {bad}"
        elif name.endswith((".xml", ".nxml")):
            with path.open("rb") as handle:
                prefix = handle.read(4096).lstrip()
            if b"<" not in prefix:
                return False, "XML opening tag not found"
        elif name.endswith(".json"):
            with path.open("r", encoding="utf-8") as handle:
                json.load(handle)
        elif name.endswith(".pdf"):
            with path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    return False, "PDF signature not found"
    except (OSError, EOFError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        return False, f"integrity check failed: {exc}"
    return True, "ok"
