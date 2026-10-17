"""Structured verification output (SRS 16 and 17.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Support(StrEnum):
    """SRS 16.1 claim labels."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTORY = "contradictory"
    UNVERIFIABLE = "unverifiable"


class Certainty(StrEnum):
    """SRS 16.5 epistemic status."""

    ESTABLISHED = "established"
    DEBATED = "debated"
    INCOMPLETE = "incomplete"
    HYPOTHESIS = "hypothesis"
    SPECULATION = "speculation"


@dataclass(frozen=True, slots=True)
class Claim:
    """One checkable statement lifted out of a draft answer."""

    index: int
    text: str
    support: Support
    certainty: Certainty
    score: float
    evidence_chunk_ids: tuple[str, ...] = ()
    numeric_tokens: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "text": self.text,
            "support": str(self.support),
            "certainty": str(self.certainty),
            "score": round(self.score, 4),
            "evidence_chunk_ids": list(self.evidence_chunk_ids),
            "numeric_tokens": list(self.numeric_tokens),
        }


@dataclass(frozen=True, slots=True)
class Issue:
    """A specific defect a checker can point at."""

    checker: str
    kind: str
    detail: str
    severity: str = "warning"
    span: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "checker": self.checker,
            "kind": self.kind,
            "detail": self.detail,
            "severity": self.severity,
            "span": self.span,
        }


@dataclass(slots=True)
class VerificationReport:
    """Everything the SRS 20.3 verification page needs to render."""

    claims: list[Claim] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    citation_coverage: float = 0.0
    grounded_fraction: float = 0.0
    numerical: list[dict[str, Any]] = field(default_factory=list)
    support_backend: str = "disabled"
    checker_status: dict[str, str] = field(default_factory=dict)

    @property
    def blocking(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def unsupported_claims(self) -> list[Claim]:
        return [
            claim
            for claim in self.claims
            if claim.support in (Support.UNSUPPORTED, Support.CONTRADICTORY)
        ]

    #: Retrieval is judged to have failed when essentially nothing in the answer
    #: could be tied to a passage. This is a statement about the *evidence*, not
    #: about the answer's correctness.
    INSUFFICIENT_GROUNDING = 0.10

    def decision(self) -> str:
        """SRS 18: accept, revise, or refuse to answer from this evidence.

        Driven by detected defects, not by how much an answer's wording overlaps
        its sources. Two earlier versions of this gate keyed on
        ``grounded_fraction``, which comes from token overlap and measures
        topical proximity rather than agreement. The first rejected 97% of
        answers; the second was measured to have an *inverted* signal — answers
        it accepted scored 0.041 below the bare model while answers it flagged
        scored 0.015 above — because overlap rewards saying more words about the
        right subject.

        What blocks now is an ``error``: arithmetic SymPy recomputed and found
        wrong, a codon that does not encode what the answer claims, an equation
        that does not balance, a pathway yield that is not the known constant, a
        reversed process order, a wrong compartment, or a claim the NLI model is
        confident the evidence contradicts. Each of those names a specific
        defect a revision can act on.

        ``insufficient_evidence`` survives for the genuine retrieval failure —
        an answer whose claims tie to nothing that came back — and is reported
        rather than treated as the answer's fault.
        """

        if any(issue.severity == "error" for issue in self.issues):
            return "revise"
        if not self.claims:
            return "accept"
        if self.grounded_fraction < self.INSUFFICIENT_GROUNDING:
            return "insufficient_evidence"
        return "accept"

    def confidence(self) -> float:
        """A blunt, explainable score; not a calibrated probability."""

        if not self.claims:
            return 0.5
        penalty = 0.1 * len(self.blocking) + 0.05 * len(
            [issue for issue in self.issues if issue.severity == "warning"]
        )
        return round(max(0.0, min(1.0, self.grounded_fraction - penalty)), 3)

    def as_dict(self) -> dict[str, Any]:
        return {
            "claims": [claim.as_dict() for claim in self.claims],
            "issues": [issue.as_dict() for issue in self.issues],
            "citation_coverage": round(self.citation_coverage, 3),
            "grounded_fraction": round(self.grounded_fraction, 3),
            "numerical": self.numerical,
            "support_backend": self.support_backend,
            "checker_status": dict(self.checker_status),
            "unsupported_claim_count": len(self.unsupported_claims),
            "decision": self.decision(),
            "confidence": self.confidence(),
        }
