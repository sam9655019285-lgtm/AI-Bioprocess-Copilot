"""Descriptive process analysis of a stored experiment.

Only describes what the stored observations contain (ranges, start/final values,
averages, time coverage). It makes no judgements about process quality, anomalies,
risk or scale-up; those belong to later phases.
"""

from math import fsum

from pydantic import BaseModel
from sqlmodel import Session

from . import repository as repo
from .db_models import ExperimentRow
from .models import ExperimentRead, Observation, ObservationRead

# Numeric process parameters analysed, with display precision (formatting only;
# calculations are never rounded).
PARAMETER_DECIMALS = {
    "temperature_c": 2,
    "ph": 2,
    "dissolved_oxygen_percent": 1,
    "agitation_rpm": 0,
    "cell_density": 2,
    "feed_rate": 2,
    "nutrient_concentration": 2,
    "aeration_rate": 3,
}
# Described as "changed from start to final" rather than "ranged from min to max".
TRENDING_PARAMETERS = {"cell_density", "nutrient_concentration"}
MIN_POINTS_FOR_TRENDS = 2


class ParameterSummary(BaseModel):
    parameter: str
    label: str
    unit: str | None
    required: bool
    decimals: int
    count: int  # observations with a value for this parameter
    start: float
    final: float
    minimum: float
    maximum: float
    average: float
    delta: float  # final - start
    start_time_hours: float
    final_time_hours: float


class MissingValues(BaseModel):
    parameter: str
    label: str
    missing: int  # observations without a value


class DataQuality(BaseModel):
    observation_count: int
    distinct_time_points: int
    duplicate_time_points: int  # observations sharing a culture time with an earlier one
    smallest_interval_hours: float | None
    largest_interval_hours: float | None
    missing_values: list[MissingValues]  # per optional parameter
    enough_for_trends: bool


class ExperimentAnalysis(BaseModel):
    experiment: ExperimentRead
    observation_count: int
    culture_start_hours: float | None
    culture_end_hours: float | None
    culture_duration_hours: float | None
    latest_observation: ObservationRead | None
    parameters: list[ParameterSummary]  # only parameters with at least one value
    data_quality: DataQuality
    summary: list[str]
    observations: list[ObservationRead]  # chronological, for charting


def _fmt(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _with_unit(text: str, unit: str | None) -> str:
    return f"{text} {unit}" if unit else text


def _sentence(text: str) -> str:
    # Units such as "% air sat." already end with a full stop.
    return text if text.endswith(".") else text + "."


def summarize_parameter(name: str, observations: list[Observation]) -> ParameterSummary | None:
    """Statistics over the observations that have a value; None if none do."""
    points = [(o.culture_time_hours, getattr(o, name)) for o in observations if getattr(o, name) is not None]
    if not points:
        return None
    values = [v for _, v in points]
    field = Observation.model_fields[name]
    (start_time, start), (final_time, final) = points[0], points[-1]
    return ParameterSummary(
        parameter=name,
        label=field.title or name,
        unit=(field.json_schema_extra or {}).get("unit"),
        required=field.is_required(),
        decimals=PARAMETER_DECIMALS[name],
        count=len(values),
        start=start,
        final=final,
        minimum=min(values),
        maximum=max(values),
        average=fsum(values) / len(values),
        delta=final - start,
        start_time_hours=start_time,
        final_time_hours=final_time,
    )


def assess_data_quality(observations: list[Observation]) -> DataQuality:
    times = [o.culture_time_hours for o in observations]
    distinct = sorted(set(times))
    intervals = [b - a for a, b in zip(distinct, distinct[1:])]
    optional = [n for n in PARAMETER_DECIMALS if not Observation.model_fields[n].is_required()]
    return DataQuality(
        observation_count=len(observations),
        distinct_time_points=len(distinct),
        duplicate_time_points=len(times) - len(distinct),
        smallest_interval_hours=min(intervals) if intervals else None,
        largest_interval_hours=max(intervals) if intervals else None,
        missing_values=[
            MissingValues(
                parameter=n,
                label=Observation.model_fields[n].title or n,
                missing=sum(getattr(o, n) is None for o in observations),
            )
            for n in optional
        ],
        enough_for_trends=len(distinct) >= MIN_POINTS_FOR_TRENDS,
    )


def describe(observations: list[Observation], parameters: list[ParameterSummary]) -> list[str]:
    """Plain factual sentences about the recorded data (no evaluation)."""
    if not observations:
        return ["No observations have been recorded for this experiment yet."]
    start, end = observations[0].culture_time_hours, observations[-1].culture_time_hours
    n = len(observations)
    if n == 1:
        sentences = [f"1 observation was recorded, at {start:g} h culture time."]
    else:
        sentences = [
            f"{n} observations were recorded over {end - start:g} culture hours ({start:g} h to {end:g} h)."
        ]
    for p in parameters:
        fmt = lambda v: _fmt(v, p.decimals)  # noqa: E731
        name = p.label
        if p.count == 1:
            sentence = f"{name} was recorded once: {_with_unit(fmt(p.start), p.unit)}"
        elif p.parameter in TRENDING_PARAMETERS:
            sentence = f"{name} changed from {fmt(p.start)} to {_with_unit(fmt(p.final), p.unit)}"
        elif p.minimum == p.maximum:
            sentence = f"{name} was {_with_unit(fmt(p.minimum), p.unit)} in all {p.count} observations"
        else:
            sentence = f"{name} ranged from {fmt(p.minimum)} to {_with_unit(fmt(p.maximum), p.unit)}"
        sentences.append(_sentence(sentence))
    return sentences


def analyze_experiment(session: Session, row: ExperimentRow) -> ExperimentAnalysis:
    observations = [repo.to_observation_read(r) for r in repo.list_observations(session, row.experiment_id)]
    parameters = [s for name in PARAMETER_DECIMALS if (s := summarize_parameter(name, observations))]
    start = observations[0].culture_time_hours if observations else None
    end = observations[-1].culture_time_hours if observations else None
    return ExperimentAnalysis(
        experiment=repo.to_experiment_read(row, len(observations)),
        observation_count=len(observations),
        culture_start_hours=start,
        culture_end_hours=end,
        culture_duration_hours=None if start is None else end - start,
        latest_observation=observations[-1] if observations else None,
        parameters=parameters,
        data_quality=assess_data_quality(observations),
        summary=describe(observations, parameters),
        observations=observations,
    )
