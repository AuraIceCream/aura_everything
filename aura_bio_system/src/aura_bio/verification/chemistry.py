"""Balance stated chemical equations and sanity-check physical magnitudes.

Two recomputations that biology answers get wrong often enough to be worth
automating:

* an unbalanced photosynthesis or respiration equation, which is the single
  most repeated error in school-level biology prose;
* a quantity stated in the wrong unit scale — a resting membrane potential of
  "-70 V" rather than "-70 mV" is a thousandfold error that reads as a typo and
  teaches a falsehood.

Both are checked by computation, not by pattern proximity. The equation checker
in particular refuses to guess: if any species in an equation is a biological
abbreviation rather than a molecular formula, the whole equation is skipped.
``periodictable`` would happily read "ATP" as astatine-phosphorus and report a
balance error on a perfectly good equation, which is exactly the class of false
positive this project has been bitten by repeatedly.
"""

from __future__ import annotations

import re
from typing import Any

from .schema import Issue

#: Species that look like formulas to a formula parser but are not. Any
#: equation mentioning one of these cannot be balanced by element and is left
#: alone rather than guessed at.
_NOT_FORMULAS = frozenset(
    {
        "ATP", "ADP", "AMP", "GTP", "GDP", "NAD", "NADH", "NADP", "NADPH", "FAD",
        "FADH", "FADH2", "DNA", "RNA", "MRNA", "TRNA", "RRNA", "COA", "ACETYL",
        "PI", "P", "NA", "K", "CL", "LIGHT", "ENERGY", "SUNLIGHT", "HEAT",
        "GLUCOSE", "PYRUVATE", "LACTATE", "ETHANOL", "UREA", "HEME", "PGA",
    }
)

#: Arrow forms that separate reactants from products.
_ARROW = re.compile(r"\s*(?:->|-->|=>|→|⟶|⇌|⇋|↔|<=>|yields|produces)\s*", re.I)

#: A species with an optional stoichiometric coefficient: "6CO2", "2 H2O".
_SPECIES = re.compile(r"^\s*(\d+)?\s*([A-Za-z][A-Za-z0-9]*)\s*$")

#: Candidate equation: at least one '+' on one side and an arrow.
_EQUATION = re.compile(
    r"([A-Za-z0-9+\s]{3,80}?)(?:->|-->|=>|→|⟶|⇌|⇋|↔|<=>)([A-Za-z0-9+\s]{3,80})"
)


def _parse_side(side: str) -> dict[str, int] | None:
    """Element counts for one side, or ``None`` if it is not parseable."""

    from periodictable import formula as pt_formula

    totals: dict[str, int] = {}
    parts = [part for part in side.split("+") if part.strip()]
    if not parts:
        return None
    for part in parts:
        match = _SPECIES.match(part)
        if match is None:
            return None
        coefficient = int(match.group(1) or 1)
        species = match.group(2)
        if species.upper() in _NOT_FORMULAS or species.isalpha() and species.isupper() is False and len(species) > 12:
            return None
        try:
            atoms = pt_formula(species).atoms
        except Exception:
            return None
        if not atoms:
            return None
        for element, count in atoms.items():
            totals[str(element)] = totals.get(str(element), 0) + coefficient * int(count)
    return totals or None


def check_chemical_equations(answer: str) -> list[Issue]:
    """Verify that any stated chemical equation balances by element."""

    issues: list[Issue] = []
    seen: set[str] = set()
    for match in _EQUATION.finditer(answer):
        raw = match.group(0).strip()
        if raw in seen:
            continue
        seen.add(raw)
        left_text, right_text = match.group(1), match.group(2)
        if "+" not in left_text and "+" not in right_text:
            # A single species on each side is a transformation statement, not
            # a stoichiometric claim worth balancing.
            continue
        left = _parse_side(left_text)
        right = _parse_side(right_text)
        if left is None or right is None:
            continue
        if left == right:
            continue
        elements = sorted(set(left) | set(right))
        differences = [
            f"{element} {left.get(element, 0)}->{right.get(element, 0)}"
            for element in elements
            if left.get(element, 0) != right.get(element, 0)
        ]
        issues.append(
            Issue(
                "chemistry",
                "unbalanced_equation",
                f"the equation does not balance: {', '.join(differences)}",
                "error",
                raw,
            )
        )
    return issues


