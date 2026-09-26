"""Transparent, scenario-based scale-up calculations (illustrative only).

Given a stored source experiment and user-chosen target settings, this computes only
quantities that follow directly from definitions:

- scale factor              = target volume / source volume
- gas flow (L/min)          = aeration (vvm) × working volume (L)
- specific feed (mL/h/L)    = feed rate (mL/h) / working volume (L)
- volume-proportional feed  = source feed rate × scale factor (same feed per litre)
- total feed (mL)           = feed rate (mL/h) × baseline culture duration (h), constant rate assumed

It applies no scale-up law: no kLa, P/V, tip speed, Reynolds number, power or
geometry, because the project holds no validated vessel or cell-line data. Source
values are the latest recorded value of each parameter; nothing missing is invented.
Read-only: nothing is written to the database.
"""

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from . import repository as repo
from .analysis import _sentence, summarize_parameter
from .db_models import ExperimentRow
from .models import ExperimentRead, Observation

DISCLAIMER = (
    "These results are illustrative scenario estimates, not validated predictions "
    "for a specific cell line or bioreactor."
)

ENGINEERING_CONSIDERATIONS = [
    "Oxygen transfer (kLa) and CO₂ removal change with vessel size and gassing strategy.",
    "Mixing time and homogeneity (pH, nutrients, dissolved gases) are usually longer at larger scale.",
    "Heat transfer: surface-to-volume ratio falls as volume increases.",
    "Mass transfer of nutrients and feed distribution depend on feed location and mixing.",
    "Shear environment from impellers and bursting bubbles affects cells.",
    "Gas–liquid behaviour: bubble size, hold-up, foaming.",
    "Bioreactor geometry (aspect ratio, baffles, sparger design).",
    "Impeller type, number, diameter and position.",
    "Control-loop performance (pH, DO, temperature) at the new scale.",
]

PRESERVED = "Preserved"  # target equals the source value
SCENARIO = "Scenario setting"  # user-chosen value that differs from, or has no, source value
BASELINE = "Baseline assumption"  # carried over from the source, not predicted
NOT_AVAILABLE = "Not available"


class ScaleUpRequest(BaseModel):
    """Scenario inputs. Omitted (null) targets are reported as not specified, never invented."""

    model_config = ConfigDict(extra="forbid")

    source_experiment_id: str = Field(min_length=1, max_length=100)
    target_scale_liters: float = Field(gt=0, le=1_000_000, allow_inf_nan=False)
    # Same temperature bounds as the simulator's initial conditions.
    target_temperature_c: float | None = Field(default=None, ge=20, le=45, allow_inf_nan=False)
    target_ph: float | None = Field(default=None, ge=0, le=14, allow_inf_nan=False)
    target_dissolved_oxygen_percent: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    target_agitation_rpm: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    target_aeration_vvm: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    target_feed_rate_ml_per_h: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class SourceInfo(BaseModel):
    experiment: ExperimentRead
    scale_liters: float
    observation_count: int
    culture_duration_hours: float | None
    latest_culture_time_hours: float | None


class ParameterComparison(BaseModel):
    parameter: str
    label: str
    unit: str | None
    source: float | None
    source_time_hours: float | None  # culture time of the source value
    target: float | None
    change: float | None  # target - source
    percent_change: float | None
    treatment: str  # PRESERVED | SCENARIO | BASELINE | NOT_AVAILABLE
    validation_note: str


class GasFlow(BaseModel):
    source_vvm: float | None
    target_vvm: float | None
    source_l_per_min: float | None
    target_l_per_min: float | None
    target_l_per_h: float | None
    ratio: float | None  # target / source gas flow


class FeedCalculation(BaseModel):
    source_ml_per_h: float | None
    target_ml_per_h: float | None
    source_ml_per_h_per_l: float | None
    target_ml_per_h_per_l: float | None
    volume_proportional_ml_per_h: float | None  # source feed × scale factor
    baseline_duration_hours: float | None
    target_total_feed_ml: float | None  # target rate × baseline duration


class AgitationComparison(BaseModel):
    source_rpm: float | None
    target_rpm: float | None
    change_rpm: float | None
    note: str = "No agitation scale-up rule is applied; the target is a user-chosen scenario setting."


class ScaleUpResult(BaseModel):
    label: str = "Illustrative simulation"
    disclaimer: str = DISCLAIMER
    source: SourceInfo
    target_scale_liters: float
    scale_factor: float
    volume_increase_liters: float
    parameters: list[ParameterComparison]
    gas_flow: GasFlow
    feed: FeedCalculation
    agitation: AgitationComparison
    summary: list[str]
    considerations: list[str] = ENGINEERING_CONSIDERATIONS


