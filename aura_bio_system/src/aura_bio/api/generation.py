"""Answer generators for the API, including a no-model fallback.

The project's local base model is not wired yet (SRS Phase 5 is pending), but
the whole pipeline — routing, retrieval, verification, tracing — is real and
worth serving now. ``ExtractiveGenerator`` composes an honest, citation-marked
answer directly from the retrieved passages so the system runs end-to-end
without a model, and clearly labels itself as extractive rather than pretending
to be a fluent tutor.

``OllamaGenerator`` is the drop-in for a real local model when one is available;
it is only imported/constructed on demand.
"""

from __future__ import annotations

import re
import textwrap
import time
from typing import Any, Sequence

from ..generation import build_prompt
from ..routing.schema import Route, TeachingMode


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if len(p.strip()) > 20]


class ExtractiveGenerator:
    """Compose a grounded answer from evidence without a language model.

    This is deliberately not trying to sound like a tutor. It states up front
    that it is assembling retrieved passages, then presents the most relevant
    sentence from each with its citation, shaped a little by teaching mode.
    """

    model_name = "extractive-no-model"

    def generate(
        self,
        route: Route,
        evidence: Sequence[Any],
        instructions: Sequence[str],
        coverage_pool: Sequence[Any] = (),
        unknown_entities: Sequence[str] = (),
    ) -> str:
        if not evidence:
            return (
                "No supporting evidence was retrieved for this question, so no "
                "grounded answer can be given. Try rephrasing, or enable a "
                "broader retrieval depth."
            )
        mode = TeachingMode(route.teaching_mode.label)
        lines: list[str] = []
        lead = _MODE_LEAD.get(mode, _MODE_LEAD[TeachingMode.GUIDED_EXPLANATION])
        lines.append(lead)
        lines.append("")
        for index, item in enumerate(evidence, 1):
            text = getattr(item, "text", "") or ""
            title = getattr(item, "title", "") or "source"
            best = _sentences(text)
            snippet = best[0] if best else text[:280]
            lines.append(f"- {snippet} [{index}]")
        lines.append("")
        lines.append(
            f"_Assembled extractively from {len(evidence)} retrieved passage(s); "
            "a local language model is not yet connected, so this is not a "
            "synthesised explanation._"
        )
        if mode == TeachingMode.SOCRATIC:
            lines.append("")
            lines.append(
                "To think it through yourself: what does the first passage imply "
                "must happen before the rest can follow?"
            )
        return "\n".join(lines)


_MODE_LEAD: dict[TeachingMode, str] = {
    TeachingMode.DIRECT_ANSWER: "In short, the retrieved evidence says:",
    TeachingMode.GUIDED_EXPLANATION: "Here is what the retrieved evidence establishes, point by point:",
    TeachingMode.EXAM: "Key points supported by the evidence:",
    TeachingMode.REVISION: "Revision points from the evidence:",
    TeachingMode.RESEARCH: "The retrieved literature reports:",
    TeachingMode.SOCRATIC: "Rather than the full answer, consider the supporting evidence:",
    TeachingMode.HOMEWORK_SUPPORT: "Working from the evidence, step by step:",
    TeachingMode.MISCONCEPTION_REPAIR: "The evidence clarifies the following:",
    TeachingMode.TEACH_BACK: "Check your understanding against the evidence:",
}


