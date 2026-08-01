"""Select a quality-filtered training corpus from the retrieval chunks.

The retrieval corpus and a training corpus want different things. Retrieval
wants coverage: a UniProt record is excellent evidence for "what does this
protein do" even though it is a structured database dump. Training on that same
record teaches the model to *emit* database dumps, which is the opposite of a
tutor's register.

So this selects for prose quality rather than coverage:

* structured record sources are excluded by default (UniProt, GO, MeSH,
  Reactome) — 5.7M chunks that would dominate any byte budget while teaching
  field-value syntax;
* chunks are scored on information density, prose shape, and length, and the
  weakest are dropped;
* near-duplicates are removed by normalised-text hash, because boilerplate
  ("This article has been cited by...") repeats across millions of papers;
* the budget is filled round-robin across sources so one corpus cannot swamp
  the mix.

Output is JSONL with a ``text`` field, ready for continued pretraining.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .jsonl import read_jsonl

#: Sources whose chunks are structured records rather than explanatory prose.
STRUCTURED_SOURCES = frozenset(
    {"uniprot_sprot", "gene_ontology", "mesh_descriptors", "reactome_summaries"}
)

#: Prose sources, best first. Textbooks are the closest register to a tutor.
PROSE_SOURCES: tuple[str, ...] = (
    "nlm_litarch_biology",
    "biolibretexts_catalog",
    "wikipedia_biology",
    "pmc_oa_comm_xml",
    "pubmed_filtered",
)

#: Target share of the budget per source. Equal round-robin would hand the
#: corpus to PubMed, which has 26M single-chunk abstracts and never exhausts,
#: while textbooks — the register a tutor should learn — contribute least.
#: Research abstracts still earn a place: they carry current terminology.
SOURCE_WEIGHTS: dict[str, float] = {
    "nlm_litarch_biology": 0.26,
    "biolibretexts_catalog": 0.14,
    "wikipedia_biology": 0.30,
    "pmc_oa_comm_xml": 0.20,
    "pubmed_filtered": 0.10,
}

#: Biology content vocabulary. A chunk that teaches biology uses several of
#: these; a biography of a biologist, or a clinical effectiveness review, does
#: not. Being in the "biology" category of a corpus is not the same as
#: containing teachable biology.
_BIOLOGY_TERMS = re.compile(
    r"\b(?:cell|cells|cellular|membrane|protein|proteins|enzyme|enzymes|gene|genes|genetic|"
    r"genome|dna|rna|mrna|chromosome|allele|mutation|nucleus|nuclear|mitochondri\w+|"
    r"chloroplast|ribosome|organelle|tissue|organism|organisms|species|bacteri\w+|virus|viral|"
    r"fungal|photosynthesis|respiration|metabolism|metabolic|glucose|atp|molecule|molecular|"
    r"amino acid|peptide|receptor|hormone|neuron|neural|synap\w+|immune|immunity|antibody|"
    r"antigen|evolution|evolutionary|natural selection|ecosystem|population|phenotype|genotype|"
    r"mitosis|meiosis|transcription|translation|replication|polymerase|substrate|catalys\w+|"
    r"physiolog\w+|anatomic\w+|anatomy|biolog\w+|biochemic\w+|pathway|secretion|diffusion|"
    r"osmosis|homeostasis|embryo\w*|differentiation|apoptosis|plasma|cytoplasm|lipid|"
    r"carbohydrate|nucleotide|codon|plasmid|bacterium|chlorophyll|stomata|xylem|phloem)\b",
    re.I,
)

#: Sections that are encyclopedic metadata about a person or an institution
#: rather than biology content.
_BIOGRAPHICAL = re.compile(
    r"^\s*(?:biography|early life|personal life|career|education|awards?(?: and honou?rs)?|"
    r"distinctions|honou?rs|publications|selected works|bibliography|positions held|"
    r"memberships?|see also|external links|filmography|discography)\b",
    re.I | re.M,
)

#: Clinical evidence-synthesis scaffolding. Real prose, but it teaches review
#: methodology, not biology.
_CLINICAL_REVIEW = re.compile(
    r"\b(?:comparative effectiveness review|systematic review|meta-analys\w+|"
    r"inclusion and exclusion criteria|risk of bias|grade(?:d)? the (?:strength|quality)|"
    r"randomi[sz]ed controlled trial|prisma|cochrane|search strategy|data extraction|"
    r"strength of evidence|key question(?:s)? \d)\b",
    re.I,
)

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")
_SENTENCE_END = re.compile(r"[.!?]")
_WHITESPACE = re.compile(r"\s+")
#: Wrappers that carry no teachable content.
_BOILERPLATE = re.compile(
    r"(?:all rights reserved|creative commons|this article (?:has been|is) cited|"
    r"supplementary (?:material|data)|competing interests|author contributions|"
    r"^\s*(?:references?|bibliography|acknowledge?ments?)\s*$|"
    r"doi:\s*10\.|^\s*fig(?:ure)?\.?\s*\d|^\s*table\s*\d)",
    re.I | re.M,
)


@dataclass(slots=True)
class QualityReport:
    kept: int = 0
    rejected: Counter = field(default_factory=Counter)
    bytes_kept: int = 0
    tokens_kept: int = 0
    by_source: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kept": self.kept,
            "bytes_kept": self.bytes_kept,
            "gib_kept": round(self.bytes_kept / 1024**3, 3),
            "estimated_tokens": self.tokens_kept,
            "rejected": dict(self.rejected.most_common()),
            "by_source": dict(self.by_source.most_common()),
        }


def quality_score(text: str, token_count: int) -> tuple[float, str | None]:
    """Score a chunk's fitness as training prose; return (score, reject_reason).

    Deliberately cheap and explainable — every rejection names its reason so a
    filtered corpus can be audited rather than trusted.
    """

    stripped = text.strip()
    if len(stripped) < 200:
        return 0.0, "too_short"
    if token_count < 60:
        return 0.0, "too_few_tokens"

    words = _WORD.findall(stripped)
    if len(words) < 40:
        return 0.0, "too_few_words"

    alpha = sum(c.isalpha() or c.isspace() for c in stripped) / len(stripped)
    if alpha < 0.70:
        # Tables, sequence dumps, and reference lists land here.
        return 0.0, "low_alpha_ratio"

    sentences = len(_SENTENCE_END.findall(stripped))
    if sentences < 2:
        return 0.0, "not_prose"
    words_per_sentence = len(words) / sentences
    if words_per_sentence < 5 or words_per_sentence > 60:
        return 0.0, "abnormal_sentence_length"

    if _BOILERPLATE.search(stripped):
        return 0.0, "boilerplate"

    unique_ratio = len(set(w.lower() for w in words)) / len(words)
    if unique_ratio < 0.30:
        return 0.0, "repetitive"

    if _BIOGRAPHICAL.search(stripped):
        return 0.0, "biographical"
    if _CLINICAL_REVIEW.search(stripped):
        return 0.0, "clinical_review"

    # Topical relevance: teachable biology uses biology vocabulary repeatedly.
    # Without this, a biologist's biography and a systematic-review methods
    # section both score highly as "good prose" while teaching no biology.
    biology_hits = len(_BIOLOGY_TERMS.findall(stripped))
    biology_density = biology_hits / max(1, len(words))
    if biology_hits < 3 or biology_density < 0.012:
        return 0.0, "off_topic"

    # Reward density and a comfortable teaching length; neither too terse nor a
    # wall of text.
    length_fit = math.exp(-abs(token_count - 320) / 320)
    topical = min(1.0, biology_density / 0.05)
    return (
        round(0.35 * unique_ratio + 0.20 * length_fit + 0.10 * min(alpha, 1.0) + 0.35 * topical, 4),
        None,
    )


def _normalised_hash(text: str) -> str:
    return hashlib.sha256(
        _WHITESPACE.sub(" ", text.strip().lower()).encode("utf-8")
    ).hexdigest()[:16]


def _source_chunks(chunk_root: Path, source_id: str) -> Iterator[dict[str, Any]]:
    for path in sorted((chunk_root / source_id).glob("*.jsonl.gz")):
        yield from read_jsonl(path)


def build_training_corpus(
    chunk_root: Path,
    output_path: Path,
    target_bytes: int,
    sources: tuple[str, ...] = PROSE_SOURCES,
    minimum_score: float = 0.45,
    include_structured: bool = False,
    shard_bytes: int = 256 * 1024 * 1024,
    max_per_document: int = 12,
    qa_fraction: float = 0.0,
    gold_path: Path | None = None,
) -> dict[str, Any]:
    """Fill a byte budget with the best available prose, balanced across sources.

    Sources are consumed round-robin so the budget reflects a deliberate mix
    rather than whichever corpus happens to be largest — PubMed alone could
    fill any budget several times over.
    """

    selected = [s for s in sources if include_structured or s not in STRUCTURED_SOURCES]
    if not selected:
        raise ValueError("No eligible sources selected")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    qa_budget = int(target_bytes * max(0.0, min(1.0, qa_fraction)))
    prose_budget = target_bytes - qa_budget
    report = QualityReport()
    seen: set[str] = set()
    # Caps how much any single document contributes. Reference works repeat a
    # template across thousands of near-identical entries (one radioligand
    # monograph per compound), which would crowd out varied teaching prose.
    per_document: Counter = Counter()
    iterators = {source: _source_chunks(chunk_root, source) for source in selected}
    exhausted: set[str] = set()
    started = time.perf_counter()

    shard_index = 0
    written_in_shard = 0
    handle = gzip.open(_shard_path(output_path, shard_index), "wt", encoding="utf-8", compresslevel=6)
    try:
        # Per-round quota proportional to the target share, so the finished mix
        # matches SOURCE_WEIGHTS instead of source size. A source that runs out
        # simply stops contributing and the rest fill the remaining budget.
        quotas = {
            source: max(4, round(256 * SOURCE_WEIGHTS.get(source, 1 / len(selected))))
            for source in selected
        }
        qa_stats: Counter = Counter()
        if qa_budget:
            writer = _Writer(handle, shard_index, written_in_shard, shard_bytes, output_path)
            _write_qa(chunk_root, gold_path, qa_budget, report, seen, writer, qa_stats)
            handle, shard_index, written_in_shard = writer.handle, writer.index, writer.written
        prose_bytes = 0
        while prose_bytes < prose_budget and len(exhausted) < len(selected):
            for source in selected:
                if source in exhausted or prose_bytes >= prose_budget:
                    continue
                for _ in range(quotas[source]):
                    try:
                        row = next(iterators[source])
                    except StopIteration:
                        exhausted.add(source)
                        break
                    text = row.get("text", "")
                    score, reason = quality_score(text, int(row.get("token_count", 0)))
                    if reason:
                        report.rejected[reason] += 1
                        continue
                    if score < minimum_score:
                        report.rejected["below_threshold"] += 1
                        continue
                    digest = _normalised_hash(text)
                    if digest in seen:
                        report.rejected["duplicate"] += 1
                        continue
                    document_id = row.get("document_id") or row.get("title", "")
                    if per_document[document_id] >= max_per_document:
                        report.rejected["document_cap"] += 1
                        continue
                    seen.add(digest)
                    per_document[document_id] += 1

                    record = json.dumps(
                        {
                            "text": text,
                            "source_id": row.get("source_id"),
                            "title": row.get("title"),
                            "chunk_id": row.get("chunk_id"),
                            "quality": score,
                        },
                        ensure_ascii=False,
                    )
                    handle.write(record + "\n")
                    size = len(text.encode("utf-8"))
                    report.kept += 1
                    report.bytes_kept += size
                    report.tokens_kept += int(row.get("token_count", 0))
                    report.by_source[source] += 1
                    prose_bytes += size
                    written_in_shard += size
                    if written_in_shard >= shard_bytes:
                        handle.close()
                        shard_index += 1
                        written_in_shard = 0
                        handle = gzip.open(
                            _shard_path(output_path, shard_index), "wt",
                            encoding="utf-8", compresslevel=6,
                        )
                    if prose_bytes >= prose_budget:
                        break
            if report.kept and report.kept % 20000 < 64:
                print(
                    f"kept={report.kept:,} {report.bytes_kept / 1024**3:.2f} GiB "
                    f"of {target_bytes / 1024**3:.2f}",
                    flush=True,
                )
    finally:
        handle.close()

    summary = report.as_dict() | {
        "output": str(output_path),
        "qa_mix": dict(qa_stats),
        "qa_fraction_requested": qa_fraction,
        "shards": shard_index + 1,
        "target_gib": round(target_bytes / 1024**3, 3),
        "sources_requested": list(selected),
        "minimum_score": minimum_score,
        "elapsed_seconds": round(time.perf_counter() - started, 1),
        "note": (
            "Text bytes, not compressed size. Estimated tokens assume the "
            "measured ~4.1 chars/token for this corpus."
        ),
    }
    manifest = output_path.with_suffix(".manifest.json")
    manifest.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _shard_path(base: Path, index: int) -> Path:
    return base.with_name(f"{base.stem}-{index:03d}.jsonl.gz")


@dataclass(slots=True)
class _Writer:
    """Shard-rotating writer shared by the QA and prose passes."""

    handle: Any
    index: int
    written: int
    shard_bytes: int
    base: Path

    def write(self, record: str, size: int) -> None:
        self.handle.write(record + "\n")
        self.written += size
        if self.written >= self.shard_bytes:
            self.handle.close()
            self.index += 1
            self.written = 0
            self.handle = gzip.open(
                _shard_path(self.base, self.index), "wt", encoding="utf-8", compresslevel=6
            )


def _write_qa(
    chunk_root: Path,
    gold_path: Path | None,
    budget: int,
    report: QualityReport,
    seen: set[str],
    writer: _Writer,
    stats: Counter,
) -> None:
    """Fill the QA budget, real supervision first, templates only to top up.

    Real QA is scarce — roughly a thousand PubMedQA items and whatever the gold
    set holds — so templates make up the rest. They are written last and marked,
    so a training run can down-weight or drop them.
    """

    from .qa_data import format_record, gold_pairs, pubmedqa_pairs, template_pair

    written = 0

    def emit(pair: dict[str, Any]) -> bool:
        nonlocal written
        text = format_record(pair)
        digest = _normalised_hash(text)
        if digest in seen:
            report.rejected["duplicate"] += 1
            return False
        seen.add(digest)
        size = len(text.encode("utf-8"))
        writer.write(
            json.dumps(
                {"text": text, "kind": pair["kind"], "question": pair["question"],
                 "source_id": pair.get("source_id", pair["kind"])},
                ensure_ascii=False,
            ),
            size,
        )
        written += size
        report.kept += 1
        report.bytes_kept += size
        report.tokens_kept += max(1, size // 4)
        stats[pair["kind"]] += 1
        return True

    for pair in gold_pairs(gold_path) if gold_path else ():
        if written >= budget:
            return
        emit(pair)
    for pair in pubmedqa_pairs(chunk_root):
        if written >= budget:
            return
        emit(pair)

    # Top up from prose chunks whose heading yields a natural question. Sources
    # are interleaved, not walked in turn: NLM LitArch never exhausts, and
    # taking it first filled 89% of the templates with GeneReviews clinical
    # entries while Wikipedia and the textbooks barely contributed.
    template_sources = ("wikipedia_biology", "biolibretexts_catalog", "nlm_litarch_biology")
    template_quota = {"wikipedia_biology": 24, "biolibretexts_catalog": 12, "nlm_litarch_biology": 8}
    streams = {source: _source_chunks(chunk_root, source) for source in template_sources}
    drained: set[str] = set()
    # Cap questions per document. When a document's sections are all generic,
    # every chunk falls back to the same title question ("what is dyt-gnal…"),
    # and a reference work with a fixed template would emit it a dozen times.
    per_title: Counter = Counter()
    max_per_title = 3
    while written < budget and len(drained) < len(template_sources):
        for source in template_sources:
            if source in drained or written >= budget:
                continue
            for _ in range(template_quota[source]):
                try:
                    row = next(streams[source])
                except StopIteration:
                    drained.add(source)
                    break
                score, reason = quality_score(row.get("text", ""), int(row.get("token_count", 0)))
                if reason or score < 0.45:
                    continue
                pair = template_pair(row)
                if pair:
                    key = row.get("document_id") or row.get("title", "")
                    if per_title[key] >= max_per_title:
                        report.rejected["template_document_cap"] += 1
                    elif emit(pair):
                        per_title[key] += 1
                if written >= budget:
                    break
