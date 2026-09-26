"""Illustrative Process Forecast endpoint (Phase 15). Read-only; forecasts are never stored."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from . import repository as repo
from .db import get_session
from .forecasting import ExperimentForecast, ForecastRequest, forecast_experiment

router = APIRouter(prefix="/api/experiments", tags=["forecasting"])


@router.post("/{experiment_id}/forecast", response_model=ExperimentForecast)
def forecast(experiment_id: str, request: ForecastRequest | None = None, session: Session = Depends(get_session)):
    """Model forecast based on available observations and configurable assumptions (not a validated prediction)."""
    row = repo.get_experiment(session, experiment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Experiment '{experiment_id}' not found.")
    return forecast_experiment(session, row, request or ForecastRequest())
