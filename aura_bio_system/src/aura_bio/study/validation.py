"""Fail closed on paths, signatures, OOXML containers and unsafe XML."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from .schema import Limits, StudyError

_ID = re.compile(r'^[a-f0-9]{32}$')
_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)


def validate_id(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise StudyError('invalid_id', 'Expected a generated study-material ID.')
    return value


def validate_filename(filename: str) -> str:
    if (not filename or len(filename) > 240 or filename.endswith((' ', '.'))
            or any(c in filename for c in '/\\:<>"|?*')
            or any(ord(c) < 32 for c in filename) or _RESERVED.match(filename)):
        raise StudyError('invalid_filename', 'Use a plain filename without paths or reserved names.')
    kind = Path(filename).suffix.lower().lstrip('.')
    if kind not in {'pdf', 'pptx', 'xlsx', 'txt', 'md', 'markdown', 'png', 'jpg', 'jpeg'}:
        raise StudyError('unsupported_format', 'Supported: PDF, PPTX, XLSX, TXT and Markdown; no macros.')
    return 'md' if kind == 'markdown' else kind


def contained(root: Path, *parts: str) -> Path:
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise StudyError('unsafe_path', 'Study path leaves its storage root.')
    # Reparse points within the root can alias another pack, not just escape it.
    cursor = root
    for component in ('', *parts):
        cursor = cursor / component
        if cursor.is_symlink() or (hasattr(cursor, 'is_junction') and cursor.is_junction()):
            raise StudyError('unsafe_path', 'Study-owned paths must not contain symlinks or junctions.')
    return target


def validate_container(path: Path, kind: str, limits: Limits) -> None:
    with path.open('rb') as handle:
        signature = handle.read(1024)
    if kind == 'pdf':
        if b'%PDF-' not in signature:
            raise StudyError('invalid_container', 'The file is not a PDF.')
    elif kind in {'png', 'jpg', 'jpeg'}:
        from .visual.assets import inspect_bytes
        inspect_bytes(path.read_bytes(), limits, expected_format='PNG' if kind == 'png' else 'JPEG')
    elif kind in {'pptx', 'xlsx'}:
        if not zipfile.is_zipfile(path):
            raise StudyError('invalid_container', 'The file is not an Office Open XML container.')
        try:
            from defusedxml.ElementTree import iterparse
        except ImportError as exc:
            raise StudyError('missing_dependency', 'Install aura-bio-system[study] for safe Office parsing.') from exc
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                names = [item.filename for item in members]
                required = 'ppt/presentation.xml' if kind == 'pptx' else 'xl/workbook.xml'
                if '[Content_Types].xml' not in names or required not in names:
                    raise StudyError('invalid_container', 'Missing required Office document parts.')
                if len(names) != len(set(names)) or len(names) > 50000:
                    raise StudyError('invalid_container', 'Duplicate or excessive archive entries.')
                if sum(item.file_size for item in members) > limits.max_expanded_bytes:
                    raise StudyError('limit', 'Expanded Office content exceeds the configured limit.')
                for item in members:
                    name = item.filename.lower()
                    if (name.startswith(('/', '\\')) or '..' in name.replace('\\', '/').split('/')
                            or ':' in name or item.flag_bits & 1 or 'vbaproject' in name):
                        raise StudyError('invalid_container', 'Unsafe, encrypted or macro-enabled Office container.')
                    if name.endswith(('.xml', '.rels')):
                        with archive.open(item) as stream:
                            for _, element in iterparse(stream, events=('end',), forbid_dtd=True):
                                if any('macroenabled' in str(value).lower() for value in element.attrib.values()):
                                    raise StudyError('invalid_container', 'Macro-enabled Office content is unsupported.')
                                element.clear()
        except StudyError:
            raise
        except Exception as exc:
            raise StudyError('invalid_container', 'Malformed or unsafe Office XML/archive.') from exc
    elif b'\x00' in signature:
        raise StudyError('invalid_encoding', 'Text must be UTF-8, not binary/UTF-16.')
