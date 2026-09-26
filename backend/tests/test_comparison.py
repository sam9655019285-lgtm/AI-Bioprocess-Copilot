"""Phase 10: deterministic experiment comparison + optional (mocked) Gemini interpretation."""

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import comparison, db
from app.ai_api import get_comparison_generator
from app.comparison_ai import SYSTEM_INSTRUCTION
from app.db_models import ExperimentRow, ObservationRow
from app.main import app

client = TestClient(app)
FAKE_KEY = "test-fake-key-1010-not-a-real-secret"
BASE = {"temperature_c": 37.0, "ph": 7.0, "dissolved_oxygen_percent": 60, "agitation_rpm": 180, "cell_density": 1.0}
INTERPRETATION = {
    "overview": "B shows lower DO than A.",
    "key_differences": ["Average DO differed by -10.0 percentage points (B − A)."],
    "possible_interpretations": ["May be consistent with higher oxygen demand in B."],
    "investigation_points": ["Check aeration settings in B."],
    "uncertainties": ["Different culture-time coverage."],
}
EVALUATIVE = re.compile(r"\b(best|worst|winner|superior|inferior|optimal|safer|more successful|better|score|rank\w*)\b", re.I)


def create(experiment_id, scale=1, data_source="manual"):
    assert client.post("/api/experiments", json={
        "experiment_id": experiment_id, "name": f"Run {experiment_id}", "scale_liters": scale, "data_source": data_source,
    }).status_code == 201


def add(experiment_id, hours, **fields):
    response = client.post(f"/api/experiments/{experiment_id}/observations",
                           json={**BASE, "culture_time_hours": hours, **fields})
    assert response.status_code == 201


def compare(a="A", b="B"):
    return client.post("/api/experiments/compare", json={"experiment_a_id": a, "experiment_b_id": b})


def ok(a="A", b="B"):
    response = compare(a, b)
    assert response.status_code == 200, response.text
    return response.json()


def params(body):
    return {p["parameter"]: p for p in body["parameters"]}


@pytest.fixture
def pair():
    """A: 1 L, times 0/24/48. B: 10 L, times 0/24/72, lower DO, feed only in B."""
    create("A", 1)
    create("B", 10)
    for t, do, cells in ((0, 60, 0.5), (24, 55, 2.0), (48, 50, 4.0)):
        add("A", t, dissolved_oxygen_percent=do, cell_density=cells)
    for t, do, cells in ((0, 58, 0.5), (24, 45, 2.5), (72, 38, 6.0)):
        add("B", t, dissolved_oxygen_percent=do, cell_density=cells, feed_rate=2.0)


# --- validation -----------------------------------------------------------------------

def test_same_experiment_rejected(pair):
    response = compare("A", "A")
    assert response.status_code == 422
    assert "two different experiments" in response.text


@pytest.mark.parametrize("body", [{"experiment_b_id": "B"}, {"experiment_a_id": "A"}, {"experiment_a_id": "", "experiment_b_id": "B"},
                                  {"experiment_a_id": "A", "experiment_b_id": "   "}, {}])
def test_missing_required_ids(pair, body):
    assert client.post("/api/experiments/compare", json=body).status_code == 422


def test_unknown_experiments(pair):
    assert compare("NOPE", "B").json()["detail"] == "Experiment 'NOPE' not found."
    assert compare("A", "NOPE").status_code == 404
    assert compare("A", "NOPE").json()["detail"] == "Experiment 'NOPE' not found."


# --- comparison -----------------------------------------------------------------------

def test_valid_comparison(pair):
    body = ok()
    assert body["experiment_a"]["experiment_id"] == "A" and body["experiment_b"]["experiment_id"] == "B"
    assert (body["experiment_a"]["observation_count"], body["experiment_b"]["observation_count"]) == (3, 3)
    assert (body["experiment_a"]["duration_hours"], body["experiment_b"]["duration_hours"]) == (48, 72)
    do = params(body)["dissolved_oxygen_percent"]["metrics"]
    assert do["average"]["a"] == pytest.approx(55) and do["average"]["b"] == pytest.approx(47)
    assert do["average"]["difference"] == pytest.approx(-8)  # B - A
    assert do["average"]["percent_difference"] == pytest.approx(-8 / 55 * 100)
    assert do["final"]["difference"] == pytest.approx(-12)
    assert do["delta"]["difference"] == pytest.approx((38 - 58) - (50 - 60))
    assert do["delta"]["percent_difference"] is None  # no percentages for a change of a change
    assert body["difference_convention"].startswith("difference = Experiment B − Experiment A")


