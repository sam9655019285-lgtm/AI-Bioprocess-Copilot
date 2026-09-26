"""Phase 11: PDF experiment report. Gemini is never called."""

import base64
import re
import zlib

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import db, gemini_service, report
from app.db_models import ExperimentRow, ObservationRow
from app.main import app

client = TestClient(app)
FAKE_KEY = "test-fake-key-1111-not-a-real-secret"
BASE = {"temperature_c": 37.0, "ph": 7.0, "dissolved_oxygen_percent": 60, "agitation_rpm": 180, "cell_density": 1.0}
AI = {
    "experiment_id": "EXP", "provider": "Gemini", "model": "gemini-test", "generated_at": "2026-09-25T10:00:00Z",
    "notice": "n", "observation_count": 3, "finding_count": 2, "scale_up_included": False,
    "analysis": {
        "overview": "AIOVERVIEWMARKER three observations.",
        "observed_patterns": [{"title": "DO decline", "observation": "DO fell.", "evidence": "Trend finding."}],
        "possible_interpretations": [{"title": "Demand", "interpretation": "May be consistent with demand.",
                                      "supporting_evidence": "Cells rose.", "uncertainty": "UNCERTAINTYMARKER"}],
        "attention_points": [], "scale_up_considerations": [], "questions_for_investigation": ["Probe calibrated?"],
    },
}
COPILOT = {
    "experiment_id": "EXP", "model": "gemini-test", "generated_at": "2026-09-25T10:05:00Z",
    "question": "QUESTIONMARKER Why did DO decrease?", "answer": "ANSWERMARKER DO fell from 60.0 to 44.0.",
    "evidence": ["EVIDENCEMARKER"], "uncertainties": ["No uptake data."], "suggested_questions": ["Was aeration constant?"],
    "context": {"observation_count": 3},
}


def pdf_text(pdf: bytes) -> str:
    """Decode the PDF's content streams (ReportLab: ASCII85 then Flate) with the standard library."""
    parts = [pdf.decode("latin-1")]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\n?endstream", pdf, re.S):
        data = match.group(1).strip()
        try:
            parts.append(zlib.decompress(base64.a85decode(data.removesuffix(b"~>"), adobe=False)).decode("latin-1"))
        except (zlib.error, ValueError):
            continue
    text = "\n".join(parts).replace("\\(", "(").replace("\\)", ")")  # PDF string escapes
    def octal(m):  # e.g. \327 = × (cp1252); leave anything that is not a byte value untouched
        value = int(m.group(1), 8)
        return bytes([value]).decode("cp1252", errors="replace") if value < 256 else m.group(0)

    return re.sub(r"\\([0-7]{3})", octal, text)


def create(experiment_id="EXP", data_source="manual", scale=1):
    assert client.post("/api/experiments", json={
        "experiment_id": experiment_id, "name": "Report test run", "scale_liters": scale, "data_source": data_source,
        "description": "Report description", "notes": "Report notes",
    }).status_code == 201


def add(hours, experiment_id="EXP", **fields):
    assert client.post(f"/api/experiments/{experiment_id}/observations",
                       json={**BASE, "culture_time_hours": hours, **fields}).status_code == 201


@pytest.fixture
def experiment():
    create()
    add(0, aeration_rate=0.1)
    add(24, ph=6.2, dissolved_oxygen_percent=52, cell_density=2.0, aeration_rate=0.1)
    add(48, dissolved_oxygen_percent=44, cell_density=4.0, aeration_rate=0.1, feed_rate=2.0)


