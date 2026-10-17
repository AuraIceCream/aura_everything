"""Source-preserving windows with complete merged-unit provenance.

The offline token count is a Unicode lexical estimate, not model-token exact.
No tokenizer/model is downloaded during ingestion.
"""
import hashlib
import re

from .schema import StudyChunk

_TOKENS = re.compile(r'\w+|[^\w\s]', re.UNICODE)


def chunk_units(units, target_tokens=450, overlap_tokens=60):
    if not 0 <= overlap_tokens < target_tokens:
        raise ValueError('Require 0 <= overlap < target tokens.')
    output, pending, budget, group = [], [], 0, None

    def emit(parts):
        text = '\n\n'.join(unit.text[start:end] for unit, start, end in parts)
        ids = tuple(dict.fromkeys(unit.unit_id for unit, _, _ in parts))
        locations = tuple(dict.fromkeys(loc for unit, _, _ in parts for loc in unit.locators))
        spans = tuple({'unit_id': unit.unit_id, 'start': start, 'end': end,'provenance':unit.provenance,
                       'provenance_details':unit.provenance_details} for unit, start, end in parts)
        digest = hashlib.sha256(repr(spans).encode() + text.encode()).hexdigest()[:32]
        output.append(StudyChunk(digest, parts[0][0].document_id, ids, locations, spans,
                                 text, len(_TOKENS.findall(text)), len(output),parts[0][0].provenance,
                                 {'spans':[{'unit_id':u.unit_id,**u.provenance_details} for u,_,_ in parts]}))

    for unit in units:
        matches = list(_TOKENS.finditer(unit.text))
        if not matches:
            continue
        # The JSON contract, not a lexical estimate, bounds a figure object.
        # Punctuation-heavy labels can exceed any guessed token window. Keep
        # validated (<=64 KiB) descriptions whole; malformed/oversized archives
        # retain the existing bounded-window fallback.
        window = target_tokens
        if unit.provenance=='vlm' and unit.role=='figure_description':
            from .visual.description import validate_description
            from .schema import StudyError
            window=max(target_tokens,3000)
            try:
                validate_description(unit.text)
            except StudyError:
                pass
            else:
                window=max(target_tokens,len(matches))
        # Derived revisions have their own figure, question and trust identity.
        # Merging two interpretations can make the correct new question unusable
        # or import an interpretation made for a different question/crop.
        key = (unit.document_id, unit.breadcrumb, unit.role,unit.provenance,
               unit.locators[0].sheet if unit.locators else None,
               unit.unit_id if unit.provenance!='native_text' else None)
        if pending and (key != group or budget + len(matches) > window):
            emit(pending)
            pending, budget = [], 0
        group = key
        if len(matches) > window:
            for start in range(0, len(matches), window - overlap_tokens):
                end = min(start + window, len(matches))
                emit([(unit, matches[start].start(), matches[end - 1].end())])
                if end == len(matches):
                    break
        else:
            pending.append((unit, 0, len(unit.text)))
            budget += len(matches)
    if pending:
        emit(pending)
    return output
