"""Phase 16: Experiment Planning (deterministic candidates; Gemini always mocked)."""

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import db
from app import planning as pl
from app.ai_api import get_planning_generator
from app.db_models import ExperimentRow, ObservationRow
from app.main import app

client = TestClient(app)
FAKE_KEY = "test-fake-key-16-do-not-leak"
FORBIDDEN = re.compile(r"optimal|guaranteed|\bbest\b|will improve", re.IGNORECASE)
ROWS = [  # t, temp, pH, DO, agitation, aeration, cell density (gentle growth: no significant anomaly)
    (0, 36.8, 7.0, 60, 120, 0.1, 1.0),
    (24, 37.0, 7.05, 50, 120, 0.1, 1.2),
    (48, 37.0, 7.1, 40, 120, 0.1, 1.4),
]


@pytest.fixture(autouse=True)
def no_gemini_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)


def create(experiment_id="EXP"):
    body = {"experiment_id": experiment_id, "name": "x", "scale_liters": 1, "data_source": "manual"}
    assert client.post("/api/experiments", json=body).status_code == 201


def add(experiment_id, t, temp, ph, do, agit, aer, cells):
    obs = {"culture_time_hours": t, "temperature_c": temp, "ph": ph, "dissolved_oxygen_percent": do,
           "agitation_rpm": agit, "aeration_rate": aer, "cell_density": cells}
    assert client.post(f"/api/experiments/{experiment_id}/observations", json=obs).status_code == 201


@pytest.fixture
def run():
    create()
    for r in ROWS:
        add("EXP", *r)


def plan(body=None, experiment_id="EXP"):
    return client.post(f"/api/experiments/{experiment_id}/plan", json=body or {})


def cond(candidate, name):
    return next(c for c in candidate["conditions"] if c["parameter"] == name)


def texts(p):
    out = [p["disclaimer"], p["objective_label"], *p["warnings"], *p["assumptions"], *p["limitations"], *p["derived_calculations"]]
    out += [p.get("message") or ""]
    for c in p["candidates"]:
        out += [c["design_role"], *c["rationale"], *c["warnings"]]
    out += [c["note"] for c in p["constraints"]] + [c["clamp_note"] or "" for c in p["constraints"]]
    return out


# --- reference / constraints -------------------------------------------------------------------

def test_reference_and_default_constraints(run):
    p = plan().json()
    ref = {r["parameter"]: r for r in p["reference"]}
    assert [r["parameter"] for r in p["reference"]] == pl.CONTROLLABLE
    assert ref["ph"]["value"] == 7.1 and ref["ph"]["category"] == "OBSERVED DATA"
    assert ref["ph"]["observed_min"] == 7.0 and ref["ph"]["observed_max"] == 7.1
    assert ref["feed_rate"]["value"] is None and ref["feed_rate"]["category"] == "NOT AVAILABLE"
    cons = {c["parameter"]: c for c in p["constraints"]}
    assert cons["temperature_c"]["category"] == "PLANNING ASSUMPTION" and (cons["temperature_c"]["min"], cons["temperature_c"]["max"]) == (34, 39)
    assert "Prototype default" in cons["temperature_c"]["note"]
    assert cons["aeration_rate"]["category"] == "NOT AVAILABLE" and cons["aeration_rate"]["changeable"] is False
    assert p["max_candidates"] == 5 and p["label"] == "Experiment Planning"


def test_user_constraints_override_defaults(run):
    p = plan({"objective": "maintain_stability", "constraints": {"temperature_c": {"min": 36, "max": 38, "step": 0.2}}}).json()
    t = next(c for c in p["constraints"] if c["parameter"] == "temperature_c")
    assert t["category"] == "USER CONSTRAINT" and (t["min"], t["max"], t["step"], t["step_source"]) == (36, 38, 0.2, "user")
    temps = sorted(cond(c, "temperature_c")["value"] for c in p["candidates"] if "temperature_c" in c["changed_parameters"])
    assert temps == [36.8, 37.2]


# --- objectives ----------------------------------------------------------------------------------

def test_improve_cell_density(run):
    p = plan({"objective": "improve_cell_density"}).json()
    assert p["objective_label"] == "Explore conditions related to cell density"
    c = p["candidates"]
    assert [x["id"] for x in c] == ["C1", "C2", "C3", "C4", "C5"]
    assert c[0]["design_role"] == "Baseline repeat" and c[0]["changed_parameters"] == []
    # default step = 10 % of the prototype range: temperature 0.5 °C, pH 0.1
    assert [(x["changed_parameters"], cond(x, x["changed_parameters"][0])["value"]) for x in c[1:]] == [
        (["temperature_c"], 36.5), (["temperature_c"], 37.5), (["ph"], 7.0), (["ph"], 7.2)]
    assert p["candidates_omitted"] == 4  # DO ±8 and agitation ±50 exceed max_candidates
    assert all("Explores sensitivity of cell density to this parameter." in x["rationale"] for x in c[1:])
    assert all(x["category"] == "CANDIDATE EXPERIMENT" for x in c)


