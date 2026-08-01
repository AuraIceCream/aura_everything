"""Assemble question-answer training data from the corpus.

Three provenances, kept distinguishable in every record because they are not
equally valuable:

* ``pubmedqa`` — 1,000 real expert-labelled research questions with evidence and
  a conclusion. Genuine reasoning supervision, but only a few megabytes exist.
* ``gold`` — benchmark answers that passed both the answer key and corpus
  verification. Highest quality, smallest quantity.
* ``template`` — questions derived structurally from a chunk's title and
  section ("Photosynthesis / Light-dependent reactions" → "What happens during
  the light-dependent reactions of photosynthesis?"). These teach answer
  *format* and grounding, not reasoning; a model cannot learn to reason from a
  question that was mechanically derived from the answer it is paired with.

The ``kind`` field is written to every record so a training run can weight or
exclude template data, and so an evaluation can never mistake it for real
supervision.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

from .jsonl import read_jsonl

QA_SOURCE = "pubmedqa_labeled"

#: Section headings that name a process, mechanism, or structure and therefore
#: convert cleanly into a question. Generic headings ("Introduction",
#: "Results") do not and are skipped.
_GENERIC_SECTIONS = frozenset(
    {
        "introduction", "abstract", "summary", "conclusion", "conclusions",
        "results", "discussion", "methods", "method", "materials and methods",
        "background", "references", "acknowledgements", "overview", "contents",
        "pages 1-5", "see also", "notes", "further reading", "external links",
        # GeneReviews repeats a fixed clinical template across ~1,000 rare
        # diseases. These headings are genetic-counselling scaffolding, not
        # biology a tutor teaches, and they would otherwise generate thousands
        # of near-identical questions.
        "molecular genetic testing", "establishing the diagnosis",
        "risk to family members", "related genetic counseling issues",
        "genetic counseling", "differential diagnosis", "nomenclature",
        "management", "surveillance", "agents/circumstances to avoid",
        "evaluation of relatives at risk", "therapies under investigation",
        "mode of inheritance", "prevalence", "clinical characteristics",
        "chapter notes", "revision history", "resources",
    }
)

_PROCESS_HINT = re.compile(
    r"\b(?:cycle|pathway|process|mechanism|reaction|synthesis|replication|"
    r"transcription|translation|respiration|photosynthesis|division|transport|"
    r"regulation|signalling|signaling|metabolism|response)\b",
    re.I,
)
_STRUCTURE_HINT = re.compile(
    r"\b(?:structure|anatomy|organelle|membrane|composition|components?|parts?)\b", re.I
)


#: Document titles that name a publication *type* rather than a subject.
#: "Systematic Reviews" is a real NLM LitArch title, and it yields the useless
#: question "what is systematic reviews, and why does it matter in biology?"
_GENERIC_TITLE = re.compile(
    r"^(?:systematic|comparative effectiveness|evidence|technology assessment|"
    r"clinical practice|practice guideline|literature)\s+(?:review|reviews|report|"
    r"synthesis|guideline|guidelines|assessment)s?$|"
    r"^(?:review|reviews|reports?|guidelines?|proceedings|abstracts?|appendix|"
    r"supplement|errata|corrigendum|index|glossary|preface|foreword|"
    r"table of contents|about this book|copyright)\b",
    re.I,
)


#: A trailing parenthetical holding surnames, or an edition marker, means the
#: title names a book rather than a concept.
_EDITION = re.compile(r"\b\d(?:st|nd|rd|th)\s+edition\b|\bvol(?:ume)?\.?\s*\d+\b", re.I)
_TRAILING_PAREN = re.compile(r"\(([^)]{2,60})\)\s*$")
_NAME = re.compile(r"^[A-Z][a-z][A-Za-z.'-]*$")


def _is_book_title(title: str) -> bool:
    """True for "Botany (Ha, Morrow, and Algiers)" but not "… (ATP)".

    An all-capital parenthetical is an acronym expansion and belongs to a
    concept; Title-case surnames belong to a textbook's author list.
    """

    if _EDITION.search(title):
        return True
    match = _TRAILING_PAREN.search(title)
    if not match:
        return False
    inner = match.group(1)
    names = [part for part in re.split(r"[,&]|\band\b", inner) if part.strip()]
    return bool(names) and all(_NAME.match(part.strip()) for part in names)


#: Chemical identifiers, catalogue numbers, and accession codes make terrible
#: questions — "what is 1(trans-[123I]iodopropen-2-yl)-4-[...]piperidine?" is a
#: lookup, not a concept a tutor teaches.
def _is_identifier(text: str) -> bool:
    symbols = sum(not (c.isalpha() or c.isspace()) for c in text)
    if symbols / max(1, len(text)) > 0.15:
        return True
    # Bracketed isotopes, long digit runs, and digit-heavy strings generally.
    if re.search(r"\[\d|\d{3,}|\d+[a-z]?-\[|\(\d", text, re.I):
        return True
    return sum(c.isdigit() for c in text) > 3


def _question_for(title: str, section: str | None) -> str | None:
    """Derive a natural question from a chunk's heading, or None."""

    title = (title or "").strip()
    section = (section or "").strip()
    if not title or len(title) > 90 or _is_identifier(title):
        return None
    if _GENERIC_TITLE.match(title):
        return None
    # Textbook titles carry an author list — "Botany (Ha, Morrow, and Algiers)".
    # Asking "what is botany (ha, morrow, and algiers)?" is asking about a book.
    if _is_book_title(title):
        return None
    # The section is quoted in the question too, so it must also be clean.
    if section and _is_identifier(section):
        section = ""
    if section and section.lower() not in _GENERIC_SECTIONS and len(section) <= 70:
        same = section.lower() in title.lower()
        if _PROCESS_HINT.search(section):
            subject = section if same else f"{section} in {title}"
            return f"Explain how {subject.lower()} works."
        if _STRUCTURE_HINT.search(section):
            # "structure of the cell membrane", not "structure in cell membrane".
            subject = section if same else f"{section} of the {title}"
            return f"Describe the {subject.lower()}."
        subject = section if same else f"{section} in {title}"
        return f"Explain {subject.lower()}."
    if _PROCESS_HINT.search(title):
        return f"Explain how {title.lower()} works."
    if _STRUCTURE_HINT.search(title):
        return f"Describe the {title.lower()}."
    return f"What is {title.lower()}, and why does it matter in biology?"


