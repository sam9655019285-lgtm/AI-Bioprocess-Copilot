import re

import pytest
from fastapi.testclient import TestClient

from app.anomaly import DEFAULT_CONFIG, detect
from app.main import app
from app.models import Observation

client = TestClient(app)

# A stable, fully recorded run: small non-monotonic variation, regular 12 h sampling.
NORMAL = [
    dict(temperature_c=t, ph=p, dissolved_oxygen_percent=do, agitation_rpm=r, cell_density=c,
         feed_rate=f, aeration_rate=a, nutrient_concentration=n)
    for t, p, do, r, c, f, a, n in [
        (37.0, 7.00, 50, 180, 1.0, 2.0, 0.050, 5.0),
        (37.1, 7.05, 52, 182, 1.1, 2.1, 0.051, 5.1),
        (37.0, 7.00, 50, 180, 1.0, 2.0, 0.050, 5.0),
        (37.1, 7.05, 52, 182, 1.1, 2.1, 0.051, 5.1),
        (37.0, 7.00, 50, 180, 1.0, 2.0, 0.050, 5.0),
    ]
]


def series(rows, times=None, **fixed):
    times = times if times is not None else [12 * i for i in range(len(rows))]
    return [
        Observation(experiment_id="EXP", culture_time_hours=t, **{**NORMAL[i % len(NORMAL)], **row, **fixed})
        for i, (t, row) in enumerate(zip(times, rows))
    ]


def run(rows, times=None, **fixed):
    return detect("EXP", series(rows, times, **fixed))


def of_type(findings, kind, parameter=None):
    return [f for f in findings if f.type == kind and (parameter is None or f.parameter == parameter)]


# --- API ---------------------------------------------------------------------------------

def create(experiment_id="EXP"):
    assert client.post("/api/experiments", json={
        "experiment_id": experiment_id, "name": "Anomaly test", "scale_liters": 1, "data_source": "manual",
    }).status_code == 201


def add(hours, **fields):
    body = {**NORMAL[0], "culture_time_hours": hours, **fields}
    assert client.post("/api/experiments/EXP/observations", json=body).status_code == 201


def test_no_observations_returns_empty_result():
    create()
    response = client.get("/api/experiments/EXP/anomalies")
    assert response.status_code == 200
    body = response.json()
    assert body["observation_count"] == 0
    assert body["finding_count"] == 0
    assert body["findings"] == []
    assert body["counts"] == {"info": 0, "attention": 0, "significant": 0}
    assert body["summary"] == ["No observations have been recorded, so no checks were run."]
    assert body["configuration"]["ranges"]["ph"] == {"min": 6.5, "max": 7.5, "severe_margin": 0.3}


def test_unknown_experiment_404():
    response = client.get("/api/experiments/NOPE/anomalies")
    assert response.status_code == 404
    assert response.json()["detail"] == "Experiment 'NOPE' not found."


def test_normal_experiment_has_no_findings():
    assert run([{}] * 5) == []


# --- A. range ----------------------------------------------------------------------------

@pytest.mark.parametrize("parameter, value, direction", [
    ("temperature_c", 33.2, "below"),
    ("ph", 6.2, "below"),
    ("dissolved_oxygen_percent", 15, "below"),
    ("agitation_rpm", 520, "above"),
    ("cell_density", 22, "above"),
])
def test_range_violation(parameter, value, direction):
    findings = run([{}, {}, {parameter: value}, {}, {}])
    (finding,) = of_type(findings, "range", parameter)
    rule = DEFAULT_CONFIG.ranges[parameter]
    assert finding.direction == direction
    assert (finding.expected_min, finding.expected_max) == (rule.min, rule.max)
    assert finding.observed_value == value
    assert finding.culture_time_hours == 24
    assert f"was {direction} the prototype monitoring range" in finding.message