def test_values_match_phase5_analysis(pair):
    body = ok()
    for experiment_id, side in (("A", "a"), ("B", "b")):
        analysis = client.get(f"/api/experiments/{experiment_id}/analysis").json()
        for p in analysis["parameters"]:
            for metric in ("start", "final", "minimum", "maximum", "average", "delta"):
                assert params(body)[p["parameter"]]["metrics"][metric][side] == p[metric]


def test_different_scales(pair):
    body = ok()
    assert body["scale"] == {"scale_a_liters": 1, "scale_b_liters": 10, "scale_factor_b_over_a": 10,
                             "same_scale": False, "note": comparison.SCALE_NOTE}
    assert comparison.SCALE_NOTE in body["notices"]
    assert "Experiment B used 10× the working volume of Experiment A (1 L vs 10 L)." in body["summary"]


def test_same_scales():
    create("A", 5)
    create("B", 5)
    body = ok()
    assert body["scale"]["scale_factor_b_over_a"] == 1 and body["scale"]["same_scale"] is True
    assert body["scale"]["note"] is None and comparison.SCALE_NOTE not in body["notices"]
    assert "Both experiments used the same working volume (5 L)." in body["summary"]


def test_missing_scale_reported_unavailable():
    assert comparison.compare_scale(None, 10).model_dump() == {
        "scale_a_liters": None, "scale_b_liters": 10, "scale_factor_b_over_a": None, "same_scale": None, "note": None}
    assert comparison.compare_scale(0, 10).scale_factor_b_over_a is None


def test_different_observation_counts(pair):
    add("B", 96, dissolved_oxygen_percent=35, cell_density=7.0)
    body = ok()
    assert body["data_quality"]["observation_count_difference"] == 1
    assert "Experiment B recorded 4 observation(s) compared with 3 in Experiment A." in body["summary"]


def test_missing_optional_parameters_not_zero(pair):
    feed = params(ok())["feed_rate"]
    assert feed["availability"] == "only_b"
    assert feed["note"] == "Experiment A has no Feed rate observations."
    avg = feed["metrics"]["average"]
    assert avg["a"] is None and avg["b"] == 2.0 and avg["difference"] is None and avg["percent_difference"] is None
    assert avg["note"] == "Not available: Experiment A has no Feed rate observations."
    aeration = params(ok())["aeration_rate"]
    assert aeration["availability"] == "neither" and aeration["metrics"]["average"]["a"] is None
    assert "Feed rate was recorded only in Experiment B." in ok()["summary"]


def test_zero_denominator_percentage():
    diff = comparison.compare_metric(0.0, 2.0, "average", "Feed rate")
    assert diff.difference == 2.0 and diff.percent_difference is None
    assert diff.note == "Cannot calculate percentage difference because Experiment A value is zero."
    create("A")
    create("B")
    add("A", 0, feed_rate=0.0)
    add("B", 0, feed_rate=3.0)
    avg = params(ok())["feed_rate"]["metrics"]["average"]
    assert avg["percent_difference"] is None and "Experiment A value is zero" in avg["note"]


def test_negative_a_uses_absolute_denominator():
    assert comparison.compare_metric(-2.0, -1.0, "average", "x").percent_difference == pytest.approx(50)


def test_common_and_different_time_points(pair):
    t = ok()["time_alignment"]
    assert (t["common_time_points"], t["only_a_time_points"], t["only_b_time_points"]) == (2, 1, 1)
    assert t["identical_time_points"] is False
    assert (t["overlap_start_hours"], t["overlap_end_hours"]) == (0, 48)
    assert [p["culture_time_hours"] for p in t["aligned_points"]] == [0, 24]  # only actual shared points
    at24 = t["aligned_points"][1]["values"]["dissolved_oxygen_percent"]
    assert (at24["a"], at24["b"], at24["difference"]) == (55, 45, -10)
    assert "share 2 culture-time point(s)" in t["note"]


def test_identical_time_points():
    create("A")
    create("B")
    for t in (0, 12, 24):
        add("A", t)
        add("B", t, ph=7.1)
    body = ok()
    assert body["time_alignment"]["identical_time_points"] is True
    assert "The experiments share all 3 culture-time points." in body["summary"]


