"""Illustrative Process Forecast (Phase 15).

Model forecast based on available observations and configurable assumptions. Phase 15
provides illustrative process forecasting based on historical observations. It is not a
validated biological or industrial prediction model. Nothing is stored.

Models (t measured from the first usable observation, t0):
  linear (DO, pH, temperature):  y = a + b·t                       least squares
  exponential (cell density):    X(t) = X0 · exp(mu · t)            least squares on ln X
  logistic (cell density):       X(t) = K / (1 + ((K − X0)/X0) · exp(−mu · t))
                                 K is a MODEL ASSUMPTION; fit on ln(X / (K − X)) = ln(X0/(K − X0)) + mu·t
Horizon: default 25 % of the observed culture-time span, capped at 100 % of it.
"""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from . import repository as repo
from .db_models import ExperimentRow
from .models import Observation

INSUFFICIENT = "Insufficient historical data for forecast."
DISCLAIMER = (
    "Illustrative Process Forecast. Model forecast based on available observations and configurable assumptions. "
    "Forecasts are model-based estimates using historical observations and configurable assumptions. "
    "They are not validated biological predictions."
)
MIN_POINTS = 3
MIN_DISTINCT_TIMES = 2
DEFAULT_HORIZON_FRACTION = 0.25
MAX_HORIZON_FRACTION = 1.0
FORECAST_STEPS = 10
DEFAULT_K_FACTOR = 2.0  # default logistic K = 2 × observed maximum (assumption)
PARAMETERS = ["cell_density", "dissolved_oxygen_percent", "ph", "temperature_c"]
LIMITATIONS = [
    "Simple models are used; they do not represent full bioreactor dynamics.",
    "Limited historical data can reduce reliability.",
    "Extrapolation becomes less reliable farther beyond the observations.",
    "Biological growth can change due to nutrients, stress, oxygen, pH and other factors.",
    "The forecast is not experimentally validated.",
]

CellModel = Literal["exponential", "logistic"]


class ForecastScenario(BaseModel):
    """What-if inputs. Only the horizon is used by the models; the others are recorded, not applied."""

    model_config = ConfigDict(extra="forbid")
    horizon_hours: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    target_scale_liters: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    temperature_c: float | None = Field(default=None, ge=20, le=45, allow_inf_nan=False)
    ph: float | None = Field(default=None, ge=0, le=14, allow_inf_nan=False)
    dissolved_oxygen_percent: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    agitation_rpm: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    aeration_rate: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    feed_rate: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    horizon_hours: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    cell_model: CellModel = "exponential"
    carrying_capacity: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False,
                                            description="Logistic K (×10⁶ cells/mL) - model assumption")
    scenario: ForecastScenario | None = None


class Point(BaseModel):
    culture_time_hours: float
    value: float


class ParameterForecast(BaseModel):
    parameter: str
    label: str
    unit: str | None
    status: Literal["available", "insufficient_data", "invalid_assumption"]
    message: str | None = None
    category: str  # MODEL FORECAST | SCENARIO RESULT | NOT AVAILABLE
    model: str | None = None
    model_label: str | None = None
    equation: str | None = None
    model_parameters: dict[str, float] = {}
    observed: list[Point] = []
    forecast: list[Point] = []
    current: Point | None = None
    forecast_end: Point | None = None
    observation_count: int = 0
    observed_start_hours: float | None = None
    observed_end_hours: float | None = None
    horizon_hours: float | None = None
    assumptions: list[str] = []
    limitations: list[str] = []


class ScenarioInput(BaseModel):
    name: str
    value: float
    unit: str
    category: str = "SCENARIO INPUT"
    used_by_model: bool
    note: str


class ExperimentForecast(BaseModel):
    label: str = "Illustrative Process Forecast"
    disclaimer: str = DISCLAIMER
    experiment_id: str
    cell_model: CellModel
    horizon_hours: float | None
    horizon_note: str | None
    parameters: list[ParameterForecast]
    scenario_inputs: list[ScenarioInput]


# --- pure helpers ----------------------------------------------------------------------------

def usable_points(observations: list[Observation], name: str) -> list[tuple[float, float]]:
    """Finite values, chronological (stable for repeated timestamps). Missing values are skipped."""
    pts = [(o.culture_time_hours, getattr(o, name)) for o in observations]
    pts = [(t, v) for t, v in pts if v is not None and math.isfinite(v) and math.isfinite(t)]
    return sorted(pts, key=lambda p: p[0])


