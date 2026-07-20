from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import mwparserfromhell
from pypdf import PdfReader

from .config import SourceConfig
from .models import Document


SKIP_XML_TAGS = {"ref-list", "ack", "permissions", "license", "supplementary-material"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _first(root: ET.Element, *names: str) -> str:
    wanted = set(names)
    for node in root.iter():
        if _local(node.tag) in wanted:
            value = _text(node)
            if value:
                return value
    return ""


def _all(root: ET.Element, name: str) -> list[str]:
    return [value for node in root.iter() if _local(node.tag) == name and (value := _text(node))]


def _stable_id(source_id: str, identity: str) -> str:
    digest = hashlib.sha256(f"{source_id}\0{identity}".encode("utf-8")).hexdigest()[:24]
    return f"{source_id}:{digest}"


def _document(
    source: SourceConfig,
    path: Path,
    identity: str,
    title: str,
    text: str,
    **kwargs: Any,
) -> Document:
    return Document(
        document_id=_stable_id(source.id, identity),
        source_id=source.id,
        category=source.category,
        title=title.strip() or path.stem,
        text=text,
        source_path=str(path),
        license_id=source.license_id,
        **kwargs,
    )


def parse_pubmed_jsonl(path: Path, source: SourceConfig) -> Iterator[Document]:
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            pmid = str(row.get("pmid") or "")
            title = row.get("title") or f"PubMed {pmid}"
            abstract = row.get("abstract") or ""
            if not abstract:
                continue
            mesh = row.get("mesh") or []
            yield _document(
                source,
                path,
                pmid or f"{path.name}:{title}",
                title,
                f"## Abstract\n\n{abstract}",
                external_id=pmid or None,
                url=row.get("url"),
                published=str(row.get("year")) if row.get("year") else None,
                metadata={
                    "doi": row.get("doi"),
                    "journal": row.get("journal"),
                    "mesh": mesh,
                    "keywords": row.get("keywords") or [],
                    "publication_types": row.get("publication_types") or [],
                },
            )


def _xml_sections(root: ET.Element) -> str:
    sections: list[str] = []
    abstract = next((node for node in root.iter() if _local(node.tag) == "abstract"), None)
    if abstract is not None and (value := _text(abstract)):
        sections.append(f"## Abstract\n\n{value}")

    body = next((node for node in root.iter() if _local(node.tag) in {"body", "book-body"}), None)
    if body is None:
        body = root
    current_heading = "Content"
    current_paragraphs: list[str] = []
    for node in body.iter():
        tag = _local(node.tag)
        if tag in SKIP_XML_TAGS:
            continue
        if tag == "title":
            value = _text(node)
            if value and value != current_heading:
                if current_paragraphs:
                    sections.append(f"## {current_heading}\n\n" + "\n\n".join(current_paragraphs))
                    current_paragraphs = []
                current_heading = value
        elif tag in {"p", "list-item", "caption"}:
            value = _text(node)
            if value:
                current_paragraphs.append(value)
    if current_paragraphs:
        sections.append(f"## {current_heading}\n\n" + "\n\n".join(current_paragraphs))
    return "\n\n".join(sections)


def _jats_document(root: ET.Element, path: Path, source: SourceConfig, ordinal: int) -> Document:
    external_id = ""
    doi = ""
    for node in root.iter():
        if _local(node.tag) in {"article-id", "book-part-id"}:
            kind = (node.attrib.get("pub-id-type") or node.attrib.get("book-part-id-type") or "").lower()
            value = _text(node)
            if kind in {"pmc", "pmcid", "pmid", "doi"} and value:
                if kind == "doi":
                    doi = value
                elif not external_id or kind in {"pmc", "pmcid"}:
                    external_id = value
    title = _first(root, "article-title", "book-part-title", "title")
    authors: list[str] = []
    for contributor in (node for node in root.iter() if _local(node.tag) in {"contrib", "author"}):
        surname = _first(contributor, "surname")
        given = _first(contributor, "given-names")
        name = " ".join(item for item in (given, surname) if item)
        if name and name not in authors:
            authors.append(name)
    identity = external_id or doi or f"{path}:{ordinal}:{title}"
    return _document(
        source,
        path,
        identity,
        title,
        _xml_sections(root),
        external_id=external_id or None,
        url=f"https://doi.org/{doi}" if doi else None,
        authors=authors[:100],
        published=_first(root, "year") or None,
        metadata={"doi": doi or None},
    )


def parse_jats(path: Path, source: SourceConfig) -> Iterator[Document]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".csv", ".tsv"}:
        yield from parse_delimited_or_text(path, source)
        return
    ordinal = 0
    # PMC batches contain many <article> elements; iterparse releases each one
    # immediately so memory use does not grow with the XML file.
    for _, node in ET.iterparse(path, events=("end",)):
        if _local(node.tag) == "article":
            ordinal += 1
            yield _jats_document(node, path, source, ordinal)
            node.clear()
    if ordinal == 0:
        root = ET.parse(path).getroot()
        yield _jats_document(root, path, source, 0)


