"""Scale-up scenario endpoint (read-only; illustrative calculations in scaleup.py)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from . import repository as repo
from .db import get_session
from .scaleup import ScaleUpError, ScaleUpRequest, ScaleUpResult, simulate_scale_up

router = APIRouter(prefix="/api/scale-up", tags=["scale-up"])


@router.post("/simulate", response_model=ScaleUpResult)
def simulate(request: ScaleUpRequest, session: Session = Depends(get_session)):
    """Compare a stored source experiment with a user-defined target-scale scenario. Writes nothing."""
    row = repo.get_experiment(session, request.source_experiment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Experiment '{request.source_experiment_id}' not found.")
    try:
        return simulate_scale_up(session, row, request)
    except ScaleUpError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
