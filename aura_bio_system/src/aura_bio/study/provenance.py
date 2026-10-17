"""Evidence origin is not a truth score. Independent of any model provider."""
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SourceMethod(StrEnum):
    NATIVE_TEXT = 'native_text'
    OCR = 'ocr'
    VLM = 'vlm'
    USER_ANNOTATION = 'user_annotation'


@dataclass(frozen=True)
class ProvenanceDetails:
    source_unit_id: str | None = None
    asset_id: str | None = None
    figure_id: str | None = None
    revision_id: str | None = None
    checksum: str | None = None
    method_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaimBasis:
    claim_index: int
    supporting_provenance: tuple[dict[str, Any], ...]
    verification_kind: str
    inputs_verified: bool = False


NATIVE_ROLES = {'body', 'title', 'notes', 'table', 'sheet', 'row', 'paragraph', 'heading', 'blank', 'page', 'image'}


def source_method(value, role='body'):
    from .schema import StudyError
    if value is None:
        if role not in NATIVE_ROLES:
            raise StudyError('invalid_provenance', 'Derived evidence is missing its source method; rebuild this index.')
        return SourceMethod.NATIVE_TEXT.value
    try:
        if value=='native_text' and role not in NATIVE_ROLES:
            raise StudyError('invalid_provenance','A derived role cannot masquerade as native text.')
        return SourceMethod(value).value
    except StudyError:
        raise
    except ValueError as exc:
        raise StudyError('invalid_provenance', 'Unknown evidence source method.') from exc