def _wiki_sections(wikitext: str) -> str:
    code = mwparserfromhell.parse(wikitext)
    output: list[str] = []
    for section in code.get_sections(include_lead=True, include_headings=True, levels=[2, 3, 4]):
        headings = section.filter_headings()
        heading = headings[0].title.strip_code().strip() if headings else "Introduction"
        if heading.casefold() in {"references", "external links", "see also", "further reading", "notes"}:
            continue
        plain = section.strip_code(normalize=True, collapse=True).strip()
        plain = re.sub(r"\[\d+\]", "", plain)
        if plain:
            output.append(f"## {heading}\n\n{plain}")
    return "\n\n".join(output)


def parse_wikipedia(path: Path, source: SourceConfig) -> Iterator[Document]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    for page in data.get("query", {}).get("pages", []):
        revisions = page.get("revisions") or []
        if not revisions:
            continue
        content = revisions[0].get("slots", {}).get("main", {}).get("content", "")
        page_id = str(page.get("pageid") or page.get("title"))
        yield _document(
            source,
            path,
            page_id,
            page.get("title") or page_id,
            _wiki_sections(content),
            external_id=page_id,
            url=page.get("canonicalurl") or page.get("fullurl"),
            published=revisions[0].get("timestamp"),
            metadata={"revision_id": revisions[0].get("revid"), "page_length": page.get("length")},
        )


def parse_pdf(path: Path, source: SourceConfig) -> Iterator[Document]:
    reader = PdfReader(path, strict=False)
    metadata = reader.metadata or {}
    title = str(metadata.get("/Title") or path.stem)
    # Twenty-five-page units limit damage from poor PDF structure and provide a
    # useful book-level section before token chunking.
    for start in range(0, len(reader.pages), 25):
        end = min(start + 25, len(reader.pages))
        pages = []
        for page_number in range(start, end):
            value = reader.pages[page_number].extract_text() or ""
            if value.strip():
                pages.append(value)
        if pages:
            section = f"Pages {start + 1}-{end}"
            yield _document(
                source,
                path,
                f"{path.name}:{start}",
                title,
                f"## {section}\n\n" + "\n\n".join(pages),
                section=section,
                metadata={"page_start": start + 1, "page_end": end, "page_count": len(reader.pages)},
            )


def parse_mesh(path: Path, source: SourceConfig) -> Iterator[Document]:
    for _, node in ET.iterparse(path, events=("end",)):
        if _local(node.tag) != "DescriptorRecord":
            continue
        external_id = _first(node, "DescriptorUI")
        title = _first(node, "DescriptorName", "String")
        values: list[str] = []
        for tag in ("Annotation", "ScopeNote", "HistoryNote", "Term", "TreeNumber"):
            values.extend(_all(node, tag))
        text = f"## MeSH descriptor\n\n{title}\n\n" + "\n\n".join(dict.fromkeys(values))
        yield _document(source, path, external_id, title, text, external_id=external_id)
        node.clear()


def parse_uniprot(path: Path, source: SourceConfig) -> Iterator[Document]:
    current: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.rstrip() == "//":
                if current:
                    yield _uniprot_record(current, path, source)
                    current = []
            else:
                current.append(line.rstrip())
    if current:
        yield _uniprot_record(current, path, source)


