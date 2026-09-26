from fastapi.testclient import TestClient

from app import simulator_api
from app.main import app
from app.models import Observation
from app.simulator import BioreactorSimulator, SimulatorConfig

REQUIRED_FIELDS = [name for name, f in Observation.model_fields.items() if f.is_required()]
FAST_CONFIG = {"seed": 42, "interval_seconds": 0.05}


def make_simulator(**overrides):
    return BioreactorSimulator(SimulatorConfig(seed=1, **overrides), experiment_id="SIM-TEST")


def receive_until(ws, message_type):
    for _ in range(10):
        message = ws.receive_json()
        if message["type"] == message_type:
            return message
    raise AssertionError(f"No {message_type!r} message received")


def test_simulator_generates_observation():
    observation = make_simulator().step()
    assert isinstance(observation, Observation)
    assert observation.experiment_id == "SIM-TEST"


def test_generated_observation_has_required_fields():
    data = make_simulator().step().model_dump()
    for field in REQUIRED_FIELDS:
        assert data[field] is not None, field


def test_generated_values_pass_observation_validation():
    sim = make_simulator(volume_liters=1000, cell_density=2.0, dissolved_oxygen_percent=20)
    for _ in range(500):  # well into the stationary phase
        Observation.model_validate(sim.step().model_dump())


def test_culture_time_increases():
    sim = make_simulator(hours_per_step=0.5)
    times = [sim.step().culture_time_hours for _ in range(5)]
    assert times[0] == 0
    assert all(later > earlier for earlier, later in zip(times, times[1:]))


def test_cell_density_grows_and_stays_bounded():
    sim = make_simulator()
    densities = [sim.step().cell_density for _ in range(400)]
    assert densities[-1] > densities[0] * 5
    assert max(densities) <= 12.0


def test_same_seed_gives_same_series():
    a, b = make_simulator(), make_simulator()
    assert [a.step() for _ in range(20)] == [b.step() for _ in range(20)]


def test_websocket_streams_valid_observations():
    with TestClient(app).websocket_connect("/api/simulator/ws") as ws:
        assert ws.receive_json() == {"type": "status", "status": "stopped", "data_source": "simulated", "run": None}
        ws.send_json({"action": "start", "config": {**FAST_CONFIG, "volume_liters": 10}})
        status = receive_until(ws, "status")
        assert status["status"] == "simulating"
        assert status["run"]["volume_liters"] == 10

        first = receive_until(ws, "observation")
        second = receive_until(ws, "observation")
        assert first["data_source"] == "simulated"
        obs1 = Observation.model_validate(first["observation"])
        obs2 = Observation.model_validate(second["observation"])
        assert obs2.culture_time_hours > obs1.culture_time_hours

        ws.send_json({"action": "stop"})
        assert receive_until(ws, "status")["status"] == "stopped"
        ws.send_json({"action": "reset"})
        assert receive_until(ws, "status")["run"] is None


def test_websocket_rejects_invalid_config_and_messages():
    with TestClient(app).websocket_connect("/api/simulator/ws") as ws:
        ws.receive_json()
        ws.send_json({"action": "start", "config": {"volume_liters": 5}})
        assert "volume_liters" in receive_until(ws, "error")["message"]
        ws.send_text("not json")
        assert receive_until(ws, "error")["message"] == "Messages must be JSON."


def test_websocket_disconnect_while_streaming_cleans_up():
    client = TestClient(app)
    with client.websocket_connect("/api/simulator/ws") as ws:
        ws.receive_json()
        ws.send_json({"action": "start", "config": FAST_CONFIG})
        receive_until(ws, "observation")
        session = next(iter(simulator_api.active_sessions))
        task = session.task
    # Leaving the context closes the socket; the server must cancel the stream task.
    assert simulator_api.active_sessions == set()
    assert task.done()

    # The app keeps serving new connections afterwards.
    with client.websocket_connect("/api/simulator/ws") as ws:
        assert ws.receive_json()["type"] == "status"
