"""Phase 18: Alert Investigation - finding precedents (deterministic; Gemini always mocked)."""

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import db
from app import precedents as pr
from app.ai_api import get_copilot_generator
from app.db_models import ExperimentRow, ObservationRow
from app.main import app

client = TestClient(app)
FAKE_KEY = "test-fake-key-18-do-not-leak"
BASE = {"temperature_c": 37.0, "ph": 7.0, "dissolved_oxygen_percent": 50.0, "agitation_rpm": 180.0, "cell_density": 1.0}
BANNED = re.compile(r"optimal|guarantee|\bbest\b|will improve|will recover|caused by|recommend", re.IGNORECASE)
DO_BELOW = {"type": "range", "parameter": "dissolved_oxygen_percent", "direction": "below"}


def create(experiment_id, rows, scale=1, source="manual"):
    body = {"experiment_id": experiment_id, "name": f"Run {experiment_id}", "scale_liters": scale, "data_source": source}
    assert client.post("/api/experiments", json=body).status_code == 201
    for t, extra in rows:
        r = client.post(f"/api/experiments/{experiment_id}/observations", json={**BASE, "culture_time_hours": t, **extra})
        assert r.status_code == 201, r.text


def do(*pairs):
    return [(t, {"dissolved_oxygen_percent": v}) for t, v in pairs]


@pytest.fixture
def history():
    # Created oldest -> newest: PREV-1, PREV-2, OTHER, CUR
    create("PREV-1", do((0, 50), (2, 40), (4, 15), (6, 18), (8, 25), (10, 30)))  # below 4–6 h, back in range at 8 h
    create("PREV-2", do((0, 50), (2, 15), (4, 12), (6, 10)), scale=10)  # below from 2 h, never back; run ends at 6 h
    create("OTHER", [(0, {}), (1, {"temperature_c": 40.0}), (2, {"temperature_c": 40.2})])  # unrelated rule
    create("CUR", do((0, 50), (1, 45), (2, 15), (3, 30), (4, 31), (5, 14)))  # earlier episode at 2 h, current at 5 h


def search(body):
    return client.post("/api/precedents/search", json=body)


def ids(result):
    return [(p["experiment_id"], p["trigger_time_hours"]) for p in result["precedents"]]


# --- exact matching ------------------------------------------------------------------------------

def test_exact_match_by_type_parameter_direction(history):
    r = search(DO_BELOW).json()
    assert ids(r) == [("CUR", 2.0), ("CUR", 5.0), ("PREV-2", 2.0), ("PREV-1", 4.0)]
    assert r["matching_experiments"] == 3 and r["experiments_searched"] == 4
    assert search({**DO_BELOW, "direction": "above"}).json()["precedents"] == []  # direction
    assert search({**DO_BELOW, "parameter": "ph"}).json()["precedents"] == []  # parameter
    changes = search({"type": "sudden_change", "parameter": "dissolved_oxygen_percent", "direction": "decreased"}).json()
    assert {p["finding_type"] for p in changes["precedents"]} == {"sudden_change"}  # type
    assert ("PREV-1", 4.0) in ids(changes) and ("PREV-1", 2.0) not in ids(changes)  # −10 is below the 15-point threshold


def test_unrelated_finding_excluded(history):
    assert all(p["experiment_id"] != "OTHER" for p in search(DO_BELOW).json()["precedents"])
    temp = search({"type": "range", "parameter": "temperature_c", "direction": "above"}).json()
    assert [p["experiment_id"] for p in temp["precedents"]] == ["OTHER"]


def test_co_occurrence_exact_parameter_set():
    create("CO-A", [(0, {}), (1, {"ph": 7.5, "dissolved_oxygen_percent": 30})])  # pH + DO change together
    create("CO-B", [(0, {}), (1, {"ph": 7.5, "dissolved_oxygen_percent": 30, "temperature_c": 38.5})])  # pH + DO + temperature
    q = {"type": "co_occurrence", "related_parameters": ["ph", "dissolved_oxygen_percent"]}
    assert [p["experiment_id"] for p in search(q).json()["precedents"]] == ["CO-A"]
    q3 = {"type": "co_occurrence", "related_parameters": ["temperature_c", "ph", "dissolved_oxygen_percent"]}
    assert [p["experiment_id"] for p in search(q3).json()["precedents"]] == ["CO-B"]  # no partial overlap
    p = search(q).json()["precedents"][0]
    assert p["related_parameters"] == ["dissolved_oxygen_percent", "ph"] and p["follow_up"]["range_return"] is None


def test_exclude_experiment(history):
    r = search({**DO_BELOW, "exclude_experiment_id": "CUR"}).json()
    assert [p["experiment_id"] for p in r["precedents"]] == ["PREV-2", "PREV-1"]
    assert r["experiments_excluded"] == 1 and r["experiments_searched"] == 3


