"""Location scorer for hyperscaler data center site selection.

Fetches real weather data from Open-Meteo and computes a multi-dimensional
suitability score covering solar potential, wind potential, climate (cooling
efficiency), and grid infrastructure reliability.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Country-level grid reliability / renewable infrastructure scores (0–100)
# Keyed by ISO 3166-1 alpha-2 country code (returned by Nominatim as country_code)
# Based on IEA and Enerdata country profiles
# ---------------------------------------------------------------------------
COUNTRY_GRID_SCORES: dict[str, float] = {
    # Northern Europe – excellent grids + high renewable share
    "IS": 99,  # Iceland
    "NO": 97,  # Norway
    "SE": 96,  # Sweden
    "DK": 95,  # Denmark
    "FI": 94,  # Finland
    "CH": 93,  # Switzerland
    "LU": 92,  # Luxembourg
    "NL": 91,  # Netherlands
    "DE": 90,  # Germany
    "AT": 90,  # Austria
    "BE": 89,  # Belgium
    "IE": 88,  # Ireland
    "GB": 87,  # United Kingdom
    # Western/Central Europe
    "FR": 88,  # France
    "PT": 85,  # Portugal
    "ES": 84,  # Spain
    "IT": 81,  # Italy
    "PL": 75,  # Poland
    "CZ": 79,  # Czech Republic
    "SK": 76,  # Slovakia
    "HU": 74,  # Hungary
    "RO": 68,  # Romania
    "BG": 65,  # Bulgaria
    "GR": 72,  # Greece
    "HR": 70,  # Croatia
    # North America
    "CA": 89,  # Canada
    "US": 84,  # United States
    # Asia-Pacific
    "JP": 91,  # Japan
    "SG": 95,  # Singapore
    "KR": 88,  # South Korea
    "AU": 82,  # Australia
    "NZ": 91,  # New Zealand
    # Emerging markets
    "CN": 78,  # China
    "IN": 67,  # India
    "BR": 72,  # Brazil
    "ZA": 55,  # South Africa
    "MX": 65,  # Mexico
    "AE": 75,  # UAE
    "SA": 68,  # Saudi Arabia
    "CL": 70,  # Chile
}
_GRID_DEFAULT = 62.0


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

    Low ambient temperatures enable free-air cooling and reduce PUE.
    Optimal: 8–14 °C annual average (e.g. Nordic / North Sea coast).
    High temperature variance incurs HVAC overhead.
    """
    t = avg_temp_c
    if 8.0 <= t <= 14.0:
        base = 100.0
    elif 4.0 <= t < 8.0:
        base = 80 + (t - 4.0) * 5.0
    elif 14.0 < t <= 22.0:
        base = 100 - (t - 14.0) * 5.0
    elif 0.0 <= t < 4.0:
        base = 65 + t * 3.75
    elif t < 0.0:
        base = max(30.0, 65 + t * 3.0)   # very cold → permafrost / heating costs
    else:  # > 22 °C
        base = max(0.0, 60 - (t - 22.0) * 4.0)

    variance_penalty = min(25.0, temp_std_c * 1.8)
    return round(max(0.0, min(100.0, base - variance_penalty)), 1)


def score_grid(country_code: str) -> float:
    """Grid reliability score based on ISO 3166-1 alpha-2 country code."""
    return COUNTRY_GRID_SCORES.get(country_code.upper(), _GRID_DEFAULT)


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


