"""Tests for POST /api/simulate/location endpoint."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _mock_weather():
    """Mock Open-Meteo to return simple synthetic data (no network)."""
    hourly = {
        "temperature_2m": [15.0] * 168,
        "windspeed_10m": [6.0] * 168,
        "direct_radiation": [300.0] * 168,
        "diffuse_radiation": [100.0] * 168,
        "cloudcover": [30.0] * 168,
        "precipitation": [0.0] * 168,
        "time": [f"2026-01-01T{h:02d}:00" for h in range(24) for _ in range(7)][:168],
    }
    payload = {"hourly": hourly}
    with patch("backend.twin.location_scorer.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = payload
        yield mock_get


def test_simulate_location_normal() -> None:
    """Normal scenario returns plausible REF and CUE with no failures."""
    response = client.post("/api/simulate/location", json={
        "lat": 59.3293,
        "lng": 18.0686,
        "scenario": "normal",
        "servers": 50000,
        "ai_intensity": 0.72,
    })
    assert response.status_code == 200
    data = response.json()

    assert data["scenario"] == "normal"
    assert "location" in data
    assert data["location"]["lat"] == 59.3293
    assert data["location"]["lng"] == 18.0686

    assert "totals" in data
    t = data["totals"]
    assert t["hours_simulated"] == 168
    assert t["it_kwh"] > 0
    assert t["facility_kwh"] > t["it_kwh"]
    assert t["ref_pct"] >= 0
    assert t["ref_pct"] <= 100
    assert t["cue_g_per_kwh"] >= 0
    assert t["failed_steps"] == 0

    assert "grid" in data
    assert data["grid"]["carbon_intensity_g_per_kwh"] > 0

    assert "daily" in data
    assert len(data["daily"]) == 7


def test_simulate_location_dunkelflaute() -> None:
    """Dunkelflaute scenario runs without error."""
    response = client.post("/api/simulate/location", json={
        "lat": 52.52,
        "lng": 13.405,
        "scenario": "dunkelflaute",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["scenario"] == "dunkelflaute"
    assert 0 <= data["totals"]["ref_pct"] <= 100
    assert data["totals"]["cue_g_per_kwh"] >= 0


def test_simulate_location_unknown_scenario() -> None:
    """Unknown scenario returns 400."""
    response = client.post("/api/simulate/location", json={
        "lat": 48.8566,
        "lng": 2.3522,
        "scenario": "quantum_flux",
    })
    assert response.status_code == 400


def test_simulate_location_ref_cue_sanity() -> None:
    """REF increases and CUE decreases with more renewables."""
    normal = client.post("/api/simulate/location", json={
        "lat": 59.3293, "lng": 18.0686,
        "scenario": "normal",
    }).json()

    dunkel = client.post("/api/simulate/location", json={
        "lat": 59.3293, "lng": 18.0686,
        "scenario": "dunkelflaute",
    }).json()

    assert normal["totals"]["ref_pct"] >= dunkel["totals"]["ref_pct"]
    assert normal["totals"]["cue_g_per_kwh"] <= dunkel["totals"]["cue_g_per_kwh"]