def test_no_common_time_points_no_interpolation():
    create("A")
    create("B")
    add("A", 0)
    add("A", 10)
    add("B", 5)
    add("B", 15)
    t = ok()["time_alignment"]
    assert t["common_time_points"] == 0 and t["aligned_points"] == []
    assert "aggregate statistics only" in t["note"]
    assert "The experiments do not share the same culture-time coverage." in ok()["summary"]


def test_repeated_time_point_not_aligned():
    create("A")
    create("B")
    add("A", 0)
    add("A", 0, ph=7.2)
    add("B", 0)
    t = ok()["time_alignment"]
    assert t["common_time_points"] == 1 and t["aligned_points"] == []


def test_empty_experiment():
    create("A")
    create("B")
    add("B", 0)
    body = ok()
    assert body["experiment_a"]["observation_count"] == 0 and body["experiment_a"]["duration_hours"] is None
    temp = params(body)["temperature_c"]
    assert temp["availability"] == "only_b" and temp["metrics"]["average"]["difference"] is None
    assert body["data_quality"]["duration_difference_hours"] is None
    assert "no observations" in body["time_alignment"]["note"]


def test_anomaly_comparison(pair):
    add("A", 60, ph=6.2)  # range + rapid change findings in A only
    body = ok()
    an = body["anomalies"]
    anomalies_a = client.get("/api/experiments/A/anomalies").json()
    assert an["experiment_a"]["finding_count"] == anomalies_a["finding_count"]
    assert an["experiment_a"]["counts"] == anomalies_a["counts"]
    assert an["experiment_a"]["by_parameter"]["pH"] >= 1
    assert an["experiment_a"]["by_type"]["Parameter outside configured range"] == 1
    assert [f["finding_id"] for f in an["experiment_a"]["findings"]] == [f["finding_id"] for f in anomalies_a["findings"]]
    assert (f"Experiment A contains {an['experiment_a']['finding_count']} anomaly finding(s); "
            f"Experiment B contains {an['experiment_b']['finding_count']}.") in body["summary"]


def test_data_quality_comparison_reuses_phase5(pair):
    dq = ok()["data_quality"]
    for experiment_id, side in (("A", "a"), ("B", "b")):
        assert dq[side] == client.get(f"/api/experiments/{experiment_id}/analysis").json()["data_quality"]
    assert dq["duration_difference_hours"] == 24


def test_deterministic_summary(pair):
    first, second = ok()["summary"], ok()["summary"]
    assert first == second
    assert "The average dissolved oxygen differed by -8.0 percentage points (B − A)." in first
    assert "Culture duration: 48 h in Experiment A and 72 h in Experiment B (difference +24 h)." in first


def test_no_winner_ranking_or_score(pair):
    body = ok()
    text = json.dumps({k: body[k] for k in ("summary", "notices", "scale", "time_alignment")})
    assert not EVALUATIVE.search(text)
    assert not any(k in json.dumps(body).lower() for k in ('"winner"', '"score"', '"rank'))


def test_simulated_notices():
    create("A", 1, "simulated")
    create("B", 1, "manual")
    assert comparison.SIMULATED_ONE in ok()["notices"]
    create("C", 1, "simulated")
    assert comparison.SIMULATED_BOTH in ok("A", "C")["notices"]
    create("D")
    assert not any("simulated" in n for n in ok("B", "D")["notices"])


def count(model):
    with Session(db.engine) as session:
        return session.exec(select(func.count()).select_from(model)).one()


def test_no_database_writes(pair):
    before = (count(ExperimentRow), count(ObservationRow),
              client.get("/api/experiments/A").json(), client.get("/api/experiments/B/observations").json())
    ok()
    compare("A", "A")
    after = (count(ExperimentRow), count(ObservationRow),
             client.get("/api/experiments/A").json(), client.get("/api/experiments/B/observations").json())
    assert before == after