def _renewable_hourly(
    hour_of_day: int,
    solar_irr_wm2: float,
    wind_ms: float,
    dc_it_mw: float,
    solar_installed_mw: float,
    wind_installed_mw: float,
) -> dict[str, float]:
    """Compute renewable generation for a single hour."""
    # IT load: slight diurnal variation (more compute during business hours)
    load_factor = 0.82 + 0.18 * math.sin(math.pi * max(0, hour_of_day - 6) / 12) \
        if 6 <= hour_of_day <= 18 else 0.82
    it_load = dc_it_mw * load_factor

    # Solar: linear to irradiance, bounded by installed capacity, ηpv ≈ 18 %
    # irr in W/m² → panel efficiency 18% → normalise to installed MW
    solar_cf = solar_irr_wm2 / 1000.0 * 0.18 / 0.18  # simplified capacity factor
    solar_gen = min(solar_installed_mw, solar_cf * solar_installed_mw)

    # Wind: cubic power law, cut-in 2.5 m/s, rated at 12 m/s, cut-out 25 m/s
    if wind_ms < 2.5 or wind_ms > 25:
        wind_cf = 0.0
    elif wind_ms < 12.0:
        wind_cf = min(1.0, (wind_ms / 12.0) ** 3)
    else:
        wind_cf = 1.0
    wind_gen = wind_cf * wind_installed_mw

    renewable_gen = solar_gen + wind_gen
    grid_import = max(0.0, it_load - renewable_gen)
    surplus = max(0.0, renewable_gen - it_load)
    ren_pct = min(100.0, renewable_gen / it_load * 100) if it_load > 0 else 0.0

    return {
        "it_load_mw": round(it_load, 3),
        "solar_mw": round(solar_gen, 3),
        "wind_mw": round(wind_gen, 3),
        "grid_mw": round(grid_import, 3),
        "surplus_mw": round(surplus, 3),
        "renewable_pct": round(ren_pct, 1),
    }


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_location(
    lat: float,
    lng: float,
    dc_capacity_mw: float = 100.0,
    servers: int = 50_000,
    ai_intensity: float = 0.70,
) -> dict[str, Any]:
    """Full location suitability analysis for a hyperscaler data centre.

    Args:
        lat: Latitude in decimal degrees.
        lng: Longitude in decimal degrees.
        dc_capacity_mw: Desired IT load capacity in MW.
        servers: Number of servers (affects demand model).
        ai_intensity: Fraction of AI workloads (0–1), increases load.

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
    peak_irr = max(total_irr) if total_irr else 500.0

    # 3. Individual scores
    s_solar = score_solar(lat, avg_irr)
    s_wind = score_wind(avg_wind)
    s_climate = score_climate(avg_temp, temp_std)
    s_grid = score_grid(loc_info["country_code"])

    composite = round(s_solar * 0.28 + s_wind * 0.28 + s_climate * 0.24 + s_grid * 0.20, 1)

    # 4. Sizing the renewable plant to cover ~80 % of demand on average
    pue = estimate_pue(avg_temp)
    effective_demand_mw = dc_capacity_mw * pue

    # Scale installed capacity proportional to score (better site → fewer panels/turbines needed)
    solar_installed = effective_demand_mw * 0.70 * (s_solar / 100)
    wind_installed = effective_demand_mw * 0.70 * (s_wind / 100)

    # 5. Hourly time series (7 days × 24 h = 168 points)
    time_series: list[dict[str, Any]] = []
    for i in range(min(168, len(temps))):
        hour_of_day = i % 24
        hourly_result = _renewable_hourly(
            hour_of_day,
            total_irr[i] if i < len(total_irr) else avg_irr,
            winds[i] if i < len(winds) else avg_wind,
            effective_demand_mw,
            solar_installed,
            wind_installed,
        )
        time_series.append({
            "hour": i,
            "timestamp": hourly["timestamps"][i] if i < len(hourly["timestamps"]) else "",
            "temperature_c": round(temps[i] if i < len(temps) else avg_temp, 1),
            "wind_speed_ms": round(winds[i] if i < len(winds) else avg_wind, 1),
            "irradiance_wm2": round(total_irr[i] if i < len(total_irr) else avg_irr, 1),
            **hourly_result,
        })

    avg_ren_pct = statistics.mean(ts["renewable_pct"] for ts in time_series) if time_series else 0.0

    # 6. Energy mix summary
    total_solar = sum(ts["solar_mw"] for ts in time_series)
    total_wind = sum(ts["wind_mw"] for ts in time_series)
    total_grid = sum(ts["grid_mw"] for ts in time_series)
    total_gen = total_solar + total_wind + total_grid
    mix = {
        "solar_pct": round(total_solar / total_gen * 100, 1) if total_gen > 0 else 0,
        "wind_pct": round(total_wind / total_gen * 100, 1) if total_gen > 0 else 0,
        "grid_pct": round(total_grid / total_gen * 100, 1) if total_gen > 0 else 0,
    }

    # 7. Recommendation text
    label, recommendation = _recommendation(composite, s_solar, s_wind, s_climate, s_grid)

    return {
        "location": {
            "lat": lat,
            "lng": lng,
            **loc_info,
        },
        "scores": {
            "solar": s_solar,
            "wind": s_wind,
            "climate": s_climate,
            "grid": s_grid,
            "composite": composite,
            "label": label,
        },
        "weather": {
            "avg_temperature_c": round(avg_temp, 1),
            "avg_wind_speed_ms": round(avg_wind, 1),
            "avg_irradiance_wm2": round(avg_irr, 1),
            "peak_irradiance_wm2": round(peak_irr, 1),
            "temp_stdev_c": round(temp_std, 1),
        },
        "energy": {
            "dc_it_capacity_mw": dc_capacity_mw,
            "estimated_pue": round(pue, 2),
            "effective_demand_mw": round(effective_demand_mw, 1),
            "solar_installed_mw": round(solar_installed, 1),
            "wind_installed_mw": round(wind_installed, 1),
            "avg_renewable_pct": round(avg_ren_pct, 1),
            "energy_mix": mix,
        },
        "recommendation": recommendation,
        "time_series": time_series,
    }


def _recommendation(
    composite: float,
    solar: float,
    wind: float,
    climate: float,
    grid: float,
) -> tuple[str, str]:
    """Generate a label and short recommendation string."""
    if composite >= 80:
        label = "Excellent"
        msg = (
            "This site is highly suitable for a renewable-powered hyperscaler data centre. "
            "Strong renewable potential combined with reliable grid infrastructure minimises "
            "dependency on fossil fallback capacity."
        )
    elif composite >= 65:
        label = "Good"
        weak = []
        if solar < 60:
            weak.append("solar irradiance")
        if wind < 60:
            weak.append("wind resources")
        if climate < 60:
            weak.append("cooling climate")
        if grid < 70:
            weak.append("grid reliability")
        weak_str = " and ".join(weak) if weak else "some dimensions"
        msg = (
            f"This is a good candidate site. Limited {weak_str} may require additional "
            "battery or hydrogen buffer storage to reach full renewable coverage."
        )
    elif composite >= 50:
        label = "Fair"
        msg = (
            "Moderate suitability. A mix of on-site renewables and long-term PPAs would be "
            "necessary. Consider hydrogen storage to bridge renewable intermittency gaps."
        )
    elif composite >= 35:
        label = "Poor"
        msg = (
            "Below-average renewable potential or infrastructure limitations make this site "
            "challenging for carbon-neutral operations at hyperscale."
        )
    else:
        label = "Unsuitable"
        msg = (
            "This site faces severe constraints (e.g. extreme climate, poor grid, low renewable "
            "potential). Alternative locations should be prioritised."
        )
    return label, msg
