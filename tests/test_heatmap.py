import pytest

from backend.twin import heatmap, location_scorer as ls


def _fake_point(lat, lng):
    return {"avg_temp": 10.0, "avg_wind": 8.0, "avg_irr": 200.0}


def _fake_points(coords):
    return {coord: _fake_point(*coord) for coord in coords}


def test_compute_grid_queries_a_capped_lattice_for_wide_viewports(monkeypatch):
    calls = []

    def fake_fetch_points(coords):
        calls.append(list(coords))
        return _fake_points(coords)

    monkeypatch.setattr(heatmap, "_fetch_points", fake_fetch_points)
    monkeypatch.setattr(heatmap, "_GRID_CACHE", {}, raising=False)

    grid = heatmap.compute_grid(north=50.0, south=40.0, east=40.0, west=-40.0)

    assert len(calls) == 1
    assert len(calls[0]) <= 64
    assert len(grid["potential"]) == grid["rows"]


def test_compute_grid_omits_component_grids_by_default(monkeypatch):
    monkeypatch.setattr(heatmap, "_fetch_points", _fake_points)
    monkeypatch.setattr(heatmap, "_GRID_CACHE", {}, raising=False)

    grid = heatmap.compute_grid(north=1.0, south=0.0, east=1.0, west=0.0, resolution=0.5)

    assert "potential" in grid
    assert "composite" not in grid
    assert "solar" not in grid
    assert "wind" not in grid
    assert len(grid["potential"]) == grid["rows"]


def test_compute_grid_can_include_component_grids(monkeypatch):
    monkeypatch.setattr(heatmap, "_fetch_points", _fake_points)
    monkeypatch.setattr(heatmap, "_GRID_CACHE", {}, raising=False)

    grid = heatmap.compute_grid(
        north=1.0, south=0.0, east=1.0, west=0.0, resolution=0.5,
        include_components=True,
    )

    assert "solar" in grid and "wind" in grid


def test_compute_grid_result_is_cached(monkeypatch):
    calls = []

    def fake_fetch_points(coords):
        calls.append(coords)
        return _fake_points(coords)

    monkeypatch.setattr(heatmap, "_fetch_points", fake_fetch_points)
    monkeypatch.setattr(heatmap, "_GRID_CACHE", {}, raising=False)

    kwargs = dict(north=1.0, south=0.0, east=1.0, west=0.0, resolution=0.5)
    heatmap.compute_grid(**kwargs)
    heatmap.compute_grid(**kwargs)

    assert len(calls) == 1


def test_compute_grid_raises_when_weather_unavailable(monkeypatch):
    monkeypatch.setattr(heatmap, "_fetch_points", lambda coords: {})
    monkeypatch.setattr(heatmap, "_GRID_CACHE", {}, raising=False)

    with pytest.raises(RuntimeError, match="No weather data"):
        heatmap.compute_grid(
            north=1.0, south=0.0, east=1.0, west=0.0, resolution=0.5,
        )


def test_compute_grid_cache_key_uses_capped_resolution(monkeypatch):
    monkeypatch.setattr(heatmap, "_fetch_points", _fake_points)
    monkeypatch.setattr(heatmap, "_GRID_CACHE", {}, raising=False)

    grid = heatmap.compute_grid(
        north=10.0, south=-10.0, east=10.0, west=-10.0, resolution=0.01,
    )

    assert len(heatmap._GRID_CACHE) == 1
    cache_key = next(iter(heatmap._GRID_CACHE))
    assert cache_key[4] == grid["resolution"]


def test_fetch_points_retries_batch_once(monkeypatch):
    calls = []

    def fake_batch(coords):
        calls.append(list(coords))
        if len(calls) == 1:
            raise RuntimeError("transient")
        return [_fake_point(*coord) for coord in coords]

    monkeypatch.setattr(heatmap, "_fetch_batch", fake_batch)
    monkeypatch.setattr(heatmap, "_WEATHER_CACHE", {}, raising=False)
    monkeypatch.setattr(heatmap.time, "sleep", lambda _seconds: None)

    result = heatmap._fetch_points([(1.0, 2.0)])

    assert len(calls) == 2
    assert result[(1.0, 2.0)] == {"avg_temp": 10.0, "avg_wind": 8.0, "avg_irr": 200.0}


def test_fetch_batch_uses_one_request_with_comma_separated_coordinates(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {"hourly": {
                    "temperature_2m": [10.0],
                    "windspeed_10m": [8.0],
                    "direct_radiation": [150.0],
                    "diffuse_radiation": [50.0],
                }},
                {"hourly": {
                    "temperature_2m": [12.0],
                    "windspeed_10m": [6.0],
                    "direct_radiation": [100.0],
                    "diffuse_radiation": [40.0],
                }},
            ]

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse()

    monkeypatch.setattr(heatmap.requests, "get", fake_get)

    result = heatmap._fetch_batch([(1.0, 2.0), (3.0, 4.0)])

    assert len(result) == 2
    assert captured["params"]["latitude"] == "1.0000,3.0000"
    assert captured["params"]["longitude"] == "2.0000,4.0000"
    assert captured["params"]["hourly"] == ls._HOURLY_VARIABLES
    assert result[0] == {"avg_temp": 10.0, "avg_wind": 8.0, "avg_irr": 200.0}
