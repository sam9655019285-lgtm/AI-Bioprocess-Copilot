"""Experiment data input endpoints: schema, manual observation entry and CSV upload.

Phase 2 is request/response only: observations are validated and returned, not stored.
"""

from typing import get_args

import annotated_types
from fastapi import APIRouter, File, HTTPException, UploadFile, status

from .csv_import import CsvFormatError, parse_observations_csv
from .models import Observation, ObservationResponse, SchemaField, UploadResult

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _schema_fields() -> list[SchemaField]:
    fields = []
    for name, info in Observation.model_fields.items():
        types = get_args(info.annotation) or (info.annotation,)
        extra = info.json_schema_extra or {}
        minimum = next((m.ge for m in info.metadata if isinstance(m, annotated_types.Ge)), None)
        maximum = next((m.le for m in info.metadata if isinstance(m, annotated_types.Le)), None)
        fields.append(SchemaField(
            name=name,
            label=info.title or name,
            type="number" if float in types else "string",
            required=info.is_required(),
            unit=extra.get("unit"),
            description=info.description,
            minimum=minimum,
            maximum=maximum,
        ))
    return fields


@router.get("/schema", response_model=list[SchemaField])
def get_schema():
    """Fields of a bioreactor observation; also the expected CSV columns, in order."""
    return _schema_fields()


@router.post("/observations", response_model=ObservationResponse, status_code=status.HTTP_201_CREATED)
def create_observation(observation: Observation):
    return ObservationResponse(message="Observation accepted.", observation=observation)


async def read_csv_upload(file: UploadFile) -> bytes:
    """Check the file type and size limit; return the raw bytes."""
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only .csv files are supported.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File is larger than 5 MB.")
    return content


@router.post("/upload", response_model=UploadResult)
async def upload_csv(file: UploadFile = File(...)):
    """Validate a CSV without saving it."""
    content = await read_csv_upload(file)
    try:
        return parse_observations_csv(content, file.filename)
    except CsvFormatError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
