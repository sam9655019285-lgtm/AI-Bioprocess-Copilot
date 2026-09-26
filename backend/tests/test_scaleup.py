import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import db
from app.db_models import ExperimentRow, ObservationRow
from app.main import app

client = TestClient(app)

BASE = {"temperature_c": 37.0, "ph": 7.0, "dissolved_oxygen_percent": 50, "agitation_rpm": 180, "cell_density": 1.0}


def create(experiment_id="SRC", scale=1, data_source="manual"):
    response = client.post("/api/experiments", json={
        "experiment_id": experiment_id, "name": f"Run {experiment_id}", "scale_liters": scale, "data_source": data_source,
    })
    assert response.status_code == 201


def add(target, hours, **fields):
    response = client.post(f"/api/experiments/{target}/observations", json={**BASE, "culture_time_hours": hours, **fields})
    assert response.status_code == 201


def simulate(**overrides):
    return client.post("/api/scale-up/simulate", json={"source_experiment_id": "SRC", "target_scale_liters": 10, **overrides})


def ok(**overrides):
    response = simulate(**overrides)
    assert response.status_code == 200, response.text
    return response.json()


def params(body):
    return {p["parameter"]: p for p in body["parameters"]}


@pytest.fixture
def source():
    """1 L source run, 0-48 h; latest values at 48 h. Aeration recorded, feed only at 24 h."""
    create()
    add("SRC", 0, aeration_rate=0.05, cell_density=0.5)
    add("SRC", 24, aeration_rate=0.05, feed_rate=2.0, cell_density=3.0)
    add("SRC", 48, aeration_rate=0.1, temperature_c=36.5, ph=6.9, dissolved_oxygen_percent=40, agitation_rpm=200, cell_density=6.0)


@pytest.mark.parametrize("target, factor", [(10, 10), (100, 100), (1000, 1000)])
def test_standard_scale_factors(source, target, factor):
    body = ok(target_scale_liters=target)
    assert body["scale_factor"] == factor
    assert body["source"]["scale_liters"] == 1
    assert body["volume_increase_liters"] == target - 1
    assert body["label"] == "Illustrative simulation"
    assert "not validated predictions" in body["disclaimer"]


def test_custom_target_scale_and_non_unit_source():
    create("SRC", scale=2)
    add("SRC", 0)
    body = ok(target_scale_liters=250)
    assert body["scale_factor"] == pytest.approx(125)
    assert body["target_scale_liters"] == 250


def test_gas_flow_calculation(source):
    body = ok(target_scale_liters=100, target_aeration_vvm=0.5)
    gas = body["gas_flow"]
    assert gas["source_vvm"] == 0.1  # latest recorded aeration
    assert gas["source_l_per_min"] == pytest.approx(0.1)  # 0.1 vvm × 1 L
    assert gas["target_l_per_min"] == pytest.approx(50)  # 0.5 vvm × 100 L
    assert gas["target_l_per_h"] == pytest.approx(3000)
    assert gas["ratio"] == pytest.approx(500)
    assert "At 0.5 vvm, the calculated gas flow for 100 L is 50 L/min (3,000 L/h)." in body["summary"]


def test_feed_calculations(source):
    body = ok(target_scale_liters=100, target_feed_rate_ml_per_h=150)
    feed = body["feed"]
    assert feed["source_ml_per_h"] == 2.0  # latest recorded feed (at 24 h), not invented at 48 h
    assert feed["source_ml_per_h_per_l"] == pytest.approx(2.0)
    assert feed["target_ml_per_h_per_l"] == pytest.approx(1.5)
    assert feed["volume_proportional_ml_per_h"] == pytest.approx(200)
    assert feed["baseline_duration_hours"] == 48
    assert feed["target_total_feed_ml"] == pytest.approx(7200)


def test_parameter_comparison(source):
    body = ok(target_temperature_c=36.5, target_ph=7.1, target_dissolved_oxygen_percent=40,
              target_agitation_rpm=120, target_aeration_vvm=0.1)
    p = params(body)
    assert (p["temperature_c"]["source"], p["temperature_c"]["target"], p["temperature_c"]["change"]) == (36.5, 36.5, 0)
    assert p["temperature_c"]["treatment"] == "Preserved"
    assert p["ph"]["change"] == pytest.approx(0.2)
    assert p["ph"]["treatment"] == "Scenario setting"
    assert p["agitation_rpm"]["change"] == -80
    assert p["agitation_rpm"]["percent_change"] == pytest.approx(-40)
    assert p["agitation_rpm"]["treatment"] == "Scenario setting"  # agitation is always a user setting
    assert p["temperature_c"]["source_time_hours"] == 48
    assert body["agitation"] == {"source_rpm": 200, "target_rpm": 120, "change_rpm": -80,
                                 "note": body["agitation"]["note"]}
    assert p["cell_density"]["treatment"] == "Baseline assumption"
    assert p["cell_density"]["target"] == p["cell_density"]["source"] == 6.0
    assert p["culture_duration_hours"]["target"] == 48
    assert all(p[name]["validation_note"] for name in p)


