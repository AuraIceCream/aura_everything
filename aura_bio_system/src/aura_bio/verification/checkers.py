"""Claim, terminology, process-order, and uncertainty checking (SRS 16.1-16.5).

These checkers are deliberately lexical and deterministic. SRS 31 Risk 4 warns
that an LLM judge will happily approve a wrong answer, so the checks that gate
the revision loop must be reproducible and inspectable. The external critic
(SRS 17) adds judgement on top; it does not replace this layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .schema import Certainty, Claim, Issue, Support, VerificationReport

# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_CITATION = re.compile(r"\[(\d+)\]")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")

#: Words that carry no topical signal when overlapping a passage.
STOPWORDS = frozenset(
    """
    the and for that this with from are was were has have had not but its it's they them their there
    which when what where who whom whose how why can could should would may might must will shall
    into onto than then thus also such some any all each both more most other another between within
    during about above below over under after before while because however therefore although though
    been being does did done use used using make makes made get gets due per via etc
    """.split()
)

#: Statements that are structural rather than factual claims.
_NON_CLAIM = re.compile(
    r"^\s*(?:in summary|to summari[sz]e|let'?s|first,|next,|finally,|for example|"
    r"here (?:is|are)|consider|remember|note that|try (?:this|to)|"
    r"self[- ]check|question:|answer:|step \d+[:.]?\s*$)",
    re.I,
)

HEDGES = (
    "may", "might", "could", "possibly", "perhaps", "suggests", "appears",
    "thought to", "believed to", "is likely", "unclear", "not fully understood",
    "remains unknown", "debated", "controversial", "hypothesis", "proposed",
    "some evidence", "preliminary",
)

#: Universals that are genuinely risky when unsupported. Bare "all", "every",
#: and "none" are deliberately excluded: biology is full of correct universal
#: statements ("all living organisms are made of cells"), and flagging them
#: produced far more false alarms than real catches.
ABSOLUTES = (
    "always",
    "never",
    "in all cases",
    "without exception",
    "no exception",
    "every single",
    "impossible",
    "proves that",
    "proven fact",
    "invariably",
)


def split_claims(answer: str) -> list[str]:
    """Split a draft into sentence-level checkable statements."""

    claims: list[str] = []
    for block in answer.split("\n"):
        stripped = block.strip()
        if not stripped:
            continue
        # Keep list markers out of the claim text but keep the claim.
        stripped = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", stripped)
        if not stripped or stripped.startswith("#"):
            continue
        for sentence in _SENTENCE_END.split(stripped):
            # Citation markers are handled by check_citations; leaving them in
            # would make "[1]" look like a numeric quantity to assert.
            sentence = re.sub(r"\s{2,}", " ", _CITATION.sub("", sentence)).strip()
            if len(sentence) < 25 or _NON_CLAIM.match(sentence):
                continue
            if sentence.endswith("?"):
                continue
            claims.append(sentence)
    return claims


def content_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN.findall(text)
        if token.lower() not in STOPWORDS
    }


# ---------------------------------------------------------------------------
# 16.1 Evidence support
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidencePassage:
    """The subset of a retrieved chunk the checkers need."""

    chunk_id: str
    text: str
    title: str = ""
    source_id: str = ""


NEGATION = re.compile(r"\b(?:not|no|never|cannot|isn't|aren't|doesn't|don't|without)\b")


def check_claim_support(
    claims: Sequence[str], evidence: Sequence[EvidencePassage]
) -> list[Claim]:
    """Label each claim against the retrieved evidence by token overlap.

    Overlap is a weak proxy for entailment and is treated as one: the labels
    distinguish "unverifiable" (nothing retrieved) from "unsupported" (evidence
    exists and does not cover this), because those demand different responses.
    """

    if not claims:
        return []
    passages = [(item, content_tokens(item.text)) for item in evidence]
    results: list[Claim] = []
    for index, text in enumerate(claims):
        tokens = content_tokens(text)
        numeric = tuple(re.findall(r"\d+(?:\.\d+)?%?", text))
        certainty = classify_certainty(text)
        if not tokens:
            results.append(Claim(index, text, Support.UNVERIFIABLE, certainty, 0.0))
            continue
        if not passages:
            results.append(Claim(index, text, Support.UNVERIFIABLE, certainty, 0.0))
            continue
        scored = sorted(
            (
                (len(tokens & passage_tokens) / len(tokens), passage)
                for passage, passage_tokens in passages
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score, _ = scored[0]
        supporting = tuple(passage.chunk_id for score, passage in scored[:3] if score >= 0.25)
        if best_score >= 0.6:
            support = Support.SUPPORTED
        elif best_score >= 0.35:
            support = Support.PARTIALLY_SUPPORTED
        else:
            support = Support.UNSUPPORTED
        # A claim whose numbers appear nowhere in evidence cannot be supported
        # however many of its words match.
        if numeric and support is Support.SUPPORTED:
            evidence_text = " ".join(passage.text for _, passage in scored[:3])
            if not all(token.rstrip("%") in evidence_text for token in numeric):
                support = Support.PARTIALLY_SUPPORTED
        results.append(Claim(index, text, support, certainty, best_score, supporting, numeric))
    return results


# ---------------------------------------------------------------------------
# 16.2 Terminology and entities
# ---------------------------------------------------------------------------

#: Term pairs that are routinely confused; flagged when both senses collide.
CONFUSABLE: tuple[tuple[str, str, str], ...] = (
    ("mitosis", "meiosis", "mitosis and meiosis are distinct divisions"),
    ("transcription", "translation", "transcription makes RNA; translation makes protein"),
    ("glycolysis", "gluconeogenesis", "opposite directions of glucose metabolism"),
    ("prokaryote", "eukaryote", "nuclear membrane presence differs"),
    ("genotype", "phenotype", "genetic constitution versus observable trait"),
    ("antigen", "antibody", "antigens are recognised; antibodies do the recognising"),
    ("artery", "vein", "direction of flow relative to the heart differs"),
    ("dna ligase", "dna helicase", "ligase joins; helicase unwinds"),
)

#: Correct spellings for terms that are commonly mangled.
MISSPELLINGS: dict[str, str] = {
    "mitochondira": "mitochondria",
    "mitochondrias": "mitochondria",
    "chromosone": "chromosome",
    "chromosomone": "chromosome",
    "riboson": "ribosome",
    "ribosone": "ribosome",
    "photosythesis": "photosynthesis",
    "photosynthisis": "photosynthesis",
    "prokaryotic cell nucleus": "prokaryotes have no nucleus",
    "deoxyribose nucleic acid": "deoxyribonucleic acid",
    "adenosine triphosphate molecule energy currency": "adenosine triphosphate",
    "endoplasmic reticulm": "endoplasmic reticulum",
    "golgi apparatas": "golgi apparatus",
    "nuclues": "nucleus",
    "cytoplasim": "cytoplasm",
    "enzime": "enzyme",
    "chlorophyl": "chlorophyll",
    "meosis": "meiosis",
    "mitosys": "mitosis",
}

#: Abbreviations that must be expanded on first use for school-level answers.
ABBREVIATIONS: dict[str, str] = {
    "atp": "adenosine triphosphate",
    "dna": "deoxyribonucleic acid",
    "rna": "ribonucleic acid",
    "mrna": "messenger rna",
    "trna": "transfer rna",
    "etc": "electron transport chain",
    "pcr": "polymerase chain reaction",
    "mhc": "major histocompatibility complex",
    "nadh": "nicotinamide adenine dinucleotide",
}

_BINOMIAL = re.compile(r"\b([A-Z][a-z]{2,})\s+([a-z]{3,})\b")

#: Genus names whose species are frequently mismatched in student answers.
KNOWN_GENERA: frozenset[str] = frozenset(
    {"Escherichia", "Homo", "Drosophila", "Arabidopsis", "Saccharomyces", "Mus", "Caenorhabditis"}
)
VALID_BINOMIALS: frozenset[str] = frozenset(
    {
        "Escherichia coli",
        "Homo sapiens",
        "Drosophila melanogaster",
        "Arabidopsis thaliana",
        "Saccharomyces cerevisiae",
        "Mus musculus",
        "Caenorhabditis elegans",
    }
)


def check_terminology(answer: str) -> list[Issue]:
    """Detect misspellings, confused pairs, and invalid species names."""

    issues: list[Issue] = []
    lowered = answer.lower()
    for wrong, right in MISSPELLINGS.items():
        # Word boundaries matter: "chlorophyll" contains "chlorophyl", so a
        # substring test flags the *correct* spelling as a misspelling.
        if re.search(rf"(?<![a-z]){re.escape(wrong)}(?![a-z])", lowered):
            issues.append(
                Issue("terminology", "misspelling", f"{wrong!r} should be {right!r}", "error", wrong)
            )
    for left, right, why in CONFUSABLE:
        if left in lowered and right in lowered:
            issues.append(
                Issue(
                    "terminology",
                    "confusable_pair",
                    f"{left!r} and {right!r} both appear; {why}",
                    "info",
                    f"{left}/{right}",
                )
            )
    for genus, species in _BINOMIAL.findall(answer):
        if genus in KNOWN_GENERA and f"{genus} {species}" not in VALID_BINOMIALS:
            issues.append(
                Issue(
                    "terminology",
                    "invalid_species",
                    f"{genus} {species!r} is not a recognised binomial for this genus",
                    "error",
                    f"{genus} {species}",
                )
            )
    return issues


def check_abbreviations(answer: str, expand_required: bool) -> list[Issue]:
    """School-level answers should expand an abbreviation on first use."""

    if not expand_required:
        return []
    issues: list[Issue] = []
    lowered = answer.lower()
    for short, long in ABBREVIATIONS.items():
        if re.search(rf"\b{re.escape(short)}\b", lowered) and long not in lowered:
            issues.append(
                Issue(
                    "terminology",
                    "unexpanded_abbreviation",
                    f"{short.upper()} is never expanded to {long!r}",
                    "warning",
                    short.upper(),
                )
            )
    return issues


# ---------------------------------------------------------------------------
# 16.3 Process consistency
# ---------------------------------------------------------------------------

#: Canonical ordered steps. Only unambiguous, textbook-stable orderings.
PROCESS_STEPS: dict[str, tuple[str, ...]] = {
    "dna replication": (
        "initiation",
        "unwinding",
        "primer",
        "elongation",
        "okazaki",
        "ligation",
        "termination",
    ),
    "transcription": ("initiation", "elongation", "termination", "splicing"),
    "translation": ("initiation", "elongation", "termination"),
    "protein synthesis": ("transcription", "translation"),
    "mitosis": ("prophase", "metaphase", "anaphase", "telophase", "cytokinesis"),
    "meiosis": (
        "prophase i",
        "metaphase i",
        "anaphase i",
        "telophase i",
        "prophase ii",
        "metaphase ii",
        "anaphase ii",
        "telophase ii",
    ),
    "cellular respiration": (
        "glycolysis",
        "pyruvate oxidation",
        "krebs cycle",
        "electron transport chain",
        "chemiosmosis",
    ),
    "photosynthesis": ("light-dependent", "calvin cycle"),
    "cell cycle": ("g1", "s phase", "g2", "mitosis"),
}

#: Where each process actually happens, for the location check.
PROCESS_LOCATION: dict[str, tuple[str, ...]] = {
    "glycolysis": ("cytoplasm", "cytosol"),
    "krebs cycle": ("mitochondrial matrix", "matrix", "mitochondri"),
    "electron transport chain": ("inner mitochondrial membrane", "mitochondri", "cristae"),
    "transcription": ("nucleus", "nucleoid"),
    "translation": ("ribosome", "cytoplasm", "rough endoplasmic reticulum"),
    "calvin cycle": ("stroma",),
    "light-dependent reactions": ("thylakoid", "grana"),
    "dna replication": ("nucleus", "nucleoid"),
}

_WRONG_LOCATION = {
    "glycolysis": ("mitochondria", "mitochondrion", "nucleus"),
    "krebs cycle": ("cytoplasm", "cytosol", "nucleus"),
    "calvin cycle": ("thylakoid", "cytoplasm"),
    "light-dependent reactions": ("stroma", "cytoplasm"),
    "transcription": ("ribosome",),
}


#: Markers that show the answer is actually presenting a sequence. Without one
#: of these, the order steps happen to be mentioned in says nothing about the
#: order being claimed: an answer to "what happens during S phase?" names S
#: phase first because it is the topic, not because it comes first.
#: A *numbered* list implies order; a bulleted list usually just enumerates
#: parts, so bullets alone are not treated as a sequence claim.
_SEQUENCE_MARKERS = re.compile(
    r"(?:^|\n)\s*\d+[.)]\s|"
    r"\b(?:then|next|followed by|after that|subsequently|first(?:ly)?|second(?:ly)?|"
    r"finally|begins? with|starts? with|proceeds? through|in order|sequence|→|->)\b",
    re.I,
)


#: How close the named steps must sit to read as one enumerated sequence.
#: A model answer runs to several thousand characters; steps mentioned in
#: different paragraphs are separate discussions, not an ordered list.
_SEQUENCE_SPAN_CHARS = 600


def asserts_sequence(answer: str) -> bool:
    """True when the answer presents its steps as an ordered sequence."""

    return bool(_SEQUENCE_MARKERS.search(answer))


#: Must appear *between* two step mentions for their order to be a claim.
_STEP_CONNECTIVE = re.compile(
    r"\b(?:then|next|followed by|after that|subsequently|finally|leads? to|"
    r"proceeds? to|before|after)\b|→|->",
    re.I,
)


def _find_step(text: str, step: str) -> int:
    """Locate a step name as a whole term, or -1.

    Step names hide inside unrelated compounds: "anaphase" in "anaphase-
    promoting complex" (a protein) and "termination" in "termination signal"
    (a stop codon). Matching those as process steps invented order errors.
    """

    match = re.search(rf"(?<![\w-]){re.escape(step)}(?![\w-])", text)
    return match.start() if match else -1


def check_process_order(answer: str, processes: Iterable[str]) -> list[Issue]:
    """Compare the order steps appear in the answer against the canonical order.

    Order is only judged when the answer actually asserts a sequence; otherwise
    prose that merely mentions the steps in a discussion order would be flagged
    as a process error it never made.
    """

    issues: list[Issue] = []
    lowered = answer.lower()
    sequenced = asserts_sequence(answer)
    for process in processes:
        steps = PROCESS_STEPS.get(process)
        if not steps:
            continue
        positions = [(step, _find_step(lowered, step)) for step in steps]
        present = [(step, at) for step, at in positions if at >= 0]
        if len(present) < 2:
            if not present:
                continue
            issues.append(
                Issue(
                    "process",
                    "insufficient_steps",
                    f"{process}: only {present[0][0]!r} of {len(steps)} named steps appears",
                    "warning",
                    process,
                )
            )
            continue
        ordered = [step for step, _ in sorted(present, key=lambda item: item[1])]
        expected = [step for step in steps if step in {name for name, _ in present}]
        # A sequence claim is compact *and* connected. Steps scattered across a
        # long answer are being discussed, not enumerated; and a connective must
        # sit between the steps themselves, not merely somewhere in the answer.
        # A checkpoint explainer organised by checkpoint rather than by time
        # mentions anaphase before metaphase without ever claiming that order.
        positions = [at for _, at in present]
        span = max(positions) - min(positions)
        between = lowered[min(positions) : max(positions)]
        connected = bool(_STEP_CONNECTIVE.search(between))
        if sequenced and span <= _SEQUENCE_SPAN_CHARS and connected and ordered != expected:
            issues.append(
                Issue(
                    "process",
                    "step_order",
                    f"{process}: stated order {ordered} does not match {expected}",
                    "error",
                    process,
                )
            )
        missing = [step for step in steps if step not in {name for name, _ in present}]
        if missing and len(missing) <= len(steps) // 2:
            issues.append(
                Issue(
                    "process",
                    "missing_steps",
                    f"{process}: does not mention {missing}",
                    "warning",
                    process,
                )
            )
    return issues


#: A locative assertion, e.g. "occurs in the", "takes place within".
_LOCATIVE = (
    r"(?:occurs?|takes?\s+place|happens?|located|found|proceeds?|is\s+carried\s+out|"
    r"operates?|resides?|situated|housed)\s+(?:in|within|inside|on|at|across)\s+(?:the\s+)?"
)


def check_process_location(answer: str) -> list[Issue]:
    """Catch a process being placed in the wrong compartment.

    Co-occurrence is not a claim. "Red blood cells lack mitochondria, so they
    rely on anaerobic glycolysis" mentions both terms close together while
    asserting the opposite, so the check requires an explicit locative link
    between the process and the compartment, inside one sentence.
    """

    issues: list[Issue] = []
    lowered = answer.lower()
    sentences = _SENTENCE_END.split(lowered)
    for process, wrong_places in _WRONG_LOCATION.items():
        if process not in lowered:
            continue
        correct = PROCESS_LOCATION.get(process, ())
        for sentence in sentences:
            if process not in sentence:
                continue
            if any(place in sentence for place in correct):
                continue
            hit = next(
                (
                    wrong
                    for wrong in wrong_places
                    # Either order: "glycolysis occurs in the mitochondria" or
                    # "in the mitochondria, the Krebs cycle takes place".
                    if re.search(
                        rf"{re.escape(process)}.{{0,60}}?{_LOCATIVE}\w*\s*{re.escape(wrong)}", sentence
                    )
                    or re.search(
                        rf"{re.escape(wrong)}.{{0,60}}?\b(?:is\s+where|hosts?|contains?)\b.{{0,40}}?"
                        rf"{re.escape(process)}",
                        sentence,
                    )
                ),
                None,
            )
            if hit:
                issues.append(
                    Issue(
                        "process",
                        "wrong_location",
                        f"{process} is placed in {hit!r}; expected one of {list(correct)}",
                        "error",
                        process,
                    )
                )
                break
    return issues


# ---------------------------------------------------------------------------
# 16.5 Uncertainty
# ---------------------------------------------------------------------------


def classify_certainty(text: str) -> Certainty:
    lowered = text.lower()
    if any(marker in lowered for marker in ("hypothesis", "hypothesised", "hypothesized", "proposed that")):
        return Certainty.HYPOTHESIS
    if any(marker in lowered for marker in ("debated", "controversial", "disputed", "no consensus")):
        return Certainty.DEBATED
    if any(marker in lowered for marker in ("not fully understood", "remains unknown", "unclear", "incompletely")):
        return Certainty.INCOMPLETE
    if any(marker in lowered for marker in HEDGES):
        return Certainty.SPECULATION
    return Certainty.ESTABLISHED


def check_uncertainty(claims: Sequence[Claim]) -> list[Issue]:
    """An unsupported claim stated as settled fact is the dangerous case."""

    issues: list[Issue] = []
    for claim in claims:
        lowered = claim.text.lower()
        # UNVERIFIABLE means nothing was retrieved, which is a statement about
        # our coverage rather than about the answer; only a claim the retrieved
        # evidence actually fails to support can be called overstated.
        #
        # CONTRADICTORY counts here as well as UNSUPPORTED. It did not need to
        # before, when support came from token overlap and a refuted claim
        # tended to land in UNSUPPORTED anyway; the NLI scorer now separates
        # the two properly, and it routed the clearest case there is --
        # "every enzyme is always a protein" against evidence naming ribozymes
        # -- to CONTRADICTORY, which silenced the very rule written for it.
        # Refuted is a stronger failure to support, not an exemption from it.
        if (
            claim.support in (Support.UNSUPPORTED, Support.CONTRADICTORY)
            and claim.certainty is Certainty.ESTABLISHED
            and any(absolute in lowered for absolute in ABSOLUTES)
        ):
            # Deliberately a warning, not an error. Measured against 243 real
            # answers, this rule fires mostly on rhetorical absolutes in
            # teaching prose ("membranes are never static") that are correct
            # biology. Surface keywords cannot separate epistemic overreach
            # from emphasis, so it surfaces the claim for review rather than
            # forcing a revision. Claim-support labels carry the hard signal.
            issues.append(
                Issue(
                    "uncertainty",
                    "overstated",
                    f"claim {claim.index} states an absolute the evidence "
                    f"{'refutes' if claim.support is Support.CONTRADICTORY else 'does not support'}: "
                    f"{claim.text[:90]!r}",
                    "warning",
                    claim.text[:90],
                )
            )
        elif claim.support is Support.UNSUPPORTED and claim.certainty is Certainty.ESTABLISHED:
            issues.append(
                Issue(
                    "uncertainty",
                    "unhedged_unsupported",
                    f"claim {claim.index} is unsupported but stated as established fact",
                    "warning",
                    claim.text[:90],
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------


def check_citations(answer: str, evidence_count: int) -> tuple[float, list[Issue]]:
    """Measure citation coverage and catch references to absent evidence."""

    issues: list[Issue] = []
    cited = {int(value) for value in _CITATION.findall(answer)}
    invalid = sorted(value for value in cited if value < 1 or value > evidence_count)
    if invalid:
        issues.append(
            Issue(
                "citation",
                "dangling_citation",
                f"answer cites evidence {invalid} but only {evidence_count} passages were supplied",
                "error",
            )
        )
    if evidence_count and not cited:
        issues.append(
            Issue("citation", "no_citations", "evidence was retrieved but never cited", "warning")
        )
    valid = {value for value in cited if 1 <= value <= evidence_count}
    coverage = len(valid) / evidence_count if evidence_count else 0.0
    return coverage, issues
