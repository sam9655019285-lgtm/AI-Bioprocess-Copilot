"""Phase 17: live monitoring & alerts (LiveMonitor, simulator WebSocket alerts, Copilot alert focus)."""

import json

import pytest
from fastapi.testclient import TestClient

from app import anomaly
from app import monitoring as mon
from app.ai_api import get_copilot_generator
from app.main import app
from app.models import Observation

client = TestClient(app)
FAKE_KEY = "test-fake-key-17-do-not-leak"
BASE = {"temperature_c": 37.0, "ph": 7.0, "dissolved_oxygen_percent": 60.0, "agitation_rpm": 180.0, "cell_density": 1.0}


def obs(t, **extra):
    return Observation(experiment_id="RUN", culture_time_hours=t, **{**BASE, **extra})


def feed(monitor, observations, saved=False):
    return [e for o in observations for e in monitor.add(o, saved)]


# --- keys ---------------------------------------------------------------------------------------

def test_stable_keys():
    findings = anomaly.detect("RUN", [obs(0), obs(1, temperature_c=40.5, ph=7.5), obs(2, temperature_c=40.6)])
    keys = mon.keyed_findings(findings)
    assert "range:temperature_c:1.0" in keys  # episode keyed by its start
    assert "change:temperature_c:1.0" in keys and "change:ph:1.0" in keys
    assert "cooccurrence:1.0" in keys
    assert all(mon.alert_key(f) is None for f in findings if f.type == "data_coverage" and f.previous_time_hours is None)


# --- LiveMonitor --------------------------------------------------------------------------------

def test_normal_run_produces_no_alerts():
    m = mon.LiveMonitor("RUN")
    assert feed(m, [obs(t * 0.5) for t in range(20)]) == []  # constant in-range values; coverage notes are not alerts


def test_new_then_updated_not_repeated_new():
    m = mon.LiveMonitor("RUN")
    feed(m, [obs(0), obs(0.5)])
    first = m.add(obs(1, temperature_c=39.5))  # also a 2.5 °C step -> a separate sudden-change alert
    assert sorted((e["event"], e["alert"]["alert_id"]) for e in first) == [("new", "change:temperature_c:1.0"), ("new", "range:temperature_c:1.0")]
    alert = next(e["alert"] for e in first if e["alert"]["alert_id"].startswith("range"))
    assert alert["experiment_id"] == "RUN" and alert["detected_at_hours"] == 1 and alert["saved"] is False
    assert alert["finding"]["severity"] == "attention" and alert["finding"]["type"] == "range"
    later = [e for e in feed(m, [obs(1.5, temperature_c=39.6), obs(2, temperature_c=39.7)]) if e["alert"]["alert_id"].startswith("range")]
    assert [e["event"] for e in later] == ["updated", "updated"]  # same episode grows: no second "new"
    assert all(e["alert"]["detected_at_hours"] == 1 for e in later)


def test_severity_escalation_is_an_update():
    m = mon.LiveMonitor("RUN")
    feed(m, [obs(0), obs(0.5, temperature_c=39.5)])
    events = m.add(obs(1, temperature_c=40.4))  # > 1 °C beyond 39 -> significant
    rng = next(e for e in events if e["alert"]["alert_id"] == "range:temperature_c:0.5")
    assert rng["event"] == "updated" and rng["alert"]["finding"]["severity"] == "significant"


def test_sudden_change_and_cooccurrence_are_single_events():
    m = mon.LiveMonitor("RUN")
    feed(m, [obs(0)])
    events = m.add(obs(0.5, temperature_c=39.5, ph=7.7))
    ids = {e["alert"]["alert_id"]: e for e in events}
    assert ids["change:temperature_c:0.5"]["alert"]["finding"]["severity"] == "significant"  # 2.5 °C > 2 × 1 °C
    assert "cooccurrence:0.5" in ids and all(e["event"] == "new" for e in events)
    assert not [e for e in m.add(obs(1, temperature_c=39.5, ph=7.7)) if e["alert"]["alert_id"].startswith("change")]


def test_duplicate_observation_and_duplicate_time_do_not_duplicate_alerts():
    m = mon.LiveMonitor("RUN")
    feed(m, [obs(0), obs(0.5, temperature_c=39.5)])
    again = m.add(obs(0.5, temperature_c=39.5))  # exact duplicate (same culture time, same values)
    assert all(e["event"] == "updated" for e in again)  # the episode gained a point; no new alert
    assert not [e for e in m.add(obs(0.5, temperature_c=39.5)) if e["event"] == "new"]


