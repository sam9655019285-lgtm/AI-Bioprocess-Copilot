"""Phase 21 evidence-linked AI tests. Gemini is always mocked: no real requests, no quota used."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import db, evidence, gemini_service
from app.ai_api import get_copilot_generator, get_generator
from app.analysis import analyze_experiment
from app.anomaly import analyze_anomalies
from app.copilot import MAX_FINDINGS_IN_CONTEXT
from app.main import app
from app import repository as repo

FAKE_KEY = "test-fake-key-2121-not-a-real-secret"
client = TestClient(app)

ANALYSIS = {
    "overview": "DO decreased during the run.",
    "observed_patterns": [{"title": "DO drop", "observation": "DO fell.", "evidence": "F-001",
                           "evidence_refs": ["F-001", "P-002", "F-999", "f-001"]}],
    "possible_interpretations": [{"title": "Uptake", "interpretation": "May be consistent with uptake.",
                                  "supporting_evidence": "Cell density rose.", "uncertainty": "No OUR data.",
                                  "evidence_refs": ["P-001"]}],
    "attention_points": [{"title": "Range", "finding_type": "range", "explanation": "Below range.",
                          "evidence_refs": ["X-1"]}],
    "scale_up_considerations": [],
    "questions_for_investigation": ["Was aeration constant?"],
}
ANSWER = {
    "answer": "The significant alert was associated with a rapid decrease in dissolved oxygen.",
    "evidence": ["DO fell between 24 h and 26 h."],
    "uncertainties": ["The evidence does not establish the cause."],
    "suggested_questions": ["What happened to cell density?"],
    "evidence_refs": ["F-001", "F-001", "P-003", "F-404", "made-up"],
}


class FakeGemini:
    def __init__(self, response):
        self.response, self.calls = response, []

    def __call__(self, system_instruction: str, prompt: str) -> str:
        self.calls.append((system_instruction, prompt))
        if isinstance(self.response, Exception):
            raise self.response
        return json.dumps(self.response)

    def context(self, marker: str | None = None) -> dict:
        prompt = self.calls[-1][1]
        end = prompt.rindex(marker) if marker else len(prompt)
        return json.loads(prompt[prompt.index("{"):end].strip())


@pytest.fixture(autouse=True)
def no_real_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    yield
    app.dependency_overrides.pop(get_generator, None)
    app.dependency_overrides.pop(get_copilot_generator, None)


def use(dep, response, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    gen = FakeGemini(response)
    app.dependency_overrides[dep] = lambda: gen
    return gen


def create(experiment_id="EXP"):
    assert client.post("/api/experiments", json={
        "experiment_id": experiment_id, "name": "Evidence run", "scale_liters": 1, "data_source": "manual",
    }).status_code == 201


def add(hours, experiment_id="EXP", **fields):
    body = {"temperature_c": 37, "ph": 7.0, "dissolved_oxygen_percent": 60, "agitation_rpm": 180,
            "cell_density": 1.0, "aeration_rate": 0.1, "culture_time_hours": hours, **fields}
    assert client.post(f"/api/experiments/{experiment_id}/observations", json=body).status_code == 201


@pytest.fixture
def experiment():
    """DO drop 50 -> 15 between 24 h and 26 h: a significant rapid change plus a range finding."""
    create()
    add(0, dissolved_oxygen_percent=52)
    add(24, dissolved_oxygen_percent=50, cell_density=2.0)
    add(26, dissolved_oxygen_percent=15, cell_density=2.2)
    add(48, dissolved_oxygen_percent=14, cell_density=3.0)


def build(experiment_id="EXP"):
    with Session(db.engine) as session:
        row = repo.get_experiment(session, experiment_id)
        analysis, anomalies = analyze_experiment(session, row), analyze_anomalies(session, row)
        return analysis, anomalies, evidence.build_evidence(analysis, anomalies.findings)


# --- evidence generation --------------------------------------------------------------

def test_evidence_ids_are_deterministic_and_ordered(experiment):
    _, anomalies, first = build()
    _, _, second = build()
    assert [e.model_dump() for e in first] == [e.model_dump() for e in second]
    ids = [e.id for e in first]
    n = len(anomalies.findings)
    assert ids[:n] == [f"F-{i:03d}" for i in range(1, n + 1)]
    assert all(i.startswith("P-") for i in ids[n:]) and len(ids) == len(set(ids))


def test_anomaly_to_evidence_mapping(experiment):
    _, anomalies, items = build()
    for f, e in zip(anomalies.findings, items):
        assert e.type == "anomaly" and e.source == "deterministic_anomaly_detection"
        assert e.description == f.message and e.parameter == f.parameter and e.finding_type == f.type_label
        assert e.severity == f.severity and e.direction == f.direction
        assert e.culture_time_end == f.culture_time_hours and e.observed_value == f.observed_value
    idx = next(i for i, f in enumerate(anomalies.findings) if f.type == "sudden_change" and f.parameter == "dissolved_oxygen_percent")
    rapid = items[idx]
    assert rapid.id == f"F-{idx + 1:03d}"  # position in the report's most-severe-first order
    assert rapid.severity == "significant" and rapid.direction == "decreased"
    assert (rapid.culture_time_start, rapid.culture_time_end) == (24, 26)
    assert (rapid.previous_value, rapid.observed_value) == (50, 15)


def test_process_statistic_and_coverage_evidence(experiment):
    analysis, anomalies, items = build()
    stats = [e for e in items if e.type == "process_statistic"]
    assert [e.parameter for e in stats] == [p.parameter for p in analysis.parameters]
    do = next(e for e in stats if e.parameter == "dissolved_oxygen_percent")
    assert (do.previous_value, do.observed_value, do.minimum, do.maximum) == (52, 14, 14, 52)
    assert do.source == "deterministic_process_analysis"
    coverage = items[-1]
    assert coverage.type == "data_coverage" and "4 observation(s)" in coverage.description


def test_filter_refs_keeps_known_and_rejects_unknown():
    rejected: list[str] = []
    kept = evidence.filter_refs(["F-001", " f-001 ", "P-002", "F-999", "", "X"], {"F-001", "P-002"}, rejected)
    assert kept == ["F-001", "P-002"] and rejected == ["F-999", "X"]


def test_empty_experiment_has_only_coverage_evidence():
    create("EMPTY")
    _, anomalies, items = build("EMPTY")
    assert anomalies.findings == [] and [e.type for e in items] == ["data_coverage"]
    assert items[0].id == "P-001" and "0 observation(s)" in items[0].description


# --- AI Analysis ------------------------------------------------------------------------

def test_ai_analysis_context_carries_ids_and_rules(experiment, monkeypatch):
    gen = use(get_generator, ANALYSIS, monkeypatch)
    assert client.post("/api/experiments/EXP/ai-analysis", json={}).status_code == 200
    system, _ = gen.calls[-1]
    ctx = gen.context()
    assert "ONLY" in system and "valid evidence IDs" in system and "Never invent" in system
    findings = ctx["anomaly_detection"]["findings"]
    assert [f["evidence_id"] for f in findings] == [f"F-{i:03d}" for i in range(1, len(findings) + 1)]
    assert all(p["evidence_id"].startswith("P-") for p in ctx["process_analysis"]["parameter_statistics"])
    assert ctx["process_analysis"]["data_coverage_evidence_id"].startswith("P-")
    assert "evidence_id" not in ctx["process_analysis"]["data_coverage"]  # Phase 5 block unchanged
    assert set(ctx["valid_evidence_ids"]) >= {"F-001", "P-001"}


def test_ai_analysis_refs_validated(experiment, monkeypatch):
    use(get_generator, ANALYSIS, monkeypatch)
    body = client.post("/api/experiments/EXP/ai-analysis", json={}).json()
    a = body["analysis"]
    assert a["observed_patterns"][0]["evidence_refs"] == ["F-001", "P-002"]  # dedup, case-normalised
    assert a["possible_interpretations"][0]["evidence_refs"] == ["P-001"]
    assert a["attention_points"][0]["evidence_refs"] == []
    assert body["rejected_evidence_refs"] == ["F-999", "X-1"]
    assert [e["id"] for e in body["evidence_items"]] == ["F-001", "P-001", "P-002"]
    assert all(e["id"] not in ("F-999", "X-1") for e in body["evidence_items"])


def test_ai_analysis_without_refs_is_compatible(experiment, monkeypatch):
    legacy = {**ANALYSIS, "observed_patterns": [{"title": "t", "observation": "o", "evidence": "e"}],
              "possible_interpretations": [], "attention_points": []}
    use(get_generator, legacy, monkeypatch)
    body = client.post("/api/experiments/EXP/ai-analysis", json={}).json()
    assert body["analysis"]["observed_patterns"][0]["evidence_refs"] == []
    assert body["evidence_items"] == [] and body["rejected_evidence_refs"] == []


# --- Copilot ------------------------------------------------------------------------------

def ask(message="Why did this run receive a significant alert?", experiment_id="EXP"):
    return client.post(f"/api/experiments/{experiment_id}/copilot", json={"message": message})


def test_copilot_refs_validated_and_items_returned(experiment, monkeypatch):
    gen = use(get_copilot_generator, ANSWER, monkeypatch)
    body = ask().json()
    assert body["answer"] == ANSWER["answer"] and body["uncertainties"] == ANSWER["uncertainties"]
    assert body["suggested_questions"] == ANSWER["suggested_questions"] and body["evidence"] == ANSWER["evidence"]
    assert body["evidence_refs"] == ["F-001", "P-003"]
    assert body["rejected_evidence_refs"] == ["F-404", "MADE-UP"]
    items = {e["id"]: e for e in body["evidence_items"]}
    assert set(items) == {"F-001", "P-003"}
    assert items["F-001"]["severity"] == "significant" and items["F-001"]["source"] == "deterministic_anomaly_detection"
    assert items["P-003"]["type"] == "process_statistic"
    ctx = gen.context("SCIENTIST'S QUESTION")
    assert ctx["anomaly_detection"]["findings"][0]["evidence_id"] == "F-001"
    assert "evidence_refs" in gen.calls[-1][0]


def test_copilot_legacy_answer_without_refs(experiment, monkeypatch):
    legacy = {k: v for k, v in ANSWER.items() if k != "evidence_refs"}
    use(get_copilot_generator, legacy, monkeypatch)
    body = ask().json()
    assert body["evidence_refs"] == [] and body["evidence_items"] == [] and body["rejected_evidence_refs"] == []
    assert body["answer"] == ANSWER["answer"]


def test_copilot_ids_only_for_findings_sent(monkeypatch):
    create()
    for i in range(120):  # alternating pH -> more findings than the Copilot sends
        add(i, ph=6.9 if i % 2 else 7.3)
    over = f"F-{MAX_FINDINGS_IN_CONTEXT + 1:03d}"
    gen = use(get_copilot_generator, {**ANSWER, "evidence_refs": ["F-001", over]}, monkeypatch)
    body = ask("What anomalies were detected?").json()
    ctx = gen.context("SCIENTIST'S QUESTION")
    assert len(ctx["anomaly_detection"]["findings"]) == MAX_FINDINGS_IN_CONTEXT
    assert over not in ctx["valid_evidence_ids"]
    assert body["evidence_refs"] == ["F-001"] and body["rejected_evidence_refs"] == [over]


def test_copilot_empty_experiment(monkeypatch):
    create("EMPTY")
    use(get_copilot_generator, {**ANSWER, "evidence_refs": ["P-001", "F-001"]}, monkeypatch)
    body = ask(experiment_id="EMPTY").json()
    assert body["evidence_refs"] == ["P-001"] and body["rejected_evidence_refs"] == ["F-001"]
    assert body["evidence_items"][0]["type"] == "data_coverage"


def test_not_configured_makes_no_call(experiment):
    assert ask().status_code == 503
    assert client.post("/api/experiments/EXP/ai-analysis", json={}).status_code == 503


def test_gemini_error_shows_no_evidence(experiment, monkeypatch):
    use(get_copilot_generator, RuntimeError(f"boom key={FAKE_KEY}"), monkeypatch)
    response = ask()
    assert response.status_code == 502 and FAKE_KEY not in response.text and "evidence_items" not in response.text


def test_invalid_ref_type_rejected_as_bad_structure(experiment, monkeypatch):
    use(get_copilot_generator, {**ANSWER, "evidence_refs": "F-001"}, monkeypatch)
    assert ask().status_code == 502


def test_no_secret_in_prompt_or_evidence(experiment, monkeypatch):
    gen = use(get_copilot_generator, ANSWER, monkeypatch)
    body = ask().text
    assert FAKE_KEY not in body and FAKE_KEY not in gen.calls[-1][0] and FAKE_KEY not in gen.calls[-1][1]


def test_schema_sent_to_gemini_has_no_default_or_maxitems():
    from app.copilot import CopilotAnswer
    for model in (CopilotAnswer, gemini_service.AIAnalysis):
        schema = json.dumps(gemini_service.gemini_schema(model))
        assert "evidence_refs" in schema and '"default"' not in schema and "maxItems" not in schema


# --- report compatibility (the PDF is unchanged; session results with evidence fields are accepted) ------

def test_report_accepts_evidence_linked_session_results(experiment, monkeypatch):
    use(get_copilot_generator, ANSWER, monkeypatch)
    reply = ask().json()
    use(get_generator, ANALYSIS, monkeypatch)
    analysis = client.post("/api/experiments/EXP/ai-analysis", json={}).json()
    response = client.post("/api/experiments/EXP/report", json={"copilot": reply, "ai_analysis": analysis})
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
