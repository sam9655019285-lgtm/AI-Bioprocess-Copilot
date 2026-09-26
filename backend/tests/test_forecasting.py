"""Phase 15: Illustrative Process Forecast (Gemini always mocked)."""

import json
import math

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import db
from app import forecasting as f
from app.ai_api import get_copilot_generator
from app.db_models import ExperimentRow, ObservationRow
from app.main import app
from app.models import Observation

client = TestClient(app)
BASE = {"temperature_c": 37.0, "ph": 7.0, "dissolved_oxygen_percent": 60, "agitation_rpm": 180, "cell_density": 1.0}


def obs(rows):
    return [Observation(experiment_id="E", culture_time_hours=t, **{**BASE, **extra}) for t, extra in rows]


# --- pure models ------------------------------------------------------------------------------

def test_linear_fit_exact():
    a, b = f.linear_fit([(0, 1.0), (1, 3.0), (2, 5.0)])
    assert (a, b) == (pytest.approx(1.0), pytest.approx(2.0))
    with pytest.raises(ValueError):
        f.linear_fit([(1, 1.0), (1, 2.0)])


def test_linear_trend_forecast():
    data = obs([(0, {"ph": 7.2}), (10, {"ph": 7.1}), (20, {"ph": 7.0}), (40, {"ph": 6.8})])
    p = f.forecast_parameter("ph", data, 10, "exponential", None, "MODEL FORECAST")
    assert p.status == "available" and p.model == "linear"
    assert p.model_parameters["slope_b_per_h"] == pytest.approx(-0.01)
    assert p.model_parameters["intercept_a"] == pytest.approx(7.2)
    assert p.forecast[-1].culture_time_hours == 50 and p.forecast[-1].value == pytest.approx(6.7)
    assert len(p.forecast) == f.FORECAST_STEPS and p.forecast[0].culture_time_hours == pytest.approx(41)
    assert (p.observed_start_hours, p.observed_end_hours, p.observation_count) == (0, 40, 4)
    assert p.current.value == 6.8 and p.category == "MODEL FORECAST"


def test_exponential_growth_recovers_rate():
    mu, x0 = 0.05, 0.5
    data = obs([(t, {"cell_density": x0 * math.exp(mu * t)}) for t in (0, 12, 24, 36, 48)])
    p = f.forecast_parameter("cell_density", data, 12, "exponential", None, "MODEL FORECAST")
    assert p.model_label == "Illustrative exponential growth model"
    assert p.model_parameters["mu_per_h"] == pytest.approx(mu) and p.model_parameters["X0"] == pytest.approx(x0)
    assert p.forecast_end.value == pytest.approx(x0 * math.exp(mu * 60))


def test_logistic_growth_recovers_rate_with_given_k():
    k, mu, x0 = 12.0, 0.08, 0.5
    x = lambda t: k / (1 + ((k - x0) / x0) * math.exp(-mu * t))  # noqa: E731
    data = obs([(t, {"cell_density": x(t)}) for t in (0, 20, 40, 60)])
    p = f.forecast_parameter("cell_density", data, 15, "logistic", k, "MODEL FORECAST")
    assert p.model_parameters == {"X0": pytest.approx(x0), "mu_per_h": pytest.approx(mu), "K": k}
    assert p.forecast_end.value == pytest.approx(x(75))
    assert p.forecast_end.value < k
    assert any("model assumption" in a for a in p.assumptions)


def test_logistic_default_k_and_invalid_k():
    data = obs([(0, {"cell_density": 1}), (10, {"cell_density": 2}), (20, {"cell_density": 4})])
    p = f.forecast_parameter("cell_density", data, 5, "logistic", None, "MODEL FORECAST")
    assert p.model_parameters["K"] == 8  # 2 × observed maximum (labelled default)
    bad = f.forecast_parameter("cell_density", data, 5, "logistic", 3.0, "MODEL FORECAST")
    assert bad.status == "invalid_assumption" and bad.forecast == [] and "must exceed" in bad.message


def test_insufficient_and_repeated_and_missing():
    two = obs([(0, {}), (10, {})])
    assert f.forecast_parameter("ph", two, 5, "exponential", None, "X").status == "insufficient_data"
    same_time = obs([(5, {}), (5, {"ph": 7.1}), (5, {"ph": 7.2})])  # 3 points, 1 distinct time
    r = f.forecast_parameter("ph", same_time, 5, "exponential", None, "X")
    assert r.status == "insufficient_data" and r.message == f.INSUFFICIENT and r.forecast == []
    repeated = obs([(0, {"ph": 7.0}), (0, {"ph": 7.2}), (10, {"ph": 7.0})])  # repeated timestamps still usable
    assert f.forecast_parameter("ph", repeated, 5, "exponential", None, "X").status == "available"
    pts = f.usable_points(obs([(0, {"feed_rate": None}), (1, {"feed_rate": 2.0})]), "feed_rate")
    assert pts == [(1, 2.0)]  # missing values skipped, not treated as 0


def test_zero_cell_density():
    data = obs([(0, {"cell_density": 0}), (10, {"cell_density": 0}), (20, {"cell_density": 1})])
    p = f.forecast_parameter("cell_density", data, 5, "exponential", None, "X")
    assert p.status == "insufficient_data" and "must be > 0" in p.message


def test_horizon_default_and_cap():
    assert f.resolve_horizon(40, None) == (10, pytest.approx(f.resolve_horizon(40, None)[1]))
    h, note = f.resolve_horizon(40, 100)
    assert h == 40 and "capped" in note
    assert f.resolve_horizon(40, 15) == (15, None)


