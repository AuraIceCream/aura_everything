"""Load the repository ``.env`` into the process environment.

Every credential in this project is read through :func:`os.environ` —
``critic_from_env`` looks for ``ZAI_API_KEY``, the device helper honours
``AURA_DEVICE``, the scorer honours ``AURA_SCORER_STRICT``. Nothing ever put
the repository's ``.env`` file *into* ``os.environ``, so a key that was present
on disk and known to work was invisible to the code that needed it. The effect
was silent rather than noisy: ``critic_from_env`` returns ``None`` when no key
is set, so the entire SRS 17 external-critique subsystem sat disabled through
every benchmark run without ever raising.

Import side effects are deliberately avoided; callers invoke :func:`load_env`
explicitly at process entry so the behaviour is greppable.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Walk up at most this far looking for a .env. The package lives at
#: ``<repo>/aura_bio_system/src/aura_bio/env.py``, so the repository root is
#: four parents up; a couple of extra levels costs nothing and survives layout
#: changes.
_MAX_DEPTH = 6


def find_env_file(start: Path | None = None) -> Path | None:
    """Return the nearest ``.env`` at or above ``start``, if there is one."""

    here = (start or Path(__file__).resolve()).resolve()
    for parent in [here, *here.parents][:_MAX_DEPTH + 1]:
        candidate = parent / ".env" if parent.is_dir() else parent.parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_env(path: Path | None = None, override: bool = False) -> dict[str, str]:
    """Load ``.env`` into ``os.environ`` and report which names were set.

    Values already present in the environment win unless ``override`` is set:
    an explicit ``ZAI_API_KEY=... python run.py`` should beat the file. Returns
    the names loaded (never the values) so callers can log what happened
    without printing a secret.
    """

    env_path = path or find_env_file()
    if env_path is None or not env_path.is_file():
        return {}

    try:
        from dotenv import dotenv_values
    except ImportError:  # python-dotenv absent: parse the simple cases ourselves
        values = _parse(env_path)
    else:
        values = {k: v for k, v in dotenv_values(env_path).items() if v is not None}

    loaded: dict[str, str] = {}
    for name, value in values.items():
        if override or name not in os.environ:
            os.environ[name] = value
            loaded[name] = "set"
    return loaded


#: Variables that decide *where large files land*, as opposed to what the
#: process is allowed to do. They are not secrets.
CACHE_VARIABLES = ("HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE", "TORCH_HOME")


def ensure_cache_location() -> dict[str, str]:
    """Apply only the cache-path variables from ``.env``, if they are unset.

    The no-import-side-effects rule above is about credentials: loading them
    implicitly would make it hard to audit what reads a key and when. Cache
    paths are a different kind of setting and a different kind of failure.

    ``.env`` sets ``HF_HOME=D:\\hf-cache`` because the system drive cannot hold
    these models. A script that forgets :func:`load_env` does not merely miss
    the setting — HuggingFace silently falls back to ``C:\\Users\\...\\.cache``
    and re-downloads gigabytes onto the drive that has no room for them. That
    is not a disabled feature; it fills the system drive, at which point
    Windows cannot grow its paging file and Ollama starts returning HTTP 500
    for every request, joblib dies with OS error 1455, and the cause looks like
    anything except a full disk. It has cost this project hours twice.

    So this one narrow group is applied at import, before any HuggingFace
    module can read it, while :func:`load_env` stays explicit for everything
    else. Existing values always win, so an explicit override still works.
    """

    env_path = find_env_file()
    if env_path is None:
        return {}
    try:
        from dotenv import dotenv_values

        values = {k: v for k, v in dotenv_values(env_path).items() if v is not None}
    except ImportError:
        values = _parse(env_path)

    applied: dict[str, str] = {}
    for name in CACHE_VARIABLES:
        value = values.get(name)
        if value and name not in os.environ:
            os.environ[name] = value
            applied[name] = value
    return applied


def _parse(path: Path) -> dict[str, str]:
    """Minimal ``KEY=value`` fallback for when python-dotenv is unavailable."""

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        values[name.strip()] = value
    return values