def test_consecutive_out_of_range_readings_grouped():
    findings = run([{}, {"ph": 6.4}, {"ph": 6.3}, {"ph": 6.45}, {}])
    (finding,) = of_type(findings, "range", "ph")
    assert [p.culture_time_hours for p in finding.points] == [12, 24, 36]
    assert finding.observed_value == 6.3  # furthest value
    assert "in 3 consecutive observations from 12 h to 36 h (lowest 6.30)" in finding.message


# --- B. sudden change -------------------------------------------------------------------

@pytest.mark.parametrize("parameter, before, after, kind", [
    ("temperature_c", 37.0, 38.5, "absolute"),
    ("ph", 7.0, 7.4, "absolute"),
    ("dissolved_oxygen_percent", 60, 40, "absolute"),
    ("cell_density", 2.0, 3.0, "relative"),
])
def test_sudden_change(parameter, before, after, kind):
    findings = run([{parameter: before}, {parameter: after}])
    (finding,) = of_type(findings, "sudden_change", parameter)
    assert (finding.previous_value, finding.observed_value) == (before, after)
    assert (finding.previous_time_hours, finding.culture_time_hours) == (0, 12)
    assert finding.absolute_change == pytest.approx(after - before)
    assert finding.relative_change_percent == pytest.approx((after - before) / before * 100)
    assert finding.threshold == DEFAULT_CONFIG.changes[parameter].threshold
    assert finding.threshold_kind == kind
    assert finding.direction == ("increased" if after > before else "decreased")
    assert finding.severity == "attention"


def test_change_at_threshold_is_not_reported_and_zero_previous_skipped():
    findings = run([{"ph": 7.0, "feed_rate": 0.0}, {"ph": 7.3, "feed_rate": 5.0}])
    assert of_type(findings, "sudden_change") == []  # 0.3 is not > 0.3; relative change from 0 is undefined


# --- C. trend ---------------------------------------------------------------------------

def test_persistent_trend():
    findings = run([{"dissolved_oxygen_percent": v} for v in (60, 55, 50, 44, 38)])
    (trend,) = of_type(findings, "trend", "dissolved_oxygen_percent")
    assert trend.severity == "info"
    assert trend.direction == "decreased"
    assert len(trend.points) == 5
    assert trend.message == "Dissolved oxygen decreased across 5 consecutive observations from 0 h to 48 h (60.0 → 38.0 % air sat.)."
    assert of_type(findings, "sudden_change") == []  # each step is below the 15-point threshold


def test_trend_requires_three_points_and_minimum_change():
    assert of_type(run([{"dissolved_oxygen_percent": 60}, {"dissolved_oxygen_percent": 52}]), "trend") == []
    assert len(of_type(run([{"dissolved_oxygen_percent": v} for v in (60, 55, 50)]), "trend")) == 1
    noise = run([{"temperature_c": v} for v in (37.0, 37.02, 37.04, 37.06)])
    assert of_type(noise, "trend") == []  # 0.06 °C total is below the 0.5 °C trend minimum


# --- D. data coverage -------------------------------------------------------------------

def test_missing_optional_values():
    rows = [{"feed_rate": None}, {}, {"feed_rate": None}, {}]
    findings = run(rows, aeration_rate=None)
    messages = [f.message for f in of_type(findings, "data_coverage")]
    assert "Optional parameter(s) not recorded: Aeration rate." in messages
    assert "Feed rate is missing in 2 of 4 observations." in messages
    assert all(f.severity == "info" for f in of_type(findings, "data_coverage"))


def test_large_gap():
    findings = run([{}] * 5, times=[0, 2, 4, 6, 30])
    (gap,) = of_type(findings, "data_coverage")
    assert gap.message == "Observations contain a 24 h gap between 6 h and 30 h."
    assert (gap.previous_time_hours, gap.culture_time_hours, gap.absolute_change) == (6, 30, 24)


def test_repeated_time_points_and_single_time_point():
    findings = run([{}] * 3, times=[0, 12, 12])
    assert "1 observation(s) share a culture time with another observation (12 h)." in [
        f.message for f in of_type(findings, "data_coverage")]
    single = run([{}, {}], times=[5, 5])
    assert any(f.message.startswith("Only one distinct culture-time point") for f in single)