def test_deterministic():
    data = obs([(t, {"cell_density": 0.5 + t / 10, "ph": 7 - t / 100}) for t in (0, 5, 10, 20)])
    a = f.forecast_parameter("cell_density", data, 5, "logistic", None, "X")
    b = f.forecast_parameter("cell_density", data, 5, "logistic", None, "X")
    assert a == b


# --- API ------------------------------------------------------------------------------------

def create(experiment_id="EXP"):
    assert client.post("/api/experiments", json={"experiment_id": experiment_id, "name": "x", "scale_liters": 1,
                                                  "data_source": "manual"}).status_code == 201


def add(t, **extra):
    assert client.post("/api/experiments/EXP/observations", json={**BASE, "culture_time_hours": t, **extra}).status_code == 201


@pytest.fixture
def run():
    create()
    for t, x, do in ((0, 0.5, 90), (24, 1.0, 80), (48, 2.0, 70), (72, 4.0, 60)):
        add(t, cell_density=x, dissolved_oxygen_percent=do)


def forecast(body=None, experiment_id="EXP"):
    return client.post(f"/api/experiments/{experiment_id}/forecast", json=body or {})


def test_api_forecast(run):
    r = forecast().json()
    assert r["label"] == "Illustrative Process Forecast" and "not validated biological predictions" in r["disclaimer"]
    assert r["horizon_hours"] == 18  # 25 % of 72 h
    p = {x["parameter"]: x for x in r["parameters"]}
    assert set(p) == set(f.PARAMETERS)
    assert p["cell_density"]["model_parameters"]["mu_per_h"] == pytest.approx(math.log(2) / 24)
    assert p["dissolved_oxygen_percent"]["model_parameters"]["slope_b_per_h"] == pytest.approx(-10 / 24)
    assert all(x["status"] == "available" and x["category"] == "MODEL FORECAST" for x in p.values())
    assert p["dissolved_oxygen_percent"]["forecast_end"]["culture_time_hours"] == 90


def test_api_model_switch_and_horizon(run):
    r = forecast({"cell_model": "logistic", "carrying_capacity": 10, "horizon_hours": 24}).json()
    cells = next(x for x in r["parameters"] if x["parameter"] == "cell_density")
    assert cells["model"] == "logistic" and cells["model_parameters"]["K"] == 10
    assert r["horizon_hours"] == 24 and cells["forecast_end"]["culture_time_hours"] == 96


def test_api_scenario_inputs_are_labelled_and_not_applied(run):
    body = {"scenario": {"horizon_hours": 12, "temperature_c": 33, "target_scale_liters": 100, "feed_rate": 2}}
    r = forecast(body).json()
    assert r["horizon_hours"] == 12
    assert all(x["category"] == "SCENARIO RESULT" for x in r["parameters"] if x["status"] == "available")
    inputs = {s["name"]: s for s in r["scenario_inputs"]}
    assert inputs["Scenario forecast horizon"]["used_by_model"] is True
    assert inputs["Scenario temperature"]["used_by_model"] is False and "no validated" in inputs["Scenario temperature"]["note"]
    assert all(s["category"] == "SCENARIO INPUT" for s in r["scenario_inputs"])
    # temperature scenario does not change the forecast
    base = forecast({"horizon_hours": 12}).json()
    assert [x["forecast_end"] for x in base["parameters"]] == [x["forecast_end"] for x in r["parameters"]]


@pytest.mark.parametrize("bad", [{"horizon_hours": 0}, {"horizon_hours": -5}, {"cell_model": "gompertz"},
                                 {"carrying_capacity": 0}, {"scenario": {"ph": 15}}, {"scenario": {"feed_rate": -1}},
                                 {"unexpected": 1}])
def test_api_invalid(run, bad):
    assert forecast(bad).status_code == 422


def test_api_unknown_and_empty():
    assert forecast(experiment_id="NOPE").status_code == 404
    create()
    r = forecast().json()
    assert r["horizon_hours"] is None
    assert all(x["status"] == "insufficient_data" and x["message"] == f.INSUFFICIENT and x["forecast"] == [] for x in r["parameters"])


def count(model):
    with Session(db.engine) as s:
        return s.exec(select(func.count()).select_from(model)).one()


def test_no_database_writes(run):
    before = (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/EXP/observations").json())
    forecast({"cell_model": "logistic"})
    forecast({"scenario": {"horizon_hours": 10}})
    assert (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/EXP/observations").json()) == before


def test_copilot_receives_forecast_summary(run, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-fake-key-15")
    calls = []

    def fake(system, prompt):
        calls.append(prompt)
        return json.dumps({"answer": "ok", "evidence": [], "uncertainties": [], "suggested_questions": []})

    app.dependency_overrides[get_copilot_generator] = lambda: fake
    try:
        r = client.post("/api/experiments/EXP/copilot", json={"message": "What does the forecast show?", "forecast": {"cell_model": "exponential"}})
        assert r.status_code == 200
        prompt = calls[0]
        ctx = json.loads(prompt[prompt.index("{"):prompt.rindex("SCIENTIST'S QUESTION")].strip())
        fc = ctx["illustrative_process_forecast"]
        assert fc["label"] == "Illustrative Process Forecast"
        assert "observed" not in fc["parameters"][0] and "forecast" not in fc["parameters"][0]  # no raw point lists
        client.post("/api/experiments/EXP/copilot", json={"message": "hi"})
        assert "illustrative_process_forecast" not in calls[-1]
    finally:
        app.dependency_overrides.pop(get_copilot_generator, None)