def _uniprot_record(lines: list[str], path: Path, source: SourceConfig) -> Document:
    fields: dict[str, list[str]] = {}
    for line in lines:
        key = line[:2]
        if key.strip():
            fields.setdefault(key, []).append(line[5:].strip())
    accession = (fields.get("AC") or [""])[0].split(";")[0]
    entry = (fields.get("ID") or [accession])[0].split()[0]
    description = " ".join(fields.get("DE", []))
    organism = " ".join(fields.get("OS", []))
    text_parts = [
        f"## Protein\n\n{entry}",
        f"## Description\n\n{description}",
        f"## Organism\n\n{organism}",
        "## Function and comments\n\n" + "\n".join(fields.get("CC", [])),
        "## Cross-references\n\n" + "\n".join(fields.get("DR", [])),
        "## Keywords\n\n" + " ".join(fields.get("KW", [])),
    ]
    return _document(
        source,
        path,
        accession or entry,
        description or entry,
        "\n\n".join(text_parts),
        external_id=accession or None,
        url=f"https://www.uniprot.org/uniprotkb/{accession}" if accession else None,
        metadata={"entry_name": entry, "organism": organism},
    )


def parse_obo(path: Path, source: SourceConfig) -> Iterator[Document]:
    stanza: dict[str, list[str]] = {}
    kind = ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                if kind == "Term" and stanza:
                    yield _obo_term(stanza, path, source)
                kind, stanza = line[1:-1], {}
            elif kind == "Term" and ": " in line:
                key, value = line.split(": ", 1)
                stanza.setdefault(key, []).append(value)
    if kind == "Term" and stanza:
        yield _obo_term(stanza, path, source)


def _obo_term(fields: dict[str, list[str]], path: Path, source: SourceConfig) -> Document:
    external_id = (fields.get("id") or [""])[0]
    title = (fields.get("name") or [external_id])[0]
    definition = " ".join(fields.get("def", []))
    relations = fields.get("is_a", []) + fields.get("relationship", [])
    synonyms = fields.get("synonym", [])
    text = f"## Gene Ontology term\n\n{title}\n\n{definition}"
    if synonyms:
        text += "\n\n## Synonyms\n\n" + "\n".join(synonyms)
    if relations:
        text += "\n\n## Relations\n\n" + "\n".join(relations)
    return _document(source, path, external_id, title, text, external_id=external_id)


def parse_reactome(path: Path, source: SourceConfig) -> Iterator[Document]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            external_id = row.get("Identifier") or ""
            title = row.get("Name") or external_id
            summary = row.get("Summation") or ""
            yield _document(
                source,
                path,
                external_id,
                title,
                f"## Pathway summary\n\n{summary}",
                external_id=external_id,
                url=f"https://reactome.org/content/detail/{external_id}" if external_id else None,
            )


def parse_pubmedqa(path: Path, source: SourceConfig) -> Iterator[Document]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    for pmid, row in data.items():
        question = row.get("QUESTION") or ""
        contexts = row.get("CONTEXTS") or []
        answer = row.get("LONG_ANSWER") or ""
        text = f"## Question\n\n{question}\n\n## Evidence\n\n" + "\n\n".join(contexts)
        if answer:
            text += f"\n\n## Answer\n\n{answer}"
        yield _document(
            source,
            path,
            str(pmid),
            question,
            text,
            external_id=str(pmid),
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            published=str(row.get("YEAR")) if row.get("YEAR") else None,
            metadata={
                "decision": row.get("final_decision"),
                "labels": row.get("LABELS") or [],
                "mesh": row.get("MESHES") or [],
            },
        )


def parse_delimited_or_text(path: Path, source: SourceConfig) -> Iterator[Document]:
    if path.suffix.lower() in {".csv", ".tsv"}:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            for ordinal, row in enumerate(csv.DictReader(handle, delimiter=delimiter), 1):
                values = [f"{key}: {value}" for key, value in row.items() if value]
                if values:
                    yield _document(source, path, f"{path}:{ordinal}", path.stem, "\n".join(values))
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            yield _document(source, path, str(path), path.stem, text)


PARSERS = {
    "pubmed_jsonl": parse_pubmed_jsonl,
    "jats_xml": parse_jats,
    "wikipedia_json": parse_wikipedia,
    "pdf": parse_pdf,
    "mesh_xml": parse_mesh,
    "uniprot_dat": parse_uniprot,
    "obo": parse_obo,
    "reactome_tsv": parse_reactome,
    "pubmedqa_json": parse_pubmedqa,
}


def parse_file(path: Path, source: SourceConfig) -> Iterator[Document]:
    try:
        parser = PARSERS[source.parser]
    except KeyError as exc:
        raise ValueError(f"Unknown parser {source.parser!r} for source {source.id}") from exc
    yield from parser(path, source)

