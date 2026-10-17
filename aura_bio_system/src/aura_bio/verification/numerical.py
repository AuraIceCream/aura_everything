"""Deterministic numerical biology checks (SRS 16.4).

These solvers exist because an LLM judge cannot be trusted on arithmetic and
because SRS 31 Risk 4 explicitly requires deterministic numerical checking
rather than a second opinion from another model. Each solver recomputes the
quantity from the premises in the question and compares it against whatever the
draft answer asserted.

Everything here is closed-form and evaluated through SymPy; no code from the
model is executed, which keeps NFR-12 (sandboxed execution) trivially satisfied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

import sympy


#: Two answers agree if they are within this relative tolerance.
TOLERANCE = 0.02


@dataclass(frozen=True, slots=True)
class NumericCheck:
    """One recomputed quantity and its verdict against the draft answer."""

    solver: str
    quantity: str
    expected: float
    stated: float | None
    verdict: str
    working: str
    inputs: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "solver": self.solver,
            "quantity": self.quantity,
            "expected": _round(self.expected),
            "stated": None if self.stated is None else _round(self.stated),
            "verdict": self.verdict,
            "working": self.working,
            "inputs": {key: _round(value) for key, value in self.inputs.items()},
        }


def _round(value: float) -> float:
    return float(sympy.Float(value, 6))


NUMBER = r"(\d+(?:\.\d+)?)"


def _numbers(text: str) -> list[float]:
    return [float(value) for value in re.findall(NUMBER, text)]


def _percent_or_fraction(value: float) -> float:
    """A stated 16 in a frequency context means 16%, not a frequency of 16."""

    return value / 100 if value > 1 else value


def _stated_values(answer: str) -> list[float]:
    values: list[float] = []
    for raw, percent in re.findall(rf"{NUMBER}\s*(%?)", answer):
        value = float(raw)
        values.append(value / 100 if percent else value)
    return values


def _match_stated(expected: float, answer: str) -> tuple[float | None, str]:
    """Find the closest number the answer asserts, and judge it.

    ``unstated`` is deliberately distinct from ``incorrect``: a draft that gives
    a method without a figure has not made a numerical error.
    """

    candidates = _stated_values(answer)
    if not candidates:
        return None, "unstated"
    best = min(candidates, key=lambda value: abs(value - expected))
    if expected == 0:
        return best, "correct" if abs(best) < TOLERANCE else "incorrect"
    return best, "correct" if abs(best - expected) / abs(expected) <= TOLERANCE else "incorrect"


# ---------------------------------------------------------------------------
# Solvers
# ---------------------------------------------------------------------------


def _named_frequency_values(quantity: str, answer: str) -> list[float]:
    """Literal named claims only, not expression prefixes or rejected examples."""
    labels = {
        "q": r"(?:\bq\b|\(\s*q\s*\))",
        "p": r"(?:\bp\b|\(\s*p\s*\))",
        "q_squared": r"(?:\bq\s*(?:\^\s*2|²)|\bq_squared\b)",
        "p_squared": r"(?:\bp\s*(?:\^\s*2|²)|\bp_squared\b)",
        "2pq": (r"(?:\b2\s*p\s*q\b|\b(?:frequency|proportion|percentage)\s+of\s+"
                r"(?:the\s+)?(?:heterozygotes|carriers)\b[^.!?\n]{0,80}?)"),
    }
    pattern = (labels[quantity] + r"\s*(?:=|is|equals)\s*"
               r"(?P<value>-?\d+(?:\.\d+)?)(?!\w|\.\d)\s*(?P<percent>%?)"
               r"(?!\s*[+*/^\-])")
    values = []
    for match in re.finditer(pattern, answer, re.I):
        # 'p + q = 1' is a sum, not a claim that q alone equals one.
        prefix = re.split(r"(?<=[.!?])\s+|[\r\n;]", answer[:match.start()])[-1]
        if (re.search(r"[+*/^\-]\s*$", prefix)
                or re.search(r"\b(?:not|incorrect(?:ly)?|wrong(?:ly)?|mistake|avoid)\b", prefix, re.I)):
            continue
        value = float(match.group("value"))
        values.append(value / 100 if match.group("percent") else value)
    return values


def hardy_weinberg(question: str, answer: str) -> list[NumericCheck]:
    """Recover p and q from a stated homozygous-recessive frequency.

    q^2 -> q -> p = 1 - q -> 2pq and p^2, which covers the standard textbook
    question shape.
    """

    if not re.search(r"hardy[\s-]?weinberg|\bq\s*\^?2\b|homozygous recessive", question, re.I):
        return []

    # An explicitly stated allele frequency is the premise; deriving q^2 from a
    # nearby number would misread "p = 0.7 ... homozygous recessive" as q^2=0.7.
    stated_p = re.search(rf"\bp\s*(?:=|is|of)\s*{NUMBER}", question, re.I)
    stated_q = re.search(rf"\bq\s*(?:=|is|of)\s*{NUMBER}(?!\s*\^?\s*2)", question, re.I)
    q_squared: float | None = None
    if stated_p:
        p_value = _percent_or_fraction(float(stated_p.group(1)))
        if 0 < p_value <= 1:
            q_squared = (1 - p_value) ** 2
    elif stated_q:
        q_value = _percent_or_fraction(float(stated_q.group(1)))
        if 0 < q_value <= 1:
            q_squared = q_value**2

    if q_squared is None:
        match = re.search(
            rf"{NUMBER}\s*(%|percent)?[^.]{{0,60}}?"
            r"(?:recessive|affected|homozygous recessive|show the recessive)",
            question,
            re.I,
        )
        if match is None:
            match = re.search(
                r"(?:recessive|affected)[^.]{0,60}?" + NUMBER + r"\s*(%|percent)?", question, re.I
            )
        if match is None:
            return []
        raw = float(match.group(1))
        q_squared = raw / 100 if match.group(2) else _percent_or_fraction(raw)
    if not 0 < q_squared <= 1:
        return []
    q = sympy.sqrt(sympy.Rational(str(q_squared)))
    p = 1 - q
    heterozygous = 2 * p * q
    homozygous_dominant = p**2
    inputs = {"q_squared": q_squared}
    # Grade whichever quantity the question actually asks for; the rest are
    # shown as working so a reviewer can see where a wrong value came from.
    lowered = question.lower()
    if re.search(r"heterozygot|carrier frequency|2pq", lowered):
        graded = "2pq"
    elif re.search(r"homozygous dominant|\bp\s*\^?\s*2\b", lowered):
        graded = "p_squared"
    elif re.search(r"homozygous recessive|recessive individuals|\bq\s*\^?\s*2\b", lowered):
        graded = "q_squared"
    elif re.search(r"\bfrequency of the recessive allele\b|\bvalue of q\b", lowered):
        graded = "q"
    else:
        graded = "2pq"

    checks: list[NumericCheck] = []
    for quantity, value, working in (
        ("q", q, f"q = sqrt(q^2) = sqrt({q_squared:g})"),
        ("p", p, f"p = 1 - q = 1 - {float(q):.6g}"),
        ("q_squared", sympy.Rational(str(q_squared)), f"q^2 = {q_squared:g}"),
        (
            "2pq",
            heterozygous,
            f"2pq = 2 * {float(p):.6g} * {float(q):.6g}",
        ),
        ("p_squared", homozygous_dominant, f"p^2 = {float(p):.6g}^2"),
    ):
        expected = float(value)
        stated, verdict = _match_stated(expected, answer) if quantity == graded else (None, "working")
        # A correct number elsewhere must not erase an explicitly wrong claim
        # about this quantity. Inspect all named literal occurrences, including
        # intermediate p/q values, while preserving the original target grade.
        for claimed in _named_frequency_values(quantity, answer):
            if abs(claimed - expected) > TOLERANCE * max(abs(expected), 1e-12):
                stated, verdict = claimed, "incorrect"
                break
        checks.append(
            NumericCheck("hardy_weinberg", quantity, expected, stated, verdict, working, inputs)
        )
    return checks


def monohybrid_ratio(question: str, answer: str) -> list[NumericCheck]:
    """Check the offspring ratio claimed for a standard Mendelian cross."""

    lowered = question.lower()
    if "cross" not in lowered and "punnett" not in lowered:
        return []
    crosses = {
        r"\bhet\w*\s*(?:x|×|with|and)\s*het\w*|\baa\s*(?:x|×)\s*aa\b": (
            "heterozygous x heterozygous",
            {"dominant_phenotype": 0.75, "recessive_phenotype": 0.25, "heterozygous": 0.5},
        ),
        r"\bhet\w*\s*(?:x|×|with|and)\s*hom\w*\s*recessive|\baa\s*(?:x|×)\s*aa\b": (
            "heterozygous x homozygous recessive",
            {"dominant_phenotype": 0.5, "recessive_phenotype": 0.5, "heterozygous": 0.5},
        ),
    }
    for pattern, (label, ratios) in crosses.items():
        if re.search(pattern, lowered):
            checks = []
            for quantity, expected in ratios.items():
                stated, verdict = (
                    _match_stated(expected, answer)
                    if quantity == "recessive_phenotype"
                    else (None, "working")
                )
                checks.append(
                    NumericCheck(
                        "mendelian",
                        quantity,
                        expected,
                        stated,
                        verdict,
                        f"{label}: expected {quantity} = {expected:g}",
                        {},
                    )
                )
            return checks
    return []


def exponential_growth(question: str, answer: str) -> list[NumericCheck]:
    """N = N0 * e^(rt), or doubling-time growth when generations are given."""

    lowered = question.lower()
    if not re.search(r"population growth|grows? exponentially|doubling time|generation time", lowered):
        return []
    initial = re.search(rf"(?:initial|starting|begins? with|n0\s*=)\D{{0,20}}{NUMBER}", lowered)
    rate = re.search(rf"(?:rate of|r\s*=|growth rate of)\s*{NUMBER}", lowered)
    time = re.search(rf"(?:after|for|over)\s*{NUMBER}\s*(hours?|minutes?|days?|generations?)", lowered)
    doubling = re.search(rf"doubl\w+\s*(?:time\s*)?(?:of|is|=)?\s*{NUMBER}\s*(hours?|minutes?|days?)", lowered)
    if initial is None or time is None:
        return []
    n0 = float(initial.group(1))
    span = float(time.group(1))
    if doubling is not None:
        period = float(doubling.group(1))
        if period <= 0:
            return []
        expected = n0 * 2 ** (span / period)
        working = f"N = {n0:g} * 2^({span:g}/{period:g})"
        inputs = {"n0": n0, "time": span, "doubling_time": period}
    elif rate is not None:
        r = _percent_or_fraction(float(rate.group(1)))
        expected = float(n0 * sympy.exp(r * span))
        working = f"N = {n0:g} * e^({r:g} * {span:g})"
        inputs = {"n0": n0, "rate": r, "time": span}
    elif "generation" in time.group(2):
        expected = n0 * 2**span
        working = f"N = {n0:g} * 2^{span:g}"
        inputs = {"n0": n0, "generations": span}
    else:
        return []
    stated, verdict = _match_stated(expected, answer)
    return [
        NumericCheck("population_growth", "final_population", expected, stated, verdict, working, inputs)
    ]


def michaelis_menten(question: str, answer: str) -> list[NumericCheck]:
    """v = Vmax * [S] / (Km + [S])."""

    lowered = question.lower()
    if not re.search(r"michaelis|\bkm\b|\bvmax\b", lowered):
        return []
    vmax = re.search(rf"vmax\s*(?:of|is|=)?\s*{NUMBER}", lowered)
    km = re.search(rf"\bkm\s*(?:of|is|=)?\s*{NUMBER}", lowered)
    substrate = re.search(rf"(?:\[s\]|substrate concentration)\s*(?:of|is|=)?\s*{NUMBER}", lowered)
    if not (vmax and km and substrate):
        return []
    v_max = float(vmax.group(1))
    k_m = float(km.group(1))
    s = float(substrate.group(1))
    if k_m + s == 0:
        return []
    expected = float(sympy.Rational(str(v_max)) * sympy.Rational(str(s)) / (sympy.Rational(str(k_m)) + sympy.Rational(str(s))))
    stated, verdict = _match_stated(expected, answer)
    return [
        NumericCheck(
            "michaelis_menten",
            "reaction_velocity",
            expected,
            stated,
            verdict,
            f"v = {v_max:g} * {s:g} / ({k_m:g} + {s:g})",
            {"vmax": v_max, "km": k_m, "substrate": s},
        )
    ]


def dilution(question: str, answer: str) -> list[NumericCheck]:
    """C1V1 = C2V2, solving for whichever term the question leaves out."""

    lowered = question.lower()
    if not re.search(r"dilut|c1\s*v1|stock solution", lowered):
        return []

    def find(*keywords: str):
        """Prefer an explicit label; only then accept looser phrasing.

        Word boundaries matter more than they look: an unanchored "to" matches
        inside "stock", which silently reassigned C2 to the stock concentration.
        """

        for keyword in keywords:
            match = re.search(rf"\b{keyword}\b\D{{0,24}}{NUMBER}", lowered)
            if match:
                return match
        return None

    c1 = find("c1", "stock concentration", "stock")
    v1 = find("v1", "stock volume")
    c2 = find("c2", "final concentration", "diluted to", "to")
    v2 = find("v2", "final volume", "total volume")
    known = {name: value for name, value in (("c1", c1), ("v1", v1), ("c2", c2), ("v2", v2)) if value}
    if len(known) != 3:
        return []
    values = {name: float(match.group(1)) for name, match in known.items()}
    missing = ({"c1", "v1", "c2", "v2"} - set(values)).pop()
    symbol = sympy.Symbol(missing, positive=True)
    terms = {name: values.get(name, symbol) for name in ("c1", "v1", "c2", "v2")}
    solutions = sympy.solve(
        sympy.Eq(terms["c1"] * terms["v1"], terms["c2"] * terms["v2"]), symbol
    )
    if not solutions:
        return []
    expected = float(solutions[0])
    stated, verdict = _match_stated(expected, answer)
    return [
        NumericCheck(
            "dilution",
            missing,
            expected,
            stated,
            verdict,
            f"C1V1 = C2V2 solved for {missing}",
            values,
        )
    ]


def allele_probability(question: str, answer: str) -> list[NumericCheck]:
    """Probability that a carrier x carrier cross produces an affected child."""

    lowered = question.lower()
    if "carrier" not in lowered or not re.search(r"probability|chance|likelihood", lowered):
        return []
    if re.search(r"both (?:parents )?(?:are )?carriers|two carriers", lowered):
        affected = sympy.Rational(1, 4)
        stated, verdict = _match_stated(float(affected), answer)
        return [
            NumericCheck(
                "carrier_cross",
                "affected_offspring",
                float(affected),
                stated,
                verdict,
                "Aa x Aa -> 1/4 aa",
                {},
            )
        ]
    return []


SOLVERS: tuple[Callable[[str, str], list[NumericCheck]], ...] = (
    hardy_weinberg,
    monohybrid_ratio,
    exponential_growth,
    michaelis_menten,
    dilution,
    allele_probability,
)


def verify_numerical(question: str, answer: str) -> list[NumericCheck]:
    """Run every solver whose preconditions the question satisfies.

    A solver that cannot recognise the question returns nothing rather than
    guessing, so silence here means "not checkable", never "correct".
    """

    checks: list[NumericCheck] = []
    for solver in SOLVERS:
        try:
            checks.extend(solver(question, answer))
        except (ValueError, ZeroDivisionError, TypeError, sympy.SympifyError):
            # A malformed question must not take down verification.
            continue
    return checks
