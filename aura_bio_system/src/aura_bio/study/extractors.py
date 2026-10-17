"""Format dispatch and reproducible source-unit identities."""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

from .schema import Document, Extraction, Limits, StudyError


def unit_id(document: Document, key: str) -> str:
    return hashlib.sha256(f'{document.document_id}:{key}'.encode()).hexdigest()[:32]


def extract_document(path: Path, document: Document, limits: Limits) -> Extraction:
    adapter = {'pdf': 'pdf', 'pptx': 'pptx', 'xlsx': 'xlsx', 'txt': 'text', 'md': 'text', 'png':'image','jpg':'image','jpeg':'image'}[document.kind]
    try:
        result = importlib.import_module(f'.extractors_{adapter}', __package__).extract(path, document, limits)
    except ImportError as exc:
        raise StudyError('missing_dependency', 'Install aura-bio-system[study] for this format.') from exc
    except StudyError:
        raise
    except Exception as exc:
        # Parser diagnostics can contain private source content; return a safe summary.
        raise StudyError('extraction_failed', f'Could not parse this {document.kind.upper()} document ({type(exc).__name__}).') from exc
    if sum(len(unit.text) for unit in result.units) > 10_000_000:
        raise StudyError('limit', 'Extracted text exceeds the 10-million-character safety limit.')
    if not any(unit.text.strip() for unit in result.units) and not result.assets:
        raise StudyError('no_text', 'No usable text was extracted; inspect the original and upload a text-bearing document.')
    return result
