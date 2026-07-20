from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


USER_AGENT = "AURA-Bio-Corpus/0.1 (provenance-first academic corpus builder)"


@dataclass(frozen=True)
class ResponseData:
    body: bytes
    headers: Any
    status: int


def request_bytes(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 60,
    retries: int = 3,
) -> ResponseData:
    request_headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    request_headers.update(headers or {})
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(
                url, data=body, headers=request_headers, method=method
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return ResponseData(response.read(), response.headers, response.status)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt == retries:
                break
            if isinstance(exc, urllib.error.HTTPError) and exc.code in {429, 503}:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = float(retry_after) if retry_after else min(5 * (2**attempt), 60)
                except ValueError:
                    delay = min(5 * (2**attempt), 60)
            else:
                delay = min(2**attempt, 8)
            time.sleep(delay)
    raise RuntimeError(f"Request failed after {retries + 1} attempts: {url}: {last_error}")


def request_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict:
    encoded = json.dumps(payload).encode("utf-8")
    response = request_bytes(
        url,
        method="POST",
        body=encoded,
        headers={"Content-Type": "application/json", **(headers or {})},
        timeout=180,
    )
    return json.loads(response.body)
