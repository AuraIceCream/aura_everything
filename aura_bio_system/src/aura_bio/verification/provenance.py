"""Measure how much of an answer is actually traceable to a source (SRS 20.3).

This is the property the accuracy numbers cannot show. Measured across three
separate benchmarks, the bare 4B model already names 87.8-95.6% of the concepts
these questions require, so retrieval adds almost nothing to *recall*. What it
adds is that a claim can be pointed at a passage. "Correct" and "correct and
checkable" are different products, and only the second is defensible for a tutor.

``check_citations`` in :mod:`.checkers` answers a different question — what
fraction of the *supplied evidence* got cited — which is a measure of how much
of the retrieval was used, not of how much of the answer is grounded. An answer
citing one passage once scores 1/9 there while an answer citing that same
passage after every sentence scores the same. Neither tells a reader whether
the sentence they are looking at came from somewhere.

Three numbers per answer, all computed from the answer text and the passages
that were in front of the model:

* **claim citation rate** — of the factual claims, how many carry an inline
  ``[n]``;
* **citation validity** — of those citations, how many point at a passage that
  plausibly contains the claim;
* **unsupported assertion rate** — factual claims with no citation at all,
  which is the number a sceptical reader cares about.

The overlap-based validity metric remains diagnostic, not an acceptance gate.
Robust mode separately requires a minimum inline citation using the verifier's
reported support labels; this does not establish correctness of every claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from .checkers import EvidencePassage, check_claim_support, content_tokens, split_claims
from .schema import Issue, Support, VerificationReport

_CITATION = re.compile(r"\[(\d+)\]")

#: Overlap between a claim and the passage it cites, above which the citation
#: is counted as plausibly supporting it. Low on purpose: the question is
#: whether the citation points somewhere relevant, not whether it entails.
SUPPORT_OVERLAP = 0.25


@dataclass(frozen=True, slots=True)
class ProvenanceReport:
    """Traceability of one answer."""

    claims: int
    cited_claims: int
    citations: int
    valid_citations: int
    dangling_citations: int
    distinct_sources: int

    @property
    def claim_citation_rate(self) -> float:
        return self.cited_claims / self.claims if self.claims else 0.0

    @property
    def citation_validity(self) -> float:
        return self.valid_citations / self.citations if self.citations else 0.0

    @property
    def unsupported_assertion_rate(self) -> float:
        return 1.0 - self.claim_citation_rate if self.claims else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "claims": self.claims,
            "cited_claims": self.cited_claims,
            "citations": self.citations,
            "valid_citations": self.valid_citations,
            "dangling_citations": self.dangling_citations,
            "distinct_sources": self.distinct_sources,
            "claim_citation_rate": round(self.claim_citation_rate, 4),
            "citation_validity": round(self.citation_validity, 4),
            "unsupported_assertion_rate": round(self.unsupported_assertion_rate, 4),
        }


def _claim_spans(answer: str) -> list[tuple[str, str]]:
    """Claims paired with the same text before citations were stripped.

    ``split_claims`` removes ``[n]`` markers so a citation is not mistaken for
    a numeric quantity — correct for claim checking, useless here. Rather than
    trying to find each stripped claim back in the original (which loses the
    trailing marker at the sentence boundary), this repeats the same split and
    keeps both forms, so a claim and its citations are paired exactly.

    It deliberately mirrors ``split_claims``; if that changes, this must too,
    and the shared filters below are imported rather than copied so the two
    cannot silently diverge on what counts as a claim.
    """

    from .checkers import _CITATION as _CLAIM_CITATION
    from .checkers import _NON_CLAIM, _SENTENCE_END

    pairs: list[tuple[str, str]] = []
    for block in answer.split("\n"):
        stripped = block.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", stripped)
        if not stripped or stripped.startswith("#"):
            continue
        for sentence in _SENTENCE_END.split(stripped):
            bare = re.sub(r"\s{2,}", " ", _CLAIM_CITATION.sub("", sentence)).strip()
            if len(bare) < 25 or _NON_CLAIM.match(bare) or bare.endswith("?"):
                continue
            pairs.append((bare, sentence))
    return pairs


def enforce_inline_support(answer: str, evidence: Sequence[EvidencePassage],
                           report: VerificationReport) -> None:
    """Require at least one inline citation linked to a supported claim.

    Robust-mode floor, not a guarantee that every claim is correct. Reuses
    verification's support labels and source IDs without fabricating a citation
    or adding a second overlap threshold. Support still depends on the reported
    backend: NLI in complete runs, lexical fallback otherwise.
    Lexical source IDs include weak candidate matches, so the cited passage
    must independently receive the checker's supported label.
    """
    if not evidence:
        report.checker_status["inline_citations"] = "no_evidence"
        return
    supported = {claim.text.casefold(): set(claim.evidence_chunk_ids)
                 for claim in report.claims if claim.support == Support.SUPPORTED}
    for claim, span in _claim_spans(answer):
        ids = supported.get(claim.casefold(), set())
        for marker in map(int, _CITATION.findall(span)):
            if 1 <= marker <= len(evidence) and evidence[marker - 1].chunk_id in ids:
                if report.support_backend == "lexical":
                    cited_support = check_claim_support([claim], [evidence[marker - 1]])
                    if cited_support[0].support != Support.SUPPORTED:
                        continue
                report.checker_status["inline_citations"] = "supported"
                return
    report.checker_status["inline_citations"] = "missing_supported_citation"
    report.issues.append(Issue(
        "citation", "no_supported_inline_citation",
        "Place an inline [n] citation beside a factual claim supported by that "
        "numbered passage. A references list alone is insufficient. Do not invent "
        "a source or attach an unrelated passage.", "error"))


def measure_provenance(
    answer: str, evidence: Sequence[EvidencePassage]
) -> ProvenanceReport:
    """Compute traceability for one answer against the passages it was given."""

    pairs = _claim_spans(answer)
    citations = 0
    valid = 0
    dangling = 0
    cited_claims = 0
    used_sources: set[str] = set()

    for claim, span in pairs:
        markers = [int(value) for value in _CITATION.findall(span)]
        if markers:
            cited_claims += 1
        tokens = content_tokens(claim)
        for marker in markers:
            citations += 1
            if marker < 1 or marker > len(evidence):
                dangling += 1
                continue
            passage = evidence[marker - 1]
            used_sources.add(passage.source_id or passage.chunk_id)
            if not tokens:
                continue
            overlap = len(tokens & content_tokens(passage.text)) / len(tokens)
            if overlap >= SUPPORT_OVERLAP:
                valid += 1

    return ProvenanceReport(
        claims=len(pairs),
        cited_claims=cited_claims,
        citations=citations,
        valid_citations=valid,
        dangling_citations=dangling,
        distinct_sources=len(used_sources),
    )
