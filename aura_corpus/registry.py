from __future__ import annotations

import tomllib
from pathlib import Path

from .models import Source


DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "config" / "sources.toml"


def load_registry(path: Path = DEFAULT_REGISTRY) -> tuple[dict, list[Source]]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)

    global_config = data.get("global", {})
    sources: list[Source] = []
    known = set(Source.__dataclass_fields__)
    for raw in data.get("sources", []):
        values = {key: value for key, value in raw.items() if key in known and key != "extra"}
        extra = {key: value for key, value in raw.items() if key not in known}
        sources.append(Source(**values, extra=extra))
    return global_config, sources


def select_sources(sources: list[Source], requested: list[str]) -> list[Source]:
    enabled = [source for source in sources if source.enabled]
    if not requested:
        return enabled
    by_id = {source.id: source for source in enabled}
    missing = sorted(set(requested) - by_id.keys())
    if missing:
        raise ValueError(f"Unknown or disabled source(s): {', '.join(missing)}")
    return [by_id[source_id] for source_id in requested]

