"""REST endpoints for stored experiments and their observations (SQLite)."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from . import repository as repo
from .analysis import ExperimentAnalysis, analyze_experiment
from .anomaly import AnomalyReport, analyze_anomalies
from .comparison import ComparisonRequest, ExperimentComparison, compare_experiments, require_pair
from .csv_import import CsvFormatError, parse_observations_csv
from .db import get_session
from .db_models import ExperimentRow
from .experiments import read_csv_upload
from .models import (
    DataSource,
    DeleteResult,
    ExperimentCreate,
    ExperimentRead,
    Observation,
    ObservationCreate,
    ObservationRead,
    SavedObservationResponse,
    SavedUploadResult,
)

router = APIRouter(prefix="/api/experiments", tags=["stored experiments"])


def _require_experiment(session: Session, experiment_id: str) -> ExperimentRow:
    row = repo.get_experiment(session, experiment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Experiment '{experiment_id}' not found.")
    return row


def _require_accepts_uploaded_data(row: ExperimentRow) -> None:
    # Keeps sources separate: simulated experiments only ever contain simulator output.
    if row.data_source == DataSource.SIMULATED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Experiment '{row.experiment_id}' is a SIMULATED experiment; it only accepts data from the simulator.",
        )


@router.post("", response_model=ExperimentRead, status_code=status.HTTP_201_CREATED)
def create_experiment(data: ExperimentCreate, session: Session = Depends(get_session)):
    duplicate = HTTPException(status.HTTP_409_CONFLICT, f"Experiment ID '{data.experiment_id}' already exists.")
    if repo.get_experiment(session, data.experiment_id):
        raise duplicate
    try:
        row = repo.create_experiment(session, data)
    except IntegrityError:  # created concurrently
        raise duplicate
    return repo.to_experiment_read(row, 0)


@router.post("/compare", response_model=ExperimentComparison)
def compare(request: ComparisonRequest, session: Session = Depends(get_session)):
    """Deterministic, read-only comparison of two experiments (differences are B − A; no ranking or score)."""
    try:
        row_a, row_b = require_pair(session, request)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return compare_experiments(session, row_a, row_b)


@router.get("", response_model=list[ExperimentRead])
def list_experiments(session: Session = Depends(get_session)):
    """All experiments, newest first, with observation counts."""
    return repo.list_experiments(session)


@router.get("/{experiment_id}", response_model=ExperimentRead)
def get_experiment(experiment_id: str, session: Session = Depends(get_session)):
    row = _require_experiment(session, experiment_id)
    return repo.to_experiment_read(row, repo.count_observations(session, experiment_id))


@router.delete("/{experiment_id}", response_model=DeleteResult)
def delete_experiment(experiment_id: str, session: Session = Depends(get_session)):
    row = _require_experiment(session, experiment_id)
    deleted = repo.delete_experiment(session, row)
    return DeleteResult(
        message=f"Deleted experiment '{experiment_id}' and {deleted} observation(s).",
        experiment_id=experiment_id,
        deleted_observations=deleted,
    )


@router.get("/{experiment_id}/observations", response_model=list[ObservationRead])
def list_observations(
    experiment_id: str,
    limit: int = Query(default=1000, ge=1, le=10_000),
    session: Session = Depends(get_session),
):
    """Observations of one experiment ordered by culture time (first `limit` rows)."""
    _require_experiment(session, experiment_id)
    return [repo.to_observation_read(r) for r in repo.list_observations(session, experiment_id, limit)]


@router.get("/{experiment_id}/analysis", response_model=ExperimentAnalysis)
def get_analysis(experiment_id: str, session: Session = Depends(get_session)):
    """Descriptive analysis of all stored observations (read-only; empty experiments return an empty analysis)."""
    return analyze_experiment(session, _require_experiment(session, experiment_id))


@router.get("/{experiment_id}/anomalies", response_model=AnomalyReport)
def get_anomalies(experiment_id: str, session: Session = Depends(get_session)):
    """Deterministic rule-based findings with evidence (read-only; nothing is stored)."""
    return analyze_anomalies(session, _require_experiment(session, experiment_id))


@router.post(
    "/{experiment_id}/observations",
    response_model=SavedObservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_observation(experiment_id: str, data: ObservationCreate, session: Session = Depends(get_session)):
    row = _require_experiment(session, experiment_id)
    _require_accepts_uploaded_data(row)
    if data.experiment_id not in (None, experiment_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Body experiment_id '{data.experiment_id}' does not match the URL experiment '{experiment_id}'.",
        )
    observation = Observation(**{**data.model_dump(), "experiment_id": experiment_id})
    (saved,) = repo.add_observations(session, experiment_id, [observation])
    count = repo.count_observations(session, experiment_id)
    return SavedObservationResponse(
        message=f"Observation saved to '{experiment_id}' ({count} observation(s) total).",
        observation=repo.to_observation_read(saved),
        observation_count=count,
    )


@router.post("/{experiment_id}/upload", response_model=SavedUploadResult)
async def upload_csv_to_experiment(
    experiment_id: str, file: UploadFile = File(...), session: Session = Depends(get_session)
):
    """Validate a CSV like /api/experiments/upload, then save the valid rows to the experiment."""
    row = _require_experiment(session, experiment_id)
    _require_accepts_uploaded_data(row)
    content = await read_csv_upload(file)
    try:
        result = parse_observations_csv(content, file.filename, target_experiment_id=experiment_id)
    except CsvFormatError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    if result.observations:
        repo.add_observations(session, experiment_id, result.observations)
    return SavedUploadResult(
        **result.model_dump(), experiment_id=experiment_id, saved_count=len(result.observations)
    )