# ---------------------------------------------------------------------------
# Physical magnitudes
# ---------------------------------------------------------------------------

#: (name, regex for the quantity, pint unit to normalise to, low, high).
#: Ranges are deliberately generous — the target is a scale error, not a
#: debatable physiological boundary.
_QUANTITIES: tuple[tuple[str, str, str, float, float], ...] = (
    ("resting membrane potential", r"resting\s+(?:membrane\s+)?potential", "millivolt", -100.0, -40.0),
    ("action potential peak", r"action\s+potential[^.;:\n]{0,30}?peak", "millivolt", 20.0, 60.0),
    ("human body temperature", r"(?:human\s+)?body\s+temperature", "degC", 35.0, 40.0),
    ("blood pH", r"blood\s+pH", "dimensionless", 7.0, 7.8),
    ("systolic blood pressure", r"systolic(?:\s+blood)?\s+pressure", "mmHg", 80.0, 160.0),
    ("resting heart rate", r"resting\s+heart\s+rate", "count_per_minute", 40.0, 110.0),
)

_UNIT_TOKEN = r"(-?\d+(?:\.\d+)?)\s*(mV|millivolts?|V|volts?|°?C|degrees?\s*C|celsius|mmHg|kPa|bpm|beats?\s*per\s*minute|)"


def _to_unit(value: float, unit: str, target: str) -> float | None:
    """Convert ``value unit`` into ``target``, or ``None`` if incomparable."""

    import pint

    unit = (unit or "").strip().lower()
    aliases = {
        "": None, "mv": "millivolt", "millivolt": "millivolt", "millivolts": "millivolt",
        "v": "volt", "volt": "volt", "volts": "volt",
        "c": "degC", "°c": "degC", "degrees c": "degC", "degree c": "degC", "celsius": "degC",
        "mmhg": "mmHg", "kpa": "kPa",
        "bpm": "count_per_minute", "beats per minute": "count_per_minute",
        "beat per minute": "count_per_minute",
    }
    name = aliases.get(unit, unit or None)
    if name is None:
        return value if target == "dimensionless" else None
    registry = _registry()
    if target == "count_per_minute" or name == "count_per_minute":
        return value if target == name else None
    try:
        quantity = registry.Quantity(value, name)
        return float(quantity.to(target).magnitude)
    except Exception:
        return None


_REGISTRY: Any = None


def _registry() -> Any:
    global _REGISTRY
    if _REGISTRY is None:
        import pint

        _REGISTRY = pint.UnitRegistry()
    return _REGISTRY


def check_units(answer: str) -> list[Issue]:
    """Flag physiological quantities stated at an impossible scale."""

    issues: list[Issue] = []
    for name, pattern, target, low, high in _QUANTITIES:
        regex = re.compile(pattern + r"[^.;:\n]{0,40}?" + _UNIT_TOKEN, re.I)
        for match in regex.finditer(answer):
            raw_value = float(match.group(1))
            unit = match.group(2)
            if target == "dimensionless" and unit:
                continue
            converted = _to_unit(raw_value, unit, target)
            if converted is None:
                continue
            if low <= converted <= high:
                continue
            # Only a scale-sized miss is reported. Being modestly outside a
            # textbook range is a judgement call, not an arithmetic error.
            span = max(abs(high), abs(low)) or 1.0
            if abs(converted) > 10 * span or abs(converted) < span / 10:
                issues.append(
                    Issue(
                        "units",
                        "implausible_magnitude",
                        f"{name} given as {match.group(1)}{(' ' + unit) if unit else ''} "
                        f"= {converted:.4g} {target}, far outside the physiological "
                        f"range {low} to {high}",
                        "error",
                        match.group(0).strip(),
                    )
                )
    return issues
