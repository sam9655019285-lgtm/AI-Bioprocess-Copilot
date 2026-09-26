"""AI process analysis: controlled input -> Gemini -> validated interpretation.

The deterministic layers stay the source of truth: Phase 5 analysis, Phase 7 findings
and (optionally) a Phase 6 scale-up scenario are computed here on the server and only
a curated subset is sent to Gemini. Nothing is written to the database.
"""

import json
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlmodel import Session

from . import gemini_service
from .analysis import ExperimentAnalysis, analyze_experiment
from .anomaly import AnomalyReport, analyze_anomalies
from .db_models import ExperimentRow
from .gemini_service import AIAnalysis, Generator
from .scaleup import ScaleUpRequest, ScaleUpResult, simulate_scale_up

NOTICE = (
    "AI-generated interpretation. Measurements and deterministic findings come from the application; "
    "AI interpretations should be reviewed by a scientist."
)
MAX_POINTS_PER_FINDING = 20

SYSTEM_INSTRUCTION = """You are an AI process-analysis assistant for cell-culture bioprocess development.
Your job is to explain the supplied experimental observations and deterministic analysis findings clearly,
for a scientist or bioprocess engineer reviewing an experiment.

Important rules:
1. Treat supplied measurements and deterministic findings as facts.
2. Do not modify, recalculate, or invent measurements.
3. Do not invent experimental results.
4. Do not invent biological mechanisms as established facts.
5. Clearly distinguish: observed fact (observed_patterns), possible interpretation (possible_interpretations),
   uncertainty (the uncertainty field), and suggested question/next investigation (questions_for_investigation).
6. Do not provide an overall safety score or risk score.
7. Do not claim that a process is safe, unsafe, optimal, or guaranteed.
8. Do not diagnose biological or medical conditions.
9. Do not replace scientist judgment.
10. If information is insufficient, explicitly say so.
11. Use the configured prototype thresholds as application rules, not universal biological limits.
12. When discussing possible causes, use cautious language such as "may be consistent with",
    "could indicate", "one possible interpretation is".
13. Never invent a threshold that was not supplied.
14. Do not recommend changing experimental parameters as though the change is validated.
15. Keep factual measurements separate from interpretation.

Output: JSON matching the provided schema. Arrays may be empty. attention_points should refer to the supplied
deterministic findings (use their type in finding_type). Only fill scale_up_considerations when a scale_up
section is present in the input; it is an illustrative scenario, not a validated prediction.
Quote numbers exactly as supplied, with their units."""


class AIAnalysisRequest(BaseModel):
    scale_up: ScaleUpRequest | None = None


class AIAnalysisResponse(BaseModel):
    experiment_id: str
    provider: str = "Gemini"
    model: str
    generated_at: datetime
    notice: str = NOTICE
    observation_count: int
    finding_count: int
    scale_up_included: bool
    analysis: AIAnalysis


# --- Controlled input ----------------------------------------------------------------

def build_ai_input(analysis: ExperimentAnalysis, anomalies: AnomalyReport, scale_up: ScaleUpResult | None) -> dict:
    """Curated, JSON-serialisable input for Gemini (no internal IDs or database fields)."""
    exp = analysis.experiment
    latest = analysis.latest_observation
    payload = {
        "experiment": {
            "experiment_id": exp.experiment_id,
            "name": exp.name,
            "description": exp.description,
            "scale_liters": exp.scale_liters,
            "data_source": exp.data_source.value,
            "observation_count": analysis.observation_count,
            "culture_start_hours": analysis.culture_start_hours,
            "culture_end_hours": analysis.culture_end_hours,
            "culture_duration_hours": analysis.culture_duration_hours,
        },
        "process_analysis": {
            "parameter_statistics": [
                p.model_dump(include={"parameter", "label", "unit", "count", "start", "final", "minimum",
                                      "maximum", "average", "delta", "start_time_hours", "final_time_hours"})
                for p in analysis.parameters
            ],
            "latest_observation": latest.model_dump(exclude={"id", "recorded_at", "experiment_id"}) if latest else None,
            "data_coverage": analysis.data_quality.model_dump(),
            "factual_summary": analysis.summary,
        },
        "anomaly_detection": {
            "counts": anomalies.counts.model_dump(),
            "summary": anomalies.summary,
            "findings": [
                {
                    **f.model_dump(exclude={"experiment_id", "points"}),
                    "points": [p.model_dump() for p in f.points[:MAX_POINTS_PER_FINDING]],
                    "point_count": len(f.points),
                }
                for f in anomalies.findings
            ],
            "monitoring_configuration": anomalies.configuration.model_dump(),
        },
    }
    if exp.data_source.value == "simulated":
        payload["experiment"]["note"] = "Simulated data generated by software, not laboratory measurements."
    if scale_up is not None:
        payload["scale_up"] = scale_up.model_dump(
            include={"label", "disclaimer", "target_scale_liters", "scale_factor", "volume_increase_liters",
                     "parameters", "gas_flow", "feed", "agitation", "summary", "considerations"}
        ) | {"source_scale_liters": scale_up.source.scale_liters}
    return payload


def build_prompt(payload: dict) -> str:
    return (
        "Analyse the following experiment data. Everything below was produced by the application's "
        "deterministic analysis and is to be treated as fact.\n\n"
        + json.dumps(payload, indent=2, default=str, ensure_ascii=False)
    )


# --- Orchestration --------------------------------------------------------------------

def run_ai_analysis(
    session: Session,
    row: ExperimentRow,
    request: AIAnalysisRequest,
    generate: Generator = gemini_service.gemini_generate,
) -> AIAnalysisResponse:
    analysis = analyze_experiment(session, row)
    anomalies = analyze_anomalies(session, row)
    scale_up = simulate_scale_up(session, row, request.scale_up) if request.scale_up else None
    payload = build_ai_input(analysis, anomalies, scale_up)

    result = gemini_service.generate_analysis(SYSTEM_INSTRUCTION, build_prompt(payload), generate)
    if scale_up is None:
        result.scale_up_considerations = []  # only meaningful when a scenario was supplied
    return AIAnalysisResponse(
        experiment_id=row.experiment_id,
        model=gemini_service.model_name(),
        generated_at=datetime.now(timezone.utc),
        observation_count=analysis.observation_count,
        finding_count=anomalies.finding_count,
        scale_up_included=scale_up is not None,
        analysis=result,
    )