def test_maintain_stability_small_steps(run):
    p = plan({"objective": "maintain_stability", "max_candidates": 8}).json()
    changes = {(x["changed_parameters"][0], cond(x, x["changed_parameters"][0])["change_from_reference"]) for x in p["candidates"][1:]}
    assert changes == {("temperature_c", -0.25), ("temperature_c", 0.25), ("ph", -0.05), ("ph", 0.05),
                       ("dissolved_oxygen_percent", -4.0), ("dissolved_oxygen_percent", 4.0), ("agitation_rpm", -25.0)}
    assert p["candidates"][0]["design_role"] == "Baseline repeat" and p["candidates_omitted"] == 1


def test_explore_conditions(run):
    p = plan({"objective": "explore_conditions", "max_candidates": 8}).json()
    centre = p["candidates"][0]
    assert centre["design_role"] == "Centre of allowed ranges"
    assert [cond(centre, n)["value"] for n in ("temperature_c", "ph", "dissolved_oxygen_percent", "agitation_rpm")] == [36.5, 7.0, 60.0, 250.0]
    assert cond(centre, "aeration_rate")["value"] == 0.1 and not cond(centre, "aeration_rate")["changed"]  # no range: held
    lows = p["candidates"][1]
    assert lows["design_role"] == "Exploration point (low Temperature)" and cond(lows, "temperature_c")["value"] == 34
    assert cond(lows, "ph")["value"] == 7.0  # others at centre
    assert p["candidates_omitted"] == 1 and len(p["candidates"]) == 8


def test_compare_candidates_two_level(run):
    body = {"objective": "compare_candidates", "constraints": {"temperature_c": {"min": 36, "max": 38}, "ph": {"min": 6.9, "max": 7.2}}}
    c = plan(body).json()["candidates"]
    assert len(c) == 4 and all(x["design_role"] == "Two-level comparison run" for x in c)
    assert [(cond(x, "temperature_c")["value"], cond(x, "ph")["value"]) for x in c] == [(36, 6.9), (36, 7.2), (38, 6.9), (38, 7.2)]
    assert all(cond(x, "dissolved_oxygen_percent")["value"] == 40 for x in c)  # not explicitly constrained -> held


def test_compare_three_factors_fractional_and_needs_constraints(run):
    body = {"objective": "compare_candidates", "constraints": {
        "temperature_c": {"min": 36, "max": 38}, "ph": {"min": 6.9, "max": 7.2}, "agitation_rpm": {"min": 100, "max": 140},
        "dissolved_oxygen_percent": {"min": 30, "max": 50}, "aeration_rate": {"min": 0.1, "max": 0.1}}}
    p = plan(body).json()
    assert len(p["candidates"]) == 4 and any("Only the first 3" in w for w in p["warnings"])
    assert {x for c in p["candidates"] for x in c["changed_parameters"]} <= {"temperature_c", "ph", "dissolved_oxygen_percent"}
    empty = plan({"objective": "compare_candidates"}).json()
    assert empty["candidates"] == [] and any("at least one changeable" in w for w in empty["warnings"])


def test_not_changeable_constraint_holds_parameter(run):
    p = plan({"objective": "maintain_stability", "max_candidates": 8,
              "constraints": {"temperature_c": {"min": 34, "max": 39, "changeable": False}}}).json()
    assert all("temperature_c" not in c["changed_parameters"] for c in p["candidates"])


# --- invariants ----------------------------------------------------------------------------------

@pytest.mark.parametrize("objective", list(pl.OBJECTIVE_LABELS))
def test_invariants_every_objective(run, objective):
    body = {"objective": objective, "max_candidates": 8,
            "constraints": {"temperature_c": {"min": 35, "max": 38.5}, "aeration_rate": {"min": 0.05, "max": 0.2}}}
    p = plan(body).json()
    assert p == plan(body).json()  # deterministic
    cons = {c["parameter"]: c for c in p["constraints"]}
    assert 1 <= len(p["candidates"]) <= 8
    assert len({tuple(c["value"] for c in x["conditions"]) for x in p["candidates"]}) == len(p["candidates"])
    for x in p["candidates"]:
        for c in x["conditions"]:
            lo, hi = cons[c["parameter"]]["min"], cons[c["parameter"]]["max"]
            if c["value"] is not None and lo is not None:
                assert lo <= c["value"] <= hi
            assert c["changed"] == (c["change_from_reference"] not in (None, 0))
            assert (c["parameter"] in x["changed_parameters"]) == c["changed"]
            if c["value"] is None:
                assert c["parameter"] == "feed_rate"  # missing reference is never invented
    assert not [t for t in texts(p) if FORBIDDEN.search(t)]


def test_max_candidates_limit(run):
    for n in (1, 3, 8):
        assert len(plan({"objective": "explore_conditions", "max_candidates": n}).json()["candidates"]) == n


