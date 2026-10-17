"""Private temporary-image HTTP adapters; upload/status never call a model."""
from dataclasses import asdict
from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from .study_packs import attachment_services, private_origin
from ..study.schema import StudyError

router = APIRouter(prefix='/api/v1/study-attachments', dependencies=[Depends(private_origin)])


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=160)


class DeleteRequest(BaseModel):
    confirmation: str


@router.post('', status_code=202)
def upload(file: UploadFile):
    try:
        return attachment_services().upload(file.filename or '', file.file)
    finally:
        file.file.close()


@router.get('/{attachment_id}')
def status(attachment_id: str):
    return attachment_services().status(attachment_id)


@router.post('/{attachment_id}/save')
def save(attachment_id: str, body: SaveRequest):
    return asdict(attachment_services().promote(attachment_id, body.name))


@router.delete('/{attachment_id}')
def remove(attachment_id: str, body: DeleteRequest):
    if body.confirmation != attachment_id:
        raise StudyError('confirmation_required', 'Confirm the exact temporary attachment ID.')
    return asdict(attachment_services().delete(attachment_id))
