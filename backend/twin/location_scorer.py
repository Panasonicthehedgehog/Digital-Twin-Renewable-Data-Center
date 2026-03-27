"""Location scorer for hyperscaler data center site selection.

Fetches real weather data from Open-Meteo and computes a multi-dimensional
suitability score covering solar potential, wind potential, climate (cooling
efficiency), and grid infrastructure reliability.
"""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Power plant database – loaded once at module startup from WRI global CSV
# ---------------------------------------------------------------------------

_RENEWABLE_FUELS: frozenset[str] = frozenset(
    ["Hydro", "Solar", "Wind", "Biomass", "Geothermal", "Wave and Tidal"]
)
_CHART_FUELS: frozenset[str] = frozenset(
    ["Hydro", "Solar", "Wind", "Biomass", "Geothermal"]
)

# Each entry: (lat, lon, capacity_mw, fuel, is_renewable)
_PLANT_DATA: list[tuple[float, float, float, str, bool]] = []


def _load_plants() -> None:
    csv_path = Path(__file__).parent.parent.parent / "data" / "all_power_plants_clean.csv"
    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    _PLANT_DATA.append((
                        float(row["latitude"]),
                        float(row["longitude"]),
                        float(row["capacity_mw"]) if row["capacity_mw"] else 0.0,
                        row["fuel1"] or "Unknown",
                        row["is_renewable"] == "True",
                        row.get("name", "Unknown"),
                    ))
                except (ValueError, KeyError):
                    continue
    except FileNotFoundError:
        pass  # graceful fallback – grid scores will be 0


_load_plants()

_REGIONAL_RADIUS_KM = 100.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 6_371.0 * 2 * math.asin(math.sqrt(a))


def get_regional_plant_stats(lat: float, lng: float) -> dict[str, Any]:
    """Aggregate power plant capacity within _REGIONAL_RADIUS_KM of the site."""
    fuel_mw: dict[str, float] = {}
    total_mw = 0.0
    renewable_mw = 0.0
    count = 0
    # Bounding-box pre-filter before haversine (1° lat ≈ 111 km)
    lat_margin = _REGIONAL_RADIUS_KM / 111.0
    lon_margin = _REGIONAL_RADIUS_KM / max(0.01, 111.0 * math.cos(math.radians(lat)))
    plant_records: list[dict[str, Any]] = []
    for p_lat, p_lon, cap, fuel, is_ren, name in _PLANT_DATA:
        if abs(p_lat - lat) > lat_margin or abs(p_lon - lng) > lon_margin:
            continue
        dist = _haversine_km(lat, lng, p_lat, p_lon)
        if dist > _REGIONAL_RADIUS_KM:
            continue
        fuel_mw[fuel] = fuel_mw.get(fuel, 0.0) + cap
        total_mw += cap
        if is_ren:
            renewable_mw += cap
        count += 1
        plant_records.append({"name": name, "fuel": fuel, "capacity_mw": cap,
                               "is_renewable": is_ren, "distance_km": round(dist, 1)})
    # Select top 3 per fuel type (by capacity) across ALL plants, fill to MAX_PLANTS.
    # The frontend handles filtering by renewable/all.
    MAX_PLANTS = 25
    TOP_PER_FUEL = 3
    renewable_records = plant_records  # include all fuels for frontend filter
    renewable_records.sort(key=lambda x: -x["capacity_mw"])
    selected: list[dict[str, Any]] = []
    seen_per_fuel: dict[str, int] = {}
    remainder: list[dict[str, Any]] = []
    for p in renewable_records:
        n = seen_per_fuel.get(p["fuel"], 0)
        if n < TOP_PER_FUEL:
            selected.append(p)
            seen_per_fuel[p["fuel"]] = n + 1
        else:
            remainder.append(p)
    slots_left = MAX_PLANTS - len(selected)
    if slots_left > 0:
        selected_ids = {id(p) for p in selected}
        for p in remainder:
            if slots_left <= 0:
                break
            if id(p) not in selected_ids:
                selected.append(p)
                slots_left -= 1
    selected.sort(key=lambda x: -x["capacity_mw"])
    return {
        "fuel_mw": fuel_mw, "total_mw": total_mw,
        "renewable_mw": renewable_mw, "plant_count": count,
        "top_plants": selected,
    }


def score_grid_regional(renewable_mw: float, total_mw: float) -> float:
    """Grid score 0–100 derived from actual regional plant data.

    50 pts for renewable fraction + 50 pts for absolute renewable capacity
    (log-scaled, ceiling at 100 GW).
    """
    fraction = renewable_mw / total_mw if total_mw > 0 else 0.0
    capacity_score = min(50.0, math.log1p(renewable_mw) / math.log1p(100_000.0) * 50.0)
    return round(fraction * 50.0 + capacity_score, 1)


