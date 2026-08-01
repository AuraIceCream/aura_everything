"""Check stated yields of the core metabolic pathways against known values.

These are the numbers school and undergraduate answers state most often and get
wrong most often: the net ATP from glycolysis, the per-turn yield of the citric
acid cycle, the cost of fixing one CO2 in the Calvin cycle. They are constants,
so checking them is a lookup and a comparison rather than an inference.

Two sources of legitimate disagreement are handled explicitly rather than
flagged. Total ATP per glucose is quoted as 30, 32, 36 or 38 depending on
whether the textbook counts the glycerol-phosphate or malate-aspartate shuttle
and what P/O ratio it assumes, so every one of those is accepted. And a yield
stated "per turn" differs from the same yield stated "per glucose" by a factor
of two for everything downstream of glycolysis, so the phrasing decides which
value applies; where it is ambiguous, nothing is reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from .schema import Issue


@dataclass(frozen=True, slots=True)
class PathwayFact:
    """One checkable constant.

    ``subject`` and ``quantity`` must both appear near the number for the fact
    to apply, which keeps "2 ATP" in a sentence about active transport from
    being read as a claim about glycolysis.

    ``requires`` and ``forbids`` exist because the same pathway has several
    correct numbers depending on the basis of the claim. Glycolysis makes four
    ATP and consumes two, so "4 ATP" and "2 ATP" are both right — "net" is what
    decides. Likewise a citric-acid-cycle yield doubles between "per turn" and
    "per glucose". Where the basis is not stated, the fact simply does not
    apply and nothing is reported.
    """

    name: str
    subject: str            # regex: the pathway being discussed
    quantity: str           # regex: the thing being counted
    accepted: tuple[float, ...]
    note: str = ""
    requires: str | None = None   # regex that must appear in the sentence
    forbids: str | None = None    # regex that must not appear
    #: Where ``forbids`` is evaluated. Some disqualifying context is stated once
    #: and holds for the whole answer: a Down syndrome explanation names trisomy
    #: in its opening and then writes "the embryo has 47 chromosomes" three
    #: sentences later, where 47 is correct precisely because of the trisomy.
    forbids_scope: str = "sentence"


#: Phrasings that fix the basis of a per-turn yield.
_TURN_BASIS = r"(?:per|each|every|one)\s+(?:turn|cycle)"
_GLUCOSE_BASIS = r"per\s+(?:glucose|molecule\s+of\s+glucose)"

FACTS: tuple[PathwayFact, ...] = (
    PathwayFact(
        "net ATP from glycolysis",
        r"glycolysis",
        r"ATP",
        (2.0,),
        "glycolysis makes 4 ATP and consumes 2, for a net of 2",
        requires=r"\bnet\b",
    ),
    PathwayFact(
        "gross ATP from glycolysis",
        r"glycolysis",
        r"ATP",
        (4.0,),
        "the substrate-level phosphorylations make 4 ATP before the 2 consumed "
        "in the investment phase are subtracted",
        requires=r"\b(?:gross|total(?:ly)?\s+produced|produced\s+in\s+total)\b",
        forbids=r"\bnet\b",
    ),
    PathwayFact(
        "NADH from glycolysis",
        r"glycolysis",
        r"NADH",
        (2.0,),
        "glycolysis reduces 2 NAD+ per glucose",
    ),
    PathwayFact(
        "pyruvate from glycolysis",
        r"glycolysis",
        r"pyruvate",
        (2.0,),
        "one six-carbon glucose yields two three-carbon pyruvates",
    ),
    PathwayFact(
        "NADH per turn of the citric acid cycle",
        r"(?:citric\s+acid|krebs|tca)\s+cycle",
        r"NADH",
        (3.0,),
        "3 NADH per turn; 6 per glucose, since each glucose gives two turns",
        requires=_TURN_BASIS,
        forbids=_GLUCOSE_BASIS,
    ),
    PathwayFact(
        "FADH2 per turn of the citric acid cycle",
        r"(?:citric\s+acid|krebs|tca)\s+cycle",
        r"FADH2|FADH₂",
        (1.0,),
        "1 FADH2 per turn; 2 per glucose",
        requires=_TURN_BASIS,
        forbids=_GLUCOSE_BASIS,
    ),
    PathwayFact(
        "CO2 per turn of the citric acid cycle",
        r"(?:citric\s+acid|krebs|tca)\s+cycle",
        r"(?:CO2|CO₂|carbon\s+dioxide)",
        (2.0,),
        "2 CO2 per turn; 4 per glucose",
        requires=_TURN_BASIS,
        forbids=_GLUCOSE_BASIS,
    ),
    PathwayFact(
        "ATP per glucose from aerobic respiration",
        r"(?:aerobic\s+respiration|cellular\s+respiration|respiration|oxidative\s+phosphorylation)",
        r"(?:total|net|about|approximately|around|up\s+to)?\s*ATP",
        (30.0, 32.0, 34.0, 36.0, 38.0),
        "textbooks quote 30-38 depending on shuttle and P/O assumptions",
    ),
    PathwayFact(
        "ATP to fix one CO2 in the Calvin cycle",
        r"calvin(?:[-\s]benson)?\s+cycle",
        r"ATP",
        (3.0, 9.0, 18.0),
        "3 ATP per CO2; 9 per triose phosphate; 18 per glucose",
    ),
    PathwayFact(
        "NADPH to fix one CO2 in the Calvin cycle",
        r"calvin(?:[-\s]benson)?\s+cycle",
        r"NADPH",
        (2.0, 6.0, 12.0),
        "2 NADPH per CO2; 6 per triose phosphate; 12 per glucose",
    ),
    PathwayFact(
        "chromosomes in a human somatic cell",
        r"human|somatic|diploid",
        r"chromosomes",
        (46.0, 23.0),
        "46 chromosomes in 23 pairs; 23 in a gamete",
        # Aneuploidy is the whole point of these topics, and there 45, 47 and 69
        # are the correct answers. A Down syndrome explanation stating "47
        # chromosomes total rather than the standard 46" was flagged as wrong.
        forbids=r"(?:trisom|monosom|aneuploid|polyploid|triploid|nondisjunction|"
                r"non-disjunction|syndrome|down'?s|klinefelter|turner|patau|edwards|"
                r"extra\s+chromosome|abnormal|karyotype)",
        forbids_scope="document",
    ),
)

_NUMBER = r"(\d+(?:\.\d+)?)"

#: Sentence splitting keeps a claim's number, subject and quantity together and
#: stops a number from one sentence being matched to a pathway in the next.
_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")


def _sentences(answer: str) -> list[str]:
    return [part.strip() for part in _SENTENCE.split(answer) if part.strip()]


#: Clause boundaries within a sentence. Commas and dashes separate claims that
#: may rest on different bases.
_CLAUSE = re.compile(r"[,;—–]| - ")


def _clause_containing(sentence: str, position: int) -> str:
    """The comma-delimited clause of ``sentence`` covering ``position``."""

    start = 0
    for match in _CLAUSE.finditer(sentence):
        if match.start() > position:
            return sentence[start:match.start()]
        start = match.end()
    return sentence[start:]


def check_pathway_stoichiometry(answer: str, facts: Sequence[PathwayFact] = FACTS) -> list[Issue]:
    """Compare stated pathway yields with their known values."""

    issues: list[Issue] = []
    seen: set[tuple[str, float]] = set()
    for sentence in _sentences(answer):
        for fact in facts:
            if not re.search(fact.subject, sentence, re.I):
                continue
            scope = sentence
            if fact.requires:
                basis = re.search(fact.requires, sentence, re.I)
                if basis is None:
                    continue
                # One sentence can carry two claims on different bases —
                # "produces 4 ATP in total, for a net of 2 ATP" is entirely
                # correct. Judge only the clause the basis marker sits in, so
                # the gross figure is not read as a net claim.
                scope = _clause_containing(sentence, basis.start())
            veto = answer if fact.forbids_scope == "document" else scope
            if fact.forbids and re.search(fact.forbids, veto, re.I):
                continue
            pattern = re.compile(
                _NUMBER + r"\s*(?:molecules?\s+of\s+)?(?:" + fact.quantity + r")", re.I
            )
            for match in pattern.finditer(scope):
                value = float(match.group(1))
                key = (fact.name, value)
                if key in seen:
                    continue
                seen.add(key)
                if any(abs(value - accepted) < 1e-6 for accepted in fact.accepted):
                    continue
                expected = " or ".join(f"{a:g}" for a in fact.accepted)
                issues.append(
                    Issue(
                        "pathway",
                        "wrong_yield",
                        f"{fact.name}: answer states {value:g}, expected {expected}"
                        + (f" ({fact.note})" if fact.note else ""),
                        "error",
                        match.group(0).strip(),
                    )
                )
    return issues