def sufficient(points: list[tuple[float, float]]) -> bool:
    return len(points) >= MIN_POINTS and len({t for t, _ in points}) >= MIN_DISTINCT_TIMES


def linear_fit(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Least-squares (intercept a, slope b) for y = a + b·t."""
    n = len(points)
    mt = sum(t for t, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((t - mt) ** 2 for t, _ in points)
    if sxx == 0:
        raise ValueError("no time spread")
    b = sum((t - mt) * (y - my) for t, y in points) / sxx
    return my - b * mt, b


def resolve_horizon(span: float, requested: float | None) -> tuple[float, str | None]:
    default = DEFAULT_HORIZON_FRACTION * span
    if requested is None:
        return default, f"Default horizon: 25 % of the observed span ({span:g} h)."
    cap = MAX_HORIZON_FRACTION * span
    if requested > cap:
        return cap, f"Requested horizon capped at 100 % of the observed span ({cap:g} h) to limit extrapolation."
    return requested, None


def forecast_times(t_end: float, horizon: float) -> list[float]:
    return [t_end + horizon * i / FORECAST_STEPS for i in range(1, FORECAST_STEPS + 1)]


def _meta(name: str):
    field = Observation.model_fields[name]
    return field.title or name, (field.json_schema_extra or {}).get("unit")


def _unavailable(name: str, status: str, message: str, n: int = 0) -> ParameterForecast:
    label, unit = _meta(name)
    return ParameterForecast(parameter=name, label=label, unit=unit, status=status, message=message,
                             category="NOT AVAILABLE", observation_count=n)


def forecast_parameter(name: str, observations: list[Observation], horizon: float | None, cell_model: CellModel,
                       carrying_capacity: float | None, category: str) -> ParameterForecast:
    points = usable_points(observations, name)
    label, unit = _meta(name)
    if not sufficient(points):
        return _unavailable(name, "insufficient_data", INSUFFICIENT, len(points))
    t0, t_end = points[0][0], points[-1][0]
    rel = [(t - t0, v) for t, v in points]
    times = forecast_times(t_end, horizon)
    assumptions = [f"Forecast horizon {horizon:g} h beyond the last observation ({t_end:g} h)."]

    if name != "cell_density":
        a, b = linear_fit(rel)
        f = lambda t: a + b * (t - t0)  # noqa: E731
        model, model_label, eq, params = "linear", "Linear trend", "y = a + b·t", {"intercept_a": a, "slope_b_per_h": b}
        assumptions.append("The recent linear trend is assumed to continue; no control action or physical bound is modelled.")
    else:
        positive = [(t, v) for t, v in rel if v > 0]
        if len(positive) < MIN_POINTS or len({t for t, _ in positive}) < MIN_DISTINCT_TIMES:
            return _unavailable(name, "insufficient_data", INSUFFICIENT + " Cell density must be > 0 for growth models.", len(points))
        if cell_model == "exponential":
            c, mu = linear_fit([(t, math.log(v)) for t, v in positive])
            x0 = math.exp(c)
            f = lambda t: x0 * math.exp(mu * (t - t0))  # noqa: E731
            model, model_label, eq = "exponential", "Illustrative exponential growth model", "X(t) = X0 · exp(mu · t)"
            params = {"X0": x0, "mu_per_h": mu}
            assumptions.append("Unlimited exponential growth at the fitted rate (no nutrient or space limitation).")
        else:
            x_max = max(v for _, v in positive)
            k = carrying_capacity if carrying_capacity is not None else DEFAULT_K_FACTOR * x_max
            if k <= x_max:
                return _unavailable(name, "invalid_assumption",
                                    f"Logistic K ({k:g}) must exceed the observed maximum ({x_max:g}).", len(points))
            c, mu = linear_fit([(t, math.log(v / (k - v))) for t, v in positive])
            x0 = k * math.exp(c) / (1 + math.exp(c))
            f = lambda t: k / (1 + ((k - x0) / x0) * math.exp(-mu * (t - t0)))  # noqa: E731
            model, model_label = "logistic", "Illustrative logistic growth model"
            eq = "X(t) = K / (1 + ((K − X0)/X0) · exp(−mu · t))"
            params = {"X0": x0, "mu_per_h": mu, "K": k}
            assumptions.append(f"K = {k:g} ×10⁶ cells/mL is a model assumption"
                               + (" (default: 2 × observed maximum)" if carrying_capacity is None else "")
                               + ", not a measured biological carrying capacity.")
    if not all(math.isfinite(p) for p in params.values()):
        return _unavailable(name, "insufficient_data", INSUFFICIENT + " The data does not support a stable estimate.", len(points))

    forecast = [Point(culture_time_hours=t, value=f(t)) for t in times]
    if not all(math.isfinite(p.value) for p in forecast):
        return _unavailable(name, "insufficient_data", INSUFFICIENT + " The data does not support a stable estimate.", len(points))
    last = Point(culture_time_hours=points[-1][0], value=points[-1][1])
    return ParameterForecast(
        parameter=name, label=label, unit=unit, status="available", category=category,
        model=model, model_label=model_label, equation=eq, model_parameters=params,
        observed=[Point(culture_time_hours=t, value=v) for t, v in points], forecast=forecast,
        current=last, forecast_end=forecast[-1], observation_count=len(points),
        observed_start_hours=t0, observed_end_hours=t_end, horizon_hours=horizon,
        assumptions=assumptions, limitations=LIMITATIONS,
    )


SCENARIO_FIELDS = {
    "horizon_hours": ("Scenario forecast horizon", "h", True, "Used as the forecast horizon."),
    "target_scale_liters": ("Scenario target scale", "L", False, "Recorded only: the forecast models are scale-independent."),
    "temperature_c": ("Scenario temperature", "°C", False, "Recorded only: no validated temperature–growth relationship is modelled."),
    "ph": ("Scenario pH", "", False, "Recorded only: no validated pH–growth relationship is modelled."),
    "dissolved_oxygen_percent": ("Scenario DO", "% air sat.", False, "Recorded only: no validated DO–growth relationship is modelled."),
    "agitation_rpm": ("Scenario agitation", "rpm", False, "Recorded only: agitation effects are not modelled."),
    "aeration_rate": ("Scenario aeration", "vvm", False, "Recorded only: aeration effects are not modelled."),
    "feed_rate": ("Scenario feed rate", "mL/h", False, "Recorded only: feed effects are not modelled."),
}


def scenario_inputs(scenario: ForecastScenario | None) -> list[ScenarioInput]:
    if scenario is None:
        return []
    return [
        ScenarioInput(name=label, value=value, unit=unit, used_by_model=used, note=note)
        for key, (label, unit, used, note) in SCENARIO_FIELDS.items()
        if (value := getattr(scenario, key)) is not None
    ]


def forecast_experiment(session: Session, row: ExperimentRow, request: ForecastRequest) -> ExperimentForecast:
    observations = [repo.to_observation_read(r) for r in repo.list_observations(session, row.experiment_id)]
    times = [o.culture_time_hours for o in observations]
    scenario_horizon = request.scenario.horizon_hours if request.scenario else None
    requested = scenario_horizon if scenario_horizon is not None else request.horizon_hours
    category = "SCENARIO RESULT" if scenario_horizon is not None else "MODEL FORECAST"
    span = (max(times) - min(times)) if times else 0
    horizon, note = resolve_horizon(span, requested) if span > 0 else (None, "No observed culture-time span.")
    params = [
        forecast_parameter(n, observations, horizon, request.cell_model, request.carrying_capacity, category)
        if horizon else _unavailable(n, "insufficient_data", INSUFFICIENT, len(usable_points(observations, n)))
        for n in PARAMETERS
    ]
    return ExperimentForecast(
        experiment_id=row.experiment_id, cell_model=request.cell_model, horizon_hours=horizon, horizon_note=note,
        parameters=params, scenario_inputs=scenario_inputs(request.scenario),
    )


def forecast_summary(forecast: ExperimentForecast) -> dict:
    """Compact, point-free summary for the AI Copilot (no raw observation lists)."""
    return {
        "label": forecast.label, "disclaimer": forecast.disclaimer, "horizon_hours": forecast.horizon_hours,
        "parameters": [
            p.model_dump(include={"parameter", "label", "unit", "status", "message", "category", "model_label", "equation",
                                  "model_parameters", "current", "forecast_end", "observation_count",
                                  "observed_start_hours", "observed_end_hours", "assumptions"})
            for p in forecast.parameters
        ],
        "limitations": LIMITATIONS,
        "scenario_inputs": [s.model_dump() for s in forecast.scenario_inputs],
    }
