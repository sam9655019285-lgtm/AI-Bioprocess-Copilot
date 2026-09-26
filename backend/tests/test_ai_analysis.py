"""Phase 8 tests. No real Gemini calls: the generator is replaced by a recording fake."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import db, gemini_service
from app.ai_analysis import SYSTEM_INSTRUCTION
from app.ai_api import get_generator
from app.db_models import ExperimentRow, ObservationRow
from app.main import app

FAKE_KEY = "test-fake-key-0000-not-a-real-secret"

VALID = {
    "overview": "Three observations over 48 h.",
    "observed_patterns": [{"title": "DO decline", "observation": "DO fell from 60.0 to 44.0 % air sat.", "evidence": "Trend finding."}],
    "possible_interpretations": [{"title": "Oxygen demand", "interpretation": "May be consistent with rising demand.",
                                  "supporting_evidence": "Cell density rose.", "uncertainty": "No oxygen uptake data."}],
    "attention_points": [{"title": "pH below range", "finding_type": "range", "explanation": "pH 6.2 at 24 h."}],
    "scale_up_considerations": [{"title": "Gas flow", "consideration": "50 L/min at 100 L.", "basis": "vvm × volume."}],
    "questions_for_investigation": ["Was the pH probe calibrated?"],
}

client = TestClient(app)


class FakeGemini:
    """Records what would be sent to Gemini and returns a canned response."""

    def __init__(self, response=VALID, error: Exception | None = None):
        self.response, self.error, self.calls = response, error, []

    def __call__(self, system_instruction: str, prompt: str) -> str:
        self.calls.append((system_instruction, prompt))
        if self.error:
            raise self.error
        return self.response if isinstance(self.response, str) else json.dumps(self.response)

    @property
    def payload(self) -> dict:
        prompt = self.calls[-1][1]
        return json.loads(prompt[prompt.index("{"):])


@pytest.fixture(autouse=True)
def no_real_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # never use a developer's real key in tests
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    yield
    app.dependency_overrides.pop(get_generator, None)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    gen = FakeGemini()
    app.dependency_overrides[get_generator] = lambda: gen
    return gen


def create(experiment_id="EXP", scale=1):
    assert client.post("/api/experiments", json={
        "experiment_id": experiment_id, "name": "AI test run", "scale_liters": scale, "data_source": "manual",
    }).status_code == 201


def add(hours, **fields):
    body = {"temperature_c": 37, "ph": 7.0, "dissolved_oxygen_percent": 60, "agitation_rpm": 180,
            "cell_density": 1.0, "aeration_rate": 0.1, "culture_time_hours": hours, **fields}
    assert client.post("/api/experiments/EXP/observations", json=body).status_code == 201


@pytest.fixture
def experiment():
    create()
    add(0)
    add(24, ph=6.2, dissolved_oxygen_percent=52, cell_density=2.0)
    add(48, dissolved_oxygen_percent=44, cell_density=4.0)


def analyse(body=None):
    return client.post("/api/experiments/EXP/ai-analysis", json=body or {})


def scale_up(target=100):
    return {"scale_up": {"source_experiment_id": "EXP", "target_scale_liters": target, "target_aeration_vvm": 0.5}}


# 1. service with a mocked SDK client

def test_gemini_service_uses_sdk_client_correctly(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    captured = {}

    def generate_content(model, contents, config):
        captured.update(model=model, contents=contents, config=config)
        return SimpleNamespace(text=json.dumps(VALID))

    fake_client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(gemini_service, "_client", lambda key: fake_client)
    result = gemini_service.generate_analysis("system", "prompt")
    assert result.overview == VALID["overview"]
    assert captured["model"] == "gemini-test-model"
    assert captured["contents"] == "prompt"
    assert captured["config"].system_instruction == "system"
    assert captured["config"].response_mime_type == "application/json"
    assert captured["config"].response_json_schema["required"][0] == "overview"


def test_default_model_and_status():
    assert gemini_service.model_name() == gemini_service.DEFAULT_MODEL
    assert client.get("/api/ai/status").json() == {"configured": False}


# 2. valid response

def test_valid_structured_response(fake, experiment):
    response = analyse()
    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["overview"] == VALID["overview"]
    assert body["analysis"]["possible_interpretations"][0]["uncertainty"] == "No oxygen uptake data."
    assert body["analysis"]["scale_up_considerations"] == []  # no scenario supplied -> not shown
    assert body["provider"] == "Gemini" and body["model"] == gemini_service.DEFAULT_MODEL
    assert body["observation_count"] == 3 and body["scale_up_included"] is False
    assert "reviewed by a scientist" in body["notice"]
    system, _ = fake.calls[0]
    assert system == SYSTEM_INSTRUCTION
    for rule in ("Do not invent experimental results", "risk score", "may be consistent with",
                 "Never invent a threshold", "not universal biological limits"):
        assert rule in system


def test_empty_arrays_are_valid(fake, experiment):
    fake.response = {**VALID, "observed_patterns": [], "possible_interpretations": [], "attention_points": [],
                     "questions_for_investigation": []}
    assert analyse().status_code == 200


# 3. invalid response

@pytest.mark.parametrize("bad", [
    "not json at all",
    json.dumps({"overview": "missing arrays"}),
    json.dumps({**VALID, "observed_patterns": [{"title": "no observation field"}]}),
    json.dumps({**VALID, "overview": ""}),
    json.dumps([1, 2, 3]),
])
def test_invalid_response_rejected(fake, experiment, bad):
    fake.response = bad
    response = analyse()
    assert response.status_code == 502
    assert "did not match the expected structure" in response.json()["detail"]
    assert "analysis" not in response.json()


# 4. missing key

def test_missing_api_key(experiment):
    gen = FakeGemini()
    app.dependency_overrides[get_generator] = lambda: gen
    response = analyse()
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]  # names the variable, never a value
    assert gen.calls == []


# 5. provider failure

def test_provider_failure(fake, experiment):
    fake.error = RuntimeError(f"401 invalid key {FAKE_KEY}")
    response = analyse()
    assert response.status_code == 502
    assert "Gemini request failed" in response.json()["detail"]
    assert FAKE_KEY not in response.text


# 6-7. unknown / empty experiment

def test_unknown_experiment(fake):
    response = client.post("/api/experiments/NOPE/ai-analysis", json={})
    assert response.status_code == 404
    assert fake.calls == []


def test_empty_experiment(fake):
    create()
    response = analyse()
    assert response.status_code == 200
    payload = fake.payload
    assert payload["experiment"]["observation_count"] == 0
    assert payload["process_analysis"]["parameter_statistics"] == []
    assert payload["process_analysis"]["latest_observation"] is None
    assert payload["anomaly_detection"]["findings"] == []


# 8-9. deterministic data passed to Gemini

def test_phase5_analysis_passed(fake, experiment):
    analyse()
    payload = fake.payload
    expected = client.get("/api/experiments/EXP/analysis").json()
    assert payload["experiment"]["culture_duration_hours"] == expected["culture_duration_hours"] == 48
    stats = {p["parameter"]: p for p in payload["process_analysis"]["parameter_statistics"]}
    for p in expected["parameters"]:
        for key in ("start", "final", "minimum", "maximum", "average", "delta"):
            assert stats[p["parameter"]][key] == p[key]
    assert payload["process_analysis"]["latest_observation"]["culture_time_hours"] == 48
    assert payload["process_analysis"]["factual_summary"] == expected["summary"]
    assert payload["process_analysis"]["data_coverage"] == expected["data_quality"]
    assert "id" not in payload["process_analysis"]["latest_observation"]  # no internal DB fields


def test_phase7_findings_passed(fake, experiment):
    analyse()
    sent = fake.payload["anomaly_detection"]
    expected = client.get("/api/experiments/EXP/anomalies").json()
    assert sent["counts"] == expected["counts"]
    assert [f["finding_id"] for f in sent["findings"]] == [f["finding_id"] for f in expected["findings"]]
    ph = next(f for f in sent["findings"] if f["type"] == "range" and f["parameter"] == "ph")
    for key in ("severity", "message", "observed_value", "expected_min", "expected_max", "evidence", "culture_time_hours"):
        assert ph[key] is not None, key
    assert sent["monitoring_configuration"]["ranges"]["ph"]["min"] == 6.5


# 10. scale-up

def test_scale_up_included_when_supplied(fake, experiment):
    response = analyse(scale_up(100))
    assert response.status_code == 200
    assert response.json()["scale_up_included"] is True
    assert response.json()["analysis"]["scale_up_considerations"] == VALID["scale_up_considerations"]
    sent = fake.payload["scale_up"]
    assert sent["scale_factor"] == 100
    assert sent["gas_flow"]["target_l_per_min"] == pytest.approx(50)
    assert "not validated predictions" in sent["disclaimer"]


def test_scale_up_absent_and_mismatch(fake, experiment):
    analyse()
    assert "scale_up" not in fake.payload
    bad = scale_up()
    bad["scale_up"]["source_experiment_id"] = "OTHER"
    assert analyse(bad).status_code == 422
    assert analyse({"scale_up": {"source_experiment_id": "EXP", "target_scale_liters": -1}}).status_code == 422


# 11. no database writes

def count(model):
    with Session(db.engine) as session:
        return session.exec(select(func.count()).select_from(model)).one()


def test_no_database_writes(fake, experiment):
    before = (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/EXP/observations").json())
    analyse(scale_up())
    fake.response = "invalid"
    analyse()
    after = (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/EXP/observations").json())
    assert before == after


# 12. key never exposed

def test_key_never_in_any_response(fake, experiment):
    responses = [client.get("/api/ai/status"), analyse(), analyse(scale_up())]
    fake.response = "{broken"
    responses.append(analyse())
    fake.error = RuntimeError(FAKE_KEY)
    responses.append(analyse())
    responses.append(client.post("/api/experiments/NOPE/ai-analysis", json={}))
    for r in responses:
        assert FAKE_KEY not in r.text
        assert "fake-key" not in r.text
    assert client.get("/api/ai/status").json() == {"configured": True}


# 13. deterministic layers independent of Gemini

def test_deterministic_analysis_works_without_gemini(experiment):
    assert client.get("/api/ai/status").json() == {"configured": False}
    assert client.get("/api/experiments/EXP/analysis").status_code == 200
    assert client.get("/api/experiments/EXP/anomalies").json()["finding_count"] > 0
    assert client.post("/api/scale-up/simulate", json={"source_experiment_id": "EXP", "target_scale_liters": 10}).status_code == 200


# --- Regression: real Gemini rejected `maxItems` in response_json_schema (400 INVALID_ARGUMENT) ---

def test_schema_sent_to_gemini_has_no_max_items(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    captured = {}

    def generate_content(model, contents, config):
        captured["config"] = config
        return SimpleNamespace(text=json.dumps(VALID))

    monkeypatch.setattr(gemini_service, "_client", lambda key: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    gemini_service.generate_analysis("system", "prompt")
    sent = json.dumps(captured["config"].response_json_schema)
    assert "maxItems" not in sent
    assert "maxLength" in sent and "$defs" in sent  # the other (accepted) constraints are kept
    assert "maxItems" in json.dumps(gemini_service.AIAnalysis.model_json_schema())  # model itself unchanged
    retry = captured["config"].http_options.retry_options
    assert (retry.attempts, retry.http_status_codes) == (3, [503])  # 429 (quota) is not retried


def test_list_limits_still_enforced_on_response(fake, experiment):
    fake.response = {**VALID, "questions_for_investigation": [f"q{i}" for i in range(21)]}
    response = analyse()
    assert response.status_code == 502
    assert "did not match the expected structure" in response.json()["detail"]


class ProviderError(Exception):
    """Shaped like google.genai.errors.APIError (code/status attributes)."""

    def __init__(self, code, status):
        super().__init__(f"{code} {status}. key={FAKE_KEY}")
        self.code, self.status = code, status


@pytest.mark.parametrize("code, status, hint", [
    (400, "INVALID_ARGUMENT", "the request was rejected as invalid"),
    (429, "RESOURCE_EXHAUSTED", "rate limit or quota reached"),
    (503, "UNAVAILABLE", "Gemini is temporarily overloaded"),
])
def test_provider_error_reports_code_and_status_only(fake, experiment, code, status, hint):
    fake.error = ProviderError(code, status)
    response = analyse()
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail.startswith(f"The Gemini request failed (Gemini {code} {status}: {hint}")
    assert FAKE_KEY not in response.text