class ScaleUpError(ValueError):
    pass


# parameter -> (request field, default treatment when the target matches, validation note)
COMPARED = {
    "temperature_c": ("target_temperature_c", PRESERVED, "Heat transfer and temperature control at the target scale."),
    "ph": ("target_ph", PRESERVED, "pH control (base addition, CO₂ removal) and mixing at the target scale."),
    "dissolved_oxygen_percent": (
        "target_dissolved_oxygen_percent", PRESERVED, "Oxygen transfer capacity of the target vessel.",
    ),
    "agitation_rpm": ("target_agitation_rpm", SCENARIO, "Mixing, shear and power input depend on vessel and impeller geometry."),
    "aeration_rate": ("target_aeration_vvm", SCENARIO, "Gas–liquid transfer, foaming and CO₂ stripping at the target scale."),
    "feed_rate": ("target_feed_rate_ml_per_h", SCENARIO, "Feed distribution and mixing at the target scale."),
}
BASELINE_NOTE = "Carried over from the source as a scenario baseline; not a prediction."


def _num(value: float) -> str:
    """Compact display: up to 3 decimals, thousands separators, no trailing zeros."""
    text = f"{value:,.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _ratio(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b not in (None, 0) else None


def _times(a: float | None, b: float | None) -> float | None:
    return a * b if a is not None and b is not None else None


def _compare(name: str, source_summary, target: float | None, treatment_if_same: str, note: str) -> ParameterComparison:
    field = Observation.model_fields[name]
    source = source_summary.final if source_summary else None
    if source is None and target is None:
        treatment = NOT_AVAILABLE
    elif target is not None and source is not None and target == source:
        treatment = treatment_if_same
    else:
        treatment = SCENARIO
    change = target - source if target is not None and source is not None else None
    return ParameterComparison(
        parameter=name,
        label=field.title or name,
        unit=(field.json_schema_extra or {}).get("unit"),
        source=source,
        source_time_hours=source_summary.final_time_hours if source_summary else None,
        target=target,
        change=change,
        percent_change=_ratio(change, source) * 100 if change is not None and source else None,
        treatment=treatment,
        validation_note=note,
    )


def _summary(result: ScaleUpResult, request: ScaleUpRequest) -> list[str]:
    src, s = result.source, result.source.scale_liters
    t = result.target_scale_liters
    lines = [f"Source experiment {src.experiment.experiment_id} scale: {_num(s)} L."]
    if src.observation_count:
        lines.append(
            f"The source has {src.observation_count} observation(s); source values are the latest recorded "
            f"value of each parameter (latest culture time {_num(src.latest_culture_time_hours)} h)."
        )
    else:
        lines.append("The source experiment has no observations, so no source process values are available.")
    lines += [f"Target scenario scale: {_num(t)} L.", f"Scale factor: {_num(result.scale_factor)}× ({_num(s)} L → {_num(t)} L)."]

    for p in result.parameters:
        unit = f" {p.unit}" if p.unit else ""
        if p.parameter in ("temperature_c", "ph", "dissolved_oxygen_percent") and p.target is not None:
            if p.treatment == PRESERVED:
                lines.append(_sentence(f"{p.label} is kept at the source value of {_num(p.target)}{unit}"))
            elif p.source is not None:
                lines.append(f"{p.label} is set to {_num(p.target)}{unit} (source: {_num(p.source)}{unit}).")
            else:
                lines.append(f"{p.label} is set to {_num(p.target)}{unit}; the source has no recorded value.")

    a = result.agitation
    if a.target_rpm is not None:
        change = ("+" if a.change_rpm > 0 else "") + _num(a.change_rpm) if a.source_rpm is not None else ""
        detail = f" (source: {_num(a.source_rpm)} rpm, change {change} rpm)" if a.source_rpm is not None else ""
        lines.append(f"Agitation is set to {_num(a.target_rpm)} rpm{detail}. No agitation scaling rule is applied.")

    g = result.gas_flow
    if g.target_l_per_min is not None:
        lines.append(
            f"At {_num(g.target_vvm)} vvm, the calculated gas flow for {_num(t)} L is "
            f"{_num(g.target_l_per_min)} L/min ({_num(g.target_l_per_h)} L/h)."
        )
    if g.source_l_per_min is not None:
        lines.append(f"Source gas flow: {_num(g.source_vvm)} vvm × {_num(s)} L = {_num(g.source_l_per_min)} L/min.")

    f = result.feed
    if f.target_ml_per_h is not None:
        lines.append(
            f"A target feed rate of {_num(f.target_ml_per_h)} mL/h is {_num(f.target_ml_per_h_per_l)} mL/h per litre"
            + (f" (source: {_num(f.source_ml_per_h_per_l)} mL/h per litre)." if f.source_ml_per_h_per_l is not None else ".")
        )
    if f.volume_proportional_ml_per_h is not None:
        lines.append(f"Keeping the source feed per litre at {_num(t)} L would correspond to {_num(f.volume_proportional_ml_per_h)} mL/h.")
    if f.target_total_feed_ml is not None:
        lines.append(
            f"Over the {_num(f.baseline_duration_hours)} h baseline duration, {_num(f.target_ml_per_h)} mL/h amounts to "
            f"{_num(f.target_total_feed_ml)} mL ({_num(f.target_total_feed_ml / 1000)} L) of feed at a constant rate."
        )
    lines.append("Cell density and culture duration are carried over from the source as baselines, not predicted.")
    return lines


