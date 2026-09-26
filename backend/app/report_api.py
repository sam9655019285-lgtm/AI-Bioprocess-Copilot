"""Experiment report endpoints (Phase 11). Reports are generated on demand and never stored."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session

from . import repository as repo
from .db import get_session
from .report import ReportRequest, build_report_data, render_pdf, report_filename
from .scaleup import ScaleUpError

router = APIRouter(prefix="/api/experiments", tags=["reports"])


def _pdf_response(session: Session, experiment_id: str, request: ReportRequest) -> Response:
    row = repo.get_experiment(session, experiment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Experiment '{experiment_id}' not found.")
    try:
        data = build_report_data(session, row, request)
    except (ValueError, ScaleUpError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return Response(
        content=render_pdf(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report_filename(experiment_id)}"'},
    )


@router.get("/{experiment_id}/report", response_class=Response)
def get_report(experiment_id: str, session: Session = Depends(get_session)):
    """Deterministic PDF report (analysis, trends, data quality, findings). Works without Gemini."""
    return _pdf_response(session, experiment_id, ReportRequest())


@router.post("/{experiment_id}/report", response_class=Response)
def post_report(experiment_id: str, request: ReportRequest, session: Session = Depends(get_session)):
    """PDF report with optional sections: a scale-up scenario (recomputed here) and AI Analysis / Copilot
    results received earlier in the session (validated, labelled as AI-generated)."""
    return _pdf_response(session, experiment_id, request)
