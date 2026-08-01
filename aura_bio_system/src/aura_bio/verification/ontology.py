"""Check named biological entities against the corpus's own ontologies.

The index already carries three authorities that nothing has been using:
116,418 Gene Ontology terms with definitions, 33,101 MeSH descriptors, and
roughly half a million Wikipedia biology titles. Together they are a usable
answer to "is this a real thing?" — computed locally, with no API and no model,
and inspectable in the sense that a failure names the exact phrase it could not
find.

This is the check the adversarial benchmark questions want. "The Golgi
mitochondrial bridge organelle" and "the Hensen-Baxter law of chromosomal
repulsion" are absent from all three authorities; "the Golgi apparatus" and
"Mendel's law of segregation" are present.

**Two deliberate design choices.**

The primary use is *question-side*: :func:`unknown_entities` reports entities a
question presupposes that the corpus has never heard of. That is a genuine
retrieval result — "1.14M biology passages contain no such entity" — and it
carries no risk of misfiring on a correct refusal.

The answer-side checker exists too, but only at ``warning`` severity and only
when the answer asserts the entity affirmatively. An answer that correctly says
"there is no such organelle" *contains* the phrase, and a checker that cannot
tell assertion from denial would punish exactly the behaviour the project wants.
The lexicon is also necessarily incomplete, so an absent term is a prompt to
look, never a proof of error.
"""

from __future__ import annotations

import gzip
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .schema import Issue

#: Sources in the index that act as naming authorities, most authoritative
#: first. Wikipedia is included for breadth: it covers common names, species
#: and structures that neither GO nor MeSH lists.
AUTHORITY_SOURCES: tuple[str, ...] = (
    "gene_ontology",
    "mesh_descriptors",
    "reactome_summaries",
    "wikipedia_biology",
)

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s-]")

#: Head nouns that mark a phrase as a claim about a *named* entity. Generic
#: heads — process, protein, molecule, gene, reaction, complex, enzyme — were
#: removed after measurement: they matched ordinary prose such as "the enzyme
#: accelerates a reaction" and produced 2.2 spurious findings per real answer.
_ENTITY_HEADS = (
    "organelle", "receptor", "channel", "pump", "law", "principle", "rule",
    "effect", "cycle", "pathway", "theory", "syndrome",
)

#: "the Krebs-Watson glucose bypass cycle" -> captures the words before the head.
#: At least one modifier must be capitalised. A fabricated entity is always
#: presented as a proper name; lowercase modifiers ("the cell cycle", "the
#: signalling pathway") are ordinary vocabulary and are left alone.
_NAMED_ENTITY = re.compile(
    r"\b(?:the|a|an)\s+((?:[A-Za-z][A-Za-z0-9'-]*\s+){1,4}?)(" + "|".join(_ENTITY_HEADS) + r")\b"
)

#: A quoted phrase is almost always the asker naming something specific.
_QUOTED = re.compile(r"['\"‘’“”]([A-Za-z][A-Za-z0-9 '‐-―-]{5,60})['\"‘’“”]")

#: Genus species, but only inside emphasis markup. Bare "Capitalised lowercase"
#: matches the opening of most English sentences: unrestricted, this fired 3,474
#: times over 537 real answers — 6.5 per answer — on "Prerequisite idea", "Core
#: idea", "For instance". Convention writes species names in italics, and the
#: answers are markdown, so emphasis is both the correct signal and a precise
#: one.
_BINOMIAL = re.compile(
    r"(?:\*\*?|__?)\s*([A-Z][a-z]{2,})\s+([a-z]{3,})\s*(?:\*\*?|__?)"
)

#: Denial phrasing near a term means the answer is refusing, not asserting.
_DENIAL = re.compile(
    r"\b(no such|does not exist|do not exist|not a real|is not a recognis|is not a recognized|"
    r"there is no|there are no|not a known|no known|fictional|not an? (?:established|accepted|"
    r"recognised|recognized|real)|does not appear to (?:be|exist)|no evidence (?:of|for)|"
    r"is not a valid|invented|made[- ]up|misconception)\b",
    re.I,
)