# ---------------------------------------------------------------------------
# Nominatim reverse geocoding
# ---------------------------------------------------------------------------

def _nominatim_reverse(lat: float, lng: float) -> dict[str, Any]:
    """Call Nominatim reverse geocode; returns address dict."""
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lng, "format": "json", "addressdetails": 1}
    headers = {"User-Agent": "DigitalTwin-DC-LocationFinder/1.0 (research project)"}
    resp = requests.get(url, params=params, headers=headers, timeout=8)
    resp.raise_for_status()
    return resp.json()


def get_location_info(lat: float, lng: float) -> dict[str, str]:
    """Return city, country, and display name for given coordinates."""
    try:
        data = _nominatim_reverse(lat, lng)
        addr = data.get("address", {})
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("municipality")
            or addr.get("county")
            or "Unknown"
        )
        country = addr.get("country", "Unknown")
        country_code = addr.get("country_code", "??").upper()
        display = f"{city}, {country}" if city != "Unknown" else f"{lat:.3f}°N, {lng:.3f}°E"
        return {"city": city, "country": country, "country_code": country_code, "display": display}
    except Exception:
        return {
            "city": "Unknown",
            "country": "Unknown",
            "country_code": "??",
            "display": f"{lat:.3f}°, {lng:.3f}°",
        }


# ---------------------------------------------------------------------------
# Open-Meteo weather data
# ---------------------------------------------------------------------------