# --- E. co-occurrence -------------------------------------------------------------------

def test_multi_parameter_co_occurrence():
    findings = run([{"dissolved_oxygen_percent": 60, "cell_density": 2.0},
                    {"dissolved_oxygen_percent": 40, "cell_density": 3.5}])
    (co,) = of_type(findings, "co_occurrence")
    assert co.message == "Dissolved oxygen decreased while cell density increased over the same observation interval (0 h to 12 h)."
    assert set(co.related_parameters) == {"dissolved_oxygen_percent", "cell_density"}
    assert len(co.related_finding_ids) == 2
    assert co.severity == "attention"  # only one of the two changes is significant (cells +75%)
    assert "no causal relationship is inferred" in co.evidence[-2]


# --- severity & evidence ----------------------------------------------------------------

def test_severity_assignment():
    assert of_type(run([{}, {"ph": 6.4}, {}]), "range")[0].severity == "attention"  # 0.1 beyond
    assert of_type(run([{}, {"ph": 6.0}, {}]), "range")[0].severity == "significant"  # 0.5 > 0.3 margin
    assert of_type(run([{"temperature_c": 37}, {"temperature_c": 38.5}]), "sudden_change")[0].severity == "attention"
    assert of_type(run([{"temperature_c": 36}, {"temperature_c": 38.5}]), "sudden_change")[0].severity == "significant"
    both = run([{"dissolved_oxygen_percent": 80, "cell_density": 2.0}, {"dissolved_oxygen_percent": 40, "cell_density": 5.0}])
    assert of_type(both, "co_occurrence")[0].severity == "significant"
    ordered = [f.severity for f in both]
    assert ordered == sorted(ordered, key=["significant", "attention", "info"].index)


def test_evidence_fields_populated_via_api():
    create()
    for hours, fields in [(0, {}), (12, {"ph": 6.1, "dissolved_oxygen_percent": 70}), (24, {"dissolved_oxygen_percent": 45})]:
        add(hours, **fields)
    body = client.get("/api/experiments/EXP/anomalies").json()
    assert body["finding_count"] == len(body["findings"]) > 0
    assert sum(body["counts"].values()) == body["finding_count"]
    assert body["experiment"]["experiment_id"] == "EXP"
    for f in body["findings"]:
        assert f["evidence"] and f["message"] and f["type_label"] and f["experiment_id"] == "EXP"
    rng = next(f for f in body["findings"] if f["type"] == "range")
    assert rng["expected_min"] == 6.5 and rng["observed_value"] == 6.1 and rng["points"]
    change = next(f for f in body["findings"] if f["type"] == "sudden_change" and f["parameter"] == "dissolved_oxygen_percent")
    for key in ("previous_value", "observed_value", "threshold", "absolute_change", "relative_change_percent",
                "direction", "previous_time_hours", "culture_time_hours"):
        assert change[key] is not None, key


def test_source_experiment_unchanged():
    create()
    add(0)
    add(12, ph=6.0)
    before = (client.get("/api/experiments/EXP").json(), client.get("/api/experiments/EXP/observations").json())
    client.get("/api/experiments/EXP/anomalies")
    after = (client.get("/api/experiments/EXP").json(), client.get("/api/experiments/EXP/observations").json())
    assert before == after


def test_summary_is_factual():
    findings = run([{"dissolved_oxygen_percent": 60, "ph": 6.2}, {"dissolved_oxygen_percent": 40, "ph": 6.3}])
    from app.anomaly import summarize
    lines = summarize(findings, series([{}, {}]))
    assert lines[0] == f"{len(findings)} finding(s) were detected across 2 observation(s)."
    assert "2 parameter reading(s) were outside a prototype monitoring range." in lines
    banned = re.compile(r"\b(unsafe|dangerous|contamina\w*|failure|risky|high risk|safe)\b", re.I)
    assert not any(banned.search(line) for line in lines)
    assert not any(banned.search(f.message) for f in findings)
