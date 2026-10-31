import asyncio
import inspect

from fastapi.testclient import TestClient

from backend.app import TwinRuntime, analyze_location, app, simulate_location
from backend.paths import resource_path
from backend.twin import heatmap
from backend.twin.config import load_config


client = TestClient(app)


def test_state_endpoint() -> None:
    response = client.get('/api/state')
    assert response.status_code == 200
    payload = response.json()
    assert 'loads' in payload
    assert payload['loads']['facility_kw'] > 0


def test_scenario_activation() -> None:
    response = client.post('/api/scenario', json={'name': 'combined_stress'})
    assert response.status_code == 200
    payload = response.json()
    assert payload['scenario'] == 'combined_stress'
    assert payload['state']['scenario'] == 'combined_stress'


def test_config_update() -> None:
    config = client.get('/api/config').json()
    config['energy']['grid_capacity_kw'] = 14000
    response = client.put('/api/config', json=config)
    assert response.status_code == 200
    payload = response.json()
    assert payload['config']['energy']['grid_capacity_kw'] == 14000


def test_location_endpoints_run_in_threadpool() -> None:
    assert not inspect.iscoroutinefunction(analyze_location)
    assert not inspect.iscoroutinefunction(simulate_location)


def test_tick_skips_simulation_without_clients(monkeypatch) -> None:
    runtime = TwinRuntime(load_config(resource_path("config/default_config.yaml")))
    runtime.clients.clear()
    calls = []
    monkeypatch.setattr(runtime.engine, "simulate_step", lambda: calls.append(1) or {})

    asyncio.run(runtime._tick())

    assert calls == []


def _fake_fetch_points(coords):
    return {
        coord: {"avg_temp": 10.0, "avg_wind": 8.0, "avg_irr": 200.0}
        for coord in coords
    }


def test_heatmap_response_is_gzipped(monkeypatch) -> None:
    monkeypatch.setattr(heatmap, "_fetch_points", _fake_fetch_points)
    monkeypatch.setattr(heatmap, "_GRID_CACHE", {}, raising=False)

    response = client.post(
        "/api/heatmap/grid",
        json={"north": 1.0, "south": 0.0, "east": 1.0, "west": 0.0},
        headers={"Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"


def test_heatmap_grid_rejects_inverted_bounds() -> None:
    response = client.post(
        "/api/heatmap/grid",
        json={"north": 10.0, "south": 20.0, "east": 1.0, "west": 0.0},
    )

    assert response.status_code == 422


def test_heatmap_grid_forwards_include_components(monkeypatch) -> None:
    monkeypatch.setattr(heatmap, "_fetch_points", _fake_fetch_points)
    monkeypatch.setattr(heatmap, "_GRID_CACHE", {}, raising=False)

    response = client.post(
        "/api/heatmap/grid",
        json={
            "north": 1.0, "south": 0.0, "east": 1.0, "west": 0.0,
            "include_components": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "solar" in payload and "wind" in payload
