import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

BASE = {"temperature_c": 37.0, "ph": 7.0, "dissolved_oxygen_percent": 50, "agitation_rpm": 180, "cell_density": 1.0}


def create(experiment_id="EXP-A", data_source="manual"):
    response = client.post("/api/experiments", json={
        "experiment_id": experiment_id, "name": f"Run {experiment_id}", "scale_liters": 10,
        "description": "analysis test", "data_source": data_source,
    })
    assert response.status_code == 201


def add(target, hours, **fields):
    response = client.post(
        f"/api/experiments/{target}/observations", json={**BASE, "culture_time_hours": hours, **fields}
    )
    assert response.status_code == 201


def analysis(target="EXP-A"):
    response = client.get(f"/api/experiments/{target}/analysis")
    assert response.status_code == 200
    return response.json()


def params(body):
    return {p["parameter"]: p for p in body["parameters"]}


@pytest.fixture
def three_point_experiment():
    """Inserted out of chronological order; culture times are non-contiguous (0, 24, 96 h)."""
    create()
    add("EXP-A", 96, temperature_c=36.5, ph=6.8, dissolved_oxygen_percent=30, cell_density=8.0, agitation_rpm=200)
    add("EXP-A", 0, temperature_c=37.0, ph=7.1, dissolved_oxygen_percent=90, cell_density=0.5, agitation_rpm=150)
    add("EXP-A", 24, temperature_c=37.2, ph=7.0, dissolved_oxygen_percent=60, cell_density=2.0, agitation_rpm=160)


def test_analysis_with_multiple_observations(three_point_experiment):
    body = analysis()
    assert body["experiment"]["experiment_id"] == "EXP-A"
    assert body["experiment"]["description"] == "analysis test"
    assert body["experiment"]["data_source"] == "manual"
    assert body["experiment"]["scale_liters"] == 10
    assert [o["culture_time_hours"] for o in body["observations"]] == [0, 24, 96]  # chronological
    assert body["latest_observation"]["culture_time_hours"] == 96
    assert body["latest_observation"]["cell_density"] == 8.0
    assert set(params(body)) == {"temperature_c", "ph", "dissolved_oxygen_percent", "agitation_rpm", "cell_density"}


def test_min_max_average(three_point_experiment):
    p = params(analysis())
    assert (p["temperature_c"]["minimum"], p["temperature_c"]["maximum"]) == (36.5, 37.2)
    assert p["temperature_c"]["average"] == pytest.approx((37.0 + 37.2 + 36.5) / 3)
    assert p["dissolved_oxygen_percent"]["average"] == pytest.approx(60.0)
    assert p["cell_density"]["average"] == pytest.approx(3.5)


def test_start_final_delta(three_point_experiment):
    p = params(analysis())
    assert (p["cell_density"]["start"], p["cell_density"]["final"]) == (0.5, 8.0)
    assert p["cell_density"]["delta"] == pytest.approx(7.5)
    assert p["ph"]["delta"] == pytest.approx(6.8 - 7.1)  # not rounded
    assert (p["ph"]["start_time_hours"], p["ph"]["final_time_hours"]) == (0, 96)


def test_culture_duration_and_time_coverage(three_point_experiment):
    body = analysis()
    assert (body["culture_start_hours"], body["culture_end_hours"]) == (0, 96)
    assert body["culture_duration_hours"] == 96
    quality = body["data_quality"]
    assert (quality["smallest_interval_hours"], quality["largest_interval_hours"]) == (24, 72)
    assert quality["enough_for_trends"] is True


def test_observation_count(three_point_experiment):
    body = analysis()
    assert body["observation_count"] == 3
    assert body["experiment"]["observation_count"] == 3
    assert body["data_quality"]["observation_count"] == 3
    assert all(p["count"] == 3 for p in body["parameters"])


def test_optional_fields_with_missing_values():
    create()
    add("EXP-A", 0)
    add("EXP-A", 12, feed_rate=1.5, nutrient_concentration=6.0)
    add("EXP-A", 24, nutrient_concentration=5.0)
    add("EXP-A", 36, feed_rate=2.5)
    body = analysis()
    p = params(body)
    assert "aeration_rate" not in p  # never recorded -> no invented statistics
    assert p["feed_rate"]["count"] == 2
    assert (p["feed_rate"]["start"], p["feed_rate"]["final"], p["feed_rate"]["delta"]) == (1.5, 2.5, 1.0)
    assert (p["feed_rate"]["start_time_hours"], p["feed_rate"]["final_time_hours"]) == (12, 36)
    assert p["feed_rate"]["average"] == pytest.approx(2.0)
    assert p["nutrient_concentration"]["delta"] == pytest.approx(-1.0)
    missing = {m["parameter"]: m["missing"] for m in body["data_quality"]["missing_values"]}
    assert missing == {"feed_rate": 2, "nutrient_concentration": 2, "aeration_rate": 4}


def test_single_observation():
    create()
    add("EXP-A", 5, cell_density=0.7)
    body = analysis()
    assert body["observation_count"] == 1
    assert body["culture_duration_hours"] == 0
    cells = params(body)["cell_density"]
    assert cells["start"] == cells["final"] == cells["minimum"] == cells["maximum"] == cells["average"] == 0.7
    assert cells["delta"] == 0
    quality = body["data_quality"]
    assert quality["enough_for_trends"] is False
    assert quality["largest_interval_hours"] is None
    assert body["summary"][0] == "1 observation was recorded, at 5 h culture time."


def test_empty_experiment_returns_empty_analysis():
    create()
    body = analysis()
    assert body["observation_count"] == 0
    assert body["parameters"] == []
    assert body["observations"] == []
    assert body["latest_observation"] is None
    assert body["culture_duration_hours"] is None
    assert body["data_quality"]["enough_for_trends"] is False
    assert body["summary"] == ["No observations have been recorded for this experiment yet."]


def test_unknown_experiment_returns_404():
    response = client.get("/api/experiments/NOPE/analysis")
    assert response.status_code == 404
    assert response.json()["detail"] == "Experiment 'NOPE' not found."


def test_duplicate_time_points_counted():
    create()
    add("EXP-A", 0)
    add("EXP-A", 0, cell_density=1.1)
    add("EXP-A", 1)
    quality = analysis()["data_quality"]
    assert (quality["distinct_time_points"], quality["duplicate_time_points"]) == (2, 1)


def test_summary_is_factual(three_point_experiment):
    summary = analysis()["summary"]
    assert summary[0] == "3 observations were recorded over 96 culture hours (0 h to 96 h)."
    assert "Cell density changed from 0.50 to 8.00 ×10⁶ cells/mL." in summary
    assert "Temperature ranged from 36.50 to 37.20 °C." in summary
    assert "Dissolved oxygen ranged from 30.0 to 90.0 % air sat." in summary  # no double full stop
    evaluative = re.compile(r"\b(good|bad|optimal|normal|abnormal|anomal\w*|risk\w*|safe|unsafe|contamina\w*)\b", re.I)
    assert not any(evaluative.search(s) for s in summary)


def test_analysis_works_for_simulated_and_csv_experiments():
    create("CSV-1", data_source="csv")
    csv_text = "culture_time_hours,temperature_c,ph,dissolved_oxygen_percent,agitation_rpm,cell_density\n0,37,7,50,100,1\n2,37,7,48,100,1.2\n"
    client.post("/api/experiments/CSV-1/upload", files={"file": ("d.csv", csv_text.encode(), "text/csv")})
    assert analysis("CSV-1")["observation_count"] == 2
    create("SIM-1", data_source="simulated")
    assert analysis("SIM-1")["experiment"]["data_source"] == "simulated"
