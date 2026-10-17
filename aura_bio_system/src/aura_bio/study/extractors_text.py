from pathlib import Path

from .extractors import unit_id
from .schema import Extraction, Locator, StudyError, Unit


def extract(path, document, limits):
    try:
        text = Path(path).read_text(encoding='utf-8-sig')
    except UnicodeError as exc:
        raise StudyError('invalid_encoding', 'Text files must use UTF-8; convert and upload again.') from exc
    lines = text.splitlines()
    units, start, heading = [], 0, document.filename
    for offset in range(1, len(lines) + 1):
        boundary = offset == len(lines) or (document.kind == 'md' and lines[offset].startswith('#'))
        if boundary:
            block = '\n'.join(lines[start:offset])
            if lines[start].startswith('#'):
                heading = lines[start].lstrip('#').strip()
            units.append(Unit(unit_id(document, f'lines:{start + 1}:{offset}'), document.document_id,
                              len(units), 'body', heading, heading, block,
                              (Locator(document.kind, start_line=start + 1, end_line=offset),)))
            start = offset
    if not text.strip():
        raise StudyError('no_text', 'The text document has no usable text.')
    return Extraction(units, [], [], {'units': len(units), 'text_units': len(units)}, 'utf8-v1')
