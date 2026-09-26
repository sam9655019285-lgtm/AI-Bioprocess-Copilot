"""Deterministic comparison of two stored experiments (read-only).

Built entirely from the existing layers: Phase 5 analysis (statistics, data quality)
and Phase 7 anomaly findings for each experiment. Differences are always B − A;
percentage differences use |A| as the denominator and are omitted when A is zero or
missing. There is no winner, ranking or score. Point-by-point values are compared only
at culture-time points that exist in both experiments (no interpolation).
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel import Session

from . import repository as repo
from .analysis import PARAMETER_DECIMALS, DataQuality, ExperimentAnalysis, ParameterSummary, analyze_experiment
from .anomaly import AnomalyReport, SeverityCounts, analyze_anomalies
from .db_models import ExperimentRow
from .models import DataSource, Observation

METRICS = ["start", "final", "minimum", "maximum", "average", "delta"]
PERCENT_METRICS = {"start", "final", "minimum", "maximum", "average"}  # not for delta (a change of a change)
MAX_FINDINGS_PER_SIDE = 25
MAX_ALIGNED_POINTS = 200
POINT_PARAMETERS = ["temperature_c", "ph", "dissolved_oxygen_percent", "agitation_rpm", "cell_density"]

SCALE_NOTE = (
    "Different working volumes are being compared. Differences may reflect scale-dependent process behavior "
    "and/or differences in operating conditions."
)
SIMULATED_ONE = (
    "One or both experiments contain simulated data. Differences reflect the software-generated dataset and "
    "should not be treated as laboratory measurements."
)
SIMULATED_BOTH = (
    "Both experiments contain simulated data. Differences reflect the software-generated datasets and should "
    "not be treated as laboratory measurements."
)


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    experiment_a_id: str = Field(min_length=1, max_length=100)
    experiment_b_id: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def different_experiments(self):
        if self.experiment_a_id == self.experiment_b_id:
            raise ValueError("Experiment A and Experiment B must be two different experiments.")
        return self


class ExperimentSide(BaseModel):
    experiment_id: str
    name: str
    description: str | None
    scale_liters: float
    data_source: DataSource
    observation_count: int
    culture_start_hours: float | None
    culture_end_hours: float | None
    duration_hours: float | None


class ScaleComparison(BaseModel):
    scale_a_liters: float | None
    scale_b_liters: float | None
    scale_factor_b_over_a: float | None
    same_scale: bool | None
    note: str | None


class MetricDifference(BaseModel):
    a: float | None
    b: float | None
    difference: float | None  # b - a
    percent_difference: float | None  # (b - a) / |a| × 100
    note: str | None = None


class ParameterComparison(BaseModel):
    parameter: str
    label: str
    unit: str | None
    decimals: int
    availability: str  # "both" | "only_a" | "only_b" | "neither"
    count_a: int
    count_b: int
    metrics: dict[str, MetricDifference]  # start, final, minimum, maximum, average, delta
    note: str | None = None


class DataQualityComparison(BaseModel):
    a: DataQuality
    b: DataQuality
    observation_count_difference: int
    duration_difference_hours: float | None


class AlignedPoint(BaseModel):
    culture_time_hours: float
    values: dict[str, MetricDifference]  # per required parameter at this shared time point


class TimeAlignment(BaseModel):
    common_time_points: int
    only_a_time_points: int
    only_b_time_points: int
    identical_time_points: bool
    overlap_start_hours: float | None
    overlap_end_hours: float | None
    aligned_points: list[AlignedPoint]  # shared, non-repeated time points only (capped)
    aligned_points_omitted: int
    note: str


class FindingSummary(BaseModel):
    finding_id: str
    type_label: str
    severity: str
    parameter_label: str | None
    culture_time_hours: float | None
    message: str


class AnomalySide(BaseModel):
    finding_count: int
    counts: SeverityCounts
    by_type: dict[str, int]
    by_parameter: dict[str, int]
    findings: list[FindingSummary]  # most severe first (capped)
    findings_omitted: int


class AnomalyComparison(BaseModel):
    experiment_a: AnomalySide
    experiment_b: AnomalySide


class ExperimentComparison(BaseModel):
    experiment_a: ExperimentSide
    experiment_b: ExperimentSide
    scale: ScaleComparison
    parameters: list[ParameterComparison]
    data_quality: DataQualityComparison
    time_alignment: TimeAlignment
    anomalies: AnomalyComparison
    summary: list[str]
    notices: list[str]
    difference_convention: str = "difference = Experiment B − Experiment A; percent difference = (B − A) / |A| × 100"


# --- building blocks -------------------------------------------------------------------

def _num(value: float, decimals: int = 2) -> str:
    text = f"{value:,.{decimals}f}"
    return "0" if float(text.replace(",", "")) == 0 else text


def _signed(value: float, decimals: int = 2) -> str:
    return ("+" if value > 0 else "") + _num(value, decimals)


def _side(analysis: ExperimentAnalysis) -> ExperimentSide:
    e = analysis.experiment
    return ExperimentSide(
        experiment_id=e.experiment_id, name=e.name, description=e.description, scale_liters=e.scale_liters,
        data_source=e.data_source, observation_count=analysis.observation_count,
        culture_start_hours=analysis.culture_start_hours, culture_end_hours=analysis.culture_end_hours,
        duration_hours=analysis.culture_duration_hours,
    )


def compare_scale(a: float | None, b: float | None) -> ScaleComparison:
    valid = a is not None and b is not None and a > 0 and b > 0
    return ScaleComparison(
        scale_a_liters=a if a is not None and a > 0 else None,
        scale_b_liters=b if b is not None and b > 0 else None,
        scale_factor_b_over_a=b / a if valid else None,
        same_scale=(a == b) if valid else None,
        note=SCALE_NOTE if valid and a != b else None,
    )


def compare_metric(a: float | None, b: float | None, metric: str, label: str) -> MetricDifference:
    if a is None or b is None:
        missing = [side for side, v in (("A", a), ("B", b)) if v is None]
        note = f"Not available: Experiment {' and '.join(missing)} {'has' if len(missing) == 1 else 'have'} no {label} observations."
        return MetricDifference(a=a, b=b, difference=None, percent_difference=None, note=note)
    difference = b - a
    if metric not in PERCENT_METRICS:
        return MetricDifference(a=a, b=b, difference=difference, percent_difference=None)
    if a == 0:
        return MetricDifference(a=a, b=b, difference=difference, percent_difference=None,
                                note="Cannot calculate percentage difference because Experiment A value is zero.")
    return MetricDifference(a=a, b=b, difference=difference, percent_difference=difference / abs(a) * 100)


def compare_parameter(name: str, a: ParameterSummary | None, b: ParameterSummary | None) -> ParameterComparison:
    field = Observation.model_fields[name]
    label = field.title or name
    availability = "both" if a and b else "only_a" if a else "only_b" if b else "neither"
    note = {
        "only_a": f"Experiment B has no {label} observations.",
        "only_b": f"Experiment A has no {label} observations.",
        "neither": f"Neither experiment has {label} observations.",
    }.get(availability)
    return ParameterComparison(
        parameter=name, label=label, unit=(field.json_schema_extra or {}).get("unit"),
        decimals=PARAMETER_DECIMALS[name], availability=availability,
        count_a=a.count if a else 0, count_b=b.count if b else 0,
        metrics={m: compare_metric(getattr(a, m) if a else None, getattr(b, m) if b else None, m, label) for m in METRICS},
        note=note,
    )


def align_time_points(obs_a: list[Observation], obs_b: list[Observation]) -> TimeAlignment:
    times_a = [o.culture_time_hours for o in obs_a]
    times_b = [o.culture_time_hours for o in obs_b]
    set_a, set_b = set(times_a), set(times_b)
    common = sorted(set_a & set_b)
    # Only compare time points that occur exactly once in each experiment (no ambiguity, no interpolation).
    unique_common = [t for t in common if times_a.count(t) == 1 and times_b.count(t) == 1]
    by_time_a = {o.culture_time_hours: o for o in obs_a}
    by_time_b = {o.culture_time_hours: o for o in obs_b}
    aligned = [
        AlignedPoint(
            culture_time_hours=t,
            values={
                p: compare_metric(getattr(by_time_a[t], p), getattr(by_time_b[t], p), "point", Observation.model_fields[p].title)
                for p in POINT_PARAMETERS
            },
        )
        for t in unique_common[:MAX_ALIGNED_POINTS]
    ]
    overlap = (max(min(set_a), min(set_b)), min(max(set_a), max(set_b))) if set_a and set_b else None
    if overlap and overlap[0] > overlap[1]:
        overlap = None
    identical = bool(set_a) and set_a == set_b
    if not set_a or not set_b:
        note = "At least one experiment has no observations, so time points cannot be aligned."
    elif identical:
        note = f"Both experiments were recorded at the same {len(common)} culture-time point(s)."
    elif common:
        note = (f"The experiments share {len(common)} culture-time point(s); only those are compared point by point. "
                "Other comparisons use aggregate statistics.")
    else:
        note = "The experiments share no culture-time points; they are compared by aggregate statistics only."
    return TimeAlignment(
        common_time_points=len(common), only_a_time_points=len(set_a - set_b), only_b_time_points=len(set_b - set_a),
        identical_time_points=identical,
        overlap_start_hours=overlap[0] if overlap else None, overlap_end_hours=overlap[1] if overlap else None,
        aligned_points=aligned, aligned_points_omitted=max(len(unique_common) - MAX_ALIGNED_POINTS, 0), note=note,
    )


def summarize_anomalies(report: AnomalyReport) -> AnomalySide:
    by_type: dict[str, int] = {}
    by_parameter: dict[str, int] = {}
    for f in report.findings:
        by_type[f.type_label] = by_type.get(f.type_label, 0) + 1
        for label in [f.parameter_label] if f.parameter_label else [Observation.model_fields[p].title for p in f.related_parameters]:
            by_parameter[label] = by_parameter.get(label, 0) + 1
    return AnomalySide(
        finding_count=report.finding_count, counts=report.counts, by_type=by_type, by_parameter=by_parameter,
        findings=[
            FindingSummary(finding_id=f.finding_id, type_label=f.type_label, severity=f.severity,
                           parameter_label=f.parameter_label, culture_time_hours=f.culture_time_hours, message=f.message)
            for f in report.findings[:MAX_FINDINGS_PER_SIDE]
        ],
        findings_omitted=max(report.finding_count - MAX_FINDINGS_PER_SIDE, 0),
    )


def build_summary(c: ExperimentComparison) -> list[str]:
    a, b, s = c.experiment_a, c.experiment_b, c.scale
    lines = []
    if s.scale_factor_b_over_a is None:
        lines.append("A scale factor cannot be calculated because a working volume is unavailable.")
    elif s.same_scale:
        lines.append(f"Both experiments used the same working volume ({a.scale_liters:g} L).")
    else:
        factor = f"{s.scale_factor_b_over_a:,.3f}".rstrip("0").rstrip(".")
        lines.append(f"Experiment B used {factor}× the working volume of Experiment A "
                     f"({a.scale_liters:g} L vs {b.scale_liters:g} L).")
    lines.append(f"Experiment B recorded {b.observation_count} observation(s) compared with {a.observation_count} in Experiment A.")
    if a.duration_hours is not None and b.duration_hours is not None:
        lines.append(f"Culture duration: {a.duration_hours:g} h in Experiment A and {b.duration_hours:g} h in Experiment B "
                     f"(difference {b.duration_hours - a.duration_hours:+g} h).")
    for p in c.parameters:
        avg = p.metrics["average"]
        if p.availability == "both" and avg.difference is not None:
            unit = "percentage points" if (p.unit or "").startswith("%") else (p.unit or "")
            lines.append(f"The average {p.label if p.label == 'pH' else p.label.lower()} differed by "
                         f"{_signed(avg.difference, p.decimals)}{' ' + unit if unit else ''} (B − A).")
        elif p.availability in ("only_a", "only_b"):
            lines.append(f"{p.label} was recorded only in Experiment {'A' if p.availability == 'only_a' else 'B'}.")
    an = c.anomalies
    lines.append(f"Experiment A contains {an.experiment_a.finding_count} anomaly finding(s); "
                 f"Experiment B contains {an.experiment_b.finding_count}.")
    t = c.time_alignment
    if t.identical_time_points:
        lines.append(f"The experiments share all {t.common_time_points} culture-time points.")
    elif t.common_time_points:
        lines.append(f"The experiments share {t.common_time_points} culture-time point(s) but do not have the same culture-time coverage.")
    elif a.observation_count and b.observation_count:
        lines.append("The experiments do not share the same culture-time coverage.")
    return lines


# --- entry point -------------------------------------------------------------------------

def compare_experiments(session: Session, row_a: ExperimentRow, row_b: ExperimentRow) -> ExperimentComparison:
    analysis_a, analysis_b = analyze_experiment(session, row_a), analyze_experiment(session, row_b)
    anomalies_a, anomalies_b = analyze_anomalies(session, row_a), analyze_anomalies(session, row_b)
    params_a = {p.parameter: p for p in analysis_a.parameters}
    params_b = {p.parameter: p for p in analysis_b.parameters}
    side_a, side_b = _side(analysis_a), _side(analysis_b)
    duration_diff = (side_b.duration_hours - side_a.duration_hours
                     if side_a.duration_hours is not None and side_b.duration_hours is not None else None)

    sources = [side_a.data_source, side_b.data_source]
    simulated = sources.count(DataSource.SIMULATED)
    scale = compare_scale(row_a.scale_liters, row_b.scale_liters)
    notices = [SIMULATED_BOTH if simulated == 2 else SIMULATED_ONE] if simulated else []
    if scale.note:
        notices.append(scale.note)

    comparison = ExperimentComparison(
        experiment_a=side_a,
        experiment_b=side_b,
        scale=scale,
        parameters=[compare_parameter(n, params_a.get(n), params_b.get(n)) for n in PARAMETER_DECIMALS],
        data_quality=DataQualityComparison(
            a=analysis_a.data_quality, b=analysis_b.data_quality,
            observation_count_difference=side_b.observation_count - side_a.observation_count,
            duration_difference_hours=duration_diff,
        ),
        time_alignment=align_time_points(analysis_a.observations, analysis_b.observations),
        anomalies=AnomalyComparison(experiment_a=summarize_anomalies(anomalies_a), experiment_b=summarize_anomalies(anomalies_b)),
        summary=[],
        notices=notices,
    )
    comparison.summary = build_summary(comparison)
    return comparison


def require_pair(session: Session, request: ComparisonRequest) -> tuple[ExperimentRow, ExperimentRow]:
    """Load both experiments or raise LookupError naming the missing one."""
    rows = []
    for experiment_id in (request.experiment_a_id, request.experiment_b_id):
        row = repo.get_experiment(session, experiment_id)
        if row is None:
            raise LookupError(f"Experiment '{experiment_id}' not found.")
        rows.append(row)
    return rows[0], rows[1]
