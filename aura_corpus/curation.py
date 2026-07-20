from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from .net import request_json


SYSTEM_PROMPT = """You are a conservative biology-corpus curator.
Classify only the supplied metadata and excerpt. Never infer a license.
Return one JSON object with exactly these fields:
decision (accept or quarantine), subdomains (array), academic_level,
document_type, quality_flags (array), confidence (0 to 1), reason.
Quarantine irrelevant, incoherent, promotional, retracted, or ambiguous material.
Do not include prose outside JSON."""


class Judge(Protocol):
    name: str

    def classify(self, record: dict[str, Any]) -> dict[str, Any]: ...


def _prompt(record: dict[str, Any]) -> str:
    safe = {
        "source_id": record.get("source_id"),
        "title": record.get("title", ""),
        "license_id": record.get("license_id", "unknown"),
        "retracted": record.get("retracted", False),
        "existing_categories": record.get("categories", []),
        "excerpt": str(record.get("text", record.get("excerpt", "")))[:6000],
    }
    return json.dumps(safe, ensure_ascii=False)


def _normalize(result: dict[str, Any], judge: str) -> dict[str, Any]:
    decision = str(result.get("decision", "quarantine")).lower()
    if decision != "accept":
        decision = "quarantine"
    try:
        confidence = max(0.0, min(1.0, float(result.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "decision": decision,
        "subdomains": [str(value) for value in result.get("subdomains", [])][:8],
        "academic_level": str(result.get("academic_level", "unknown")),
        "document_type": str(result.get("document_type", "unknown")),
        "quality_flags": [str(value) for value in result.get("quality_flags", [])][:12],
        "confidence": confidence,
        "reason": str(result.get("reason", ""))[:1000],
        "judge": judge,
    }


@dataclass
class OllamaJudge:
    model: str = "qwen3.5:4b"
    endpoint: str = "http://127.0.0.1:11434/api/chat"
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.name = f"ollama:{self.model}"

    def classify(self, record: dict[str, Any]) -> dict[str, Any]:
        response = request_json(
            self.endpoint,
            {
                "model": self.model,
                "stream": False,
                "think": False,
                "format": "json",
                "options": {"temperature": 0, "num_predict": 400},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _prompt(record)},
                ],
            },
        )
        content = response.get("message", {}).get("content", "{}")
        return _normalize(json.loads(content), self.name)


@dataclass
class GLMJudge:
    model: str = "glm-4.5-flash"
    endpoint: str = "https://api.z.ai/api/paas/v4/chat/completions"
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.name = f"zai:{self.model}"

    def classify(self, record: dict[str, Any]) -> dict[str, Any]:
        api_key = os.environ.get("ZAI_API_KEY")
        if not api_key:
            raise RuntimeError("ZAI_API_KEY is not set")
        response = request_json(
            self.endpoint,
            {
                "model": self.model,
                "temperature": 0,
                "max_tokens": 400,
                "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _prompt(record)},
                ],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return _normalize(json.loads(content), self.name)


def deterministic_gate(record: dict[str, Any]) -> dict[str, Any] | None:
    license_state = str(record.get("license_state", "unknown")).lower()
    if license_state not in {"allowed", "reviewed"}:
        return {
            "decision": "quarantine",
            "confidence": 1.0,
            "reason": f"deterministic license gate: {license_state}",
            "judge": "rules",
        }
    if record.get("retracted") is True:
        return {
            "decision": "quarantine",
            "confidence": 1.0,
            "reason": "deterministic retraction gate",
            "judge": "rules",
        }
    text = str(record.get("text", record.get("excerpt", ""))).strip()
    if text and len(text) < 200:
        return {
            "decision": "quarantine",
            "confidence": 1.0,
            "reason": "deterministic minimum-text gate",
            "judge": "rules",
        }
    return None


@dataclass
class CascadeCurator:
    local: Judge
    external: Judge | None = None
    local_accept_threshold: float = 0.85

    def classify(self, record: dict[str, Any]) -> dict[str, Any]:
        gated = deterministic_gate(record)
        if gated:
            return {**gated, "review_chain": [gated]}

        local = self.local.classify(record)
        if local["confidence"] >= self.local_accept_threshold:
            return {**local, "review_chain": [local]}
        if self.external is None:
            return {
                **local,
                "decision": "quarantine",
                "reason": "local confidence below threshold; no external judge configured",
                "review_chain": [local],
            }

        external = self.external.classify(record)
        agreed = local["decision"] == external["decision"]
        if agreed:
            result = dict(external)
            result["confidence"] = min(local["confidence"], external["confidence"])
            result["reason"] = f"judges agreed; external: {external['reason']}"
        else:
            result = {
                **external,
                "decision": "quarantine",
                "confidence": 1.0 - abs(local["confidence"] - external["confidence"]),
                "reason": "local and external judges disagreed",
            }
        result["review_chain"] = [local, external]
        return result