def test_current_finding_never_matches_itself_and_earlier_episode_is_labelled(history):
    r = search({**DO_BELOW, "current": {"experiment_id": "CUR", "alert_id": "range:dissolved_oxygen_percent:5.0"}}).json()
    assert ids(r) == [("CUR", 2.0), ("PREV-2", 2.0), ("PREV-1", 4.0)]
    first = r["precedents"][0]
    assert first["same_run"] is True and first["relation"] == "Earlier in this run"
    assert r["precedents"][1]["relation"] == "Stored experiment"
    # investigating the EARLIER episode: the later one is not a precedent, and neither is the finding itself
    r2 = search({**DO_BELOW, "current": {"experiment_id": "CUR", "alert_id": "range:dissolved_oxygen_percent:2.0"}}).json()
    assert ("CUR", 2.0) not in ids(r2) and ("CUR", 5.0) not in ids(r2)


def test_unsaved_live_run_searches_stored_only(history):
    r = search({**DO_BELOW, "current": {"experiment_id": "SIM-1L-LIVE", "alert_id": "range:dissolved_oxygen_percent:1.0"}}).json()
    assert "SIM-1L-LIVE" not in {p["experiment_id"] for p in r["precedents"]} and len(r["precedents"]) == 4


# --- follow-up -----------------------------------------------------------------------------------

def precedent(result, experiment_id):
    return next(p for p in result["precedents"] if p["experiment_id"] == experiment_id)


def test_follow_up_returned_to_range(history):
    p = precedent(search(DO_BELOW).json(), "PREV-1")
    fu = p["follow_up"]
    assert (fu["window_start_hours"], fu["window_end_hours"]) == (4.0, 16.0)
    assert fu["range_return"]["status"] == "returned" and fu["range_return"]["returned_at_hours"] == 8.0
    assert fu["range_return"]["range_min"] == 20 and fu["range_return"]["range_max"] == 100
    assert fu["values_at_window_end"][0]["value"] == 30.0 and fu["values_at_window_end"][0]["culture_time_hours"] == 10.0
    assert fu["run_ended_before_window_end"] is True and fu["observed_until_hours"] == 10.0  # no extrapolation
    assert p["episode_end_hours"] == 6.0 and p["severity"] == "attention"  # 5 below 20 %, within the 10-point margin
    assert (p["data_source"], p["scale_liters"], p["name"]) == ("manual", 1.0, "Run PREV-1")


def test_follow_up_never_returned_and_later_findings(history):
    fu = precedent(search(DO_BELOW).json(), "PREV-2")["follow_up"]
    assert fu["range_return"]["status"] == "not_observed_in_window" and fu["range_return"]["returned_at_hours"] is None
    assert "failed" not in fu["range_return"]["note"].lower()
    assert all(f["culture_time_hours"] > 2.0 for f in fu["later_findings"])
    changes = search({"type": "sudden_change", "parameter": "dissolved_oxygen_percent", "direction": "decreased"}).json()
    fu2 = next(p for p in changes["precedents"] if p["experiment_id"] == "PREV-1")["follow_up"]
    assert fu2["range_return"]["status"] == "returned" and fu2["range_return"]["returned_at_hours"] == 8.0


def test_follow_up_window_is_configurable_and_full_window(history):
    fu = precedent(search({**DO_BELOW, "follow_up_hours": 3}).json(), "PREV-1")["follow_up"]
    assert fu["window_end_hours"] == 7.0 and fu["run_ended_before_window_end"] is False
    assert fu["range_return"]["status"] == "not_observed_in_window"  # 8 h is outside a 3 h window
    assert fu["values_at_window_end"][0]["culture_time_hours"] == 6.0


def test_missing_values_and_no_prototype_range():
    create("AER", [(0, {"aeration_rate": 0.1}), (1, {}), (2, {"aeration_rate": 0.2}), (3, {"aeration_rate": 0.2})])
    r = search({"type": "sudden_change", "parameter": "aeration_rate", "direction": "increased"}).json()
    p = r["precedents"][0]
    assert p["trigger_time_hours"] == 2.0  # missing value skipped, not treated as 0
    assert p["follow_up"]["range_return"]["status"] == "no_prototype_range"


def test_duplicate_times_empty_and_insufficient():
    create("DUP", do((0, 50), (1, 15), (1, 15), (2, 25)))
    create("EMPTY", [])
    create("ONE", do((0, 10)))
    r = search(DO_BELOW).json()
    assert r["experiments_searched"] == 3
    assert {p["experiment_id"] for p in r["precedents"]} == {"DUP", "ONE"}  # a single out-of-range reading is still a range finding
    assert r == search(DO_BELOW).json()


def test_deterministic(history):
    assert search(DO_BELOW).json() == search(DO_BELOW).json()


def test_cap_and_skipped_reported(history, monkeypatch):
    monkeypatch.setattr(pr, "MAX_EXPERIMENTS", 2)
    r = search(DO_BELOW).json()
    assert r["experiments_searched"] == 2 and r["experiments_skipped"] == 2 and r["search_cap"] == 2
    assert {p["experiment_id"] for p in r["precedents"]} == {"CUR"}  # the two newest: CUR, OTHER
    assert any("2 older experiment(s) were not" in line for line in r["limitations"])


