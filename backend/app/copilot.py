"""AI Copilot: answers a scientist's question about ONE stored experiment.

Deterministic first: the context is the application's own analysis (Phase 5), anomaly
findings (Phase 7), an optional scale-up scenario (Phase 6, recomputed here) and an
optional earlier AI process analysis (Phase 8, labelled as AI interpretation). Gemini
only interprets that context; it never gets the raw observation history. Nothing is stored.
"""

import json
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from . import gemini_service
from .ai_analysis import build_ai_input
from .analysis import analyze_experiment
from .anomaly import analyze_anomalies
from .db_models import ExperimentRow
from .forecasting import ForecastRequest, forecast_experiment, forecast_summary
from .gemini_service import AIAnalysis, Generator
from .scaleup import ScaleUpRequest, simulate_scale_up

NOTICE = (
    "This Copilot is a decision-support prototype. It does not control a physical bioreactor and does not "
    "replace scientist or process-engineering judgment."
)
MAX_FINDINGS_IN_CONTEXT = 40  # most severe first; the rest are counted, not sent

SYSTEM_INSTRUCTION = """You are the AI Copilot of a cell-culture bioprocess development application.
You answer a scientist's question about ONE experiment, using ONLY the supplied experiment context.
The context was produced by the application's deterministic analysis and is to be treated as fact.

Rules:
- Use only the supplied experiment context. Do not use outside data about this experiment.
- Do not invent measurements, results, thresholds or missing sensor data.
- Do not recalculate values the context already provides (statistics, changes, findings); quote them exactly, with units.
- Clearly distinguish observations (what the data shows) from interpretations (what it might mean).
- Do not claim causation from correlation alone; co-occurring changes are not proof of cause.
- Mention uncertainty where appropriate, including limits of the data (few observations, gaps, missing parameters,
  simulated data).
- If the question cannot be answered from the supplied context, say so plainly and state what information is missing.
- Do not claim that a parameter or process is optimal, safe or unsafe unless the supplied context establishes it.
- Do not provide unsafe biological or medical instructions.
- You do not control any bioreactor and must not pretend to; never phrase output as actions being taken.
- Frame suggestions as points to investigate or check, not as commands or validated parameter changes.
- Prototype monitoring ranges and thresholds are application rules, not universal biological limits.
- Scale-up information, when present, is an illustrative scenario, not a validated prediction.
- A previous AI process analysis, when present, is an earlier AI interpretation, not fact.
- An illustrative process forecast, when present, is a simple model estimate from the application (not a validated
  prediction); interpret it with its assumptions and limitations and do not recalculate it.
- Use concise, scientist-friendly language.

Output JSON matching the schema:
- answer: a direct answer to the question.
- evidence: specific supporting facts from the context (values, times, finding messages).
- uncertainties: what is uncertain or missing for this question.
- suggested_questions: short follow-up questions the scientist could ask next."""


class CopilotAnswer(BaseModel):
    """Structured answer returned by Gemini (validated before use)."""

    answer: str = Field(min_length=1, max_length=6000)
    evidence: list[str] = Field(max_length=12)
    uncertainties: list[str] = Field(max_length=10)
    suggested_questions: list[str] = Field(max_length=6)


class CopilotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=2000)
    scale_up: ScaleUpRequest | None = None
    ai_analysis: AIAnalysis | None = Field(
        default=None, description="Optional earlier Phase 8 AI analysis of this experiment (shown to Gemini as AI interpretation)."
    )
    forecast: ForecastRequest | None = Field(
        default=None, description="Optional forecast settings; the forecast is recomputed here and summarised (Phase 15)."
    )


class CopilotContextInfo(BaseModel):
    observation_count: int
    finding_count: int
    findings_in_context: int
    scale_up_included: bool
    ai_analysis_included: bool


class CopilotResponse(BaseModel):
    experiment_id: str
    provider: str = "Gemini"
    model: str
    generated_at: datetime
    notice: str = NOTICE
    question: str
    answer: str
    evidence: list[str]
    uncertainties: list[str]
    suggested_questions: list[str]
    context: CopilotContextInfo


def build_copilot_context(session: Session, row: ExperimentRow, request: CopilotRequest) -> tuple[dict, CopilotContextInfo]:
    """Bounded, curated context built from the existing deterministic layers."""
    analysis = analyze_experiment(session, row)
    anomalies = analyze_anomalies(session, row)
    scale_up = simulate_scale_up(session, row, request.scale_up) if request.scale_up else None
    context = build_ai_input(analysis, anomalies, scale_up)

    findings = context["anomaly_detection"]["findings"]
    if len(findings) > MAX_FINDINGS_IN_CONTEXT:
        context["anomaly_detection"]["findings"] = findings[:MAX_FINDINGS_IN_CONTEXT]
        context["anomaly_detection"]["findings_omitted"] = len(findings) - MAX_FINDINGS_IN_CONTEXT
        context["anomaly_detection"]["note"] = (
            f"Only the {MAX_FINDINGS_IN_CONTEXT} most severe findings are included; counts cover all findings."
        )
    if request.ai_analysis is not None:
        context["previous_ai_process_analysis"] = {
            "note": "Earlier AI-generated interpretation (Phase 8). Not deterministic fact.",
            **request.ai_analysis.model_dump(),
        }
    if request.forecast is not None:
        context["illustrative_process_forecast"] = forecast_summary(forecast_experiment(session, row, request.forecast))
    info = CopilotContextInfo(
        observation_count=analysis.observation_count,
        finding_count=anomalies.finding_count,
        findings_in_context=len(context["anomaly_detection"]["findings"]),
        scale_up_included=scale_up is not None,
        ai_analysis_included=request.ai_analysis is not None,
    )
    return context, info


def build_prompt(context: dict, message: str) -> str:
    return (
        "EXPERIMENT CONTEXT (from the application's deterministic analysis; treat as fact):\n"
        + json.dumps(context, indent=2, default=str, ensure_ascii=False)
        + "\n\nSCIENTIST'S QUESTION:\n"
        + message
    )


def ask_copilot(session: Session, row: ExperimentRow, request: CopilotRequest, generate: Generator | None = None) -> CopilotResponse:
    context, info = build_copilot_context(session, row, request)
    answer = gemini_service.generate_structured(SYSTEM_INSTRUCTION, build_prompt(context, request.message), CopilotAnswer, generate)
    return CopilotResponse(
        experiment_id=row.experiment_id,
        model=gemini_service.model_name(),
        generated_at=datetime.now(timezone.utc),
        question=request.message,
        **answer.model_dump(),
        context=info,
    )
