"""Phase 14: advanced (illustrative) scale-up modeling."""

import math

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import db
from app import scaleup_modeling as m
from app.db_models import ExperimentRow, ObservationRow
from app.main import app

client = TestClient(app)
C = m.ModelConstants()


# --- pure formulas ---------------------------------------------------------------------------

def test_power_and_power_per_volume():
    # Np 5, rho 1000, 120 rpm = 2 rev/s, D 0.05 m -> P = 5*1000*8*0.05^5 = 0.0125 W; V = 1 L
    assert m.power_w(5, 1000, 120, 0.05) == pytest.approx(0.0125)
    assert m.power_per_volume(5, 1000, 120, 0.05, 1) == pytest.approx(12.5)
    assert m.power_per_volume(5, 1000, 120, 0.05, 1000) == pytest.approx(0.0125)
    assert m.power_per_volume(5, 1000, 120, None, 1) is None  # missing geometry -> not available
    assert m.power_per_volume(5, 1000, 0, 0.05, 1) == 0


def test_tip_speed():
    assert m.tip_speed(120, 0.05) == pytest.approx(math.pi * 0.05 * 2)
    assert m.tip_speed(None, 0.05) is None and m.tip_speed(120, None) is None


def test_kla():
    assert m.kla(C, 12.5, 0.1) == pytest.approx(5 * 12.5 ** 0.4 * 0.1 ** 0.5)
    assert m.kla(m.ModelConstants(k=2, a=1, b=1), 10, 0.5) == pytest.approx(10)
    assert m.kla(C, 0, 0.1) == 0 and m.kla(C, 12.5, 0) == 0
    assert m.kla(C, None, 0.1) is None


def test_otr_uses_do_conversion_assumption():
    assert m.otr(10, 0.21, 40) == pytest.approx(10 * (0.21 - 0.4 * 0.21))
    assert m.otr(10, 0.21, 100) == pytest.approx(0)
    assert m.otr(None, 0.21, 40) is None and m.otr(10, 0.21, None) is None


def test_our_units():
    # qO2 0.2 pmol/cell/h × 5 ×10⁶ cells/mL = 0.2e-9 mmol × 5e9 /L/h = 1.0 mmol/L/h
    assert m.our(0.2, 5) == pytest.approx(1.0)
    assert m.our(0, 5) == 0 and m.our(0.2, None) is None


def test_oxygen_balance_states():
    assert m.oxygen_balance(2.0, 1.0).state == "Estimated transfer capacity exceeds estimated uptake"
    assert m.oxygen_balance(1.0, 2.0).state == "Estimated uptake exceeds estimated transfer capacity"
    assert m.oxygen_balance(1.0, 1.05).state == "Approximately balanced"
    b = m.oxygen_balance(2.0, 1.5)
    assert b.difference_mmol_l_h == pytest.approx(0.5) and b.category == m.DERIVED
    assert m.oxygen_balance(None, 1.0).category == m.NOT_AVAILABLE
    for s in ("safe", "unsafe", "optimal", "failure"):
        assert s not in (m.oxygen_balance(2, 1).state + m.oxygen_balance(1, 2).state).lower()


def test_agitation_strategies():
    assert m.target_rpm("constant_rpm", 120, None, None, 1, 100) == 120
    assert m.target_rpm("constant_tip_speed", 120, 0.05, 0.25, 1, 100) == pytest.approx(24)
    n = m.target_rpm("constant_pv", 120, 0.05, 0.25, 1, 100)
    assert n == pytest.approx(120 * (0.2) ** (5 / 3) * 100 ** (1 / 3))
    # constant P/V really keeps P/V constant
    assert m.power_per_volume(5, 1000, n, 0.25, 100) == pytest.approx(m.power_per_volume(5, 1000, 120, 0.05, 1))
    assert m.target_rpm("constant_tip_speed", 120, None, 0.25, 1, 100) is None
    assert m.target_rpm("constant_rpm", None, 0.05, 0.25, 1, 100) is None


def test_aeration_strategies():
    assert m.target_aeration("constant_vvm", 0.1, 1, 100) == (0.1, pytest.approx(10))
    vvm, q = m.target_aeration("constant_gas_flow", 0.1, 1, 100)
    assert q == pytest.approx(0.1) and vvm == pytest.approx(0.001)
    assert m.target_aeration("constant_vvm", None, 1, 100) == (None, None)


# --- API -----------------------------------------------------------------------------------

def create(experiment_id="SRC", scale=1):
    assert client.post("/api/experiments", json={"experiment_id": experiment_id, "name": "x", "scale_liters": scale,
                                                  "data_source": "manual"}).status_code == 201


def add(hours, **f):
    body = {"temperature_c": 37, "ph": 7, "dissolved_oxygen_percent": 40, "agitation_rpm": 120, "cell_density": 5.0,
            "aeration_rate": 0.1, "culture_time_hours": hours, **f}
    assert client.post("/api/experiments/SRC/observations", json=body).status_code == 201


def model(**overrides):
    return client.post("/api/scale-up/model", json={"source_experiment_id": "SRC", "target_scale_liters": 100, **overrides})


GEOM = {"source_impeller_diameter_m": 0.05, "target_impeller_diameter_m": 0.25}


