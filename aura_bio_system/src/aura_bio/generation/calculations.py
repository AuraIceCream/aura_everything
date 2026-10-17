"""Render narrowly validated tool results, never benchmark answer keys."""

from __future__ import annotations

import math
import re
from typing import Sequence

from ..verification.numerical import NumericCheck


def render_validated_calculation(question: str, checks: Sequence[NumericCheck]) -> str | None:
    """Worked Hardy-Weinberg answer, or None when recognition is uncertain.

    Restricts ownership to a single frequency premise and a single explicit
    numerical request under stated equilibrium. Rechecks the solver values
    against that premise before rendering; other tasks remain model-generated.
    """
    if (not checks or any(c.solver != "hardy_weinberg" for c in checks)
            or not re.search(r"hardy[\s-]?weinberg\s+equilibrium", question, re.I)
            or re.search(r"\b(?:not|outside|violates?|departures?|non-equilibrium)\b", question, re.I)):
        return None
    requests = list(re.finditer(r"\b(?:what|find|calculate|determine)\b", question, re.I))
    if len(requests) != 1:
        return None
    request = question[requests[-1].start():]
    if (re.search(r"\band\b", request, re.I)
            or re.search(r"\b(?:explain|compare|discuss|why|describe)\b", question, re.I)):
        return None
    targets = {
        "2pq": r"heterozygot|carrier|\b2\s*p\s*q\b",
        "q_squared": r"homozygous recessive|\bq\s*(?:\^\s*2|²|squared)",
        "p_squared": r"homozygous dominant|\bp\s*(?:\^\s*2|²|squared)",
        "q": r"recessive allele|\bvalue of q\b",
        "p": r"dominant allele|\bvalue of p\b",
    }
    quantities = [name for name, pattern in targets.items() if re.search(pattern, request, re.I)]
    if len(quantities) != 1:
        return None
    # Exponents and the name 2pq are not frequency premises. Other extra
    # numbers (multiple populations, counts, ratios) make ownership unsafe.
    cleaned = re.sub(r"\b[pq]\s*(?:\^\s*2|²)|\b2\s*p\s*q\b", "frequency", question, flags=re.I)
    numbers = list(re.finditer(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", cleaned))
    if len(numbers) != 1:
        return None
    datum = numbers[0]
    raw = float(datum.group())
    percent = re.match(r"\s*(?:%|percent\b)", cleaned[datum.end():], re.I) is not None
    value = raw / 100 if percent else raw
    if not 0 < value <= 1:
        return None
    prefix = cleaned[:datum.start()]
    if re.search(r"\bp\s*(?:=|is|of)\s*$", prefix, re.I):
        p, q = value, 1 - value
    elif re.search(r"\bq\s*(?:=|is|of)\s*$", prefix, re.I):
        q, p = value, 1 - value
    elif re.search(r"recessive|affected", question[:requests[-1].start()], re.I):
        q, p = math.sqrt(value), 1 - math.sqrt(value)
    else:
        return None
    values = {"q": q, "p": p, "q_squared": q * q, "p_squared": p * p, "2pq": 2 * p * q}
    supplied = {c.quantity: c.expected for c in checks}
    if (len(checks) != len(values) or supplied.keys() != values.keys()
            or any(not math.isfinite(supplied[k]) or abs(supplied[k] - v) > 1e-9
                   for k, v in values.items())):
        return None
    quantity = quantities[0]
    names = {"2pq": "heterozygotes", "q_squared": "homozygous recessive individuals",
             "p_squared": "homozygous dominant individuals", "q": "the recessive allele",
             "p": "the dominant allele"}
    formulas = {"2pq": f"2pq = 2 * {p:.6g} * {q:.6g}",
                "q_squared": f"q^2 = {q:.6g}^2", "p_squared": f"p^2 = {p:.6g}^2",
                "q": f"q = sqrt({q*q:.6g})", "p": f"p = 1 - {q:.6g}"}
    result = values[quantity]
    return (
        "Using the stated Hardy-Weinberg equilibrium assumption and the question's frequency premise:\n\n"
        f"q^2 = {q*q:.6g}\nq = sqrt({q*q:.6g}) = {q:.6g}\np = 1 - {q:.6g} = {p:.6g}\n"
        f"{formulas[quantity]} = {result:.6g}\n\n"
        f"Therefore, the frequency of {names[quantity]} is {result:.6g} ({result*100:.6g}%).\n\n"
        "This calculation uses the question's premises, not numeric examples from retrieved sources."
    )
