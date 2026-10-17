"""Deterministic grading of an answer against a benchmark answer key.

Grading is intentionally rule-based, not an LLM judge: SRS 24 and 31 Risk 4
require reproducible, evidence-anchored scoring. An optional LLM judge can be
layered on top for teaching quality, but the accuracy/faithfulness numbers that
drive the ablation come from here.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from ..verification.checkers import check_process_order
from ..verification.numerical import verify_numerical
from .schema import BenchmarkQuestion


#: Set ``AURA_SCORER_STRICT=1`` to grade with exact key phrases, ignoring
#: singular/plural agreement. That is how every run before 2026-07-29 was
#: graded, and keeping it reachable is what makes those numbers still
#: comparable — including the published baseline of 0.822, which the
#: number-agreeing scorer reports as 0.855 on the identical answers.
STRICT_NUMBER_AGREEMENT = os.environ.get("AURA_SCORER_STRICT", "") == "1"


@dataclass(slots=True)
class QuestionScore:
    question_id: str
    subdomain: str
    task_type: str
    concept_recall: float           # fraction of must_include concepts present
    avoided_forbidden: bool         # no must_avoid phrase appeared
    numeric_correct: bool | None    # None when not a numeric question
    order_correct: bool | None      # None when not a process-order question
    hallucinated: bool | None       # None when not adversarial
    overall: float
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "subdomain": self.subdomain,
            "task_type": self.task_type,
            "concept_recall": round(self.concept_recall, 3),
            "avoided_forbidden": self.avoided_forbidden,
            "numeric_correct": self.numeric_correct,
            "order_correct": self.order_correct,
            "hallucinated": self.hallucinated,
            "overall": round(self.overall, 3),
            "detail": self.detail,
        }


#: Emphasis, inline-code and math delimiters. These are formatting, not
#: content, and they sit *inside* key phrases often enough to matter: the
#: pipeline wrote "**allele** frequency", and the key "allele frequency"
#: compiles to ``allele\s+frequenc...``, which cannot match across the ``**``.
#: The answer plainly contains the concept; only the renderer's markup was in
#: the way. Left unfixed this penalises whichever system formats its answers
#: more heavily, which is the pipeline — it is instructed to structure output,
#: while the bare model is not.
_MARKUP = re.compile(r"[*`]+|\$+")


def strip_markup(text: str) -> str:
    """Remove formatting that cannot change what an answer claims.

    Delimiters are deleted rather than replaced with a space, so that
    "thermo**regulation**" reads as one word exactly as it renders. A LaTeX
    command loses its backslash but keeps its name, so ``\\alpha`` still
    matches a key phrase containing "alpha" — replacing the whole command with
    a space would destroy content instead of formatting.

    Measured over 1,680 baseline and 188 pipeline key phrases, this recovers
    one phrase in each and breaks none.
    """

    return _MARKUP.sub("", text).replace("\\", "")


#: British ``-ise`` against American ``-ize``. The answer keys were written with
#: the former ("neutralise", "opsonisation", "depolarise", "hybridise") and the
#: model answers in the latter, so the key and the answer disagree on spelling
#: while agreeing completely on biology.
_ISE = re.compile(r"(?<=[a-z])is(e|ed|es|ing|ation)\b")


def normalise_orthography(text: str) -> str:
    """Fold spelling and separator conventions that carry no meaning.

    Two rules, both applied identically to the answer and to the key phrase, so
    that over-folding cannot create a false miss: if a transform maps two words
    together, it maps them together on both sides.

    * ``-ise``/``-isation`` to ``-ize``/``-ization``.
    * Hyphen to space, so the key "R group" matches the near-universal
      "R-group", and "alpha helix" matches "alpha-helix".

    Measured across 1,680 baseline and 188 pipeline key phrases these recover
    11 and 3 phrases respectively and break none. Both systems gain, which is
    the point: this corrects the measurement rather than favouring a system.

    Deliberately *not* stemming. "divergent" still fails the key "diverge", and
    that is left alone — a scorer that guesses at word senses stops being
    reproducible, which is the property SRS 24 asks of it.
    """

    return _ISE.sub(lambda m: "iz" + m.group(1), text).replace("-", " ")


def _present(answer_lower: str, phrase: str) -> bool:
    """Whole-token containment so 'ATP' does not match inside 'flATPack'.

    Number agreement is ignored on the final word: an answer that says
    "prokaryotes" has covered the key phrase "prokaryote", and one that says
    "hydrogen bonds" has covered "hydrogen bond". The strict form missed 3.3%
    of all key phrases across the baseline run purely on a trailing 's', which
    understates every system equally but understates them all the same.

    Deliberately only plural/singular — no stemming and no synonyms. A scorer
    that guesses at meaning stops being reproducible, which is the property
    SRS 24 wants from it.
    """

    phrase = phrase.strip().lower()
    if not phrase:
        return False
    if not re.search(r"[a-z0-9]", phrase):
        return phrase in answer_lower
    if STRICT_NUMBER_AGREEMENT:
        # Strict mode reproduces the pre-2026-07-29 numbers exactly, so it skips
        # every normalisation, orthographic ones included.
        return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", answer_lower) is not None
    # The answer is normalised once by score_answer; the phrase must be folded
    # the same way here or the two sides stop being comparable.
    phrase = normalise_orthography(phrase)
    words = phrase.split()
    last = words[-1]
    # Singular forms of a plural key phrase, longest first. Never shorten a word
    # to a stub the optional suffix below could then match alone ('gas' -> 'ga').
    stems = [last]
    if len(last) > 5 and last.endswith("es"):
        stems.append(last[:-2])
    if len(last) > 4 and last.endswith("s") and not last.endswith("ss"):
        stems.append(last[:-1])
    alternation = "|".join(re.escape(stem) for stem in stems)
    prefix = re.escape(" ".join(words[:-1])).replace(r"\ ", r"\s+")
    head = f"{prefix}\\s+" if words[:-1] else ""
    pattern = rf"(?<![a-z0-9]){head}(?:{alternation})(?:e?s)?(?![a-z0-9])"
    return re.search(pattern, answer_lower) is not None


def score_answer(question: BenchmarkQuestion, answer: str) -> QuestionScore:
    key = question.answer_key
    lowered = strip_markup(answer.lower())
    if not STRICT_NUMBER_AGREEMENT:
        lowered = normalise_orthography(lowered)
    detail: dict[str, Any] = {}

    hits = [phrase for phrase in key.must_include if _present(lowered, phrase)]
    concept_recall = len(hits) / len(key.must_include) if key.must_include else 1.0
    if key.must_include:
        detail["missing_concepts"] = [p for p in key.must_include if p not in hits]

    forbidden_hit = [phrase for phrase in key.must_avoid if _present(lowered, phrase)]
    avoided = not forbidden_hit
    if forbidden_hit:
        detail["forbidden_present"] = forbidden_hit

    numeric_correct: bool | None = None
    if key.numeric is not None:
        # The declared answer is authoritative for grading. verify_numerical
        # recomputes from the premises and may target a different sub-quantity
        # (for a monohybrid cross it grades the recessive fraction, not the
        # dominant one), so it is only a corroborating signal here.
        numeric_correct = _numeric_match(answer, key.numeric, key.numeric_tolerance)
        checks = verify_numerical(question.question, answer)
        if checks:
            detail["numeric"] = [c.as_dict() for c in checks]
            # Never promote a different solver sub-quantity into the declared
            # answer, or let correct working override an incorrect conclusion.

    order_correct: bool | None = None
    if key.ordered_steps:
        issues = check_process_order(answer, [question.question.lower()])
        # check_process_order keys off known process names; also do a direct
        # order check against the declared steps.
        order_correct = _steps_in_order(lowered, key.ordered_steps)
        detail["order_issues"] = [i.as_dict() for i in issues]

    hallucinated: bool | None = None
    if question.adversarial:
        # A correct response refuses / flags the entity as non-existent.
        refused = any(_present(lowered, marker) for marker in key.must_include)
        fabricated = bool(forbidden_hit)
        hallucinated = fabricated or not refused

    overall = _combine(concept_recall, avoided, numeric_correct, order_correct, hallucinated)
    return QuestionScore(
        question_id=question.id,
        subdomain=question.subdomain,
        task_type=question.task_type,
        concept_recall=concept_recall,
        avoided_forbidden=avoided,
        numeric_correct=numeric_correct,
        order_correct=order_correct,
        hallucinated=hallucinated,
        overall=overall,
        detail=detail,
    )


def _numbers_in(text: str) -> list[float]:
    """Pull comparable numbers out of an answer: decimals, fractions, percents.

    A biology answer may express 0.25 as '0.25', '1/4', or '25%', so all three
    must reduce to the same value before comparison.
    """

    values: list[float] = []
    for match in re.finditer(r"(-?\d+(?:\.\d+)?)\s*(%|/\s*(\d+(?:\.\d+)?))?", text):
        raw = float(match.group(1))
        if match.group(2) and match.group(2).startswith("/"):
            denom = float(match.group(3))
            if denom:
                values.append(raw / denom)
        elif match.group(2) == "%":
            values.append(raw / 100)
            values.append(raw)  # keep the bare number too; '25%' can mean 25 or 0.25
        else:
            values.append(raw)
    return values


def _numeric_match(answer: str, expected: float, tolerance: float) -> bool:
    conclusions = list(re.finditer(
        r"\b(?:therefore|thus|hence|in conclusion|final (?:answer|result))\b", answer, re.I))
    if conclusions:
        # Prefer the last explicitly marked conclusion to incidental numbers
        # in the working. Limit it to its paragraph; this remains rule-based.
        answer = answer[conclusions[-1].end():].split("\n\n", 1)[0]
    numbers = _numbers_in(answer)
    if not numbers:
        return False
    if expected == 0:
        return any(abs(n) <= tolerance for n in numbers)
    return any(abs(n - expected) / abs(expected) <= tolerance for n in numbers)


def _steps_in_order(answer_lower: str, steps: tuple[str, ...]) -> bool:
    positions = [(step, answer_lower.find(step.lower())) for step in steps]
    present = [(step, at) for step, at in positions if at >= 0]
    if len(present) < 2:
        return False
    return [s for s, _ in present] == [s for s, _ in sorted(present, key=lambda x: x[1])]


def _combine(
    concept_recall: float,
    avoided: bool,
    numeric_correct: bool | None,
    order_correct: bool | None,
    hallucinated: bool | None,
) -> float:
    """A single 0-1 score, dominated by the check that matters most per type.

    Adversarial questions are graded purely on whether the model hallucinated;
    numeric questions are dominated by getting the number right; everything else
    blends concept recall with not stating a forbidden misconception.
    """

    if hallucinated is not None:
        return 0.0 if hallucinated else 1.0
    if numeric_correct is not None:
        base = 1.0 if numeric_correct else 0.0
        return round(0.8 * base + 0.2 * concept_recall, 4)
    if order_correct is not None:
        return round(0.5 * concept_recall + 0.4 * (1.0 if order_correct else 0.0)
                     + 0.1 * (1.0 if avoided else 0.0), 4)
    penalty = 0.0 if avoided else 0.5
    return round(max(0.0, concept_recall - penalty), 4)
