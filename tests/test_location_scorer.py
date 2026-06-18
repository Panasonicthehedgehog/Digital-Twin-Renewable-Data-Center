from backend.twin import location_scorer as ls


def test_score_load_coverage_uses_effective_demand():
    assert ls.score_load_coverage(100.0, 50.0) == 100.0   # capped at 100
    assert ls.score_load_coverage(50.0, 100.0) == 50.0
    assert ls.score_load_coverage(50.0, 0.0) == 0.0        # guard against div-by-zero


def _fake_weather(lat, lng, days=7):
    n = 168
    return {"hourly": {
        "temperature_2m": [5.0] * n,
        "windspeed_10m": [8.0] * n,
        "direct_radiation": [150.0] * n,
        "diffuse_radiation": [50.0] * n,
        "cloudcover": [0.0] * n,
        "precipitation": [0.0] * n,
        "time": ["2026-06-18T00:00"] * n,
    }}


def test_analyze_location_renames_to_suitability_and_uses_effective_demand(monkeypatch):
    monkeypatch.setattr(ls, "get_location_info",
                        lambda lat, lng: {"city": "X", "country": "Y",
                                          "country_code": "DE", "display": "X, Y"})
    monkeypatch.setattr(ls, "fetch_weather_forecast", _fake_weather)
    monkeypatch.setattr(ls, "get_regional_plant_stats",
                        lambda lat, lng: {"fuel_mw": {"Solar": 500.0, "Wind": 300.0},
                                          "total_mw": 1000.0, "renewable_mw": 800.0,
                                          "plant_count": 5, "top_plants": []})
    result = ls.analyze_location(0.0, 0.0, servers=1000, ai_intensity=0.5)

    assert "suitability" in result["scores"]
    assert "composite" not in result["scores"]
    assert "effective_demand_mw" in result["regional_grid"]
    # coverage uses effective demand (= dc_capacity * PUE), not raw IT load
    rg = result["regional_grid"]
    expected = ls.score_load_coverage(rg["effective_renewable_mw"], rg["effective_demand_mw"])
    assert result["scores"]["load_coverage"] == expected


def test_analyze_location_coverage_uses_expected_generation(monkeypatch):
    monkeypatch.setattr(ls, "get_location_info",
                        lambda lat, lng: {"city": "X", "country": "Y",
                                          "country_code": "DE", "display": "X, Y"})
    monkeypatch.setattr(ls, "fetch_weather_forecast", _fake_weather)
    monkeypatch.setattr(ls, "get_regional_plant_stats",
                        lambda lat, lng: {"fuel_mw": {"Solar": 500.0, "Wind": 300.0},
                                          "total_mw": 1000.0, "renewable_mw": 800.0,
                                          "plant_count": 5, "top_plants": []})
    result = ls.analyze_location(0.0, 0.0, servers=1000, ai_intensity=0.5)

    rg = result["regional_grid"]
    assert "effective_renewable_mw" in rg
    # expected generation must be below nameplate (CFs < 1)
    assert rg["effective_renewable_mw"] < rg["renewable_mw"]
    # load_coverage is derived from expected generation, not nameplate
    expected = ls.score_load_coverage(rg["effective_renewable_mw"], rg["effective_demand_mw"])
    assert result["scores"]["load_coverage"] == expected
