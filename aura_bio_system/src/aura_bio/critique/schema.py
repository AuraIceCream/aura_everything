"""Structured critic output and the accept/revise decision (SRS 17.3, 18)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..verification.schema import Support, VerificationReport


@dataclass(frozen=True, slots=True)
class Critique:
    """The SRS 17.3 critic record, validated rather than trusted.

    A critic that returns malformed JSON, or claims an answer is supported when
    the deterministic verifier found unsupported claims, must not be able to
    wave a bad answer through. ``trusted`` records whether this instance came
    from a well-formed response.
    """

    answer_supported: bool
    unsupported_claims: tuple[str, ...] = ()
    terminology_errors: tuple[str, ...] = ()
    process_errors: tuple[str, ...] = ()
    missing_concepts: tuple[str, ...] = ()
    academic_level_match: bool = True
    teaching_quality_score: int = 3
    decision: str = "accept"
    model: str = "none"
    trusted: bool = True
    raw: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer_supported": self.answer_supported,
            "unsupported_claims": list(self.unsupported_claims),
            "terminology_errors": list(self.terminology_errors),
            "process_errors": list(self.process_errors),
            "missing_concepts": list(self.missing_concepts),
            "academic_level_match": self.academic_level_match,
            "teaching_quality_score": self.teaching_quality_score,
            "decision": self.decision,
            "model": self.model,
            "trusted": self.trusted,
        }


_DECISIONS = {"accept", "revise", "reject"}


def parse_critique(payload: str, model: str = "unknown") -> Critique:
    """Parse a critic response, degrading to an untrusted record on garbage.

    Models wrap JSON in prose and fences often enough that extracting the first
    balanced object is worth doing before giving up.
    """

    data = _extract_json(payload)
    if data is None:
        return Critique(
            answer_supported=False,
            decision="revise",
            model=model,
            trusted=False,
            raw=payload[:2000],
        )
    decision = str(data.get("decision", "accept")).strip().lower()
    if decision not in _DECISIONS:
        decision = "revise"
    try:
        score = int(data.get("teaching_quality_score", 3))
    except (TypeError, ValueError):
        score = 3
    return Critique(
        answer_supported=bool(data.get("answer_supported", False)),
        unsupported_claims=_strings(data.get("unsupported_claims")),
        terminology_errors=_strings(data.get("terminology_errors")),
        process_errors=_strings(data.get("process_errors")),
        missing_concepts=_strings(data.get("missing_concepts")),
        academic_level_match=bool(data.get("academic_level_match", True)),
        teaching_quality_score=max(1, min(5, score)),
        decision=decision,
        model=model,
        trusted=True,
        raw=None,
    )


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _extract_json(payload: str) -> dict[str, Any] | None:
    text = payload.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def combine_decision(report: VerificationReport, critique: Critique | None) -> str:
    """Deterministic checks win; the critic can only ever be more strict.

    SRS 31 Risk 4: an LLM judge may approve an incorrect answer, so a critic
    saying "accept" cannot clear evidence the verifier flagged as an error.
    """

    verifier_decision = report.decision()
    if verifier_decision != "accept":
        return verifier_decision
    if critique is None:
        return "accept"
    if not critique.trusted:
        return "accept"
    if critique.decision in ("revise", "reject"):
        return "revise"
    return "accept"


@dataclass(slots=True)
class RevisionRecord:
    """One pass through draft, verification, critique, and revision."""

    iteration: int
    answer: str
    verification: dict[str, Any]
    critique: dict[str, Any] | None
    decision: str
    instructions: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "answer": self.answer,
            "verification": self.verification,
            "critique": self.critique,
            "decision": self.decision,
            "instructions": list(self.instructions),
        }


def revision_instructions(report: VerificationReport, critique: Critique | None) -> tuple[str, ...]:
    """Turn findings into concrete edits, so revision is targeted not vague."""

    instructions: list[str] = []
    for issue in report.issues:
        if issue.severity == "error":
            instructions.append(f"Fix the {issue.kind.replace('_', ' ')}: {issue.detail}")
    # Only a claim the evidence *contradicts* is a defect. A claim the evidence
    # merely fails to mention is usually correct biology that retrieval missed,
    # and telling the model to remove or hedge it deletes the answer's substance:
    # measured, this is what turned a complete water-properties answer into one
    # that no longer mentioned specific heat capacity. Weak grounding is reported
    # in the trace; it is not an edit instruction.
    for claim in report.claims:
        if claim.support is Support.CONTRADICTORY:
            instructions.append(
                f"Correct this claim, which the retrieved evidence contradicts: "
                f"{claim.text[:160]!r}"
            )
    if report.citation_coverage == 0.0 and report.claims:
        instructions.append("Cite the supplied passages as [1], [2] where they back a statement.")
    if critique is not None and critique.trusted:
        for concept in critique.missing_concepts:
            instructions.append(f"Cover the missing concept: {concept}")
        if not critique.academic_level_match:
            instructions.append("Re-pitch the explanation at the requested academic level.")
    # Duplicated instructions make the revision prompt worse, not better.
    return tuple(dict.fromkeys(instructions))