@pytest.fixture(autouse=True)
def gemini_must_not_be_called(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("the report must not call Gemini")

    monkeypatch.setattr(gemini_service, "gemini_generate", forbidden)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def get_pdf(experiment_id="EXP"):
    response = client.get(f"/api/experiments/{experiment_id}/report")
    assert response.status_code == 200, response.text
    return response


def post_pdf(body, experiment_id="EXP"):
    return client.post(f"/api/experiments/{experiment_id}/report", json=body)


# --- basics ---------------------------------------------------------------------------------

def test_valid_report_is_a_pdf(experiment):
    response = get_pdf()
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="bioprocess-report-EXP.pdf"'
    assert response.content.startswith(b"%PDF") and len(response.content) > 3000
    text = pdf_text(response.content)
    for heading in ("AI COPILOT FOR SCALABLE CELL-CULTURE BIOPROCESS DESIGN", "Cell-Culture Bioprocess Experiment Report",
                    "1. Executive Overview", "2. Experiment Details", "3. Process Statistics", "4. Process Trends",
                    "5. Data Quality", "6. Anomaly / Findings", "7. Scale-Up Scenario", "8. AI Analysis",
                    "9. AI Copilot", "10. Limitations", "Page 1", "Report description"):
        assert heading in text, heading


def test_unknown_experiment():
    assert client.get("/api/experiments/NOPE/report").status_code == 404
    assert post_pdf({}, "NOPE").status_code == 404


def test_empty_experiment_report():
    create()
    text = pdf_text(get_pdf().content)
    assert "Observations: 0" in text
    assert "No observations have been recorded, so no checks were run." in text
    assert text.count("Insufficient data for trend.") == 5


def test_existing_analysis_values_appear(experiment):
    analysis = client.get("/api/experiments/EXP/analysis").json()
    text = pdf_text(get_pdf().content)
    do = next(p for p in analysis["parameters"] if p["parameter"] == "dissolved_oxygen_percent")
    for value in (f"{do['start']:,.1f}", f"{do['final']:,.1f}", f"{do['average']:,.2f}", f"{do['delta']:,.1f}"):
        assert value in text, value
    for sentence in analysis["summary"][:1]:
        assert sentence.split(" (")[0] in text
    assert "Culture duration: 48 h" in text


def test_missing_optional_values_are_not_zero(experiment):
    analysis_rows = {r[0]: r for r in report.parameter_rows(
        report.build_report_data(Session(db.engine), _row("EXP"), report.ReportRequest()).analysis)}
    nutrient = analysis_rows["Nutrient concentration"]
    assert nutrient[3:] == [report.NOT_AVAILABLE] * 6  # never 0.00
    feed = analysis_rows["Feed rate"]
    assert feed[2] == "1" and feed[3] == "2.00"  # only the recorded value
    assert "Not available: no observations of this parameter" in pdf_text(get_pdf().content)


def _row(experiment_id):
    with Session(db.engine) as session:
        return session.exec(select(ExperimentRow).where(ExperimentRow.experiment_id == experiment_id)).one()


def test_anomaly_findings_included(experiment):
    anomalies = client.get("/api/experiments/EXP/anomalies").json()
    rows = report.finding_rows(report.build_report_data(Session(db.engine), _row("EXP"), report.ReportRequest()).anomalies)
    assert [r[4] for r in rows] == [f["message"] for f in anomalies["findings"]]
    text = pdf_text(get_pdf().content)
    assert f"{anomalies['finding_count']} finding(s)" in text
    assert "SIGNIFICANT" in text and "Rapid parameter" in text  # type label may wrap in its cell


def test_data_quality_rows(experiment):
    rows = dict(report.data_quality_rows(*_data_parts()))
    assert rows["Observations"] == "3" and rows["Distinct time points"] == "3"
    assert "Nutrient concentration: not recorded" in rows["Missing optional values"]
    assert rows["Trend charts"].startswith("Available")


def _data_parts():
    data = report.build_report_data(Session(db.engine), _row("EXP"), report.ReportRequest())
    return data.analysis, data.anomalies


# --- optional sections ------------------------------------------------------------------

def test_scale_up_section(experiment):
    text = pdf_text(get_pdf().content)
    assert "Scale-up scenario not included." in text
    response = post_pdf({"scale_up": {"source_experiment_id": "EXP", "target_scale_liters": 100, "target_aeration_vvm": 0.5}})
    assert response.status_code == 200
    text = pdf_text(response.content)
    assert "SCENARIO ASSUMPTIONS" in text and "100×" in text
    assert "0.5 vvm × 100 L = 50 L/min" in text
    assert "Baseline assumption" in text and "Scale-up scenario not included." not in text


def test_ai_section_optional(experiment):
    assert "AI analysis not included." in pdf_text(get_pdf().content)
    response = post_pdf({"ai_analysis": AI})
    assert response.status_code == 200
    text = pdf_text(response.content)
    assert "AI INTERPRETATION" in text and "AIOVERVIEWMARKER" in text and "UNCERTAINTYMARKER" in text
    assert "AI analysis not included." not in text


def test_copilot_section_optional(experiment):
    assert "AI Copilot response not included." in pdf_text(get_pdf().content)
    text = pdf_text(post_pdf({"copilot": COPILOT}).content)
    for marker in ("QUESTIONMARKER", "ANSWERMARKER", "EVIDENCEMARKER", "no conversation history is stored"):
        assert marker in text, marker


def test_all_sections_together(experiment):
    body = {"scale_up": {"source_experiment_id": "EXP", "target_scale_liters": 10}, "ai_analysis": AI, "copilot": COPILOT}
    response = post_pdf(body)
    assert response.status_code == 200 and response.content.startswith(b"%PDF")


@pytest.mark.parametrize("body", [
    {"scale_up": {"source_experiment_id": "OTHER", "target_scale_liters": 10}},
    {"ai_analysis": {**AI, "experiment_id": "OTHER"}},
    {"copilot": {**COPILOT, "experiment_id": "OTHER"}},
    {"ai_analysis": {"analysis": {"overview": "missing lists"}}},  # invalid structure is rejected, not repaired
    {"copilot": {"question": "", "answer": "x", "evidence": [], "uncertainties": [], "suggested_questions": []}},
    {"unexpected": True},
])
def test_invalid_optional_sections_rejected(experiment, body):
    assert post_pdf(body).status_code == 422


def test_simulated_experiment_report():
    create("SIM", data_source="simulated")
    text = pdf_text(get_pdf("SIM").content)
    assert "Simulated data." in text and "SIMULATED" in text


def test_long_run_charts_are_drawn(experiment):
    for t in range(49, 60):
        add(t, dissolved_oxygen_percent=44 - (t - 48) * 0.5)
    assert get_pdf().content.startswith(b"%PDF")


# --- Gemini independence & security ------------------------------------------------------

def test_report_without_gemini(experiment):
    assert client.get("/api/ai/status").json() == {"configured": False}
    assert get_pdf().status_code == 200  # the autouse fixture fails the test if Gemini were called


def test_no_api_key_or_secrets_in_report(experiment, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    body = {"ai_analysis": AI, "copilot": COPILOT, "scale_up": {"source_experiment_id": "EXP", "target_scale_liters": 10}}
    for response in (get_pdf(), post_pdf(body)):
        raw = response.content.decode("latin-1")
        text = pdf_text(response.content)
        for secret in (FAKE_KEY, "fake-key", "GEMINI_API_KEY"):
            assert secret not in raw and secret not in text


def count(model):
    with Session(db.engine) as session:
        return session.exec(select(func.count()).select_from(model)).one()


def test_report_does_not_modify_data(experiment):
    before = (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/EXP").json(),
              client.get("/api/experiments/EXP/observations").json())
    get_pdf()
    post_pdf({"scale_up": {"source_experiment_id": "EXP", "target_scale_liters": 10}, "ai_analysis": AI})
    after = (count(ExperimentRow), count(ObservationRow), client.get("/api/experiments/EXP").json(),
             client.get("/api/experiments/EXP/observations").json())
    assert before == after


# --- text safety -----------------------------------------------------------------------------

def test_symbols_mapped_for_pdf_fonts():
    assert report.rich("×10⁶ cells/mL") == "×10<super>6</super> cells/mL"
    assert report.rich("A → B <tag> & CO₂") == "A -&gt; B &lt;tag&gt; &amp; CO<sub>2</sub>"
    assert report.plain("Cell density (×10⁶ cells/mL)") == "Cell density (×10^6 cells/mL)"
    assert report.rich("emoji 😀") == "emoji ?"
