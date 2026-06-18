import pytest

from backend.twin import location_scorer as ls


def test_solar_capacity_factor():
    assert ls.solar_capacity_factor(0.0) == 0.0
    assert ls.solar_capacity_factor(250.0) == pytest.approx(0.20)   # 250/1000*0.80
    assert ls.solar_capacity_factor(1000.0) == 0.40                 # 0.80 capped to 0.40


def test_wind_capacity_factor():
    assert ls.wind_capacity_factor(0.0) == 0.0
    assert ls.wind_capacity_factor(2.0) == 0.0                      # v_hub=2.8 <= 3 -> 0
    assert ls.wind_capacity_factor(7.0) == pytest.approx((7.0 * 1.4 - 3.0) / 9.0 * 0.55)
    assert ls.wind_capacity_factor(10.0) == 0.55                    # v_hub=14 -> rated
    assert ls.wind_capacity_factor(20.0) == 0.0                     # v_hub=28 > 25 -> cut-out


def test_expected_generation_mw_weights_each_fuel():
    fuel = {"Solar": 1000.0, "Wind": 1000.0, "Hydro": 100.0, "Coal": 5000.0}
    result = ls.expected_generation_mw(fuel, avg_irr_wm2=250.0, avg_wind_ms=10.0)
    # Solar 1000*0.20 + Wind 1000*0.55 + Hydro 100*0.40 ; Coal ignored
    assert result == pytest.approx(1000 * 0.20 + 1000 * 0.55 + 100 * 0.40, abs=0.05)


def test_expected_generation_mw_never_exceeds_nameplate():
    fuel = {"Solar": 500.0, "Wind": 500.0, "Geothermal": 200.0}
    result = ls.expected_generation_mw(fuel, avg_irr_wm2=300.0, avg_wind_ms=8.0)
    assert 0.0 < result <= sum(fuel.values())


def test_expected_generation_mw_empty():
    assert ls.expected_generation_mw({}, 200.0, 8.0) == 0.0