def pubmedqa_pairs(chunk_root: Path) -> Iterator[dict[str, Any]]:
    """Reassemble PubMedQA's Question/Evidence/Answer chunks into QA records."""

    grouped: dict[str, dict[str, Any]] = defaultdict(dict)
    directory = chunk_root / QA_SOURCE
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.jsonl.gz")):
        for row in read_jsonl(path):
            section = (row.get("section") or "").strip().lower()
            if section in ("question", "evidence", "answer"):
                # Strip the repeated title/section preamble the chunker adds.
                text = row["text"]
                marker = row.get("section") or ""
                if marker and marker in text:
                    text = text.split(marker, 1)[1].strip()
                grouped[row["document_id"]][section] = text
                grouped[row["document_id"]]["_meta"] = row.get("metadata", {})
    for document_id, parts in grouped.items():
        question, answer = parts.get("question"), parts.get("answer")
        if not question or not answer or len(answer) < 40:
            continue
        yield {
            "kind": "pubmedqa",
            "question": question.strip(),
            "answer": answer.strip(),
            "evidence": (parts.get("evidence") or "").strip(),
            "decision": (parts.get("_meta") or {}).get("decision"),
            "document_id": document_id,
        }


def gold_pairs(gold_path: Path) -> Iterator[dict[str, Any]]:
    """Read the corpus-verified benchmark answers.

    A missing path is an error rather than an empty iterator: the gold set is
    the highest-quality supervision available, and silently building a corpus
    without it looks identical to success.
    """

    if not gold_path.is_file():
        raise FileNotFoundError(
            f"--gold was given but no file exists at {gold_path}. "
            "Build it with benchmarks/build_gold_set.py, or omit --gold."
        )
    for line in gold_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        yield {
            "kind": "gold",
            "question": row["question"],
            "answer": row["answer"],
            "evidence": "",
            "subdomain": row.get("subdomain"),
            "supporting_chunk_ids": row.get("supporting_chunk_ids", []),
        }


def template_pair(row: dict[str, Any]) -> dict[str, Any] | None:
    """Turn one prose chunk into a QA-formatted record, or None if unsuitable."""

    question = _question_for(row.get("title", ""), row.get("section"))
    if question is None:
        return None
    text = row.get("text", "")
    # Drop the heading preamble the chunker prepends so the answer does not
    # simply restate the question.
    for marker in (row.get("section") or "", row.get("title") or ""):
        if marker and text.startswith(marker):
            text = text[len(marker):].strip()
    if len(text) < 250:
        return None
    return {
        "kind": "template",
        "question": question,
        "answer": text,
        "evidence": "",
        "source_id": row.get("source_id"),
        "chunk_id": row.get("chunk_id"),
    }


def format_record(pair: dict[str, Any]) -> str:
    """Render a QA record as an instruction-tuning text block."""

    parts = [f"### Question\n{pair['question']}"]
    if pair.get("evidence"):
        parts.append(f"\n### Evidence\n{pair['evidence']}")
    parts.append(f"\n### Answer\n{pair['answer']}")
    return "\n".join(parts)