def simulate_scale_up(session: Session, row: ExperimentRow, request: ScaleUpRequest) -> ScaleUpResult:
    if row.scale_liters <= 0:
        raise ScaleUpError(f"Source experiment '{row.experiment_id}' has a non-positive scale; cannot compute a scale factor.")
    source_scale = row.scale_liters
    target_scale = request.target_scale_liters
    factor = target_scale / source_scale

    observations = [repo.to_observation_read(r) for r in repo.list_observations(session, row.experiment_id)]
    latest = {name: summarize_parameter(name, observations) for name in (*COMPARED, "cell_density")}
    duration = observations[-1].culture_time_hours - observations[0].culture_time_hours if observations else None

    parameters = [
        _compare(name, latest[name], getattr(request, field), treatment, note)
        for name, (field, treatment, note) in COMPARED.items()
    ]
    cells = latest["cell_density"]
    parameters.append(ParameterComparison(
        parameter="cell_density", label="Cell density", unit=Observation.model_fields["cell_density"].json_schema_extra["unit"],
        source=cells.final if cells else None, source_time_hours=cells.final_time_hours if cells else None,
        target=cells.final if cells else None, change=0.0 if cells else None, percent_change=0.0 if cells else None,
        treatment=BASELINE if cells else NOT_AVAILABLE, validation_note=BASELINE_NOTE,
    ))
    parameters.append(ParameterComparison(
        parameter="culture_duration_hours", label="Culture duration", unit="h",
        source=duration, source_time_hours=None, target=duration, change=0.0 if duration is not None else None,
        percent_change=0.0 if duration else None, treatment=BASELINE if duration is not None else NOT_AVAILABLE,
        validation_note=BASELINE_NOTE,
    ))
    by_name = {p.parameter: p for p in parameters}

    aeration, feed, agitation = by_name["aeration_rate"], by_name["feed_rate"], by_name["agitation_rpm"]
    source_gas = _times(aeration.source, source_scale)
    target_gas = _times(aeration.target, target_scale)
    result = ScaleUpResult(
        source=SourceInfo(
            experiment=repo.to_experiment_read(row, len(observations)),
            scale_liters=source_scale,
            observation_count=len(observations),
            culture_duration_hours=duration,
            latest_culture_time_hours=observations[-1].culture_time_hours if observations else None,
        ),
        target_scale_liters=target_scale,
        scale_factor=factor,
        volume_increase_liters=target_scale - source_scale,
        parameters=parameters,
        gas_flow=GasFlow(
            source_vvm=aeration.source,
            target_vvm=aeration.target,
            source_l_per_min=source_gas,
            target_l_per_min=target_gas,
            target_l_per_h=_times(target_gas, 60),
            ratio=_ratio(target_gas, source_gas),
        ),
        feed=FeedCalculation(
            source_ml_per_h=feed.source,
            target_ml_per_h=feed.target,
            source_ml_per_h_per_l=_ratio(feed.source, source_scale),
            target_ml_per_h_per_l=_ratio(feed.target, target_scale),
            volume_proportional_ml_per_h=_times(feed.source, factor),
            baseline_duration_hours=duration,
            target_total_feed_ml=_times(feed.target, duration),
        ),
        agitation=AgitationComparison(source_rpm=agitation.source, target_rpm=agitation.target, change_rpm=agitation.change),
        summary=[],
    )
    result.summary = _summary(result, request)
    return result
