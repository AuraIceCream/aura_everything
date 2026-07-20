from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from typing import Protocol

from .models import Chunk, Document


HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


class Tokenizer(Protocol):
    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]: ...
    def decode(self, token_ids: list[int], skip_special_tokens: bool = True) -> str: ...


def _sections(text: str) -> list[tuple[str | None, str]]:
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [(None, text)]
    output: list[tuple[str | None, str]] = []
    lead = text[: matches[0].start()].strip()
    if lead:
        output.append((None, lead))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if body:
            output.append((match.group(1).strip(), body))
    return output


def chunk_document(
    document: Document,
    tokenizer: Tokenizer,
    minimum: int,
    target: int,
    maximum: int,
    overlap: int,
) -> Iterator[Chunk]:
    """Create bounded windows while preserving the cleaned source text.

    Fast Hugging Face tokenizers provide character offsets. Those offsets are
    used only to choose boundaries; unlike ``tokenizer.decode``, they do not
    lowercase, respell, or alter punctuation in the stored passage.
    """

    if not (0 <= overlap < target <= maximum):
        raise ValueError("Expected 0 <= overlap < target <= maximum")
    ordinal = 0

    def emit(text: str, section: str | None) -> Chunk:
        nonlocal ordinal
        ordinal += 1
        text = text.strip()
        token_count = len(tokenizer.encode(text, add_special_tokens=False))
        digest = hashlib.sha256(
            f"{document.document_id}\0{ordinal}\0{text}".encode("utf-8")
        ).hexdigest()[:24]
        return Chunk(
            chunk_id=f"chunk:{digest}",
            document_id=document.document_id,
            source_id=document.source_id,
            category=document.category,
            title=document.title,
            text=text,
            token_count=token_count,
            ordinal=ordinal,
            source_path=document.source_path,
            external_id=document.external_id,
            url=document.url,
            license_id=document.license_id,
            section=section or document.section,
            metadata=document.metadata,
        )

    for section, body in _sections(document.text):
        prefix = document.title
        if section and section.casefold() != document.title.casefold():
            prefix += f"\n\n{section}"
        prefix += "\n\n"
        prefix_tokens = len(tokenizer.encode(prefix, add_special_tokens=False))
        body_budget = max(1, target - prefix_tokens)
        body_ids = tokenizer.encode(body, add_special_tokens=False)
        if prefix_tokens + len(body_ids) <= maximum:
            yield emit(prefix + body, section)
            continue

        offsets: list[tuple[int, int]] | None = None
        try:
            encoded = tokenizer(body, add_special_tokens=False, return_offsets_mapping=True)
            offsets = [tuple(pair) for pair in encoded["offset_mapping"]]
        except (TypeError, KeyError, NotImplementedError):
            # The fallback exists for simple/custom tokenizers. Production BGE
            # uses a fast tokenizer and always takes the source-preserving path.
            offsets = None

        step = max(1, body_budget - overlap)
        start = 0
        while start < len(body_ids):
            end = min(start + body_budget, len(body_ids))
            if offsets:
                char_start = offsets[start][0]
                char_end = offsets[end - 1][1]
                while char_start > 0 and not body[char_start - 1].isspace():
                    char_start -= 1
                passage = body[char_start:char_end]
            else:
                passage = tokenizer.decode(body_ids[start:end], skip_special_tokens=True)
            yield emit(prefix + passage, section)
            if end >= len(body_ids):
                break
            proposed = start + step
            # Avoid a tiny final fragment by moving the last full window to the
            # end. It overlaps more, but loses no source text.
            if len(body_ids) - proposed < minimum:
                proposed = max(start + 1, len(body_ids) - body_budget)
            start = proposed