def test_missing_values_and_insufficient_data():
    m = mon.LiveMonitor("RUN")
    assert m.add(obs(0, feed_rate=None, aeration_rate=None)) == []  # one point: nothing to compare
    events = m.add(obs(0.5, feed_rate=2.0))  # optional value appears; missing is never treated as an anomaly
    assert events == []


def test_window_cap_bounds_memory():
    m = mon.LiveMonitor("RUN", window_size=5)
    feed(m, [obs(t) for t in range(20)])
    assert len(m.window) == 5 and m.window[0].culture_time_hours == 15


def test_deterministic_and_consistent_with_detect():
    series = [obs(0), obs(0.5, temperature_c=38.0), obs(1, temperature_c=39.8, dissolved_oxygen_percent=35.0),
              obs(1.5, temperature_c=40.5, dissolved_oxygen_percent=15.0), obs(2, temperature_c=37.2, dissolved_oxygen_percent=18.0)]
    a, b = mon.LiveMonitor("RUN"), mon.LiveMonitor("RUN")
    assert feed(a, series) == feed(b, series)
    expected = {mon.alert_key(f): f.model_dump(mode="json") for f in anomaly.detect("RUN", series) if mon.alert_key(f)}
    assert {k: f.model_dump(mode="json") for k, f in a.current.items()} == expected  # exactly detect() output


# --- simulator WebSocket ------------------------------------------------------------------------

CONFIG = {"seed": 7, "interval_seconds": 0.05}


def receive_until(ws, predicate, limit=200):
    for _ in range(limit):
        m = ws.receive_json()
        if predicate(m):
            return m
    raise AssertionError("expected message not received")


def test_ws_disturbance_triggers_alert_after_observation():
    with client.websocket_connect("/api/simulator/ws") as ws:
        ws.receive_json()  # initial status
        ws.send_json({"action": "start", "config": CONFIG})
        receive_until(ws, lambda m: m["type"] == "observation" and m["observation"]["culture_time_hours"] >= 1)
        ws.send_json({"action": "disturb", "parameter": "temperature_c", "offset": 3})
        disturbed = receive_until(ws, lambda m: m["type"] == "observation" and (m["observation"]["notes"] or "").startswith("SIMULATED DISTURBANCE"))
        assert disturbed["observation"]["temperature_c"] > 39.5
        alert = receive_until(ws, lambda m: m["type"] == "alert")
        assert alert["event"] == "new" and alert["alert"]["alert_id"].startswith(("change:temperature_c", "range:temperature_c"))
        assert alert["alert"]["detected_at_hours"] == disturbed["observation"]["culture_time_hours"]
        assert alert["alert"]["saved"] is False
        ws.send_json({"action": "stop"})


def test_ws_invalid_disturbance():
    with client.websocket_connect("/api/simulator/ws") as ws:
        ws.receive_json()
        ws.send_json({"action": "disturb", "parameter": "temperature_c", "offset": 3})
        assert "no simulated run" in ws.receive_json()["message"].lower()
        ws.send_json({"action": "start", "config": CONFIG})
        for bad in ({"parameter": "cell_density", "offset": 1}, {"parameter": "ph", "offset": "x"},
                    {"parameter": "ph", "offset": 50}, {"parameter": "ph"}):
            ws.send_json({"action": "disturb", **bad})
            m = receive_until(ws, lambda m: m["type"] == "error", limit=400)
            assert "disturbance" in m["message"].lower()
        ws.send_json({"action": "reset"})


def test_ws_reset_clears_monitor_and_pause_resume_does_not_repeat():
    with client.websocket_connect("/api/simulator/ws") as ws:
        ws.receive_json()
        ws.send_json({"action": "start", "config": CONFIG})
        receive_until(ws, lambda m: m["type"] == "observation")
        ws.send_json({"action": "disturb", "parameter": "temperature_c", "offset": 3})
        first = receive_until(ws, lambda m: m["type"] == "alert" and m["event"] == "new")
        ws.send_json({"action": "stop"})
        receive_until(ws, lambda m: m["type"] == "status" and m["status"] == "stopped")
        ws.send_json({"action": "start"})
        receive_until(ws, lambda m: m["type"] == "status" and m["status"] == "simulating")
        seen = [receive_until(ws, lambda m: m["type"] in ("observation", "alert")) for _ in range(6)]
        assert not [m for m in seen if m["type"] == "alert" and m["event"] == "new" and m["alert"]["alert_id"] == first["alert"]["alert_id"]]
        ws.send_json({"action": "reset"})
        receive_until(ws, lambda m: m["type"] == "status" and m["run"] is None)
        ws.send_json({"action": "start", "config": CONFIG})
        ws.send_json({"action": "disturb", "parameter": "temperature_c", "offset": 3})
        again = receive_until(ws, lambda m: m["type"] == "alert")
        assert again["event"] == "new"  # a new run starts with a fresh monitor
        ws.send_json({"action": "reset"})


def test_ws_saved_run_marks_alerts_saved():
    body = {"experiment_id": "SIM-SAVE", "name": "s", "scale_liters": 1, "data_source": "simulated"}
    assert client.post("/api/experiments", json=body).status_code == 201
    with client.websocket_connect("/api/simulator/ws") as ws:
        ws.receive_json()
        ws.send_json({"action": "start", "config": CONFIG, "save_to": "SIM-SAVE"})
        receive_until(ws, lambda m: m["type"] == "observation")
        ws.send_json({"action": "disturb", "parameter": "temperature_c", "offset": 3})
        alert = receive_until(ws, lambda m: m["type"] == "alert")
        assert alert["alert"]["saved"] is True and alert["alert"]["experiment_id"] == "SIM-SAVE"
        ws.send_json({"action": "stop"})
        receive_until(ws, lambda m: m["type"] == "status" and m["status"] == "stopped")
    stored = client.get("/api/experiments/SIM-SAVE/observations").json()
    assert any((o["notes"] or "").startswith("SIMULATED DISTURBANCE") for o in stored)


# --- Copilot alert focus (Gemini mocked) --------------------------------------------------------

@pytest.fixture
def stored_alert_run():
    body = {"experiment_id": "ALERT", "name": "a", "scale_liters": 1, "data_source": "manual"}
    assert client.post("/api/experiments", json=body).status_code == 201
    for t, temp in ((0, 37.0), (0.5, 37.1), (1, 40.5), (1.5, 40.6)):
        o = {**BASE, "culture_time_hours": t, "temperature_c": temp}
        assert client.post("/api/experiments/ALERT/observations", json=o).status_code == 201


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    calls = []

    def fake(system, prompt):
        calls.append(prompt)
        return json.dumps({"answer": "ok", "evidence": [], "uncertainties": [], "suggested_questions": []})

    app.dependency_overrides[get_copilot_generator] = lambda: fake
    yield calls
    app.dependency_overrides.pop(get_copilot_generator, None)


def copilot(body, experiment_id="ALERT"):
    return client.post(f"/api/experiments/{experiment_id}/copilot", json=body)


def context_of(prompt):
    return json.loads(prompt[prompt.index("{"):prompt.rindex("SCIENTIST'S QUESTION")].strip())


def test_copilot_focus_alert_located_server_side(stored_alert_run, gemini):
    r = copilot({"message": "Explain this alert.", "alert": {"alert_id": "range:temperature_c:1.0"}})
    assert r.status_code == 200 and FAKE_KEY not in r.text
    focus = context_of(gemini[0])["focus_alert"]
    assert focus["alert_id"] == "range:temperature_c:1.0"
    assert focus["finding"]["type"] == "range" and focus["finding"]["severity"] == "significant"
    assert [p["culture_time_hours"] for p in focus["finding"]["points"]] == [1.0, 1.5]  # bounded evidence points only
    assert "observations" not in context_of(gemini[0])
    assert FAKE_KEY not in gemini[0]


def test_copilot_unknown_alert_is_404_without_gemini(stored_alert_run, gemini):
    r = copilot({"message": "Explain.", "alert": {"alert_id": "range:ph:99.0"}})
    assert r.status_code == 404 and gemini == []


@pytest.mark.parametrize("alert", [{"alert_id": ""}, {"alert_id": "x" * 201}, {"alert_id": "a", "finding": {}}])
def test_copilot_invalid_alert_is_422(stored_alert_run, gemini, alert):
    assert copilot({"message": "Explain.", "alert": alert}).status_code == 422 and gemini == []


def test_copilot_without_alert_unchanged(stored_alert_run, gemini):
    assert copilot({"message": "Summarise."}).status_code == 200
    assert "focus_alert" not in context_of(gemini[0])


def test_copilot_alert_needs_gemini_key(stored_alert_run, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert copilot({"message": "Explain.", "alert": {"alert_id": "range:temperature_c:1.0"}}).status_code == 503
