"""Optional Gemini interpretation of an already-calculated experiment comparison.

Gemini receives only the curated deterministic comparison (no raw observations and no
point-by-point values) and must not recalculate anything.
"""

import json
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlmodel import Session

from . import gemini_service
from .comparison import ExperimentComparison, compare_experiments
from .db_models import ExperimentRow
from .gemini_service import Generator

NOTICE = (
    "AI-generated interpretation of the deterministic comparison. Numerical values come from the application; "
    "review the interpretation before relying on it."
)

SYSTEM_INSTRUCTION = """You interpret a comparison of two cell-culture experiments (Experiment A and Experiment B)
for a scientist or bioprocess engineer. The comparison was calculated by the application and is the only source
of numerical facts.

Rules:
- Use only the supplied comparison context.
- Do not invent measurements, and do not recalculate values; quote the supplied values and differences exactly, with units.
- Differences are defined as Experiment B minus Experiment A.
- Clearly distinguish observations (what differs) from interpretations (what it might mean).
- Do not claim causation from correlation alone.
- Do not declare an overall winner and do not rank the experiments; describe measurable differences instead.
- Do not use unsupported evaluative terms such as optimal, safe, best, better, superior or more successful.
- Mention uncertainty, including different scales, different culture-time coverage, missing parameters and small numbers of observations.
- Identify process differences that may warrant investigation, framed as investigation points, not commands.
- If the comparison does not contain enough information, say so.
- Do not provide unsafe biological or medical instructions.
- You do not control any bioreactor and must not pretend to.
- Treat simulated data as simulated (software-generated, not laboratory measurements).
- Prototype monitoring ranges behind anomaly findings are application rules, not universal biological limits.

Output JSON matching the schema; arrays may be empty."""


class ComparisonInterpretation(BaseModel):
    overview: str = Field(min_length=1, max_length=4000)
    key_differences: list[str] = Field(max_length=10)
    possible_interpretations: list[str] = Field(max_length=8)
    investigation_points: list[str] = Field(max_length=8)
    uncertainties: list[str] = Field(max_length=8)


class ComparisonInterpretationResponse(BaseModel):
    experiment_a_id: str
    experiment_b_id: str
    provider: str = "Gemini"
    model: str
    generated_at: datetime
    notice: str = NOTICE
    interpretation: ComparisonInterpretation


def build_comparison_context(comparison: ExperimentComparison) -> dict:
    """Curated context: aggregate comparison only - no raw observations, no point-by-point values."""
    context = comparison.model_dump(mode="json")
    alignment = context["time_alignment"]
    alignment.pop("aligned_points")
    alignment.pop("aligned_points_omitted")
    return context


def build_prompt(context: dict) -> str:
    return (
        "COMPARISON CONTEXT (calculated by the application; treat as fact; differences are B − A):\n"
        + json.dumps(context, indent=2, ensure_ascii=False)
    )


def interpret_comparison(
    session: Session, row_a: ExperimentRow, row_b: ExperimentRow, generate: Generator | None = None
) -> ComparisonInterpretationResponse:
    comparison = compare_experiments(session, row_a, row_b)
    prompt = build_prompt(build_comparison_context(comparison))
    interpretation = gemini_service.generate_structured(SYSTEM_INSTRUCTION, prompt, ComparisonInterpretation, generate)
    return ComparisonInterpretationResponse(
        experiment_a_id=row_a.experiment_id,
        experiment_b_id=row_b.experiment_id,
        model=gemini_service.model_name(),
        generated_at=datetime.now(timezone.utc),
        interpretation=interpretation,
    )
