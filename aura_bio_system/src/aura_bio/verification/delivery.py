"""Conservative delivery checks, separate from factual verification."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .schema import Issue


def check_answer_delivery(answer: str, evidence: Sequence[Any],
                          generation: Mapping[str, Any], query: str = "") -> list[Issue]:
    """Flag incomplete output and long source dumps; never rewrite an answer.

    Source echo requires an internal-style heading AND a long verbatim prefix
    of supplied evidence. Ordinary definitions, citations and requested quotes
    do not qualify. This intentionally does not detect paraphrased context dumps.
    """
    issues = []
    if generation.get("done_reason") == "length":
        issues.append(Issue(
            "generation", "truncated_answer",
            "The output budget was exhausted. Return a shorter complete answer; "
            "cover requested parts first and omit repetition and source excerpts.", "error"))

    quote_request = re.search(r"\b(?:quote|verbatim|(?:show|provide|give|copy|include)\s+"
                              r"(?:me\s+)?(?:the\s+|a\s+|an\s+)?(?:source\s+)?excerpts?)\b", query, re.I)
    no_quote = re.search(r"\b(?:do not|don't|without|avoid|never)\s+(?:\w+\s+){0,2}"
                        r"(?:quote|quoting|verbatim|excerpts?)\b", query, re.I)
    if quote_request and not no_quote:
        return issues

    # Strip only heading decoration; do not treat prose mentioning evidence as
    # an internal heading. Require substantial copied body after that heading.
    header = re.compile(r"(?:relevant source excerpts(?:\s*\([^)]*\))?|"
                        r"numbered evidence[^:]*|source excerpts|evidence)", re.I)
    lines = answer.splitlines()
    for index, line in enumerate(lines):
        if not header.fullmatch(line.strip(" \t#*:")):
            continue
        body = " ".join("\n".join(lines[index + 1:]).casefold().split())
        for passage in evidence:
            source = " ".join((getattr(passage, "text", "") or "").casefold().split())
            if len(source) >= 180 and source[:180] in body:
                issues.append(Issue(
                    "generation", "source_context_echo",
                    "A long source excerpt was copied under an internal context heading. "
                    "Remove the source dump; explain the requested facts concisely "
                    "with supported inline citations.", "error"))
                return issues
    return issues
