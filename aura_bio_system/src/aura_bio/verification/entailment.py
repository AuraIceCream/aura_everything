"""Claim support by natural-language inference rather than token overlap.

``Support.CONTRADICTORY`` has been in the schema since the beginning, is read by
``VerificationReport.unsupported_claims`` and by ``revision_instructions`` — and
was never once produced. :func:`check_claim_support` labels claims by counting
shared tokens between a claim and a passage, and its own docstring calls that "a
weak proxy for entailment". Token overlap measures topical proximity, so the
verifier could tell that a claim was *about* the same subject as its evidence
but never whether it *agreed* with it. An answer stating the exact opposite of
its evidence scored as well supported.

That is also why the accept/revise signal came out inverted when measured:
answers the verifier accepted scored 0.041 *below* baseline while answers it
flagged scored 0.015 above. Overlap rewards verbosity on topic.

NLI gives the three labels the schema always wanted, directly:

===============  ==========================
NLI label        ``Support``
===============  ==========================
entailment       ``SUPPORTED``
neutral          ``UNVERIFIABLE``
contradiction    ``CONTRADICTORY``
===============  ==========================

**Fencing.** This is the only learned component in the verifier, and it is
allowed to do exactly one thing that matters: a confident contradiction may
block an answer. Weak or neutral support must never block on its own — that was
the mistake that rejected 97% of answers and drove revisions to delete correct
content. The deterministic checkers keep sole authority over ``error`` severity
(SRS 31 Risk 4: nothing learned gets to wave an answer through, and nothing
learned gets to veto on a shrug either).

Runs on CPU by default. The 4 GiB card holds the LLM, and evicting it to score
a dozen claims is the trade the reranker already taught us not to make.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Sequence

from .checkers import EvidencePassage
from .schema import Claim, Certainty, Issue, Support

DEFAULT_MODEL = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"

#: Above this, a contradiction is confident enough to block an answer. Set high
#: deliberately: a false contradiction costs a wasted revision, and this project
#: has a documented history of over-eager verifiers making answers worse.
CONTRADICTION_THRESHOLD = 0.75

#: Above this, an entailment counts as support.
ENTAILMENT_THRESHOLD = 0.50

#: Passage text is truncated to the model's comfortable window; AURA chunks
#: target ~450 tokens, so this keeps whole chunks intact in the common case.
MAX_PREMISE_CHARS = 1800


@dataclass(frozen=True, slots=True)
class EntailmentResult:
    """One claim scored against its best-matching passage."""

    claim: str
    label: str
    entailment: float
    neutral: float
    contradiction: float
    chunk_id: str

    @property
    def support(self) -> Support:
        """Map NLI output onto the schema's support labels.

        Neutral becomes ``UNSUPPORTED``, not ``UNVERIFIABLE``. The distinction
        is load-bearing: ``check_uncertainty`` documents ``UNVERIFIABLE`` as
        "nothing was retrieved", a statement about *our coverage*, whereas
        ``UNSUPPORTED`` means evidence came back and does not cover the claim.
        These results only exist when passages were retrieved, so neutral is
        always the latter.
        """

        if self.label == "contradiction" and self.contradiction >= CONTRADICTION_THRESHOLD:
            return Support.CONTRADICTORY
        if self.label == "entailment" and self.entailment >= ENTAILMENT_THRESHOLD:
            return Support.SUPPORTED
        if self.entailment >= 0.30:
            return Support.PARTIALLY_SUPPORTED
        return Support.UNSUPPORTED


class EntailmentScorer:
    """Lazily loaded NLI cross-encoder over (passage, claim) pairs."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        batch_size: int = 8,
        max_passages: int = 4,
    ) -> None:
        self.model_name = model_name
        self.device = device or os.environ.get("AURA_NLI_DEVICE") or "cpu"
        self.batch_size = batch_size
        # Scoring every claim against every passage is quadratic and mostly
        # wasted; the highest-overlap passages are where agreement or conflict
        # will be found.
        self.max_passages = max_passages
        self._pipe: Any = None

    @property
    def available(self) -> bool:
        try:
            self._load()
        except Exception:
            return False
        return self._pipe is not None

    def _load(self) -> Any:
        if self._pipe is None:
            if os.environ.get("AURA_NLI", "").lower() in {"off", "0", "false"}:
                raise RuntimeError("NLI disabled via AURA_NLI")
            os.environ.setdefault("USE_TF", "0")
            os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
            # HF_HOME lives in .env and points at D:. Without it the cache
            # defaults to the system drive, which sits near zero free space —
            # a test run once pulled 362 MB onto a volume with 90 MB spare.
            from ..env import load_env

            load_env()
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            # local_files_only: a verifier must never make a network call in
            # the middle of answering. If the model has not been fetched
            # deliberately, this raises and the caller falls back to token
            # overlap.
            tokenizer = AutoTokenizer.from_pretrained(self.model_name, local_files_only=True)
            model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name, local_files_only=True
            )
            model.eval()
            self._pipe = (tokenizer, model)
        return self._pipe

    def score(self, premise: str, hypotheses: Sequence[str]) -> list[dict[str, float]]:
        """Probabilities per hypothesis against one premise."""

        import torch

        tokenizer, model = self._load()
        results: list[dict[str, float]] = []
        labels = {v.lower(): k for k, v in model.config.id2label.items()}
        for start in range(0, len(hypotheses), self.batch_size):
            batch = list(hypotheses[start: start + self.batch_size])
            encoded = tokenizer(
                [premise[:MAX_PREMISE_CHARS]] * len(batch),
                batch,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True,
            )
            with torch.no_grad():
                logits = model(**encoded).logits
            probabilities = torch.softmax(logits, dim=-1)
            for row in probabilities:
                results.append(
                    {
                        name: float(row[index])
                        for name, index in labels.items()
                    }
                )
        return results


