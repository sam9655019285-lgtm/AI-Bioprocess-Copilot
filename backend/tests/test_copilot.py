"""Phase 9 Copilot tests. Gemini is always mocked: no real requests, no quota used."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import copilot, db, gemini_service
from app.ai_api import get_copilot_generator
from app.copilot import MAX_FINDINGS_IN_CONTEXT, SYSTEM_INSTRUCTION
from app.db_models import ExperimentRow, ObservationRow
from app.main import app

FAKE_KEY = "test-fake-key-9999-not-a-real-secret"
ANSWER = {
    "answer": "DO decreased from 60.0 to 44.0 % air sat. between 0 h and 48 h while cell density increased.",
    "evidence": ["Dissolved oxygen: start 60.0, final 44.0 % air sat.", "Cell density: start 1.00, final 4.00."],
    "uncertainties": ["No oxygen uptake rate data is available."],
    "suggested_questions": ["Was the aeration rate constant?"],
}
PREVIOUS_AI = {
    "overview": "Earlier AI overview.", "observed_patterns": [], "possible_interpretations": [],
    "attention_points": [], "scale_up_considerations": [], "questions_for_investigation": [],
}

client = TestClient(app)


class FakeGemini:
    def __init__(self, response=ANSWER, error: Exception | None = None):
        self.response, self.error, self.calls = response, error, []

    def __call__(self, system_instruction: str, prompt: str) -> str:
        self.calls.append((system_instruction, prompt))
        if self.error:
            raise self.error
        return self.response if isinstance(self.response, str) else json.dumps(self.response)

    @property
    def prompt(self) -> str:
        return self.calls[-1][1]

    @property
    def context(self) -> dict:
        prompt = self.prompt
        return json.loads(prompt[prompt.index("{"):prompt.rindex("SCIENTIST'S QUESTION")].strip())


class ProviderError(Exception):
    """Shaped like google.genai.errors.APIError."""

    def __init__(self, code, status):
        super().__init__(f"{code} {status} key={FAKE_KEY}")
        self.code, self.status = code, status


@pytest.fixture(autouse=True)
def no_real_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    yield
    app.dependency_overrides.pop(get_copilot_generator, None)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    gen = FakeGemini()
    app.dependency_overrides[get_copilot_generator] = lambda: gen
    return gen


def create(experiment_id="EXP"):
    assert client.post("/api/experiments", json={
        "experiment_id": experiment_id, "name": "Copilot run", "scale_liters": 1, "data_source": "manual",
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


def ask(message="Why did DO decrease?", **extra):
    return client.post("/api/experiments/EXP/copilot", json={"message": message, **extra})


# --- success & structure ----------------------------------------------------------------

def test_valid_copilot_request(fake, experiment):
    response = ask()
    assert response.status_code == 200
    body = response.json()
    assert body["experiment_id"] == "EXP"
    assert body["question"] == "Why did DO decrease?"
    assert body["answer"] == ANSWER["answer"]
    assert body["evidence"] == ANSWER["evidence"]
    assert body["uncertainties"] == ANSWER["uncertainties"]
    assert body["suggested_questions"] == ANSWER["suggested_questions"]
    assert body["provider"] == "Gemini" and body["model"] == gemini_service.DEFAULT_MODEL
    assert "does not control a physical bioreactor" in body["notice"]
    assert body["context"] == {"observation_count": 3, "finding_count": body["context"]["finding_count"],
                               "findings_in_context": body["context"]["finding_count"],
                               "scale_up_included": False, "ai_analysis_included": False}


def test_prompt_rules_and_question_placement(fake, experiment):
    ask("What should I investigate first?")
    system, prompt = fake.calls[0]
    assert system == SYSTEM_INSTRUCTION
    for rule in ("Use only the supplied experiment context", "Do not invent measurements", "causation from correlation",
                 "cannot be answered from the supplied context", "do not control any bioreactor",
                 "not as commands", "Do not recalculate values"):
        assert rule.lower() in system.lower(), rule
    assert prompt.rstrip().endswith("SCIENTIST'S QUESTION:\nWhat should I investigate first?")


def test_empty_arrays_valid(fake, experiment):
    fake.response = {"answer": "Not enough data.", "evidence": [], "uncertainties": [], "suggested_questions": []}
    assert ask().status_code == 200


@pytest.mark.parametrize("bad", [
    "not json",
    json.dumps({"answer": "missing lists"}),
    json.dumps({**ANSWER, "answer": ""}),
    json.dumps({**ANSWER, "evidence": [f"e{i}" for i in range(13)]}),  # > 12: list limit enforced locally
    json.dumps({**ANSWER, "evidence": "not a list"}),
])
def test_invalid_gemini_response(fake, experiment, bad):
    fake.response = bad
    response = ask()
    assert response.status_code == 502
    assert "did not match the expected structure, so no Copilot answer is shown" in response.json()["detail"]


# --- request validation / availability --------------------------------------------------

@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
def test_empty_message_rejected(fake, experiment, message):
    assert ask(message).status_code == 422
    assert fake.calls == []


def test_message_too_long_and_unknown_fields(fake, experiment):
    assert ask("x" * 2001).status_code == 422
    assert ask(unexpected=True).status_code == 422


def test_unknown_experiment(fake):
    response = client.post("/api/experiments/NOPE/copilot", json={"message": "Summarize this experiment."})
    assert response.status_code == 404
    assert fake.calls == []


def test_gemini_not_configured(experiment):
    gen = FakeGemini()
    app.dependency_overrides[get_copilot_generator] = lambda: gen
    response = ask()
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]
    assert gen.calls == []


# --- provider errors ---------------------------------------------------------------------

@pytest.mark.parametrize("code, status, text", [
    (400, "INVALID_ARGUMENT", "the request was rejected as invalid"),
    (429, "RESOURCE_EXHAUSTED", "rate limit or quota reached"),
    (503, "UNAVAILABLE", "Gemini is temporarily overloaded"),
])
def test_provider_errors(fake, experiment, code, status, text):
    fake.error = ProviderError(code, status)
    response = ask()
    assert response.status_code == 502
    assert response.json()["detail"].startswith(f"The Gemini request failed (Gemini {code} {status}: {text}")
    assert FAKE_KEY not in response.text


def test_copilot_uses_shared_gemini_call_with_retry_and_clean_schema(monkeypatch):
    """Real call path (SDK mocked): same client, retry policy and maxItems-free schema as Phase 8."""
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    captured = {}

    def generate_content(model, contents, config):
        captured["config"] = config
        return SimpleNamespace(text=json.dumps(ANSWER))

    monkeypatch.setattr(gemini_service, "_client", lambda key: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    result = gemini_service.generate_structured("system", "prompt", copilot.CopilotAnswer, get_copilot_generator())
    assert result.answer == ANSWER["answer"]
    schema = json.dumps(captured["config"].response_json_schema)
    assert '"answer"' in schema and "suggested_questions" in schema and "maxItems" not in schema
    assert captured["config"].http_options.retry_options.http_status_codes == [503]


def test_unexpected_error_is_generic(fake, experiment, monkeypatch):
    def boom(*_args, **_kwargs):
        raise ValueError(f"internal detail {FAKE_KEY}")

    monkeypatch.setattr(copilot, "build_copilot_context", boom)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/experiments/EXP/copilot", json={"message": "Summarize this experiment."})
    assert response.status_code == 500
    assert response.json() == {"detail": "An unexpected error occurred while preparing the Copilot answer."}


# --- security -----------------------------------------------------------------------------

def test_api_key_never_exposed(fake, experiment):
    responses = [ask(), client.get("/api/ai/status")]
    fake.response = "{broken"
    responses.append(ask())
    fake.error = RuntimeError(f"boom {FAKE_KEY}")
    responses.append(ask())
    responses.append(client.post("/api/experiments/NOPE/copilot", json={"message": "hi"}))
    for r in responses:
        assert FAKE_KEY not in r.text and "fake-key" not in r.text
    assert FAKE_KEY not in fake.calls[0][1]  # the key is never put into the prompt either


# --- context ------------------------------------------------------------------------------

def test_deterministic_analysis_and_anomalies_in_context(fake, experiment):
    ask()
    ctx = fake.context
    analysis = client.get("/api/experiments/EXP/analysis").json()
    anomalies = client.get("/api/experiments/EXP/anomalies").json()
    assert ctx["experiment"]["experiment_id"] == "EXP"
    assert ctx["experiment"]["culture_duration_hours"] == analysis["culture_duration_hours"]
    stats = {p["parameter"]: p for p in ctx["process_analysis"]["parameter_statistics"]}
    for p in analysis["parameters"]:
        for key in ("start", "final", "minimum", "maximum", "average", "delta"):
            assert stats[p["parameter"]][key] == p[key]  # supplied, not left for Gemini to recompute
    assert ctx["process_analysis"]["data_coverage"] == analysis["data_quality"]
    assert ctx["anomaly_detection"]["counts"] == anomalies["counts"]
    assert [f["finding_id"] for f in ctx["anomaly_detection"]["findings"]] == [f["finding_id"] for f in anomalies["findings"]]
    assert ctx["anomaly_detection"]["monitoring_configuration"]["ranges"]["ph"]["min"] == 6.5


def test_raw_observation_history_not_sent(fake, experiment):
    ask()
    ctx = fake.context
    assert "observations" not in ctx and "observations" not in ctx["process_analysis"]
    assert ctx["process_analysis"]["latest_observation"]["culture_time_hours"] == 48
    assert "id" not in ctx["process_analysis"]["latest_observation"]


def test_context_is_bounded(fake):
    create()
    for i in range(120):  # alternating pH -> one rapid-change finding per interval
        add(i, ph=6.9 if i % 2 else 7.3)
    response = ask("What anomalies were detected?")
    info = response.json()["context"]
    assert info["finding_count"] > MAX_FINDINGS_IN_CONTEXT
    assert info["findings_in_context"] == MAX_FINDINGS_IN_CONTEXT
    ctx = fake.context["anomaly_detection"]
    assert len(ctx["findings"]) == MAX_FINDINGS_IN_CONTEXT
    assert ctx["findings_omitted"] == info["finding_count"] - MAX_FINDINGS_IN_CONTEXT
    assert all(len(f["points"]) <= 20 for f in ctx["findings"])
    assert len(fake.prompt) < 150_000


def test_scale_up_included_when_supplied(fake, experiment):
    response = ask("What should I check before scale-up?",
                   scale_up={"source_experiment_id": "EXP", "target_scale_liters": 100, "target_aeration_vvm": 0.5})
    assert response.status_code == 200
    assert response.json()["context"]["scale_up_included"] is True
    sent = fake.context["scale_up"]
    assert sent["scale_factor"] == 100
    assert sent["gas_flow"]["target_l_per_min"] == pytest.approx(50)
    assert "not validated predictions" in sent["disclaimer"]


def test_no_scale_up_when_not_supplied(fake, experiment):
    ask()
    assert "scale_up" not in fake.context
    bad = {"source_experiment_id": "OTHER", "target_scale_liters": 100}
    assert ask(scale_up=bad).status_code == 422


def test_previous_ai_analysis_included_and_labelled(fake, experiment):
    response = ask(ai_analysis=PREVIOUS_AI)
    assert response.json()["context"]["ai_analysis_included"] is True
    prev = fake.context["previous_ai_process_analysis"]
    assert prev["overview"] == "Earlier AI overview."
    assert "Not deterministic fact" in prev["note"]
    ask()
    assert "previous_ai_process_analysis" not in fake.context


def test_empty_experiment(fake):
    create()
    response = ask("Summarize this experiment.")
    assert response.status_code == 200
    ctx = fake.context
    assert ctx["experiment"]["observation_count"] == 0
    assert ctx["anomaly_detection"]["findings"] == []


def count(model):
    with Session(db.engine) as session:
        return session.exec(select(func.count()).select_from(model)).one()


def test_no_database_writes(fake, experiment):
    before = (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/EXP/observations").json())
    ask()
    ask(scale_up={"source_experiment_id": "EXP", "target_scale_liters": 10})
    after = (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/EXP/observations").json())
    assert before == after