def fetch_weather_forecast(lat: float, lng: float, days: int = 7) -> dict[str, Any]:
    """Fetch hourly forecast from Open-Meteo (free, no API key required)."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lng,
        "hourly": [
            "temperature_2m",
            "windspeed_10m",
            "direct_radiation",
            "diffuse_radiation",
            "cloudcover",
            "precipitation",
        ],
        "forecast_days": days,
        "timezone": "UTC",
        "windspeed_unit": "ms",
    }
    resp = requests.get(url, params=params, timeout=12)
    resp.raise_for_status()
    return resp.json()


def _parse_hourly(weather: dict[str, Any]) -> dict[str, list[float]]:
    """Extract and clean hourly arrays from Open-Meteo response."""
    h = weather.get("hourly", {})

    def clean(key: str) -> list[float]:
        raw = h.get(key, [])
        return [float(v) if v is not None else 0.0 for v in raw]

    return {
        "temperature": clean("temperature_2m"),
        "wind_speed": clean("windspeed_10m"),
        "direct_radiation": clean("direct_radiation"),
        "diffuse_radiation": clean("diffuse_radiation"),
        "cloudcover": clean("cloudcover"),
        "precipitation": clean("precipitation"),
        "timestamps": h.get("time", []),
    }


# ---------------------------------------------------------------------------
# Individual scoring functions
# ---------------------------------------------------------------------------

def score_solar(lat: float, avg_irradiance_wm2: float) -> float:
    """Solar suitability score 0–100.

    Optimal band: 20–35° latitude (Mediterranean / Sun Belt).
    Also rewards higher actual irradiance from weather data.
    """
    abs_lat = abs(lat)
    if abs_lat <= 10:
        lat_factor = 0.78   # equatorial – high humidity/clouds reduce output
    elif abs_lat <= 30:
        lat_factor = 1.00   # optimal solar belt
    elif abs_lat <= 40:
        lat_factor = 0.88
    elif abs_lat <= 50:
        lat_factor = 0.68
    elif abs_lat <= 60:
        lat_factor = 0.45
    elif abs_lat <= 70:
        lat_factor = 0.22
    else:
        lat_factor = 0.08   # arctic

    # Normalise actual irradiance against ~350 W/m² (excellent annual average)
    irr_factor = min(1.0, avg_irradiance_wm2 / 350.0)

    raw = (lat_factor * 0.55 + irr_factor * 0.45) * 100
    return round(max(0.0, min(100.0, raw)), 1)


def score_wind(avg_wind_ms: float) -> float:
    """Wind suitability score 0–100.

    Class 4+ sites (≥7 m/s) are commercially viable.
    Optimal for large turbines: 7–12 m/s.
    """
    w = avg_wind_ms
    if w < 2.0:
        s = 5.0
    elif w < 4.0:
        s = 5 + (w - 2.0) * 12.5      # 5 → 30
    elif w < 6.0:
        s = 30 + (w - 4.0) * 22.5     # 30 → 75
    elif w < 9.0:
        s = 75 + (w - 6.0) * 8.33     # 75 → 100
    elif w < 13.0:
        s = 100.0
    elif w < 18.0:
        s = 100 - (w - 13.0) * 5.0    # 100 → 75 (extreme wind = wear)
    else:
        s = max(40.0, 75 - (w - 18.0) * 6.0)

    return round(max(0.0, min(100.0, s)), 1)


def score_climate(avg_temp_c: float, temp_std_c: float) -> float:
    """Climate/cooling suitability score 0–100.

    Colder ambient air enables free-air cooling and directly lowers PUE —
    consistent with estimate_pue() where <5 °C → PUE 1.10 (best class).

    Breakpoints:
        0–10 °C   : 100   optimal free-air cooling, no freeze risk
       -10– 0 °C  :  95   near-optimal, minimal freeze-protection overhead
       -20–-10 °C :  88   cold, standard freeze protection required
        < -20 °C  :  ↓    operational challenges (heat tracing, arctic logistics)
       10– 20 °C  :  ↓    mechanical cooling increasingly required
       20– 30 °C  :  ↓    significant cooling load
        > 30 °C   :  ↓    severe, approaches 0 at ~40 °C

    Temperature variance (stdev over 7-day hourly series) adds HVAC complexity.
    """
    t = avg_temp_c
    if 0.0 <= t <= 10.0:
        base = 100.0
    elif -10.0 <= t < 0.0:
        base = 95.0
    elif -20.0 <= t < -10.0:
        base = 88.0
    elif t < -20.0:
        base = max(60.0, 88.0 + (t + 20.0) * 1.4)   # at -20: 88, at ~-40: 60
    elif t <= 20.0:
        base = 100.0 - (t - 10.0) * 3.0              # at 10: 100, at 20: 70
    elif t <= 30.0:
        base = 70.0 - (t - 20.0) * 3.5               # at 20: 70, at 30: 35
    else:
        base = max(0.0, 35.0 - (t - 30.0) * 3.5)     # at 30: 35, at ~40: 0

    variance_penalty = min(20.0, temp_std_c * 1.5)
    return round(max(0.0, min(100.0, base - variance_penalty)), 1)




# ---------------------------------------------------------------------------
# Derived / composite metrics
# ---------------------------------------------------------------------------

def estimate_pue(avg_temp_c: float) -> float:
    """Estimate Power Usage Effectiveness.

    Free-cooling thresholds assume state-of-the-art CRAC/CRAH systems.
    """
    if avg_temp_c < 5:
        return 1.10
    elif avg_temp_c < 10:
        return 1.12
    elif avg_temp_c < 15:
        return 1.16
    elif avg_temp_c < 20:
        return 1.22
    elif avg_temp_c < 25:
        return 1.32
    elif avg_temp_c < 30:
        return 1.48
    else:
        return 1.65



# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_location(
    lat: float,
    lng: float,
    servers: int = 50_000,
    ai_intensity: float = 0.70,
) -> dict[str, Any]:
    """Full location suitability analysis for a hyperscaler data centre.

    IT load capacity is derived from server count and AI intensity using the
    GPU power curve (PDF §2.1): E_GPU(u) = 0.8 + 5.2·u^1.2 + 0.6·u [kW/server].

    Args:
        lat: Latitude in decimal degrees.
        lng: Longitude in decimal degrees.
        servers: Number of GPU servers.
        ai_intensity: AI workload utilisation (0–1).

    Returns:
        Nested dict with location metadata, scores, weather stats,
        energy balance, and 7-day hourly time series.
    """
    # 1. Location metadata
    loc_info = get_location_info(lat, lng)

    # 2. Weather data
    raw_weather = fetch_weather_forecast(lat, lng, days=7)
    hourly = _parse_hourly(raw_weather)

    temps = hourly["temperature"]
    winds = hourly["wind_speed"]
    direct = hourly["direct_radiation"]
    diffuse = hourly["diffuse_radiation"]
    total_irr = [d + f for d, f in zip(direct, diffuse)]

    avg_temp = statistics.mean(temps) if temps else 15.0
    avg_wind = statistics.mean(winds) if winds else 5.0
    avg_irr = statistics.mean(total_irr) if total_irr else 100.0
    temp_std = statistics.stdev(temps) if len(temps) > 1 else 5.0

    # 3. Regional plant stats (CPU-only, no network – plants already in memory)
    regional_stats = get_regional_plant_stats(lat, lng)

    # 4. Individual scores (load-independent)
    s_climate = score_climate(avg_temp, temp_std)
    s_grid = score_grid_regional(regional_stats["renewable_mw"], regional_stats["total_mw"])

    # 5. IT load capacity from server count × AI intensity (PDF §2.1 GPU power curve)
    u = ai_intensity
    kw_per_server = 0.8 + 5.2 * u ** 1.2 + 0.6 * u
    dc_capacity_mw = servers * kw_per_server / 1000

    pue = estimate_pue(avg_temp)
    effective_demand_mw = dc_capacity_mw * pue

    # 6. Load-coverage score: actual regional renewable capacity vs. DC IT load.
    #    Uses the same data as the Regional Grid section → score and display are consistent.
    coverage_ratio_pct = (
        min(200.0, regional_stats["renewable_mw"] / dc_capacity_mw * 100)
        if dc_capacity_mw > 0 else 0.0
    )
    s_load_coverage = round(min(100.0, coverage_ratio_pct), 1)

    # 7. Composite score – three dimensions for a grid-connected hyperscaler DC.
    # Grid renewable mix (40%) + actual load coverage (35%) + cooling climate (25%).
    composite = round(
        s_grid            * 0.40
        + s_load_coverage * 0.35
        + s_climate       * 0.25,
        1,
    )

    # 9. Regional grid coverage + fuel mix for frontend chart (all sources)
    chart_fuel_mw: dict[str, float] = {}
    nonren_mw = 0.0
    for fuel, mw in regional_stats["fuel_mw"].items():
        if fuel in _CHART_FUELS:
            chart_fuel_mw[fuel] = round(chart_fuel_mw.get(fuel, 0.0) + mw, 1)
        elif fuel in _RENEWABLE_FUELS:
            chart_fuel_mw["Other Renewable"] = round(chart_fuel_mw.get("Other Renewable", 0.0) + mw, 1)
        else:
            nonren_mw += mw
    if nonren_mw > 0:
        chart_fuel_mw["Non-Renewable"] = round(nonren_mw, 1)
    chart_fuel_mw = dict(sorted(chart_fuel_mw.items(), key=lambda x: -x[1]))

    regional_grid = {
        "radius_km": int(_REGIONAL_RADIUS_KM),
        "total_mw": round(regional_stats["total_mw"], 1),
        "renewable_mw": round(regional_stats["renewable_mw"], 1),
        "renewable_fraction_pct": round(
            regional_stats["renewable_mw"] / regional_stats["total_mw"] * 100
            if regional_stats["total_mw"] > 0 else 0.0, 1
        ),
        "plant_count": regional_stats["plant_count"],
        "fuel_mix_mw": chart_fuel_mw,
        "it_load_mw": round(dc_capacity_mw, 1),
        "coverage_ratio_pct": round(coverage_ratio_pct, 1),
        "coverage_possible": regional_stats["renewable_mw"] >= dc_capacity_mw,
        "top_plants": regional_stats["top_plants"],
    }

    # 8. Recommendation text
    label, recommendation = _recommendation(composite, s_climate, s_grid, s_load_coverage)

    return {
        "location": {
            "lat": lat,
            "lng": lng,
            **loc_info,
        },
        "scores": {
            "climate": s_climate,
            "grid": s_grid,
            "load_coverage": s_load_coverage,
            "composite": composite,
            "label": label,
        },
        "weather": {
            "avg_temperature_c": round(avg_temp, 1),
            "avg_wind_speed_ms": round(avg_wind, 1),
            "avg_irradiance_wm2": round(avg_irr, 1),
            "temp_stdev_c": round(temp_std, 1),
        },
        "energy": {
            "dc_it_capacity_mw": round(dc_capacity_mw, 1),
            "estimated_pue": round(pue, 2),
            "effective_demand_mw": round(effective_demand_mw, 1),
        },
        "regional_grid": regional_grid,
        "recommendation": recommendation,
    }


def _recommendation(
    composite: float,
    climate: float,
    grid: float,
    load_coverage: float,
) -> tuple[str, str]:
    """Generate a label and short recommendation string."""
    if composite >= 80:
        label = "Excellent"
        msg = (
            "This site is highly suitable for a renewable-powered hyperscaler data centre. "
            "The regional grid is predominantly renewable and capacity is sufficient to cover "
            "the projected IT load with minimal fossil fallback."
        )
    elif composite >= 65:
        label = "Good"
        weak = []
        if climate < 60:
            weak.append("cooling conditions")
        if grid < 60:
            weak.append("renewable grid mix")
        if load_coverage < 60:
            weak.append("renewable load coverage")
        weak_str = " and ".join(weak) if weak else "some dimensions"
        msg = (
            f"Good candidate site. Limitations in {weak_str} may require long-term PPAs "
            "or additional storage to reach full renewable coverage."
        )
    elif composite >= 50:
        label = "Fair"
        msg = (
            "Moderate suitability. The regional grid lacks sufficient renewable capacity "
            "to cover the IT load. Long-term PPAs and storage investment would be required."
        )
    elif composite >= 35:
        label = "Poor"
        msg = (
            "Below-average renewable grid infrastructure or poor cooling conditions make "
            "this site challenging for carbon-neutral hyperscale operations."
        )
    else:
        label = "Unsuitable"
        msg = (
            "This site faces severe constraints: insufficient renewable grid capacity, "
            "extreme climate, or a combination of both. Alternative locations should be prioritised."
        )
    return label, msg