_SCORER: EntailmentScorer | None = None


def default_scorer() -> EntailmentScorer:
    global _SCORER
    if _SCORER is None:
        _SCORER = EntailmentScorer()
    return _SCORER


def _overlap(claim: str, passage: str) -> float:
    from .checkers import content_tokens

    tokens = content_tokens(claim)
    if not tokens:
        return 0.0
    return len(tokens & content_tokens(passage)) / len(tokens)


def entail_claims(
    claims: Sequence[str],
    evidence: Sequence[EvidencePassage],
    scorer: EntailmentScorer | None = None,
) -> list[EntailmentResult]:
    """Label each claim against the passages most likely to bear on it."""

    if not claims or not evidence:
        return []
    scorer = scorer or default_scorer()
    results: list[EntailmentResult] = []
    for claim in claims:
        ranked = sorted(evidence, key=lambda p: _overlap(claim, p.text), reverse=True)
        best: EntailmentResult | None = None
        for passage in ranked[: scorer.max_passages]:
            scores = scorer.score(passage.text, [claim])[0]
            entailment = scores.get("entailment", 0.0)
            neutral = scores.get("neutral", 0.0)
            contradiction = scores.get("contradiction", 0.0)
            label = max(
                (("entailment", entailment), ("neutral", neutral), ("contradiction", contradiction)),
                key=lambda item: item[1],
            )[0]
            candidate = EntailmentResult(
                claim=claim, label=label, entailment=entailment, neutral=neutral,
                contradiction=contradiction, chunk_id=passage.chunk_id,
            )
            # A claim only needs one passage to support it, so the best
            # entailment wins; but a confident contradiction is worth surfacing
            # even when another passage is merely neutral.
            if best is None:
                best = candidate
            elif candidate.support is Support.CONTRADICTORY and best.support is not Support.CONTRADICTORY:
                best = candidate
            elif candidate.entailment > best.entailment and best.support is not Support.CONTRADICTORY:
                best = candidate
            if best.support is Support.SUPPORTED:
                break
        if best is not None:
            results.append(best)
    return results


def claims_from_entailment(results: Sequence[EntailmentResult]) -> list[Claim]:
    """Convert NLI results into the schema's :class:`Claim` records."""

    from .checkers import classify_certainty

    return [
        Claim(
            index=index,
            text=result.claim,
            support=result.support,
            certainty=classify_certainty(result.claim),
            score=round(result.entailment, 4),
            evidence_chunk_ids=(result.chunk_id,),
        )
        for index, result in enumerate(results)
    ]


#: Fraction of an answer's claims that must be contradicted before the answer
#: is sent back for revision. A single flagged sentence is a review item, not
#: grounds for regenerating everything around it.
MATERIAL_CONTRADICTION_FRACTION = 0.15


def check_entailment(
    results: Sequence[EntailmentResult],
    material_fraction: float = MATERIAL_CONTRADICTION_FRACTION,
) -> list[Issue]:
    """Report contradicted claims, blocking only when they are a real share.

    Severity is decided by *how much* of the answer is contradicted, not by
    whether anything is. The 0.75 per-claim threshold was tuned on the twelve
    labelled critic cases, which carry one to three claims each — so one
    contradiction there is a third to all of the answer. A real teaching answer
    carries thirty-odd claims, and at any non-zero per-claim false-positive rate
    at least one of thirty will trip: measured, this fired on 18 of 50 answers
    and the resulting revisions cost 3.2 points on exactly those questions,
    because a revision that rewrites a sound answer loses content.

    So a single contradicted claim among many is surfaced as a warning — it
    still reaches the trace and the reviewer — while a materially contradicted
    answer still blocks. On the labelled cases nothing changes: one contradiction
    out of one or two claims is far above the fraction.
    """

    contradicted = [r for r in results if r.support is Support.CONTRADICTORY]
    if not contradicted:
        return []
    fraction = len(contradicted) / len(results) if results else 0.0
    material = fraction >= material_fraction
    severity = "error" if material else "warning"
    return [
        Issue(
            "entailment",
            "contradicts_evidence",
            f"the retrieved evidence contradicts this claim "
            f"(p={result.contradiction:.2f}; {len(contradicted)} of {len(results)} "
            f"claims contradicted): {result.claim[:160]!r}",
            severity,
            result.claim[:160],
        )
        for result in contradicted
    ]