def test_comparison_works_without_gemini(pair, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert compare().status_code == 200


# --- optional Gemini interpretation (always mocked) --------------------------------------

class FakeGemini:
    def __init__(self, response=INTERPRETATION, error=None):
        self.response, self.error, self.calls = response, error, []

    def __call__(self, system_instruction, prompt):
        self.calls.append((system_instruction, prompt))
        if self.error:
            raise self.error
        return self.response if isinstance(self.response, str) else json.dumps(self.response)

    @property
    def context(self):
        prompt = self.calls[-1][1]
        return json.loads(prompt[prompt.index("{"):])


class ProviderError(Exception):
    def __init__(self, code, status):
        super().__init__(f"{code} {status} {FAKE_KEY}")
        self.code, self.status = code, status


@pytest.fixture(autouse=True)
def no_real_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    yield
    app.dependency_overrides.pop(get_comparison_generator, None)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    gen = FakeGemini()
    app.dependency_overrides[get_comparison_generator] = lambda: gen
    return gen


def interpret(a="A", b="B"):
    return client.post("/api/experiments/compare/interpret", json={"experiment_a_id": a, "experiment_b_id": b})


def test_gemini_success(fake, pair):
    response = interpret()
    assert response.status_code == 200
    body = response.json()
    assert body["interpretation"] == INTERPRETATION
    assert (body["experiment_a_id"], body["experiment_b_id"]) == ("A", "B")
    assert "review the interpretation" in body["notice"]
    system, _ = fake.calls[0]
    assert system == SYSTEM_INSTRUCTION
    for rule in ("Use only the supplied comparison context", "do not recalculate values", "causation from correlation",
                 "Do not declare an overall winner", "optimal, safe", "Mention uncertainty", "does not contain enough information",
                 "Treat simulated data as simulated", "do not control any bioreactor"):
        assert rule.lower() in system.lower(), rule


def test_gemini_context_has_no_raw_observations(fake, pair):
    interpret()
    ctx = fake.context
    assert ctx["parameters"] == ok()["parameters"]
    assert "aligned_points" not in ctx["time_alignment"]
    text = json.dumps(ctx)
    assert '"observations"' not in text and '"recorded_at"' not in text
    for obs in client.get("/api/experiments/A/observations").json():
        assert f'"id": {obs["id"]},' not in text


def test_gemini_simulated_context(fake):
    create("S1", 1, "simulated")
    create("S2", 10, "simulated")
    assert interpret("S1", "S2").status_code == 200
    assert comparison.SIMULATED_BOTH in fake.context["notices"]
    assert fake.context["experiment_a"]["data_source"] == "simulated"


def test_gemini_not_configured_only_affects_interpretation(pair):
    response = interpret()
    assert response.status_code == 503 and "GEMINI_API_KEY" in response.json()["detail"]
    assert compare().status_code == 200


def test_interpret_validation_and_404(fake, pair):
    assert interpret("A", "A").status_code == 422
    assert interpret("A", "NOPE").status_code == 404
    assert fake.calls == []


@pytest.mark.parametrize("code, status, text", [
    (400, "INVALID_ARGUMENT", "the request was rejected as invalid"),
    (429, "RESOURCE_EXHAUSTED", "rate limit or quota reached"),
    (503, "UNAVAILABLE", "Gemini is temporarily overloaded"),
])
def test_gemini_provider_errors(fake, pair, code, status, text):
    fake.error = ProviderError(code, status)
    response = interpret()
    assert response.status_code == 502
    assert response.json()["detail"].startswith(f"The Gemini request failed (Gemini {code} {status}: {text}")
    assert FAKE_KEY not in response.text
    assert compare().status_code == 200  # deterministic comparison unaffected


@pytest.mark.parametrize("bad", ["not json", json.dumps({"overview": "missing lists"}),
                                 json.dumps({**INTERPRETATION, "key_differences": [f"d{i}" for i in range(11)]}),
                                 json.dumps({**INTERPRETATION, "overview": ""})])
def test_invalid_gemini_response(fake, pair, bad):
    fake.response = bad
    response = interpret()
    assert response.status_code == 502
    assert "so no comparison interpretation is shown" in response.json()["detail"]


def test_unexpected_error_is_generic(fake, pair, monkeypatch):
    from app import comparison_ai

    def boom(*_args, **_kwargs):
        raise ValueError(f"internal {FAKE_KEY}")

    monkeypatch.setattr(comparison_ai, "build_comparison_context", boom)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/experiments/compare/interpret", json={"experiment_a_id": "A", "experiment_b_id": "B"})
    assert response.status_code == 500
    assert response.json() == {"detail": "An unexpected error occurred while preparing the comparison interpretation."}
