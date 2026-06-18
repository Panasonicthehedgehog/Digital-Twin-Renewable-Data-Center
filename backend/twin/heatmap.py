"""Heatmap grid — renewable potential overlay for the location map.

Fetches 7-day weather forecasts from Open-Meteo for a sparse set of points
within the viewport bounding box, then bilinearly interpolates to a finer
grid for a smooth coloured overlay on the Leaflet map.
"""

from __future__ import annotations

import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from backend.twin.location_scorer import (
    fetch_weather_forecast,
    _parse_hourly,
    score_solar,
    score_wind,
)

# ---------------------------------------------------------------------------
# In-memory cache for per-coordinate weather summaries (15 min TTL)
# ---------------------------------------------------------------------------

_WEATHER_CACHE: dict[str, tuple[float, dict[str, float]]] = {}
_CACHE_TTL = 15 * 60


def _cache_key(lat: float, lng: float) -> str:
    rlat = round(lat * 4) / 4
    rlng = round(lng * 4) / 4
    return f"{rlat:.2f},{rlng:.2f}"


def _get_cached(lat: float, lng: float) -> dict[str, float] | None:
    entry = _WEATHER_CACHE.get(_cache_key(lat, lng))
    if entry and time.time() - entry[0] < _CACHE_TTL:
        return entry[1]
    return None


def _set_cached(lat: float, lng: float, data: dict[str, float]) -> None:
    _WEATHER_CACHE[_cache_key(lat, lng)] = (time.time(), data)


def _fetch_point(lat: float, lng: float) -> dict[str, float] | None:
    cached = _get_cached(lat, lng)
    if cached:
        return cached
    try:
        raw = fetch_weather_forecast(lat, lng, days=7)
        hourly = _parse_hourly(raw)
        temps = hourly["temperature"]
        winds = hourly["wind_speed"]
        total_irr = [d + f for d, f in zip(hourly["direct_radiation"], hourly["diffuse_radiation"])]
        result = {
            "avg_temp": statistics.mean(temps) if temps else 15.0,
            "avg_wind": statistics.mean(winds) if winds else 5.0,
            "avg_irr": statistics.mean(total_irr) if total_irr else 100.0,
        }
        _set_cached(lat, lng, result)
        return result
    except Exception:
        return None


# ---------------------------------------------------------------------------
# IDW interpolation helpers
# ---------------------------------------------------------------------------

def _idw(ri: int, cj: int, key: str, sparse: dict[tuple[int, int], dict[str, float]]) -> float:
    q = [(math.sqrt((ri - qri) ** 2 + (cj - qcj) ** 2), data[key])
         for (qri, qcj), data in sparse.items() if data is not None]
    if not q:
        return 0.0
    q.sort(key=lambda x: x[0])
    nearest = q[:4]
    tw = 0.0
    ws = 0.0
    for d, v in nearest:
        if d < 0.001:
            return v
        w = 1.0 / d
        ws += w * v
        tw += w
    return ws / tw if tw > 0 else 0.0


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def compute_grid(
    north: float,
    south: float,
    east: float,
    west: float,
    resolution: float | None = None,
    max_workers: int = 10,
) -> dict[str, Any]:
    # Auto-resolution — target ~40 cells per dimension
    if resolution is None:
        span = max(east - west, north - south)
        resolution = max(0.02, span / 40)
    resolution = max(0.01, min(2.0, resolution))

    # Build fine grid
    lats = [north - i * resolution for i in range(int((north - south) / resolution) + 1)]
    lngs = [west + j * resolution for j in range(int((east - west) / resolution) + 1)]
    rows, cols = len(lats), len(lngs)

    # Hard cap on grid size
    if rows > 80 or cols > 80:
        scale = max(rows / 80, cols / 80)
        resolution = max(0.01, resolution * scale)
        lats = [north - i * resolution for i in range(int((north - south) / resolution) + 1)]
        lngs = [west + j * resolution for j in range(int((east - west) / resolution) + 1)]
        rows, cols = len(lats), len(lngs)

    # Sparse query grid (~6–8 pts per dimension)
    qstep = max(1, min(rows, cols) // 7)
    qindices: list[tuple[int, int]] = []
    qcoords: list[tuple[float, float]] = []
    for ri in range(0, rows, qstep):
        for cj in range(0, cols, qstep):
            qindices.append((ri, cj))
            qcoords.append((lats[ri], lngs[cj]))

    # Parallel weather fetch
    sparse: dict[tuple[int, int], dict[str, float] | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut = {pool.submit(_fetch_point, lat, lng): (ri, cj)
               for (lat, lng), (ri, cj) in zip(qcoords, qindices)}
        for f in as_completed(fut):
            sparse[fut[f]] = f.result()

    # Build full grids
    solar: list[list[float]] = []
    wind: list[list[float]] = []
    potential: list[list[float]] = []

    for ri in range(rows):
        solar_row: list[float] = []
        wind_row: list[float] = []
        pot_row: list[float] = []
        for cj in range(cols):
            pt = sparse.get((ri, cj))
            if pt is not None:
                irr, wnd = pt["avg_irr"], pt["avg_wind"]
            else:
                irr = _idw(ri, cj, "avg_irr", sparse)
                wnd = _idw(ri, cj, "avg_wind", sparse)
            ss = score_solar(lats[ri], irr)
            sw = score_wind(wnd)
            solar_row.append(ss)
            wind_row.append(sw)
            pot_row.append(round(ss * 0.6 + sw * 0.4, 1))
        solar.append(solar_row)
        wind.append(wind_row)
        potential.append(pot_row)

    return {
        "bounds": {
            "north": round(lats[0], 4),
            "south": round(lats[-1], 4),
            "east": round(lngs[-1], 4),
            "west": round(lngs[0], 4),
        },
        "resolution": round(resolution, 4),
        "rows": rows,
        "cols": cols,
        "solar": solar,
        "wind": wind,
        "potential": potential,
        "vmin": 0,
        "vmax": 100,
    }
