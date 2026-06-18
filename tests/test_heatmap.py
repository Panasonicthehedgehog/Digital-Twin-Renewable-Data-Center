from backend.twin import heatmap


def test_compute_grid_returns_potential_not_composite(monkeypatch):
    monkeypatch.setattr(heatmap, "_fetch_point",
                        lambda lat, lng: {"avg_temp": 10.0, "avg_wind": 8.0, "avg_irr": 200.0})
    grid = heatmap.compute_grid(north=1.0, south=0.0, east=1.0, west=0.0, resolution=0.5)
    assert "potential" in grid
    assert "composite" not in grid
    assert "solar" in grid and "wind" in grid
    assert len(grid["potential"]) == grid["rows"]
