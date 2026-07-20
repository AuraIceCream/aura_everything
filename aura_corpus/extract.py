from __future__ import annotations

import bz2
import gzip
import os
import shutil
import tarfile
import zipfile
from pathlib import Path


TEXT_SUFFIXES = {".xml", ".nxml", ".txt", ".md", ".json", ".csv", ".tsv"}


def extract_text_members(archive_path: Path, output_root: Path) -> tuple[int, int]:
    """Safely extract only text-like members from a tar archive."""
    extracted = 0
    skipped = 0
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            member_path = Path(member.name)
            if (
                not member.isfile()
                or member_path.suffix.lower() not in TEXT_SUFFIXES
                or member.name.startswith(("/", "\\"))
                or ".." in member_path.parts
            ):
                skipped += 1
                continue
            destination = output_root / member_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                skipped += 1
                continue
            with source, destination.open("wb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
            extracted += 1
    return extracted, skipped


def decompress_single_file(source: Path, destination: Path) -> None:
    """Atomically decompress a .gz or .bz2 single-file dataset."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    opener = gzip.open if source.suffix.lower() == ".gz" else bz2.open
    try:
        with opener(source, "rb") as input_handle, temporary.open("wb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle, 1024 * 1024)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def extract_zip_text_members(archive_path: Path, output_root: Path) -> tuple[int, int]:
    extracted = skipped = 0
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            member_path = Path(member.filename)
            if (
                member.is_dir()
                or member_path.suffix.lower() not in TEXT_SUFFIXES
                or member.filename.startswith(("/", "\\"))
                or ".." in member_path.parts
            ):
                skipped += 1
                continue
            destination = output_root / member_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
            extracted += 1
    return extracted, skipped
