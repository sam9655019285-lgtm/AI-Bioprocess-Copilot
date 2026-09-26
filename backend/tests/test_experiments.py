from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "sample_data" / "example_observations.csv"

VALID_OBSERVATION = {
    "experiment_id": "EXP-001",
    "culture_time_hours": 24,
    "temperature_c": 37.0,
    "ph": 7.05,
    "dissolved_oxygen_percent": 82,
    "agitation_rpm": 120,
    "cell_density": 0.85,
}

HEADER = (
    "experiment_id,culture_time_hours,temperature_c,ph,dissolved_oxygen_percent,"
    "agitation_rpm,cell_density,feed_rate,nutrient_concentration,aeration_rate,notes"
)


def upload(csv_text, filename="data.csv"):
    return client.post(
        "/api/experiments/upload",
        files={"file": (filename, csv_text.encode("utf-8"), "text/csv")},
    )


def error_fields(response):
    return {err["loc"][-1] for err in response.json()["detail"]}


def test_schema_lists_required_and_optional_fields():
    response = client.get("/api/experiments/schema")
    assert response.status_code == 200
    fields = {f["name"]: f for f in response.json()}
    assert fields["ph"]["required"] is True
    assert fields["ph"]["maximum"] == 14
    assert fields["feed_rate"]["required"] is False
    assert fields["notes"]["type"] == "string"


def test_valid_manual_observation():
    payload = {**VALID_OBSERVATION, "feed_rate": 2.5, "notes": "Day 1"}
    response = client.post("/api/experiments/observations", json=payload)
    assert response.status_code == 201
    observation = response.json()["observation"]
    assert observation["experiment_id"] == "EXP-001"
    assert observation["feed_rate"] == 2.5
    assert observation["aeration_rate"] is None


def test_manual_observation_missing_required_field():
    payload = {k: v for k, v in VALID_OBSERVATION.items() if k != "ph"}
    response = client.post("/api/experiments/observations", json=payload)
    assert response.status_code == 422
    assert error_fields(response) == {"ph"}


def test_manual_observation_invalid_numeric_value():
    payload = {**VALID_OBSERVATION, "temperature_c": "warm"}
    response = client.post("/api/experiments/observations", json=payload)
    assert response.status_code == 422
    assert error_fields(response) == {"temperature_c"}


def test_manual_observation_rejects_nan_and_negative_values():
    payload = {**VALID_OBSERVATION, "cell_density": -1, "agitation_rpm": "nan"}
    response = client.post("/api/experiments/observations", json=payload)
    assert response.status_code == 422
    assert error_fields(response) == {"cell_density", "agitation_rpm"}


def test_valid_csv_upload():
    csv_text = "\n".join([
        HEADER,
        "EXP-001,0,37.0,7.1,95,120,0.3,,6.0,0.05,Inoculation",
        "EXP-001,24,37.0,7.05,82,120,0.85,,,,",
        "",  # blank lines are skipped
    ])
    response = upload(csv_text)
    assert response.status_code == 200
    body = response.json()
    assert body["total_rows"] == 2
    assert body["accepted_count"] == 2
    assert body["rejected_count"] == 0
    assert body["errors"] == []
    assert body["observations"][0]["notes"] == "Inoculation"
    assert body["observations"][1]["nutrient_concentration"] is None


def test_csv_missing_required_column():
    csv_text = "experiment_id,culture_time_hours,temperature_c,ph\nEXP-001,0,37,7.1\n"
    response = upload(csv_text)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "dissolved_oxygen_percent" in detail
    assert "cell_density" in detail


def test_csv_with_invalid_row():
    csv_text = "\n".join([
        HEADER,
        "EXP-001,0,37.0,7.1,95,120,0.3,,,,",
        "EXP-001,24,37.0,abc,82,120,,,,,",
        "EXP-001,48,36.9,7.0,68,130,2.1,,,,",
    ])
    body = upload(csv_text).json()
    assert body["accepted_count"] == 2
    assert body["rejected_count"] == 1
    errors = {(e["row"], e["field"]): e for e in body["errors"]}
    assert errors.keys() == {(3, "ph"), (3, "cell_density")}
    assert errors[(3, "ph")]["value"] == "abc"


def test_csv_reports_ignored_columns_and_rejects_non_csv():
    csv_text = HEADER + ",operator\nEXP-001,0,37,7.1,95,120,0.3,,,,,Alice\n"
    assert upload(csv_text).json()["ignored_columns"] == ["operator"]
    assert upload("hello", filename="data.txt").status_code == 400
    assert upload("").status_code == 422


def test_sample_data_file_is_valid():
    with open(SAMPLE_CSV, "rb") as f:
        response = client.post("/api/experiments/upload", files={"file": ("example.csv", f, "text/csv")})
    body = response.json()
    assert body["rejected_count"] == 0
    assert body["accepted_count"] == 8