def normalise(phrase: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace for lookup.

    Hyphens become spaces. Sources disagree about them — the encyclopaedia
    titles "Hardy–Weinberg principle" with an en dash, which strips to a space,
    while a learner types an ASCII hyphen. Keeping hyphens made those two
    different strings and reported a foundational principle as unknown.
    """

    return _WS.sub(" ", _PUNCT.sub(" ", phrase.lower()).replace("-", " ")).strip()


#: Textbook names the corpus files under a different title. Kept deliberately
#: short and explicit: these are corpus-vocabulary reconciliations, not domain
#: knowledge, and every one is a name a learner is more likely to type than the
#: title the encyclopaedia chose. Measured, "Krebs cycle" was the only such gap
#: across 433 real benchmark questions.
ALIASES: dict[str, str] = {
    "krebs cycle": "citric acid cycle",
    "tca cycle": "citric acid cycle",
    "tricarboxylic acid cycle": "citric acid cycle",
    "sodium potassium pump": "na+/k+-atpase",
    "calvin benson cycle": "calvin cycle",
    "electron transport chain": "electron transport chain",
}


@dataclass(slots=True)
class Lexicon:
    """Normalised entity names drawn from the corpus's naming authorities."""

    names: frozenset[str]
    sources: tuple[str, ...] = ()

    def __contains__(self, phrase: str) -> bool:
        return normalise(phrase) in self.names

    def known(self, phrase: str) -> bool:
        """True if the phrase, or a trailing sub-phrase of it, is a known entity.

        Extraction over-reaches: "the chromosomal basis of Down syndrome" is
        captured whole, but the entity is "Down syndrome". Trying successively
        shorter suffixes recovers it, and cannot make a fabricated entity look
        real — no suffix of "Golgi mitochondrial bridge organelle" is a listed
        term either.

        A genuine synonym gap survives this: the corpus titles the citric acid
        cycle so, and calls nothing "Krebs cycle". That is why a miss is
        reported as something to check, never as proof of invention.
        """

        key = normalise(phrase)
        if not key:
            return False
        words = re.sub(r"^(?:the|a|an)\s+", "", key).split()
        for start in range(len(words) - 1):
            suffix = " ".join(words[start:])
            if suffix in self.names or normalise(ALIASES.get(suffix, "")) in self.names:
                return True
        return bool(words) and words[-1] in self.names and len(words) == 1

    def __len__(self) -> int:
        return len(self.names)


def default_lexicon_path() -> Path:
    return Path(__file__).resolve().parents[3] / "benchmarks" / "entity_lexicon.txt.gz"


def build_lexicon(
    index_path: Path,
    out_path: Path | None = None,
    sources: Iterable[str] = AUTHORITY_SOURCES,
    max_words: int = 8,
) -> Path:
    """Extract distinct entity names from the index into a compressed list.

    Runs once. Streaming ``title`` alone keeps SQLite from paging the large
    ``text`` column, which matters because every data partition on this machine
    is one SATA disk.
    """

    out_path = out_path or default_lexicon_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    try:
        names: set[str] = set()
        placeholders = ",".join("?" * len(tuple(sources)))
        cursor = connection.execute(
            f"SELECT DISTINCT title FROM chunks WHERE source_id IN ({placeholders})",
            tuple(sources),
        )
        for (title,) in cursor:
            if not title:
                continue
            key = normalise(title)
            if key and len(key.split()) <= max_words:
                names.add(key)
    finally:
        connection.close()

    with gzip.open(out_path, "wt", encoding="utf-8") as handle:
        for name in sorted(names):
            handle.write(name + "\n")
    return out_path


_LEXICON: Lexicon | None = None


def load_lexicon(path: Path | None = None) -> Lexicon:
    """Load (and memoise) the entity lexicon; empty if it has not been built."""

    global _LEXICON
    if _LEXICON is not None:
        return _LEXICON
    path = path or default_lexicon_path()
    if not path.is_file():
        _LEXICON = Lexicon(frozenset())
        return _LEXICON
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        _LEXICON = Lexicon(frozenset(line.strip() for line in handle if line.strip()),
                           AUTHORITY_SOURCES)
    return _LEXICON


def candidate_entities(text: str, include_quoted: bool = True) -> list[str]:
    """Phrases in ``text`` that read as claims about a named biological entity.

    ``include_quoted`` belongs to the question side. A question quoting a term
    is naming something specific and is the strongest possible signal. An
    *answer* quoting a term is usually teaching: measured over real output,
    quotation marks surrounded analogies — "Roommate", "factory", "mortar" —
    and produced roughly one spurious finding per answer.
    """

    found: list[str] = []
    if include_quoted:
        for match in _QUOTED.finditer(text):
            found.append(match.group(1).strip())
    for match in _NAMED_ENTITY.finditer(text):
        modifiers = match.group(1).strip()
        words = modifiers.split()
        # Require a proper-noun-looking modifier that is not merely the first
        # word of a sentence. Fabricated entities are named after people or
        # invented compounds — "Hensen-Baxter", "Krebs-Watson", "Golgi".
        if not any(word[:1].isupper() for word in words):
            continue
        found.append(f"{modifiers} {match.group(2)}".strip())
    seen: set[str] = set()
    unique: list[str] = []
    for phrase in found:
        key = normalise(phrase)
        if key and key not in seen:
            seen.add(key)
            unique.append(phrase)
    return unique


def unknown_entities(text: str, lexicon: Lexicon | None = None) -> list[str]:
    """Named entities in ``text`` that no corpus authority lists.

    This is the question-side signal: it says "we searched every naming
    authority in the corpus and this does not appear", which is a retrieval
    result rather than an opinion.
    """

    lexicon = lexicon or load_lexicon()
    if not len(lexicon):
        return []
    return [phrase for phrase in candidate_entities(text) if not lexicon.known(phrase)]


def check_ontology_terms(answer: str, lexicon: Lexicon | None = None) -> list[Issue]:
    """Warn where an answer asserts an entity the corpus authorities lack."""

    lexicon = lexicon or load_lexicon()
    if not len(lexicon):
        return []
    issues: list[Issue] = []
    for phrase in candidate_entities(answer, include_quoted=False):
        if lexicon.known(phrase):
            continue
        # Is the answer denying this entity rather than asserting it? Look at
        # the sentence around the mention.
        index = answer.lower().find(phrase.lower()[:40])
        window = answer[max(0, index - 220): index + len(phrase) + 220] if index >= 0 else answer
        if _DENIAL.search(window):
            continue
        issues.append(
            Issue(
                "ontology",
                "unknown_entity",
                f"{phrase!r} is not listed in Gene Ontology, MeSH, Reactome or the "
                "encyclopaedia titles in this corpus; check that it is a real entity",
                "warning",
                phrase,
            )
        )
    return issues


def check_taxonomy(answer: str, lexicon: Lexicon | None = None) -> list[Issue]:
    """Warn on binomial names absent from the corpus."""

    lexicon = lexicon or load_lexicon()
    if not len(lexicon):
        return []
    issues: list[Issue] = []
    seen: set[str] = set()
    for match in _BINOMIAL.finditer(answer):
        genus, species = match.group(1), match.group(2)
        binomial = f"{genus} {species}"
        key = normalise(binomial)
        if key in seen:
            continue
        seen.add(key)
        if lexicon.known(binomial):
            continue
        window_start = max(0, match.start() - 200)
        if _DENIAL.search(answer[window_start: match.end() + 200]):
            continue
        issues.append(
            Issue(
                "ontology",
                "unknown_species",
                f"{binomial!r} does not appear as a species in this corpus; "
                "verify the binomial before presenting it as established",
                "warning",
                binomial,
            )
        )
    return issues