def test_relative_position_and_extrapolation(run):
    c = plan({"objective": "improve_cell_density"}).json()["candidates"]
    low_t = cond(c[1], "temperature_c")
    assert low_t["relative_position"] == pytest.approx((36.5 - 34) / 5, abs=1e-3)
    assert low_t["extrapolation"] and "Extrapolation beyond observed conditions" in c[1]["warnings"][0]
    assert not cond(c[3], "ph")["extrapolation"] and c[3]["warnings"] == []  # pH 7.0 is within observed 7.0–7.1
    assert c[0]["warnings"] == []


def test_clamp_when_reference_outside_range(run):
    p = plan({"objective": "maintain_stability", "constraints": {"ph": {"min": 6.8, "max": 7.0, "step": 0.05}}}).json()
    ph = next(c for c in p["constraints"] if c["parameter"] == "ph")
    assert ph["clamped"] and "clamped" in ph["clamp_note"] and ph["clamp_note"] in p["warnings"]
    assert cond(p["candidates"][0], "ph")["value"] == 7.0 and cond(p["candidates"][0], "ph")["change_from_reference"] == -0.1


def test_anomaly_warning():
    create("ANOM")
    for t, cells in ((0, 1.0), (24, 4.0), (48, 4.2)):  # 300 % jump -> significant sudden change
        add("ANOM", t, 37, 7.0, 50, 120, 0.1, cells)
    p = plan(experiment_id="ANOM").json()
    assert any("baseline repeat may be appropriate" in w for w in p["warnings"])


def test_no_anomaly_warning_for_clean_run(run):
    assert not any("anomaly" in w for w in plan().json()["warnings"])


def test_empty_and_unknown_experiment():
    assert plan(experiment_id="NOPE").status_code == 404
    create()
    p = plan().json()
    assert p["candidates"] == [] and "no observations" in p["message"]
    assert all(r["category"] == "NOT AVAILABLE" for r in p["reference"])


@pytest.mark.parametrize("bad", [
    {"objective": "maximise_titer"},
    {"max_candidates": 0}, {"max_candidates": 9},
    {"constraints": {"ph": {"min": 7.5, "max": 7.0}}},  # min > max
    {"constraints": {"cell_density": {"min": 1, "max": 2}}},  # not controllable
    {"constraints": {"glucose": {"min": 1, "max": 2}}},  # unknown
    {"constraints": {"ph": {"min": 6, "max": 15}}},  # outside Observation limit 0–14
    {"constraints": {"feed_rate": {"min": -1, "max": 2}}},  # rates >= 0
    {"constraints": {"ph": {"min": 6.8, "max": 7.2, "step": 0}}},
    {"constraints": {"ph": {"min": 6.8, "max": 7.2, "extra": 1}}},
    {"unexpected": True},
])
def test_invalid_input(run, bad):
    assert plan(bad).status_code == 422


def count(model):
    with Session(db.engine) as s:
        return s.exec(select(func.count()).select_from(model)).one()


def test_no_database_writes(run):
    before = (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/EXP/observations").json())
    for objective in pl.OBJECTIVE_LABELS:
        plan({"objective": objective})
    assert (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/EXP/observations").json()) == before


def test_plan_endpoint_never_calls_gemini(run, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    app.dependency_overrides[get_planning_generator] = lambda: pytest.fail  # would fail if called
    try:
        assert plan({"objective": "explore_conditions"}).status_code == 200
    finally:
        app.dependency_overrides.pop(get_planning_generator, None)


# --- AI interpretation (mocked) ------------------------------------------------------------------

def interpret(body=None, experiment_id="EXP"):
    return client.post(f"/api/experiments/{experiment_id}/plan/interpret", json=body or {})


def test_interpret_with_mocked_gemini(run, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    calls = []

    def fake(system, prompt):
        calls.append((system, prompt))
        return json.dumps({"candidate_explanations": [{"candidate_id": "C1", "explanation": "Checks reproducibility."}],
                           "considerations": ["c"], "uncertainties": ["u"]})

    app.dependency_overrides[get_planning_generator] = lambda: fake
    try:
        r = interpret({"objective": "improve_cell_density"})
        assert r.status_code == 200
        body = r.json()
        assert body["category"] == "AI INTERPRETATION" and body["interpretation"]["candidate_explanations"][0]["candidate_id"] == "C1"
        system, prompt = calls[0]
        ctx = json.loads(prompt[prompt.index("{"):])
        assert ctx == plan({"objective": "improve_cell_density"}).json()  # exactly the deterministic plan
        assert "observations" not in ctx and "culture_time_hours" not in prompt  # no raw history
        assert "7.05" not in prompt  # an intermediate (not min/max/final) observation never reaches Gemini
        assert FAKE_KEY not in r.text and FAKE_KEY not in prompt and FAKE_KEY not in system
    finally:
        app.dependency_overrides.pop(get_planning_generator, None)


def test_interpret_errors(run, monkeypatch):
    assert interpret().status_code == 503  # no key configured
    assert interpret(experiment_id="NOPE").status_code == 404
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    app.dependency_overrides[get_planning_generator] = lambda: (lambda s, p: "not json")
    try:
        r = interpret()
        assert r.status_code == 502 and FAKE_KEY not in r.text
        assert interpret({"max_candidates": 99}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_planning_generator, None)
