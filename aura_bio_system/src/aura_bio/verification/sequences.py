"""Recompute nucleic-acid and protein claims with Biopython (SRS 16).

SymPy is the only verifier component that has ever bought a measurable gain
(+0.200 on numerical questions) and the reason is structural: it *recomputes*
the answer rather than looking for words near each other. Every lexical checker
in this package has, at some point, fired on correct prose. So this module
follows SymPy's shape — extract an explicit, self-contained claim, recompute it
from first principles, and stay silent otherwise.

Silence is the default on purpose. A pattern only fires when the answer states
something checkable in full ("the complement of ATCG is TAGC", "AUG codes for
methionine"); anything hedged, partial, or merely adjacent is left alone. A
missed check costs nothing, while a false error costs a wasted revision and a
worse answer.
"""

from __future__ import annotations

import re
from typing import Iterable

from .schema import Issue

#: Full names of the twenty standard amino acids, plus the stop pseudo-residue.
#: Biopython ships one- and three-letter tables but not full names, and answers
#: are written in full names.
_AMINO_ACIDS: dict[str, str] = {
    "alanine": "A", "arginine": "R", "asparagine": "N", "aspartate": "D",
    "aspartic acid": "D", "cysteine": "C", "glutamate": "E", "glutamic acid": "E",
    "glutamine": "Q", "glycine": "G", "histidine": "H", "isoleucine": "I",
    "leucine": "L", "lysine": "K", "methionine": "M", "phenylalanine": "F",
    "proline": "P", "serine": "S", "threonine": "T", "tryptophan": "W",
    "tyrosine": "Y", "valine": "V",
}

#: A run of nucleotide letters long enough to be a deliberate sequence rather
#: than an abbreviation. "DNA" and "RNA" are excluded by the length floor of 4,
#: and word boundaries keep it from matching inside ordinary words.
_SEQUENCE = re.compile(r"(?<![A-Za-z0-9])([ACGTUacgtu]{4,})(?![A-Za-z0-9])")

_CODON_CODES_FOR = re.compile(
    r"(?<![A-Za-z])([ACGUTacgut]{3})(?![A-Za-z])[^.;:\n]{0,40}?"
    r"\b(?:codes?\s+for|encodes?|specifies|translates?\s+(?:to|as|into)|"
    r"corresponds?\s+to|is\s+(?:the\s+)?codon\s+for)\b[^.;:\n]{0,30}?"
    r"\b(" + "|".join(sorted(_AMINO_ACIDS, key=len, reverse=True)) + r")\b",
    re.I,
)

#: The codon must be the subject of the assertion, not merely nearby. A gap of
#: forty characters matched "translation starts at ATG ... and ends at a stop
#: codon" in real output and reported that ATG is a stop codon. Only a direct
#: copula binds the codon to the claim.
_STOP_CODON = re.compile(
    r"(?<![A-Za-z])([ACGUTacgut]{3})(?![A-Za-z])[\s`'\"*)\],]{0,4}"
    r"(?:is|are|acts?\s+as|serves?\s+as|functions?\s+as)\s+(?:a|an|the)?\s*"
    r"(stop|termination|nonsense)\s+codon\b",
    re.I,
)

_START_CODON = re.compile(
    r"(?<![A-Za-z])([ACGUTacgut]{3})(?![A-Za-z])[\s`'\"*)\],]{0,4}"
    r"(?:is|are|acts?\s+as|serves?\s+as|functions?\s+as)\s+(?:a|an|the)?\s*"
    r"(start|initiation)\s+codon\b",
    re.I,
)

_COMPLEMENT = re.compile(
    r"\b(reverse\s+complement|complement)\s+of\s+(?:the\s+)?(?:sequence\s+)?"
    r"(?<![A-Za-z0-9])([ACGTUacgtu]{4,})(?![A-Za-z0-9])[^.;:\n]{0,30}?"
    r"(?:is|=|gives|would\s+be|becomes)\s+(?:5'\s*-?\s*)?"
    r"(?<![A-Za-z0-9])([ACGTUacgtu]{4,})(?![A-Za-z0-9])",
    re.I,
)

_GC_CONTENT = re.compile(
    r"\bGC\s+content\b[^.;:\n]{0,60}?(\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent)", re.I
)

#: Stop and start codons in both DNA and RNA spelling.
_STOPS = {"TAA", "TAG", "TGA", "UAA", "UAG", "UGA"}
_STARTS = {"ATG", "AUG"}


def _issue(kind: str, detail: str, span: str, severity: str = "error") -> Issue:
    return Issue("sequence", kind, detail, severity, span)


def _translate(codon: str) -> str | None:
    """One codon to a one-letter amino acid, or ``None`` if it is a stop."""

    from Bio.Data import CodonTable

    table = CodonTable.unambiguous_dna_by_id[1]
    dna = codon.upper().replace("U", "T")
    if dna in table.stop_codons:
        return None
    return table.forward_table.get(dna)


