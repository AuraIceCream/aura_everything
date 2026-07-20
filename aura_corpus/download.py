from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .models import RemoteFile
from .net import USER_AGENT, request_bytes
from .store import ManifestStore
from .validation import digest, validate


class DownloadLimitExceeded(RuntimeError):
    pass


class DownloadBudget:
    def __init__(
        self,
        limit: int | None,
        used: int = 0,
        source_limit: int | None = None,
        source_used: int = 0,
    ) -> None:
        self.limit = limit
        self.used = used
        self.source_limit = source_limit
        self.source_used = source_used
        self.lock = threading.Lock()

    def consume(self, amount: int) -> None:
        if self.limit is None and self.source_limit is None:
            return
        with self.lock:
            if self.limit is not None and self.used + amount > self.limit:
                raise DownloadLimitExceeded(
                    f"corpus download would exceed total cap of {self.limit} bytes"
                )
            if self.source_limit is not None and self.source_used + amount > self.source_limit:
                raise DownloadLimitExceeded(
                    f"selected source download would exceed cap of {self.source_limit} bytes"
                )
            self.used += amount
            self.source_used += amount


def _sidecar_checksum(item: RemoteFile) -> tuple[str | None, str | None]:
    if not item.checksum_url:
        return item.checksum_algorithm, item.expected_checksum
    response = request_bytes(item.checksum_url)
    text = response.body.decode("ascii", errors="replace")
    # Providers commonly publish either "<hash>  filename" or
    # "MD5(filename)= <hash>". Match the digest independently of layout.
    match = re.search(r"(?i)(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])", text)
    if match:
        return "md5", match.group(1).lower()
    raise ValueError(f"Invalid MD5 sidecar: {item.checksum_url}")


def download_one(
    item: RemoteFile,
    destination: Path,
    store: ManifestStore,
    quarantine_root: Path,
    max_bytes: int | None = None,
    retries: int = 3,
    budget: DownloadBudget | None = None,
) -> tuple[str, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    try:
        algorithm, expected = _sidecar_checksum(item)
    except Exception as exc:
        store.update(item.source_id, item.filename, "partial", error=f"checksum metadata: {exc}")
        return "partial", str(exc)
    if destination.exists():
        valid, reason = validate(destination)
        checksum_ok = not (expected and algorithm) or digest(destination, algorithm).lower() == expected.lower()
        if valid and checksum_ok:
            sha256 = digest(destination, "sha256")
            store.update(
                item.source_id,
                item.filename,
                "complete",
                actual_bytes=destination.stat().st_size,
                sha256=sha256,
                error=None,
            )
            return "skipped", str(destination)
        quarantine = quarantine_root / item.source_id / destination.name
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        if quarantine.exists():
            quarantine.unlink()
        shutil.move(str(destination), str(quarantine))

    store.update(item.source_id, item.filename, "downloading", error=None)
    if algorithm or expected:
        store.update(
            item.source_id,
            item.filename,
            "downloading",
            checksum_algorithm=algorithm,
            expected_checksum=expected,
        )

    last_error: Exception | None = None
    transfer_complete = False
    for attempt in range(retries + 1):
        try:
            _stream_download(item.url, part, max_bytes=max_bytes, budget=budget)
            os.replace(part, destination)
            transfer_complete = True
            if expected and algorithm:
                actual = digest(destination, algorithm)
                if actual.lower() != expected.lower():
                    raise ValueError(
                        f"{algorithm} mismatch: expected {expected}, received {actual}"
                    )
            valid, reason = validate(destination)
            if not valid:
                raise ValueError(reason)
            sha256 = digest(destination, "sha256")
            store.update(
                item.source_id,
                item.filename,
                "complete",
                actual_bytes=destination.stat().st_size,
                sha256=sha256,
                error=None,
            )
            return "complete", str(destination)
        except Exception as exc:  # failure is recorded and retried uniformly
            last_error = exc
            if attempt < retries:
                time.sleep(min(2**attempt, 8))
                continue
            break

    failed_path = destination if transfer_complete else None
    if failed_path and failed_path.exists():
        quarantine = quarantine_root / item.source_id / failed_path.name
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        if quarantine.exists():
            quarantine.unlink()
        shutil.move(str(failed_path), str(quarantine))
    status = "quarantined" if transfer_complete else "partial"
    store.update(item.source_id, item.filename, status, error=str(last_error))
    return status, str(last_error)


def _stream_download(
    url: str,
    part: Path,
    max_bytes: int | None,
    budget: DownloadBudget | None = None,
) -> None:
    existing = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and part.exists():
            return
        raise
    with response:
        append = existing > 0 and response.status == 206
        if existing and not append:
            existing = 0
        mode = "ab" if append else "wb"
        total = existing
        with part.open(mode) as handle:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if max_bytes is not None and total > max_bytes:
                    raise DownloadLimitExceeded(
                        f"download exceeded per-file cap of {max_bytes} bytes"
                    )
                if budget:
                    budget.consume(len(block))
                handle.write(block)
