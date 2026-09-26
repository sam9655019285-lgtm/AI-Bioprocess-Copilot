"""Experiment Planning endpoint (Phase 16). Read-only and deterministic; plans are never stored, Gemini is not called."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from . import repository as repo
from .db import get_session
from .planning import ExperimentPlan, PlanRequest, plan_experiment

router = APIRouter(prefix="/api/experiments", tags=["planning"])


@router.post("/{experiment_id}/plan", response_model=ExperimentPlan)
def plan(experiment_id: str, request: PlanRequest | None = None, session: Session = Depends(get_session)):
    """Candidate experiment conditions from simple design rules (no outcome prediction)."""
    row = repo.get_experiment(session, experiment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Experiment '{experiment_id}' not found.")
    return plan_experiment(session, row, request or PlanRequest())
