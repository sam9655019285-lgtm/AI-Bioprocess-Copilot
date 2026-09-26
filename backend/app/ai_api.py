"""AI endpoints (Gemini): process analysis (Phase 8) and Copilot (Phase 9). The API key stays server-side."""

import logging
from functools import partial

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from . import gemini_service
from . import repository as repo
from .ai_analysis import AIAnalysisRequest, AIAnalysisResponse, run_ai_analysis
from .comparison import ComparisonRequest, require_pair
from .comparison_ai import ComparisonInterpretation, ComparisonInterpretationResponse, interpret_comparison
from .copilot import CopilotAnswer, CopilotRequest, CopilotResponse, ask_copilot
from .db import get_session
from .db_models import ExperimentRow
from .gemini_service import GeminiNotConfigured, GeminiProviderError, GeminiResponseError, Generator
from .planning import PlanRequest
from .planning_ai import PlanInterpretation, PlanInterpretationResponse, interpret_plan
from .scaleup import ScaleUpError

router = APIRouter(tags=["ai"])
logger = logging.getLogger(__name__)

NOT_CONFIGURED = (
    "Gemini is not configured on the server. Set GEMINI_API_KEY for the backend and restart it. "
    "Deterministic analysis and anomaly checks remain available."
)


PROVIDER_HINTS = {
    400: "the request was rejected as invalid",
    401: "the API key was rejected",
    403: "the API key is not permitted to use this model or API",
    404: "the configured model was not found",
    429: "rate limit or quota reached (the free tier also has a daily per-model request limit); try again later",
    500: "Gemini internal error; try again shortly",
    503: "Gemini is temporarily overloaded; try again shortly",
}


def _provider_error_message(exc: GeminiProviderError) -> str:
    """Safe description: provider HTTP code + status name only (never the key or raw provider text)."""
    reason = "provider or network error"
    if exc.code:
        reason = f"Gemini {exc.code}{' ' + exc.status if exc.status else ''}"
        if exc.code in PROVIDER_HINTS:
            reason += f": {PROVIDER_HINTS[exc.code]}"
    return (
        f"The Gemini request failed ({reason}). Deterministic analysis and anomaly checks remain available."
    )


def get_generator() -> Generator:
    """The Gemini call; overridden in tests so no real requests are made."""
    return gemini_service.gemini_generate


@router.get("/api/ai/status")
def ai_status():
    """Only whether a Gemini key is configured - never the key or any part of it."""
    return {"configured": gemini_service.is_configured()}


def _load(session: Session, experiment_id: str, scale_up) -> ExperimentRow:
    """Shared checks: experiment exists, scenario belongs to it, Gemini configured."""
    row = repo.get_experiment(session, experiment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Experiment '{experiment_id}' not found.")
    if scale_up and scale_up.source_experiment_id != experiment_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "scale_up.source_experiment_id must match the experiment being analysed.",
        )
    if not gemini_service.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED)
    return row


def _call_gemini(action, what: str):
    """Run an AI action and map every failure to a safe, controlled HTTP error."""
    try:
        return action()
    except HTTPException:
        raise
    except ScaleUpError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except GeminiNotConfigured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED)
    except GeminiProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _provider_error_message(exc))
    except GeminiResponseError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Gemini returned a response that did not match the expected structure, so no {what} is shown. "
            "Please try again.",
        )
    except SQLAlchemyError:
        raise  # handled by the app-wide database error handler (503)
    except Exception:
        logger.exception("Unexpected error while preparing the %s", what)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"An unexpected error occurred while preparing the {what}."
        )


@router.post("/api/experiments/{experiment_id}/ai-analysis", response_model=AIAnalysisResponse)
def ai_analysis(
    experiment_id: str,
    request: AIAnalysisRequest | None = None,
    session: Session = Depends(get_session),
    generate: Generator = Depends(get_generator),
):
    """Gemini interpretation of the deterministic analysis and findings. Nothing is stored."""
    request = request or AIAnalysisRequest()
    row = _load(session, experiment_id, request.scale_up)
    return _call_gemini(lambda: run_ai_analysis(session, row, request, generate), "AI analysis")


def get_copilot_generator() -> Generator:
    """The Gemini call for Copilot answers; overridden in tests so no real requests are made."""
    return partial(gemini_service.gemini_generate, response_model=CopilotAnswer)


@router.post("/api/experiments/{experiment_id}/copilot", response_model=CopilotResponse)
def copilot(
    experiment_id: str,
    request: CopilotRequest,
    session: Session = Depends(get_session),
    generate: Generator = Depends(get_copilot_generator),
):
    """Answer a question about one experiment from its deterministic context. Nothing is stored."""
    row = _load(session, experiment_id, request.scale_up)
    return _call_gemini(lambda: ask_copilot(session, row, request, generate), "Copilot answer")


def get_comparison_generator() -> Generator:
    """The Gemini call for comparison interpretations; overridden in tests."""
    return partial(gemini_service.gemini_generate, response_model=ComparisonInterpretation)


@router.post("/api/experiments/compare/interpret", response_model=ComparisonInterpretationResponse)
def interpret_experiment_comparison(
    request: ComparisonRequest,
    session: Session = Depends(get_session),
    generate: Generator = Depends(get_comparison_generator),
):
    """Optional Gemini interpretation of the deterministic comparison. Nothing is stored."""
    try:
        row_a, row_b = require_pair(session, request)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if not gemini_service.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED)
    return _call_gemini(lambda: interpret_comparison(session, row_a, row_b, generate), "comparison interpretation")


def get_planning_generator() -> Generator:
    """The Gemini call for experiment-plan explanations (Phase 16); overridden in tests."""
    return partial(gemini_service.gemini_generate, response_model=PlanInterpretation)


@router.post("/api/experiments/{experiment_id}/plan/interpret", response_model=PlanInterpretationResponse)
def interpret_experiment_plan(
    experiment_id: str,
    request: PlanRequest,
    session: Session = Depends(get_session),
    generate: Generator = Depends(get_planning_generator),
):
    """Optional Gemini explanation of the deterministic candidate experiments. Nothing is stored."""
    row = _load(session, experiment_id, None)
    return _call_gemini(lambda: interpret_plan(session, row, request, generate), "plan explanation")