@pytest.fixture
def source():
    create()
    add(0, agitation_rpm=100)
    add(24)  # latest: 120 rpm, 0.1 vvm, DO 40 %, 5 ×10⁶ cells/mL


def test_full_model(source):
    r = model(**GEOM).json()
    assert r["label"] == "Engineering estimate" and "not a validated industrial bioreactor model" in r["disclaimer"]
    s, t = r["source"], r["target"]
    assert s["rpm"]["value"] == 120 and s["rpm"]["category"] == m.OBSERVED
    assert s["power_per_volume_w_m3"]["value"] == pytest.approx(12.5)
    assert s["power_per_volume_w_m3"]["category"] == m.DERIVED and s["power_per_volume_w_m3"]["unit"] == "W/m³"
    kla_s = 5 * 12.5 ** 0.4 * 0.1 ** 0.5
    assert s["kla_per_h"]["value"] == pytest.approx(kla_s) and s["kla_per_h"]["unit"] == "1/h"
    assert s["otr_mmol_l_h"]["value"] == pytest.approx(kla_s * 0.21 * 0.6)
    assert s["our_mmol_l_h"]["value"] == pytest.approx(1.0) and s["our_mmol_l_h"]["unit"] == "mmol/L/h"
    # default: constant P/V + constant vvm at the target
    assert t["power_per_volume_w_m3"]["value"] == pytest.approx(12.5)
    assert t["vvm"]["value"] == 0.1 and t["gas_flow_l_min"]["value"] == pytest.approx(10)
    assert t["rpm"]["category"] == m.SCENARIO
    assert r["oxygen_balance_source"]["state"] == "Estimated uptake exceeds estimated transfer capacity"
    cats = {q["category"] for q in r["assumptions"]}
    assert m.ASSUMPTION in cats
    assert {row["strategy"] for row in r["strategy_comparison"]} == set(m.STRATEGY_LABELS)
    for word in ("best", "recommend"):
        assert all(word not in row["assumption"].lower() for row in r["strategy_comparison"])


def test_selected_strategies_change_target(source):
    rpm = model(**GEOM, agitation_strategy="constant_rpm", aeration_strategy="constant_gas_flow").json()["target"]
    assert rpm["rpm"]["value"] == 120 and rpm["gas_flow_l_min"]["value"] == pytest.approx(0.1)
    tip = model(**GEOM, agitation_strategy="constant_tip_speed").json()["target"]
    assert tip["rpm"]["value"] == pytest.approx(24)
    assert tip["tip_speed_m_s"]["value"] == pytest.approx(m.tip_speed(120, 0.05))
    bigger = model(**GEOM, target_scale_liters=1000).json()["target"]["gas_flow_l_min"]["value"]
    assert bigger == pytest.approx(100)  # changing target scale updates results


def test_missing_geometry_not_available(source):
    r = model().json()
    s = r["source"]
    for key in ("power_per_volume_w_m3", "tip_speed_m_s", "kla_per_h", "otr_mmol_l_h"):
        assert s[key]["value"] is None and s[key]["category"] == m.NOT_AVAILABLE
    assert s["our_mmol_l_h"]["value"] == pytest.approx(1.0)  # needs no geometry
    assert r["oxygen_balance_source"]["category"] == m.NOT_AVAILABLE
    rows = {(x["strategy"], x["parameter"]): x for x in r["strategy_comparison"]}
    assert rows[("constant_rpm", "Agitation")]["target"] == 120
    assert rows[("constant_pv", "Agitation")]["target"] is None
    assert any("Impeller diameters were not supplied" in n for n in r["notes"])


@pytest.mark.parametrize("bad", [
    {"target_scale_liters": 0}, {"target_scale_liters": -1}, {"source_impeller_diameter_m": 0},
    {"target_impeller_diameter_m": -0.1}, {"power_number": 0}, {"liquid_density_kg_m3": 0},
    {"q_o2_pmol_per_cell_h": -1}, {"oxygen_saturation_mmol_l": 0}, {"constants": {"k": 0}},
    {"constants": {"a": -1}}, {"agitation_strategy": "best"}, {"unknown": 1},
])
def test_invalid_inputs(source, bad):
    assert model(**bad).status_code == 422


def test_zero_rpm_and_aeration_no_division_errors():
    create()
    add(0, agitation_rpm=0, aeration_rate=0)
    r = model(**GEOM).json()
    assert r["source"]["power_per_volume_w_m3"]["value"] == 0
    assert r["source"]["kla_per_h"]["value"] == 0
    assert r["target"]["rpm"]["value"] == 0


def test_missing_and_empty_experiment():
    assert client.post("/api/scale-up/model", json={"source_experiment_id": "NOPE", "target_scale_liters": 10}).status_code == 404
    create()
    r = model(**GEOM).json()
    assert r["source"]["rpm"]["category"] == m.NOT_AVAILABLE and r["source"]["our_mmol_l_h"]["value"] is None
    assert r["oxygen_balance_target"]["category"] == m.NOT_AVAILABLE
    assert any("no observations" in n for n in r["notes"])


def count(model_cls):
    with Session(db.engine) as s:
        return s.exec(select(func.count()).select_from(model_cls)).one()


def test_no_database_writes(source):
    before = (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/SRC/observations").json())
    model(**GEOM)
    model()
    assert (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/SRC/observations").json()) == before