class OllamaGenerator:
    """Call a local Ollama model with the SRS 12 prompt.

    Constructed only when a model is actually configured, so importing the API
    never requires Ollama to be installed or running.

    Thinking is disabled: the default AURA model is Qwen 3.5, whose reasoning
    tokens would otherwise consume the whole generation budget and return an
    empty message (``done_reason: length``). The tutor answer is what we want,
    not the scratchpad.

    ``num_gpu`` forces full GPU offload; see the inline note where it is sent.

    ``num_ctx`` is set explicitly rather than left at the Modelfile default.
    That default is 2048, and a RAG prompt routinely exceeds it: 9-16 evidence
    passages at ~300-450 tokens each already approaches 2048 before the system
    prompt, teaching-mode structure, or revision instructions are counted.
    Ollama truncates silently when a request exceeds the context window, which
    measured as a real answer of "1" to a straightforward question — not an
    error, just a ruined prompt. 8192 was measured to still fit entirely on a
    4 GiB GTX 1650 (3.3 GiB used, 100% GPU) alongside the ~3.1 GiB model.
    """

    def __init__(
        self,
        model: str = "aura-bio:v0",
        host: str = "http://127.0.0.1:11434",
        num_predict: int = 1024,
        num_ctx: int = 8192,
        timeout: int = 300,
        think: bool = False,
        retries: int = 2,
        num_gpu: int = 99,
    ) -> None:
        self.model_name = model
        self.host = host.rstrip("/")
        self.num_predict = num_predict
        self.num_ctx = num_ctx
        self.timeout = timeout
        self.think = think
        self.retries = retries
        self.num_gpu = num_gpu
        #: Answers that only succeeded after dropping full-GPU offload. Their
        #: latency is not comparable to a run where every answer was fully
        #: offloaded, so a run that reports any of these should say so.
        self.degraded_calls = 0

    def available(self) -> bool:
        """True if the Ollama server has this model loaded and reachable."""

        import json
        import urllib.request

        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=3) as response:
                tags = json.loads(response.read().decode("utf-8"))
        except Exception:
            return False
        names = {model.get("name", "") for model in tags.get("models", [])}
        base = self.model_name.split(":")[0]
        return self.model_name in names or any(name.split(":")[0] == base for name in names)

    def generate(
        self,
        route: Route,
        evidence: Sequence[Any],
        instructions: Sequence[str],
        coverage_pool: Sequence[Any] = (),
        unknown_entities: Sequence[str] = (),
    ) -> str:
        import json
        import urllib.request

        prompt = build_prompt(route, evidence, instructions, coverage_pool, unknown_entities)

        def payload_for(num_gpu: int | None) -> bytes:
            options: dict[str, object] = {
                "temperature": 0.2,
                "num_predict": self.num_predict,
                "num_ctx": self.num_ctx,
            }
            if num_gpu is not None:
                # Ask for every layer on the GPU, as run_baseline.py already
                # did. Without it Ollama sizes the offload against whatever
                # VRAM happens to be free and quietly splits the model: on
                # this 4 GiB card that measured 53%/47% CPU/GPU and 9.2
                # tok/s against 19.6 tok/s fully offloaded. Leaving it unset
                # here meant the baseline generated at twice the pipeline's
                # speed for reasons that had nothing to do with either.
                options["num_gpu"] = num_gpu
            return json.dumps(
                {
                    "model": self.model_name,
                    "messages": prompt.as_messages(),
                    "stream": False,
                    "think": self.think,
                    "options": options,
                }
            ).encode("utf-8")

        # A transient stall — the model being paged back onto a 4 GiB card, or
        # another process taking the GPU — otherwise loses the whole question:
        # in the first benchmark run 4 of 189 scored zero on a bare timeout.
        #
        # Repeating the *identical* request is only the right response to a
        # transient fault. Asking for full offload is not transient: if the card
        # cannot hold every layer, Ollama refuses to size down, because the
        # explicit setting overrides its fitting logic, and llama-server aborts:
        #
        #   common_fit_params: failed to fit params to free device memory:
        #   n_gpu_layers already set by user to 99, abort
        #   GGML_ASSERT(ctx->mem_buffer != NULL) failed
        #
        # which surfaces as a bare HTTP 500. That is what six of six questions
        # hit with 48 MiB of VRAM free, the desktop having taken the rest — and
        # all three attempts failed identically, because nothing about the
        # request had changed. The last attempt therefore drops the setting and
        # lets Ollama fit the model to whatever VRAM it actually has. That is
        # slower, and it makes this answer's latency incomparable to the
        # baseline's, so it is counted and reported rather than hidden.
        ladder: list[int | None] = [self.num_gpu] * self.retries + [None]
        last: Exception | None = None
        for attempt, num_gpu in enumerate(ladder):
            request = urllib.request.Request(
                f"{self.host}/api/chat",
                data=payload_for(num_gpu),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                if num_gpu is None:
                    self.degraded_calls += 1
                return body.get("message", {}).get("content", "").strip()
            except Exception as exc:  # timeouts, resets, truncated bodies
                last = exc
                if attempt < len(ladder) - 1:
                    time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"Ollama generation failed after {len(ladder)} attempts: {last}")
