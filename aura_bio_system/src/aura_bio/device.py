"""Device selection: prefer the GPU wherever the system runs.

Project policy is that model work runs on the device GPU. Three components can
use one:

* the local LLM — served by Ollama, which offloads to the GPU on its own;
* the BGE query encoder — PyTorch;
* the cross-encoder reranker — PyTorch.

The PyTorch pieces can only reach the GPU if a CUDA (or ROCm/MPS) build of
torch is installed; a ``+cpu`` wheel silently has no device. ``resolve_device``
picks the best available accelerator so the code is portable across machines,
and ``device_report`` explains what is actually in use rather than assuming.
"""

from __future__ import annotations

import os
from typing import Any


def resolve_device(explicit: str | None = None) -> str | None:
    """Return the torch device string to use, preferring an accelerator.

    ``AURA_DEVICE`` overrides everything. Returning ``None`` lets the caller's
    library apply its own default, which is the right behaviour when torch is
    absent entirely.
    """

    override = explicit or os.environ.get("AURA_DEVICE")
    if override:
        return override
    try:
        import torch
    except ImportError:
        return None
    if torch.cuda.is_available():
        return "cuda"
    # Apple silicon, when the project is run on a Mac.
    backends = getattr(torch, "backends", None)
    mps = getattr(backends, "mps", None) if backends else None
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def device_report() -> dict[str, Any]:
    """Describe what accelerator is available and why, for diagnostics."""

    report: dict[str, Any] = {
        "selected": resolve_device(),
        "torch_installed": False,
        "torch_version": None,
        "cuda_available": False,
        "gpu_name": None,
        "reason": None,
    }
    try:
        import torch
    except ImportError:
        report["reason"] = "torch is not installed; PyTorch components unavailable"
        return report
    report["torch_installed"] = True
    report["torch_version"] = torch.__version__
    report["cuda_available"] = bool(torch.cuda.is_available())
    if torch.cuda.is_available():
        report["gpu_name"] = torch.cuda.get_device_name(0)
        report["reason"] = "CUDA build detected; encoder and reranker run on GPU"
    elif "+cpu" in torch.__version__:
        report["reason"] = (
            "a CPU-only torch wheel is installed, so the encoder and reranker cannot "
            "use the GPU. Install a CUDA build to enable it, for example: "
            "pip install --force-reinstall torch --index-url "
            "https://download.pytorch.org/whl/cu121"
        )
    else:
        report["reason"] = "no CUDA device visible to torch"
    return report
