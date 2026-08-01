"""`aura-bio-api` entry point: serve the FastAPI app with uvicorn."""

from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> int:
    from ..env import load_env

    # The app resolves its critic and device from the environment; the keys
    # live in the repository .env rather than the shell.
    load_env()
    parser = argparse.ArgumentParser(prog="aura-bio-api", description="Serve the AURA-Bio API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--index-root", help="override AURA_INDEX_ROOT")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)
    if args.index_root:
        os.environ["AURA_INDEX_ROOT"] = args.index_root

    import uvicorn

    uvicorn.run("aura_bio.api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