def test_limitations_and_no_causation(history):
    r = search(DO_BELOW).json()
    assert r["no_causation_note"] == "No causal inference is made from these historical observations."
    assert r["no_causation_note"] in r["limitations"] and r["experiments_skipped"] == 0


def test_no_results_is_not_a_conclusion(history):
    r = search({"type": "trend", "parameter": "ph", "direction": "increased"}).json()
    assert r["precedents"] == [] and r["matching_experiments"] == 0 and r["experiments_searched"] == 4


def count(model):
    with Session(db.engine) as s:
        return s.exec(select(func.count()).select_from(model)).one()


def test_no_database_writes(history):
    before = (count(ExperimentRow), count(ObservationRow))
    search(DO_BELOW)
    search({"type": "co_occurrence", "related_parameters": ["ph", "dissolved_oxygen_percent"]})
    assert (count(ExperimentRow), count(ObservationRow)) == before


@pytest.mark.parametrize("bad", [
    {},
    {"type": "data_coverage"},
    {"type": "range", "parameter": "dissolved_oxygen_percent"},  # direction missing
    {"type": "range", "parameter": "dissolved_oxygen_percent", "direction": "increased"},  # wrong direction for type
    {"type": "sudden_change", "parameter": "glucose", "direction": "increased"},
    {"type": "co_occurrence", "related_parameters": ["ph"]},
    {"type": "co_occurrence", "related_parameters": ["ph", "bogus"]},
    {"type": "co_occurrence", "parameter": "ph", "related_parameters": ["ph", "temperature_c"]},
    {**DO_BELOW, "related_parameters": ["ph", "temperature_c"]},
    {**DO_BELOW, "follow_up_hours": 0}, {**DO_BELOW, "follow_up_hours": 500},
    {**DO_BELOW, "current": {"experiment_id": "X"}},
    {**DO_BELOW, "similarity": 0.9},  # extra fields rejected
])
def test_invalid_requests(bad):
    assert search(bad).status_code == 422


def test_search_never_calls_gemini(history, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    app.dependency_overrides[get_copilot_generator] = lambda: pytest.fail
    try:
        assert search(DO_BELOW).status_code == 200
    finally:
        app.dependency_overrides.pop(get_copilot_generator, None)


def test_no_unsafe_wording(history):
    r = search({**DO_BELOW, "current": {"experiment_id": "CUR", "alert_id": "range:dissolved_oxygen_percent:5.0"}}).json()
    texts = r["limitations"] + [r["no_causation_note"]]
    for p in r["precedents"]:
        fu = p["follow_up"]
        texts += [p["message"], p["relation"], fu["range_return"]["note"]] + [f["message"] for f in fu["later_findings"]]
    assert not [t for t in texts if BANNED.search(t)]


# --- Copilot integration (Gemini mocked) ---------------------------------------------------------

@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    calls = []

    def fake(system, prompt):
        calls.append((system, prompt))
        return json.dumps({"answer": "ok", "evidence": [], "uncertainties": [], "suggested_questions": []})

    app.dependency_overrides[get_copilot_generator] = lambda: fake
    yield calls
    app.dependency_overrides.pop(get_copilot_generator, None)


def context_of(prompt):
    return json.loads(prompt[prompt.index("{"):prompt.rindex("SCIENTIST'S QUESTION")].strip())


def explain(include, experiment_id="CUR", alert_id="range:dissolved_oxygen_percent:5.0"):
    alert = {"alert_id": alert_id} if include is None else {"alert_id": alert_id, "include_precedents": include}
    return client.post(f"/api/experiments/{experiment_id}/copilot", json={"message": "Explain this alert.", "alert": alert})


def test_copilot_include_precedents_bounded_summary(history, gemini):
    for i in range(6):  # 6 more stored runs with the same rule -> more than 5 precedents in total
        create(f"MORE-{i}", do((0, 50), (1, 15)))
    r = explain(True)
    assert r.status_code == 200 and FAKE_KEY not in r.text
    system, prompt = gemini[0]
    summary = context_of(prompt)["focus_alert"]["precedents"]
    assert len(summary["precedents"]) == 5 and summary["precedents_total"] == 9 and summary["precedents_omitted"] == 4
    assert summary["precedents"][0]["relation"] == "Earlier in this run"
    text = json.dumps(summary)
    assert '"points"' not in text and '"observations"' not in text and "culture_time_hours" not in text
    assert "observations" not in context_of(prompt)
    assert "same-rule matches in stored data" in system.lower() and FAKE_KEY not in prompt + system


def test_copilot_without_precedents_unchanged(history, gemini):
    assert explain(None).status_code == 200 and explain(False).status_code == 200
    first, second = context_of(gemini[0][1]), context_of(gemini[1][1])
    assert "precedents" not in first["focus_alert"] and first == second  # default and explicit False are identical


def test_copilot_unknown_alert_404_and_no_key_503(history, gemini, monkeypatch):
    assert explain(True, alert_id="range:ph:99.0").status_code == 404 and gemini == []
    monkeypatch.delenv("GEMINI_API_KEY")
    assert explain(True).status_code == 503 and gemini == []
