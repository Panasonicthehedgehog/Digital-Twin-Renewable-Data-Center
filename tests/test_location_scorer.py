import threading

import pytest

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


def test_score_grid_regional_is_renewable_fraction():
    assert ls.score_grid_regional(800.0, 1000.0) == 80.0
    assert ls.score_grid_regional(50.0, 50.0) == 100.0      # fully renewable
    assert ls.score_grid_regional(0.0, 0.0) == 0.0          # no plants -> guard


def test_grid_and_coverage_are_decoupled(monkeypatch):
    # Small but 100% renewable region + large DC: grid high, coverage low.
    monkeypatch.setattr(ls, "get_location_info",
                        lambda lat, lng: {"city": "X", "country": "Y",
                                          "country_code": "DE", "display": "X, Y"})
    monkeypatch.setattr(ls, "fetch_weather_forecast", _fake_weather)
    monkeypatch.setattr(ls, "get_regional_plant_stats",
                        lambda lat, lng: {"fuel_mw": {"Solar": 50.0},
                                          "total_mw": 50.0, "renewable_mw": 50.0,
                                          "plant_count": 1, "top_plants": []})
    result = ls.analyze_location(0.0, 0.0, servers=200_000, ai_intensity=0.7)
    assert result["scores"]["grid"] == 100.0
    assert result["scores"]["load_coverage"] < 100.0


class _FakeWeatherResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return _fake_weather(0, 0)


def test_fetch_weather_forecast_is_cached(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _FakeWeatherResponse()

    monkeypatch.setattr(ls.requests, "get", fake_get)
    monkeypatch.setattr(ls, "_WEATHER_FORECAST_CACHE", {}, raising=False)

    ls.fetch_weather_forecast(52.5200, 13.4000)
    ls.fetch_weather_forecast(52.5201, 13.4001)

    assert len(calls) == 1


def test_fetch_weather_forecast_requests_only_used_variables(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params)
        return _FakeWeatherResponse()

    monkeypatch.setattr(ls.requests, "get", fake_get)
    monkeypatch.setattr(ls, "_WEATHER_FORECAST_CACHE", {}, raising=False)

    ls.fetch_weather_forecast(0.0, 0.0)

    assert captured["hourly"] == [
        "temperature_2m", "windspeed_10m", "direct_radiation", "diffuse_radiation",
    ]


def test_get_location_info_is_cached(monkeypatch):
    calls = []

    def fake_reverse(lat, lng):
        calls.append((lat, lng))
        return {"address": {"city": "X", "country": "Y", "country_code": "de"}}

    monkeypatch.setattr(ls, "_nominatim_reverse", fake_reverse)
    monkeypatch.setattr(ls, "_LOCATION_CACHE", {}, raising=False)

    first = ls.get_location_info(52.5200, 13.4050)
    second = ls.get_location_info(52.5201, 13.4051)

    assert len(calls) == 1
    assert first == second


def _fake_weather_with_temp(temp: float) -> dict:
    n = 168
    return {"hourly": {
        "temperature_2m": [temp] * n,
        "windspeed_10m": [8.0] * n,
        "direct_radiation": [150.0] * n,
        "diffuse_radiation": [50.0] * n,
        "time": ["2026-06-18T00:00"] * n,
    }}


def test_analyze_location_pue_uses_rounded_temperature(monkeypatch):
    monkeypatch.setattr(ls, "get_location_info",
                        lambda lat, lng: {"city": "X", "country": "Y",
                                          "country_code": "DE", "display": "X, Y"})
    monkeypatch.setattr(ls, "fetch_weather_forecast",
                        lambda lat, lng, days=7: _fake_weather_with_temp(14.96))
    monkeypatch.setattr(ls, "get_regional_plant_stats",
                        lambda lat, lng: {"fuel_mw": {"Solar": 500.0},
                                          "total_mw": 500.0, "renewable_mw": 500.0,
                                          "plant_count": 1, "top_plants": []})

    result = ls.analyze_location(0.0, 0.0, servers=1000, ai_intensity=0.5)

    # The frontend recomputes PUE from the rounded value returned to it.
    assert result["weather"]["avg_temperature_c"] == 15.0
    assert result["energy"]["estimated_pue"] == ls.estimate_pue(15.0)


def test_nominatim_reverse_releases_lock_before_http(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"address": {}}

    def fake_get(*args, **kwargs):
        entered.set()
        assert release.wait(2.0)
        return FakeResponse()

    monkeypatch.setattr(ls.requests, "get", fake_get)
    monkeypatch.setattr(ls.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(ls, "_NOMINATIM_LAST", 0.0, raising=False)

    worker = threading.Thread(target=ls._nominatim_reverse, args=(1.0, 2.0))
    worker.start()
    try:
        assert entered.wait(1.0)

        # The lock must not be held while the HTTP request is in flight.
        assert ls._NOMINATIM_LOCK.acquire(timeout=0.5)
        ls._NOMINATIM_LOCK.release()
    finally:
        release.set()
        worker.join(2.0)

    assert not worker.is_alive()


def test_nominatim_reverse_throttles_requests(monkeypatch):
    clock = [100.0]
    sleeps = []

    monkeypatch.setattr(ls, "_NOMINATIM_LAST", 0.0, raising=False)
    monkeypatch.setattr(ls.time, "monotonic", lambda: clock[0])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(ls.time, "sleep", fake_sleep)

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"address": {}}

    monkeypatch.setattr(ls.requests, "get", lambda *args, **kwargs: FakeResponse())

    ls._nominatim_reverse(1.0, 2.0)
    clock[0] += 0.2
    ls._nominatim_reverse(3.0, 4.0)

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.8)
