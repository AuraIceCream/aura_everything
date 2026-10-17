"""Prompt construction for the local biology model (SRS 12, 9.2).

The prompt is assembled from the route so that teaching mode and learner level
visibly change the answer's structure, which is an explicit acceptance
criterion (SRS 35.5). Evidence is numbered so the model can cite it as [1], [2]
and the verifier can check those citations against the passages it was given.

No model is imported here; this module only turns a route and evidence into the
strings a generator will send.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from ..routing.schema import LearnerLevel, Route, TeachingMode
from ..verification.checkers import STOPWORDS as _VERIFIER_STOPWORDS

SYSTEM_PROMPT = (
    "You are AURA-Bio, a biology tutor. Answer the learner's question completely "
    "and correctly.\n"
    "\n"
    "The numbered evidence is retrieved by search. It is there to ground, cite, "
    "and enrich your answer — it does not define the answer's scope. Retrieval is "
    "partial by nature: it often returns a research paper or an encyclopaedia "
    "extract that touches the topic without covering the standard account of it.\n"
    "\n"
    "Therefore:\n"
    "- Cite evidence inline as [1], [2] wherever it backs a statement.\n"
    "- Where the established textbook account of the topic goes beyond the "
    "evidence, still give it. Naming the standard structures, enzymes, stages, "
    "and properties is part of a correct answer; omitting one because no "
    "passage happened to mention it makes the answer wrong, not cautious.\n"
    "- Write the answer you would write with no passages in front of you, then "
    "add what the evidence contributes. Measured, the commonest failure of a "
    "retrieval system is not inventing things — it is quietly covering less "
    "ground than the same model would have covered unaided, because attention "
    "follows what can be cited.\n"
    "- Never contradict the evidence. If it conflicts with what you would "
    "otherwise say, follow the evidence and note the disagreement.\n"
    "- Do not discuss the retrieval itself. Never write phrases like 'the "
    "evidence does not mention', 'the passages do not support', or 'based on "
    "the retrieved sources'. The learner is asking about biology, not about "
    "the search results.\n"
    "\n"
    "Name things the way a textbook names them. Where a structure, process, or "
    "property has a conventional term, use that exact term at least once, even "
    "when you also explain it in your own words. A learner needs the phrase they "
    "will actually meet in their syllabus and their exam; an accurate paraphrase "
    "that never names the standard term leaves them unable to recognise it.\n"
    "\n"
    # Deliberately does not spell out a refusal formula. The benchmark scores
    # adversarial questions by looking for markers like "no such" and "does not
    # exist" in the answer, so putting those exact words here would score the
    # prompt rather than the model. State the required behaviour and let the
    # wording be the model's own.
    "If a question takes for granted some entity, law, or process that is not "
    "real, correct that false premise plainly instead of describing it as "
    "though it were genuine, then point the learner to the nearest real "
    "concept. Never invent detail to fill the gap.\n"
    "\n"
    "Never present medical content as professional medical advice. Prefer precise "
    "biological terminology, and define a term the first time you use it when the "
    "learner is at or below senior-secondary level."
)

COMPACT_SYSTEM_PROMPT = (
    "You are AURA-Bio, a biology tutor. Answer each requested part briefly using "
    "standard terms. Ignore off-topic excerpts; cite relevant support inline as "
    "[n]. Never invent facts, numbers or citations. Correct false premises. "
    "Apply explicit corrections, retain correct content, and return one clean "
    "answer, not the old draft plus an addendum. Do not repeat or discuss retrieval."
)

#: How each learner level should shape vocabulary and depth.
LEVEL_GUIDANCE: dict[LearnerLevel, str] = {
    LearnerLevel.ELEMENTARY: "Use everyday words and one concrete everyday example. Avoid jargon.",
    LearnerLevel.MIDDLE_SCHOOL: "Keep sentences short. Introduce at most a few key terms, each defined.",
    LearnerLevel.HIGH_SCHOOL: "Use standard school terminology and define each term on first use.",
    LearnerLevel.SENIOR_SECONDARY: (
        "Match a senior-secondary syllabus: correct mechanisms, named steps, and "
        "exam-appropriate precision."
    ),
    LearnerLevel.UNDERGRADUATE: "Use full technical vocabulary and mechanistic detail.",
    LearnerLevel.POSTGRADUATE: "Assume a strong background; be concise and rigorous.",
    LearnerLevel.RESEARCH: (
        "Write for a researcher: technical, evidence-led, and explicit about "
        "uncertainty and open questions."
    ),
    LearnerLevel.GENERAL_PUBLIC: "Explain plainly for a curious non-specialist, minimal jargon.",
}

#: The structure each teaching mode imposes (SRS 9.1-9.2).
MODE_STRUCTURE: dict[TeachingMode, tuple[str, ...]] = {
    TeachingMode.DIRECT_ANSWER: ("Give a concise, direct answer in one short paragraph.",),
    TeachingMode.GUIDED_EXPLANATION: (
        "Structure the answer as:",
        "1. Prerequisite idea the learner needs first.",
        "2. Core idea in one sentence.",
        "3. Simple explanation, then the technical explanation.",
        "4. The ordered mechanism, if there is one.",
        "5. One example or analogy, and where the analogy breaks down.",
        "6. One common misconception.",
        "7. A one-line summary and a self-check question.",
    ),
    TeachingMode.SOCRATIC: (
        "Do not reveal the full answer. Ask two or three guiding questions and "
        "give a hint after each, leading the learner toward the idea.",
    ),
    TeachingMode.EXAM: (
        "Write an exam-style answer with: definition, key points, mechanism, "
        "a note on the diagram to draw, applications, conclusion, and common mistakes.",
    ),
    TeachingMode.HOMEWORK_SUPPORT: (
        "Give a complete, worked explanation with the reasoning shown, and cite "
        "the evidence for each factual step.",
    ),
    TeachingMode.REVISION: (
        "Produce compact revision material: short bullet notes, a small table if "
        "useful, a mnemonic if natural, and three recall questions.",
    ),
    TeachingMode.MISCONCEPTION_REPAIR: (
        "Name the likely misconception, explain precisely why it is wrong, then "
        "give the correct model and one check the learner can use to remember it.",
    ),
    TeachingMode.RESEARCH: (
        "Answer at research level: precise terminology, evidence with citations, "
        "explicit uncertainty, and the current state of understanding.",
    ),
    TeachingMode.TEACH_BACK: (
        "Ask the learner to explain the concept back, then evaluate their "
        "explanation against the evidence and correct any gaps.",
    ),
}

#: How the model should treat the retrieved passages, restated next to them.
#:
#: The earlier wording ("give only what the evidence supports") measured badly:
#: the model dutifully narrowed each answer to whatever the search happened to
#: return, dropping canonical content it plainly knew. On "Explain how DNA
#: replication occurs" it produced 4,987 characters that never named primase,
#: the leading and lagging strands, or Okazaki fragments, because the retrieved
#: passages were about PCR. The bare model, asked the same question with no
#: evidence at all, named all four.
EVIDENCE_POLICY = (
    "Use the evidence above for specifics, citations, and detail. Do not let it "
    "limit what you cover: answer the question in full from established biology, "
    "citing the evidence where it applies and simply stating the rest. Do not "
    "comment on what the evidence does or does not contain."
)

#: Completeness reminder — a question that asks for a count must deliver it.
#:
#: The budget clause is not style advice. An answer is capped at ``num_predict``
#: tokens, and a guided explanation that spends it on the prerequisite, the
#: analogy, and a leisurely simple explanation gets cut off partway through the
#: mechanism. Measured: a DNA replication answer ran to 5,513 characters and
#: was truncated before it ever named primase, the lagging strand, or Okazaki
#: fragments — the substance of the question. Scaffolding is worth having, but
#: not at the cost of the thing being taught.
COMPLETENESS = (
    "Cover every part of the question. If it asks for a specific number of "
    "items, give exactly that many, each named explicitly. If it names two "
    "things to compare, cover both.\n"
    "Budget your length: keep the prerequisite, the analogy, and the "
    "misconception to two or three sentences each, and spend most of the answer "
    "on the mechanism and the named structures, enzymes, and stages it involves. "
    "Never leave the mechanism half-finished in order to fit in scaffolding.\n"
    "The requested format organises your answer; it does not limit it. Say "
    "everything you would have said if no format had been asked for, and every "
    "component you would name if no passages had been supplied. A section "
    "heading is not a quota."
)

#: Revision must be additive. A revision that deletes correct content to satisfy
#: a grounding complaint scores worse than the draft it replaced.
REVISION_HEADER = (
    "Revise the previous answer to fix these specific problems. Keep everything "
    "that was correct — correct and add, never delete content that answers the "
    "question. Return one clean answer, not the draft plus an addendum, and do "
    "not repeat paragraphs:"
)
FRESH_REVISION_HEADER = (
    "Write a fresh answer to the question, addressing these specific problems "
    "found in the previous attempt. Do not repeat paragraphs:"
)


@dataclass(frozen=True, slots=True)
class Prompt:
    system: str
    user: str

    def as_messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


def format_evidence(evidence: Sequence[Any]) -> str:
    """Number passages for citation, with source and section for context."""

    if not evidence:
        return "(no evidence retrieved)"
    lines: list[str] = []
    for index, item in enumerate(evidence, 1):
        title = getattr(item, "title", "") or ""
        section = getattr(item, "section", None) or ""
        source = getattr(item, "source_id", "") or ""
        header = " / ".join(part for part in (title, section, source) if part)
        text = (getattr(item, "text", "") or "").strip()
        lines.append(f"[{index}] {header}\n{text}")
    return "\n\n".join(lines)


#: Words that appear in retrieved passages without naming anything biological.
#:
#: Ranking is by how many passages contain a term, so function words win on
#: every query — measured, six of twelve slots on "Define homeostasis" went to
#: that, this, from, have, with, through, and the biology the checklist existed
#: to surface never made the cut. The verifier's STOPWORDS covers most of them;
#: the rest are paper-scaffolding nouns and the prepositions it omits.
_GENERIC = frozenset(
    """
    study studies research results result data figure table analysis analyses method methods
    show shows shown found find findings report reported described describe description
    review reviews article paper section chapter introduction conclusion discussion
    also however therefore thus although whereas within between during following
    used using use based including include included various different several many
    such these those their there where when which while more most other another
    high higher low lower large larger small smaller number numbers level levels
    type types form forms part parts case cases example examples time times year years
    important significant associated related specific general common known
    through across along upon among against toward towards without inside outside
    able will just only even much well often usually generally likely possible
    pages access press what whom does note like others rather since still under
    ontology term terms descriptor descriptors catalog summaries entry record
    entrez uniprot refseq pubmed ncbi ensembl omim hgnc pmid doi isbn accession
    thumb jpg png svg file image caption align upright infobox citation
    """.split()
) | _VERIFIER_STOPWORDS

_TERM = re.compile(r"[A-Za-z][A-Za-z0-9'-]{3,}")


def coverage_terms(
    query: str, evidence: Sequence[Any], limit: int = 16, min_passages: int = 2
) -> list[str]:
    """Terms several retrieved passages agree on that the question did not name.

    This is the cheap half of what retrieval is for. Recall is scored on whether
    an answer names the structures, enzymes, and stages that belong to the topic,
    and the measured failure was omission, not error: a complete-looking answer
    on DNA replication that never said "Okazaki fragments". Handing the model the
    vocabulary its own retrieved evidence keeps repeating raises coverage without
    a second generation pass.

    Consensus across passages is the filter that keeps this honest. A term one
    passage happens to use is that passage's topic drift; a term appearing in
    several independently retrieved passages is the topic. The result is a
    suggestion in the prompt, never an instruction to assert anything: the model
    is told to use only what is relevant.
    """

    asked = {token.lower() for token in _TERM.findall(query)}
    passage_count: dict[str, int] = {}
    total_count: dict[str, int] = {}
    for item in evidence:
        text = (getattr(item, "text", "") or "").lower()
        seen: set[str] = set()
        for token in _TERM.findall(text):
            if token in _GENERIC or token in asked or len(token) < 4:
                continue
            seen.add(token)
            total_count[token] = total_count.get(token, 0) + 1
        for token in seen:
            passage_count[token] = passage_count.get(token, 0) + 1

    # Consensus across passages, or heavy repetition inside one: a term a single
    # passage uses three times is that passage's subject, not its drift.
    candidates = [
        term
        for term, count in passage_count.items()
        if count >= min_passages or total_count[term] >= 3
    ]
    candidates.sort(key=lambda term: (-passage_count[term], -total_count[term], term))
    # An earlier version also pulled distinctive terms from the top-ranked
    # passages regardless of consensus. It was never validated end to end and
    # measurably injected source boilerplate ("symbol", "summary", "provided")
    # into the checklist, so it is gone. Consensus is the filter that works.
    return candidates[:limit]


#: Told to the model when the corpus's naming authorities contain no entity by
#: a name the question uses. Deliberately phrased as a search result rather than
#: a verdict: the lexicon is incomplete, and the model must stay free to
#: recognise a real term the corpus happens to file under another title.
UNKNOWN_ENTITY_NOTICE = (
    "A search of this corpus's naming authorities (Gene Ontology, MeSH, "
    "Reactome and the encyclopaedia index, {count:,} entries) found no entity "
    "called {names}. That is evidence, not proof — the index is incomplete and "
    "files some things under other names. Treat it as a prompt to check: if the "
    "term really is not a recognised one, correct the premise instead of "
    "describing it."
)


def build_prompt(
    route: Route,
    evidence: Sequence[Any],
    instructions: Sequence[str] = (),
    coverage_pool: Sequence[Any] = (),
    unknown_entities: Sequence[str] = (),
    previous_answer: str = "",
    profile: str = "standard",
) -> Prompt:
    """Assemble the system and user prompts for one generation call.

    ``coverage_pool`` is the wider pre-rerank candidate set. Only ``evidence``
    is quoted and cited; the pool is used solely to widen the vocabulary
    checklist. Measured on the benchmark subset, 66% of the concepts the bare
    model fails to name are present somewhere in the top-30 retrieved passages,
    but reranking narrows the prompt to 4-10 of them, so most of that signal
    never reached the model. Drawing the checklist from the full pool recovers
    it without putting unvetted passages in front of the learner.
    """

    if profile == "compact":
        return _compact_prompt(route, evidence, instructions, unknown_entities, previous_answer)
    if profile != "standard":
        raise ValueError(f"Unknown prompt profile: {profile}")

    level = LearnerLevel(route.learner_level.label)
    mode = TeachingMode(route.teaching_mode.label)

    parts: list[str] = [f"Question: {route.query}", ""]
    parts.append(f"Learner level: {level}. {LEVEL_GUIDANCE.get(level, '')}")
    parts.append(f"Subdomain: {route.subdomain.label}.")
    parts.append("")
    parts.append(f"Teaching mode: {mode}.")
    parts.extend(MODE_STRUCTURE.get(mode, ()))
    parts.append("")

    parts.append(COMPLETENESS)
    parts.append("")

    if unknown_entities:
        from ..verification.ontology import load_lexicon

        names = ", ".join(f"'{name}'" for name in unknown_entities)
        parts.append(
            UNKNOWN_ENTITY_NOTICE.format(count=len(load_lexicon()), names=names)
        )
        parts.append("")

    if route.needs_retrieval:
        parts.append("Evidence:")
        parts.append(format_evidence(evidence))
        parts.append("")
        terms = coverage_terms(route.query, coverage_pool or evidence)
        if terms:
            parts.append(
                "Terms the retrieved passages repeatedly use: "
                + ", ".join(terms)
                + ". Cover the ones that genuinely belong in the answer, and "
                "ignore the rest — this is a checklist of vocabulary, not a "
                "list of claims to make."
            )
            parts.append("")
        parts.append(EVIDENCE_POLICY)
    else:
        parts.append("Answer from established textbook knowledge; no sources were retrieved.")

    if instructions:
        parts.append("")
        if previous_answer:
            parts.append("Previous answer to revise:")
            parts.append(previous_answer)
            parts.append("")
        parts.append(REVISION_HEADER if previous_answer else FRESH_REVISION_HEADER)
        parts.extend(f"- {item}" for item in instructions)

    return Prompt(system=SYSTEM_PROMPT, user="\n".join(parts))


def _compact_prompt(
    route: Route,
    evidence: Sequence[Any],
    instructions: Sequence[str],
    unknown_entities: Sequence[str],
    previous_answer: str,
) -> Prompt:
    """Bound context for small local models while retaining source attribution."""

    parts = [
        f"Question: {route.query}",
        f"Audience: {route.learner_level.label}.",
    ]
    if route.teaching_mode.label in ("socratic", "teach_back"):
        parts.extend(MODE_STRUCTURE[TeachingMode(route.teaching_mode.label)])
    else:
        parts.append(
            "Use short bullets, with one or two sentences each. For comparisons, "
            "use one bullet per item covering the requested attributes. Put process "
            "steps in order; cover every requested part before adding examples."
        )
    parts.append(
        "Use inline [n] beside claims actually supported by the numbered sources. "
        "Do not append source excerpts, source metadata, the old draft or feedback. "
        "Avoid introductions, repeated summaries and unrequested numerical examples."
    )
    if instructions:
        parts.append("Corrections / constraints:\n" + "\n".join(f"- {x}" for x in instructions))
    if previous_answer:
        parts.append("Previous draft to correct, not repeat:\n" + previous_answer)
    if unknown_entities:
        parts.append(
            "Possibly unrecognized names: " + ", ".join(unknown_entities)
            + ". Check them before accepting the premise."
        )
    if route.needs_retrieval:
        parts.append("Relevant source excerpts (use only where applicable):")
        # Selection owns the budget: preserve the verifier's passages and
        # citation numbering. The external critic has its own excerpt budget.
        parts.append(format_evidence(evidence))
    return Prompt(system=COMPACT_SYSTEM_PROMPT, user="\n\n".join(parts))


def focus_revision_instructions(instructions: Sequence[str], limit: int = 4) -> tuple[str, ...]:
    """Prioritise concrete defects over broad feedback; keep edits intact."""
    def priority(text: str) -> int:
        if text.startswith("Fix the"):
            return 0
        if text.startswith(("Correct this process error", "Correct this terminology error")):
            return 1
        if text.startswith("Correct this claim"):
            return 2
        if text.startswith("Cover the missing concept"):
            return 3
        return 4

    return tuple(sorted(dict.fromkeys(instructions), key=priority)[:limit])