def check_codon_claims(answer: str) -> list[Issue]:
    """Verify stated codon-to-amino-acid, stop and start assignments."""

    issues: list[Issue] = []
    for match in _CODON_CODES_FOR.finditer(answer):
        codon, named = match.group(1).upper(), match.group(2).lower()
        expected = _translate(codon)
        claimed = _AMINO_ACIDS[named]
        if expected is None:
            issues.append(_issue(
                "wrong_codon",
                f"{codon} is a stop codon, but the answer says it codes for {named}",
                match.group(0).strip(),
            ))
        elif expected != claimed:
            from Bio.Data import IUPACData

            actual = IUPACData.protein_letters_1to3.get(expected, expected)
            issues.append(_issue(
                "wrong_codon",
                f"{codon} codes for {actual}, not {named}",
                match.group(0).strip(),
            ))
    for match in _STOP_CODON.finditer(answer):
        codon = match.group(1).upper()
        if codon not in _STOPS:
            issues.append(_issue(
                "wrong_codon",
                f"{codon} is not a stop codon (the stop codons are UAA, UAG and UGA)",
                match.group(0).strip(),
            ))
    for match in _START_CODON.finditer(answer):
        codon = match.group(1).upper()
        if codon not in _STARTS:
            issues.append(_issue(
                "wrong_codon",
                f"{codon} is not the start codon (translation initiates at AUG)",
                match.group(0).strip(),
            ))
    return issues


def check_complement_claims(answer: str) -> list[Issue]:
    """Recompute any stated complement or reverse complement."""

    from Bio.Seq import Seq

    issues: list[Issue] = []
    for match in _COMPLEMENT.finditer(answer):
        kind, source, claimed = match.group(1).lower(), match.group(2).upper(), match.group(3).upper()
        # A sequence written with both T and U is not a real sequence; skip
        # rather than guess which alphabet was meant.
        if "T" in source and "U" in source:
            continue
        seq = Seq(source.replace("U", "T"))
        expected = str(seq.reverse_complement() if "reverse" in kind else seq.complement())
        if "U" in source:
            expected = expected.replace("T", "U")
        if expected != claimed:
            issues.append(_issue(
                "wrong_complement",
                f"the {kind} of {source} is {expected}, not {claimed}",
                match.group(0).strip(),
            ))
    return issues


def check_gc_content(answer: str) -> list[Issue]:
    """Recompute a stated GC percentage against the nearest quoted sequence."""

    from Bio.SeqUtils import gc_fraction

    issues: list[Issue] = []
    for match in _GC_CONTENT.finditer(answer):
        stated = float(match.group(1))
        window = answer[max(0, match.start() - 200): match.end() + 200]
        candidates = [s.upper() for s in _SEQUENCE.findall(window) if len(s) >= 6]
        if len(candidates) != 1:
            # Zero sequences means nothing to check; several means we cannot
            # tell which one the percentage refers to. Both are left alone.
            continue
        actual = gc_fraction(candidates[0]) * 100
        if abs(actual - stated) > 1.0:
            issues.append(_issue(
                "wrong_gc_content",
                f"{candidates[0]} has GC content {actual:.1f}%, not {stated:.1f}%",
                match.group(0).strip(),
            ))
    return issues


def check_sequence_alphabet(answer: str, minimum_length: int = 8) -> list[Issue]:
    """Flag a stated nucleotide sequence containing impossible letters.

    The candidate must be written in upper case. Sequences are conventionally
    uppercase, and without that requirement the word after "sequence" gets
    judged as nucleotides: real output containing "any sequence containing a
    Start codon" was reported as an invalid sequence because CONTAINING is 80%
    ACGTUN letters. Purity is also raised, so a genuine sequence with one typo
    is caught while an English word is not.
    """

    issues: list[Issue] = []
    pattern = re.compile(
        r"\b(?:sequence|strand|oligo(?:nucleotide)?|primer)\b[^.;:\n]{0,40}?"
        r"(?<![A-Za-z0-9])([A-Z]{" + str(minimum_length) + r",})(?![A-Za-z0-9])"
    )
    legal = set("ACGTUN")
    run = re.compile(r"[ACGTUN]{4,}")
    for match in pattern.finditer(answer):
        token = match.group(1)
        bad = sorted({c for c in token if c not in legal})
        purity = sum(1 for c in token if c in legal) / len(token)
        # A real sequence contains an actual stretch of nucleotides. Requiring
        # one run of four rules out uppercase English — ANALYSIS and CONTAINING
        # are majority-legal letters but never four in a row — without
        # demanding the near-perfect purity that would miss a typo'd sequence.
        if bad and purity >= 0.6 and run.search(token):
            issues.append(_issue(
                "invalid_sequence",
                f"{token} is described as a sequence but contains {', '.join(bad)}, "
                "which are not nucleotides",
                match.group(0).strip(),
            ))
    return issues


def check_sequences(answer: str) -> list[Issue]:
    """Run every sequence-level recomputation."""

    issues: list[Issue] = []
    for check in (check_codon_claims, check_complement_claims, check_gc_content,
                  check_sequence_alphabet):
        try:
            issues.extend(check(answer))
        except Exception:
            # A verifier must never be able to fail the request (SRS 18.3); an
            # unparseable claim simply goes unchecked.
            continue
    return _dedup(issues)


def _dedup(issues: Iterable[Issue]) -> list[Issue]:
    seen: set[tuple[str, str]] = set()
    unique: list[Issue] = []
    for issue in issues:
        key = (issue.kind, issue.detail)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique
