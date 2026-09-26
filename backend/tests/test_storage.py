from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, func, select

from app import db, repository, simulator_api
from app.db_models import ObservationRow
from app.main import app
from app.models import Observation

client = TestClient(app)

OBSERVATION = {
    "culture_time_hours": 24,
    "temperature_c": 37.0,
    "ph": 7.05,
    "dissolved_oxygen_percent": 82,
    "agitation_rpm": 120,
    "cell_density": 0.85,
}
HEADER = "culture_time_hours,temperature_c,ph,dissolved_oxygen_percent,agitation_rpm,cell_density,notes"


def create(experiment_id="EXP-A", data_source="manual", **extra):
    payload = {"experiment_id": experiment_id, "name": f"Run {experiment_id}", "scale_liters": 10,
               "data_source": data_source, **extra}
    return client.post("/api/experiments", json=payload)


def add(target, **fields):
    return client.post(f"/api/experiments/{target}/observations", json={**OBSERVATION, **fields})


def upload(experiment_id, csv_text, filename="data.csv"):
    return client.post(
        f"/api/experiments/{experiment_id}/upload",
        files={"file": (filename, csv_text.encode("utf-8"), "text/csv")},
    )


def stored_observation_count(experiment_id=None):
    with Session(db.engine) as session:
        query = select(func.count()).select_from(ObservationRow)
        if experiment_id:
            query = query.where(ObservationRow.experiment_id == experiment_id)
        return session.exec(query).one()


def receive(ws, message_type):
    for _ in range(20):
        message = ws.receive_json()
        if message["type"] == message_type:
            return message
    raise AssertionError(f"No {message_type!r} message received")


# --- 1. Database initialisation ---------------------------------------------------

def test_database_initialises_from_missing_file(tmp_path):
    path = tmp_path / "nested" / "new.db"
    engine = db.create_db_engine(f"sqlite:///{path.as_posix()}")
    db.init_db(engine)
    assert path.exists()
    assert {"experiments", "observations"} <= set(inspect(engine).get_table_names())
    (fk,) = inspect(engine).get_foreign_keys("observations")
    assert fk["referred_table"] == "experiments"
    assert fk["options"].get("ondelete") == "CASCADE"
    engine.dispose()


def test_app_startup_creates_tables():
    with TestClient(app) as started:  # runs the lifespan (init_db)
        assert started.get("/api/experiments").status_code == 200
    assert {"experiments", "observations"} <= set(inspect(db.engine).get_table_names())


def test_observation_table_matches_validation_model():
    stored = set(ObservationRow.model_fields) - {"id", "recorded_at"}
    assert stored == set(Observation.model_fields)


# --- 2-5. Experiments -------------------------------------------------------------

def test_create_experiment():
    response = create(description="Pilot", notes="first")
    assert response.status_code == 201
    body = response.json()
    assert body["experiment_id"] == "EXP-A"
    assert body["data_source"] == "manual"
    assert body["scale_liters"] == 10
    assert body["observation_count"] == 0
    assert body["created_at"].endswith(("Z", "+00:00"))


def test_create_experiment_validation():
    assert create(data_source="spreadsheet").status_code == 422
    assert create(experiment_id="bad id/with slash").status_code == 422
    assert create(experiment_id="schema").status_code == 422
    assert create(scale_liters=0).status_code == 422


def test_duplicate_experiment_rejected():
    assert create().status_code == 201
    response = create()
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_list_experiments_newest_first_with_counts():
    create("EXP-OLD")
    create("EXP-NEW", data_source="csv")
    add("EXP-OLD")
    body = client.get("/api/experiments").json()
    assert [e["experiment_id"] for e in body] == ["EXP-NEW", "EXP-OLD"]
    assert {e["experiment_id"]: e["observation_count"] for e in body} == {"EXP-NEW": 0, "EXP-OLD": 1}


def test_get_experiment_and_not_found():
    create()
    add("EXP-A")
    add("EXP-A", culture_time_hours=48)
    body = client.get("/api/experiments/EXP-A").json()
    assert body["observation_count"] == 2
    assert "observations" not in body
    missing = client.get("/api/experiments/NOPE")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Experiment 'NOPE' not found."


def test_fixed_routes_still_win_over_experiment_ids():
    assert isinstance(client.get("/api/experiments/schema").json(), list)


# --- 6-9, 11. Observations --------------------------------------------------------

def test_add_valid_observation():
    create()
    response = add("EXP-A", feed_rate=2.5, notes="day 1")
    assert response.status_code == 201
    body = response.json()
    assert body["observation_count"] == 1
    assert body["observation"]["experiment_id"] == "EXP-A"
    assert body["observation"]["feed_rate"] == 2.5
    assert body["observation"]["id"] > 0
    assert stored_observation_count("EXP-A") == 1


def test_invalid_observation_rejected_and_not_saved():
    create()
    response = add("EXP-A", ph="acidic", cell_density=None)
    assert response.status_code == 422
    assert {e["loc"][-1] for e in response.json()["detail"]} == {"ph", "cell_density"}
    assert add("NOPE").status_code == 404
    assert stored_observation_count() == 0


def test_get_observations_ordered_with_limit():
    create()
    for hours in (48, 0, 24):
        add("EXP-A", culture_time_hours=hours)
    body = client.get("/api/experiments/EXP-A/observations").json()
    assert [o["culture_time_hours"] for o in body] == [0, 24, 48]
    assert "recorded_at" in body[0]
    assert len(client.get("/api/experiments/EXP-A/observations?limit=2").json()) == 2
    assert client.get("/api/experiments/EXP-A/observations?limit=0").status_code == 422
    assert client.get("/api/experiments/NOPE/observations").status_code == 404


def test_empty_experiment_has_no_observations():
    create()
    assert client.get("/api/experiments/EXP-A/observations").json() == []


def test_observations_belong_to_their_experiment():
    create("EXP-1")
    create("EXP-2")
    add("EXP-1", culture_time_hours=1)
    add("EXP-1", culture_time_hours=2)
    add("EXP-2", culture_time_hours=99)
    one = client.get("/api/experiments/EXP-1/observations").json()
    two = client.get("/api/experiments/EXP-2/observations").json()
    assert [o["culture_time_hours"] for o in one] == [1, 2]
    assert [o["culture_time_hours"] for o in two] == [99]
    assert {o["experiment_id"] for o in one} == {"EXP-1"}


def test_manual_observation_persisted_with_matching_body_id():
    create()
    assert add("EXP-A", experiment_id="EXP-A").status_code == 201
    mismatch = add("EXP-A", experiment_id="EXP-B")
    assert mismatch.status_code == 422
    assert "does not match" in mismatch.json()["detail"]
    stored = client.get("/api/experiments/EXP-A/observations").json()
    assert len(stored) == 1
    assert stored[0]["temperature_c"] == 37.0


def test_simulated_experiment_rejects_manual_and_csv_data():
    create("SIM-X", data_source="simulated")
    assert add("SIM-X").status_code == 409
    assert upload("SIM-X", HEADER + "\n1,37,7,50,100,1,\n").status_code == 409
    assert stored_observation_count() == 0


# --- 10. Delete -------------------------------------------------------------------

def test_delete_experiment_removes_its_observations():
    create("EXP-1")
    create("EXP-2")
    add("EXP-1")
    add("EXP-1", culture_time_hours=48)
    add("EXP-2")
    response = client.delete("/api/experiments/EXP-1")
    assert response.status_code == 200
    assert response.json()["deleted_observations"] == 2
    assert client.get("/api/experiments/EXP-1").status_code == 404
    assert stored_observation_count("EXP-1") == 0
    assert stored_observation_count("EXP-2") == 1  # other experiments untouched
    assert client.delete("/api/experiments/EXP-1").status_code == 404


def test_database_cascade_prevents_orphans():
    create()
    add("EXP-A")
    with Session(db.engine) as session:  # bypass the API: the FK cascade alone must remove observations
        session.connection().exec_driver_sql("DELETE FROM experiments WHERE experiment_id = 'EXP-A'")
        session.commit()
    assert stored_observation_count() == 0


# --- 12-13. CSV -------------------------------------------------------------------

def test_valid_csv_rows_persisted():
    create("EXP-CSV", data_source="csv")
    csv_text = "\n".join([HEADER, "0,37,7.1,95,120,0.3,start", "24,37,7.05,82,120,0.85,"])
    response = upload("EXP-CSV", csv_text)
    assert response.status_code == 200
    body = response.json()
    assert body["saved_count"] == body["accepted_count"] == 2
    assert body["experiment_id"] == "EXP-CSV"
    stored = client.get("/api/experiments/EXP-CSV/observations").json()
    assert [o["notes"] for o in stored] == ["start", None]


def test_invalid_csv_rows_reported_and_only_valid_rows_saved():
    create("EXP-CSV", data_source="csv")
    csv_text = "\n".join([
        "experiment_id," + HEADER,
        "EXP-CSV,0,37,7.1,95,120,0.3,",
        ",24,37,abc,82,120,0.85,",      # invalid pH (empty experiment_id takes the target)
        "OTHER,48,37,7.0,70,120,2.0,",   # belongs to a different experiment
        "EXP-CSV,72,37,6.9,60,130,4.0,",
    ])
    body = upload("EXP-CSV", csv_text).json()
    assert (body["accepted_count"], body["rejected_count"], body["saved_count"]) == (2, 2, 2)
    assert {(e["row"], e["field"]) for e in body["errors"]} == {(3, "ph"), (4, "experiment_id")}
    assert stored_observation_count("EXP-CSV") == 2


def test_invalid_csv_file_saves_nothing():
    create("EXP-CSV", data_source="csv")
    response = upload("EXP-CSV", "culture_time_hours,ph\n1,7\n")
    assert response.status_code == 422
    assert "Missing required column" in response.json()["detail"]
    assert upload("NOPE", HEADER + "\n").status_code == 404
    assert stored_observation_count() == 0


# --- 14. Simulator persistence ----------------------------------------------------

def test_simulator_observations_persisted_without_duplicates():
    create("SIM-RUN", data_source="simulated", scale_liters=1000)
    with client.websocket_connect("/api/simulator/ws") as ws:
        ws.receive_json()
        ws.send_json({"action": "start", "config": {"seed": 1, "interval_seconds": 0.05}, "save_to": "SIM-RUN"})
        status = receive(ws, "status")
        assert status["run"]["saving_to"] == "SIM-RUN"
        assert status["run"]["experiment_id"] == "SIM-RUN"
        assert status["run"]["volume_liters"] == 1000  # the stored experiment defines the scale
        streamed = [receive(ws, "observation") for _ in range(3)]
        ws.send_json({"action": "stop"})
        while (message := ws.receive_json())["type"] != "status":
            streamed.append(message)  # observations already in flight before the stop
    assert all(m["saved"] is True for m in streamed)
    stored = client.get("/api/experiments/SIM-RUN/observations").json()
    assert [o["culture_time_hours"] for o in stored] == [m["observation"]["culture_time_hours"] for m in streamed]
    assert len({o["id"] for o in stored}) == len(streamed)


def test_simulator_save_target_checks():
    create("MANUAL-1")
    create("SIM-FULL", data_source="simulated")
    with client.websocket_connect("/api/simulator/ws") as ws:
        ws.receive_json()
        ws.send_json({"action": "start", "config": {}, "save_to": "MANUAL-1"})
        assert "only be saved to a SIMULATED experiment" in receive(ws, "error")["message"]
        ws.send_json({"action": "start", "config": {}, "save_to": "MISSING"})
        assert "not found" in receive(ws, "error")["message"]
    with Session(db.engine) as session:
        session.add(ObservationRow(experiment_id="SIM-FULL", **OBSERVATION))
        session.commit()
    with client.websocket_connect("/api/simulator/ws") as ws:
        ws.receive_json()
        ws.send_json({"action": "start", "config": {}, "save_to": "SIM-FULL"})
        assert "already has 1 observation" in receive(ws, "error")["message"]


def test_simulator_keeps_streaming_when_saving_fails(monkeypatch):
    create("SIM-RUN", data_source="simulated")

    def broken_save(*_args):
        raise RuntimeError("disk full")

    monkeypatch.setattr(simulator_api, "save_simulated_observation", broken_save)
    with client.websocket_connect("/api/simulator/ws") as ws:
        ws.receive_json()
        ws.send_json({"action": "start", "config": {"interval_seconds": 0.05}, "save_to": "SIM-RUN"})
        assert receive(ws, "persistence_error")["message"].endswith("The simulation continues.")
        first = receive(ws, "observation")
        second = receive(ws, "observation")
        assert first["saved"] is False and second["saved"] is False
        assert second["observation"]["culture_time_hours"] > first["observation"]["culture_time_hours"]


def test_simulator_without_save_to_does_not_persist():
    with client.websocket_connect("/api/simulator/ws") as ws:
        ws.receive_json()
        ws.send_json({"action": "start", "config": {"interval_seconds": 0.05}})
        assert receive(ws, "observation")["saved"] is None
    assert stored_observation_count() == 0


# --- 15. Phase 1 health (Phase 2/3 behaviour is covered by the existing test modules) ---

def test_health_still_ok():
    assert client.get("/api/health").json()["status"] == "ok"


def test_database_errors_become_friendly_503(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception("database is locked"))

    monkeypatch.setattr(repository, "list_experiments", fail)
    response = TestClient(app, raise_server_exceptions=False).get("/api/experiments")
    assert response.status_code == 503
    assert response.json()["detail"].startswith("Database error")
    assert "Traceback" not in response.text