@pytest.mark.parametrize("bad", [
    {"target_scale_liters": 0},
    {"target_scale_liters": -10},
    {"target_scale_liters": "big"},
    {"target_ph": 15},
    {"target_temperature_c": 90},
    {"target_dissolved_oxygen_percent": -1},
    {"target_agitation_rpm": -5},
    {"target_aeration_vvm": -0.1},
    {"target_feed_rate_ml_per_h": -2},
    {"unexpected": 1},
])
def test_invalid_inputs_rejected(source, bad):
    response = simulate(**bad)
    assert response.status_code == 422


def test_unknown_experiment():
    response = client.post("/api/scale-up/simulate", json={"source_experiment_id": "NOPE", "target_scale_liters": 10})
    assert response.status_code == 404
    assert response.json()["detail"] == "Experiment 'NOPE' not found."


def test_empty_experiment():
    create()
    body = ok(target_scale_liters=100, target_aeration_vvm=0.2, target_temperature_c=37)
    assert body["scale_factor"] == 100
    assert body["source"]["observation_count"] == 0
    p = params(body)
    assert p["temperature_c"]["source"] is None
    assert p["temperature_c"]["change"] is None
    assert p["temperature_c"]["treatment"] == "Scenario setting"
    assert p["cell_density"]["treatment"] == "Not available"
    assert body["gas_flow"]["source_l_per_min"] is None
    assert body["gas_flow"]["target_l_per_min"] == pytest.approx(20)
    assert body["feed"]["baseline_duration_hours"] is None
    assert "The source experiment has no observations, so no source process values are available." in body["summary"]


def test_missing_optional_values_not_invented():
    create()
    add("SRC", 0)
    add("SRC", 10)
    body = ok(target_scale_liters=100)  # no targets given either
    p = params(body)
    for name in ("aeration_rate", "feed_rate"):
        assert p[name]["source"] is None and p[name]["target"] is None
        assert p[name]["treatment"] == "Not available"
    assert body["gas_flow"] == {"source_vvm": None, "target_vvm": None, "source_l_per_min": None,
                                "target_l_per_min": None, "target_l_per_h": None, "ratio": None}
    assert body["feed"]["volume_proportional_ml_per_h"] is None
    assert body["feed"]["target_total_feed_ml"] is None
    assert p["temperature_c"]["target"] is None  # not specified -> not assumed


def count(model):
    with Session(db.engine) as session:
        return session.exec(select(func.count()).select_from(model)).one()


def test_source_experiment_unchanged(source):
    before_exp = client.get("/api/experiments/SRC").json()
    before_obs = client.get("/api/experiments/SRC/observations").json()
    counts = (count(ExperimentRow), count(ObservationRow))
    ok(target_scale_liters=1000, target_temperature_c=30, target_ph=6.5, target_feed_rate_ml_per_h=999)
    assert client.get("/api/experiments/SRC").json() == before_exp
    assert client.get("/api/experiments/SRC/observations").json() == before_obs
    assert (count(ExperimentRow), count(ObservationRow)) == counts


def test_summary_is_factual(source):
    body = ok(target_scale_liters=100, target_temperature_c=36.5, target_ph=7.0, target_aeration_vvm=0.5,
              target_dissolved_oxygen_percent=40,
              target_agitation_rpm=150, target_feed_rate_ml_per_h=100)
    summary = body["summary"]
    assert summary[0] == "Source experiment SRC scale: 1 L."
    assert "Target scenario scale: 100 L." in summary
    assert "Scale factor: 100× (1 L → 100 L)." in summary
    assert "Temperature is kept at the source value of 36.5 °C." in summary
    assert "Agitation is set to 150 rpm (source: 200 rpm, change -50 rpm). No agitation scaling rule is applied." in summary
    assert not any(line.endswith("..") for line in summary)
    banned = re.compile(r"\b(safe|unsafe|optimal|best|guarantee\w*|production-ready|validated)\b", re.I)
    assert not any(banned.search(line) for line in summary)
    assert len(body["considerations"]) >= 9
