"""External LLM critics (SRS 17) and a client abstraction over providers.

An external critic is a development-time reviewer, never the primary generator
(SRS 17.2). It receives the draft answer plus the evidence and returns the
structured SRS 17.3 critique, which the pipeline folds into its decision only
in the safe direction (an approving critic cannot clear a verifier error).

Two providers are implemented so they can be compared for this use case:

* ``GLMCritic``    — Z.AI GLM (OpenAI-compatible chat completions), key ZAI_API_KEY;
* ``GeminiCritic`` — Google Gemini (generateContent), key GEMINI_API_KEY / GOOGLE_API_KEY.

Both produce a ``Critique`` through the same tolerant parser, so downstream code
does not care which model reviewed the answer.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Sequence

from ..routing.schema import Route
from ..verification.checkers import content_tokens
from .schema import Critique, parse_critique

CRITIC_SYSTEM = (
    "You are a strict biology answer reviewer. You are given a student-facing "
    "answer and the numbered evidence it was allowed to use. Judge only against "
    "that evidence and established biology. Do not rewrite the answer. Respond "
    "with a single JSON object and nothing else, using exactly these keys: "
    "answer_supported (bool), unsupported_claims (list of strings), "
    "terminology_errors (list of strings), process_errors (list of strings), "
    "missing_concepts (list of strings), academic_level_match (bool), "
    "teaching_quality_score (integer 1-5), decision (one of \"accept\", "
    "\"revise\", \"reject\"). Mark answer_supported false and choose \"revise\" "
    "if any claim is not supported by the evidence or is biologically wrong."
)


def _critic_excerpt(text: str, query: str, answer: str, budget: int = 600) -> str:
    """Select verbatim relevant sentences without changing source numbering.

    Keep negations and units inside their sentence. Relevance is deterministic,
    not a support judgement: a contradiction can rank just as highly as support.
    Selected sentences retain source order; omissions are visibly marked.
    """
    if len(text) <= budget:
        return text
    # A single newline may only be a PDF/text line wrap, not a sentence end.
    # Keep its qualifier attached; separate only paragraphs and explicit items.
    blocks = re.split(r"\n\s*\n|\n(?=\s*(?:[-*•]|\d+[.)])\s+)", text)
    sentences = [s.strip() for block in blocks
                 for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", " ".join(block.splitlines()))
                 if s.strip()]
    asked, claimed = content_tokens(query), content_tokens(answer)
    scores = [(3 * len(asked & content_tokens(s)) + len(claimed & content_tokens(s)), i)
              for i, s in enumerate(sentences)]
    selected = []
    seen = set()
    remaining = budget - len("[Selected sentences; other text omitted]\n")
    for score, index in sorted(scores, key=lambda item: (-item[0], item[1])):
        sentence = sentences[index]
        if score <= 0 or sentence in seen or len(sentence) + 1 > remaining:
            continue
        selected.append(index)
        seen.add(sentence)
        remaining -= len(sentence) + 1
    if selected:
        return "[Selected sentences; other text omitted]\n" + "\n".join(sentences[i] for i in sorted(selected))
    marker = "\n[Excerpt clipped; remaining text omitted]"
    return text[:budget - len(marker)].rstrip() + marker


def build_critic_prompt(route: Route, answer: str, evidence: Sequence[Any]) -> str:
    if getattr(route, 'evidence_scope', 'core') == 'pack_only':
        return json.dumps({'question': route.query, 'learner_level': route.learner_level.label,
                           'style': route.teaching_mode.label, 'untrusted_draft': answer,
                           'untrusted_evidence': [{'citation': i, 'title': getattr(item, 'title', ''),
                            'excerpt': _critic_excerpt(getattr(item, 'text', ''), route.query, answer)}
                            for i, item in enumerate(evidence, 1)]}, ensure_ascii=False)
    lines = [
        f"Question: {route.query}",
        f"Intended learner level: {route.learner_level.label}.",
        f"Teaching mode: {route.teaching_mode.label}.",
        "",
        "Numbered evidence the answer was allowed to use (excerpts may omit text):",
    ]
    if evidence:
        for index, item in enumerate(evidence, 1):
            title = getattr(item, "title", "") or ""
            text = _critic_excerpt(getattr(item, "text", "") or "", route.query, answer)
            lines.append(f"[{index}] {title}\n{text}")
    else:
        lines.append("(no evidence was retrieved)")
    lines += ["", "Answer to review:", answer, "", "Return only the JSON object."]
    return "\n".join(lines)


def critic_system(route):
    if getattr(route, 'evidence_scope', 'core') == 'pack_only':
        from ..study.prompts import STUDY_CRITIC_SYSTEM
        return STUDY_CRITIC_SYSTEM
    return CRITIC_SYSTEM


@dataclass(slots=True)
class CriticResult:
    """A critique plus the operational cost of obtaining it, for comparison."""

    critique: Critique
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    raw: str
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "critique": self.critique.as_dict(),
            "latency_ms": round(self.latency_ms, 1),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "error": self.error,
        }


#: Provider free tiers rate-limit bursts, and a batch review (one call per
#: answer) trips them easily. A 429 is transient, so it is retried with
#: exponential backoff rather than being reported as a critic failure.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 2.0


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    last: Exception | None = None
    for attempt in range(max_attempts):
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json", **headers}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in RETRY_STATUS or attempt == max_attempts - 1:
                raise
            # Honour Retry-After when the provider sends it.
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = float(retry_after) if retry_after else BASE_BACKOFF_SECONDS * (2**attempt)
            except ValueError:
                delay = BASE_BACKOFF_SECONDS * (2**attempt)
            time.sleep(min(delay, 30.0))
        except Exception as exc:
            last = exc
            if attempt == max_attempts - 1:
                raise
            time.sleep(BASE_BACKOFF_SECONDS * (2**attempt))
    raise last if last else RuntimeError("request failed")


class GLMCritic:
    """Z.AI GLM critic (OpenAI-compatible chat completions)."""

    def __init__(
        self,
        model: str | None = None,
        endpoint: str | None = None,
        timeout: int = 60,
    ) -> None:
        self.model = model or os.environ.get("ZAI_MODEL", "glm-4.7-flash")
        self.endpoint = endpoint or os.environ.get(
            "ZAI_ENDPOINT", "https://api.z.ai/api/paas/v4/chat/completions"
        )
        self.timeout = timeout
        self.name = f"zai:{self.model}"

    def review(self, route: Route, answer: str, evidence: Sequence[Any]) -> Critique:
        return self.review_detailed(route, answer, evidence).critique

    def review_detailed(self, route: Route, answer: str, evidence: Sequence[Any]) -> CriticResult:
        api_key = os.environ.get("ZAI_API_KEY")
        if not api_key:
            raise RuntimeError("ZAI_API_KEY is not set")
        started = time.perf_counter()
        try:
            body = _post_json(
                self.endpoint,
                {
                    "model": self.model,
                    "temperature": 0,
                    "max_tokens": 700,
                    "thinking": {"type": "disabled"},
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": critic_system(route)},
                        {"role": "user", "content": build_critic_prompt(route, answer, evidence)},
                    ],
                },
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=self.timeout,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            return CriticResult(Critique(False, decision="revise", model=self.name,
                                        trusted=False, failure_kind=type(exc).__name__),
                                elapsed, None, None, "", str(exc))
        elapsed = (time.perf_counter() - started) * 1000
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = body.get("usage", {})
        return CriticResult(
            parse_critique(content, self.name),
            elapsed,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            content,
        )


class GeminiCritic:
    """Google Gemini critic (generateContent REST API)."""

    def __init__(self, model: str = "gemini-2.5-flash", timeout: int = 60) -> None:
        self.model = model
        self.timeout = timeout
        self.name = f"gemini:{self.model}"

    def review(self, route: Route, answer: str, evidence: Sequence[Any]) -> Critique:
        return self.review_detailed(route, answer, evidence).critique

    def review_detailed(self, route: Route, answer: str, evidence: Sequence[Any]) -> CriticResult:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY / GOOGLE_API_KEY is not set")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={api_key}"
        )
        started = time.perf_counter()
        try:
            body = _post_json(
                url,
                {
                    "systemInstruction": {"parts": [{"text": critic_system(route)}]},
                    "contents": [
                        {"role": "user", "parts": [{"text": build_critic_prompt(route, answer, evidence)}]}
                    ],
                    "generationConfig": {
                        "temperature": 0,
                        "responseMimeType": "application/json",
                        "maxOutputTokens": 700,
                    },
                },
                headers={},
                timeout=self.timeout,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            return CriticResult(Critique(False, decision="revise", model=self.name,
                                        trusted=False, failure_kind=type(exc).__name__),
                                elapsed, None, None, "", str(exc))
        elapsed = (time.perf_counter() - started) * 1000
        content = ""
        candidates = body.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [{}])
            content = parts[0].get("text", "") if parts else ""
        usage = body.get("usageMetadata", {})
        return CriticResult(
            parse_critique(content, self.name),
            elapsed,
            usage.get("promptTokenCount"),
            usage.get("candidatesTokenCount"),
            content,
        )


def critic_from_env(preference: str = "glm") -> Any | None:
    """Pick an available external critic, honouring keys that are actually set."""

    if preference == "gemini" and (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        return GeminiCritic()
    if os.environ.get("ZAI_API_KEY"):
        return GLMCritic()
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return GeminiCritic()
    return None
