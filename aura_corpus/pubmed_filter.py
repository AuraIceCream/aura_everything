from __future__ import annotations

import gzip
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _article_record(article: ET.Element, min_abstract_chars: int) -> tuple[dict | None, str]:
    citation = article.find("MedlineCitation")
    data = citation.find("Article") if citation is not None else None
    if citation is None or data is None:
        return None, "malformed"
    pmid = _text(citation.find("PMID"))
    title = _text(data.find("ArticleTitle"))
    abstract_parts = []
    for part in data.findall("Abstract/AbstractText"):
        value = _text(part)
        if not value:
            continue
        label = part.attrib.get("Label") or part.attrib.get("NlmCategory")
        abstract_parts.append(f"{label}: {value}" if label else value)
    abstract = "\n".join(abstract_parts)
    if not pmid or not title:
        return None, "malformed"
    if len(abstract) < min_abstract_chars:
        return None, "short_or_missing_abstract"

    languages = [_text(node).lower() for node in data.findall("Language") if _text(node)]
    if languages and "eng" not in languages:
        return None, "non_english"
    publication_types = [
        _text(node) for node in data.findall("PublicationTypeList/PublicationType") if _text(node)
    ]
    lowered_types = {value.lower() for value in publication_types}
    if "retracted publication" in lowered_types:
        return None, "retracted"
    low_value = {"editorial", "news", "newspaper article", "comment", "letter"}
    if lowered_types and lowered_types <= low_value:
        return None, "low_value_type"

    mesh = []
    for heading in citation.findall("MeshHeadingList/MeshHeading"):
        descriptor = heading.find("DescriptorName")
        name = _text(descriptor)
        if name:
            mesh.append(
                {
                    "name": name,
                    "ui": descriptor.attrib.get("UI") if descriptor is not None else None,
                    "major": descriptor.attrib.get("MajorTopicYN") == "Y" if descriptor is not None else False,
                }
            )
    keywords = sorted(
        {_text(node) for node in citation.findall("KeywordList/Keyword") if _text(node)}
    )
    journal = _text(data.find("Journal/Title"))
    year = _text(data.find("Journal/JournalIssue/PubDate/Year"))
    if not year:
        year = _text(data.find("Journal/JournalIssue/PubDate/MedlineDate"))
    doi = ""
    for identifier in article.findall("PubmedData/ArticleIdList/ArticleId"):
        if identifier.attrib.get("IdType") == "doi":
            doi = _text(identifier)
            break
    return {
        "source_id": "pubmed_baseline",
        "pmid": pmid,
        "doi": doi or None,
        "title": title,
        "abstract": abstract,
        "journal": journal or None,
        "year": year or None,
        "publication_types": publication_types,
        "mesh": mesh,
        "keywords": keywords,
        "language": "eng",
        "license_id": "NLM-PubMed-Terms",
        "license_state": "reviewed_source_terms",
        "retracted": False,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    }, "accepted"


def filter_pubmed_file(
    source: Path,
    destination: Path,
    *,
    min_abstract_chars: int = 300,
) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    counts = {
        "input": 0,
        "accepted": 0,
        "short_or_missing_abstract": 0,
        "non_english": 0,
        "retracted": 0,
        "low_value_type": 0,
        "malformed": 0,
    }
    try:
        with gzip.open(source, "rb") as input_handle, gzip.open(
            temporary, "wt", encoding="utf-8", compresslevel=6
        ) as output_handle:
            for _, article in ET.iterparse(input_handle, events=("end",)):
                if article.tag not in {"PubmedArticle", "PubmedBookArticle"}:
                    continue
                counts["input"] += 1
                record, reason = _article_record(article, min_abstract_chars)
                counts[reason] = counts.get(reason, 0) + 1
                if record is not None:
                    output_handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                    output_handle.write("\n")
                article.clear()
        with gzip.open(temporary, "rb") as check:
            while check.read(1024 * 1024):
                pass
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    counts["input_bytes"] = source.stat().st_size
    counts["output_bytes"] = destination.stat().st_size
    return counts
