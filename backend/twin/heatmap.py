"""Heatmap grid — renewable potential overlay for the location map.

Fetches 7-day weather forecasts from Open-Meteo for a fixed lattice of points
within the viewport bounding box, then interpolates to a finer grid for a
smooth coloured overlay on the Leaflet map.

Weather for all lattice points is fetched in a single Open-Meteo request
(comma-separated coordinates), which keeps latency and rate-limit usage low.
"""

from __future__ import annotations

import math
import statistics
import threading
import time
from typing import Any

import requests

from backend.twin.location_scorer import (
    _OPEN_METEO_URL,
    _open_meteo_params,
    _parse_hourly,
    score_solar,
    score_wind,
)

# ---------------------------------------------------------------------------
# In-memory cache for per-coordinate weather summaries (15 min TTL)
# ---------------------------------------------------------------------------

_WEATHER_CACHE: dict[str, tuple[float, dict[str, float]]] = {}
_CACHE_TTL = 15 * 60
_CACHE_MAX = 1024
_CACHE_LOCK = threading.Lock()


def _cache_key(lat: float, lng: float) -> str:
    rlat = round(lat * 4) / 4
    rlng = round(lng * 4) / 4
    return f"{rlat:.2f},{rlng:.2f}"


def _get_cached(lat: float, lng: float) -> dict[str, float] | None:
    key = _cache_key(lat, lng)
    with _CACHE_LOCK:
        entry = _WEATHER_CACHE.get(key)
        if entry and time.time() - entry[0] < _CACHE_TTL:
            return entry[1]
        if entry:
            _WEATHER_CACHE.pop(key, None)
    return None


def _set_cached(lat: float, lng: float, data: dict[str, float]) -> None:
    key = _cache_key(lat, lng)
    with _CACHE_LOCK:
        if len(_WEATHER_CACHE) >= _CACHE_MAX:
            oldest = min(_WEATHER_CACHE, key=lambda k: _WEATHER_CACHE[k][0])
            _WEATHER_CACHE.pop(oldest, None)
        _WEATHER_CACHE[key] = (time.time(), data)


# ---------------------------------------------------------------------------
# Weather fetching
# ---------------------------------------------------------------------------

def _summarize(raw: dict[str, Any]) -> dict[str, float]:
    """Reduce a raw Open-Meteo response to the three heatmap inputs."""
    hourly = _parse_hourly(raw)
    temps = hourly["temperature"]
    winds = hourly["wind_speed"]
    total_irr = [d + f for d, f in zip(hourly["direct_radiation"], hourly["diffuse_radiation"])]
    return {
        "avg_temp": statistics.mean(temps) if temps else 15.0,
        "avg_wind": statistics.mean(winds) if winds else 5.0,
        "avg_irr": statistics.mean(total_irr) if total_irr else 100.0,
    }


def _fetch_batch(coords: list[tuple[float, float]]) -> list[dict[str, float] | None]:
    """Fetch forecasts for multiple coordinates in one Open-Meteo request.

    Open-Meteo accepts comma-separated latitude/longitude lists and returns
    one response object per coordinate, in request order.
    """
    if not coords:
        return []

    params = _open_meteo_params(
        ",".join(f"{lat:.4f}" for lat, _ in coords),
        ",".join(f"{lng:.4f}" for _, lng in coords),
        days=7,
    )
    resp = requests.get(_OPEN_METEO_URL, params=params, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    items = payload if isinstance(payload, list) else [payload]

    results: list[dict[str, float] | None] = []
    for item in items:
        try:
            results.append(_summarize(item))
        except Exception:
            results.append(None)

    if len(results) < len(coords):
        results.extend([None] * (len(coords) - len(results)))
    return results[:len(coords)]


def _fetch_points(coords: list[tuple[float, float]]) -> dict[tuple[float, float], dict[str, float]]:
    """Return weather summaries for ``coords``, using cache + one batch request."""
    results: dict[tuple[float, float], dict[str, float]] = {}
    misses: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()

    for coord in coords:
        if coord in seen:
            continue
        seen.add(coord)
        cached = _get_cached(*coord)
        if cached is not None:
            results[coord] = cached
        else:
            misses.append(coord)

    if misses:
        fetched: list[dict[str, float] | None] | None = None
        for attempt in range(2):
            try:
                fetched = _fetch_batch(misses)
                break
            except Exception:
                if attempt == 0:
                    time.sleep(0.5)

        if fetched is None:
            fetched = [None] * len(misses)

        for coord, summary in zip(misses, fetched):
            if summary is not None:
                _set_cached(*coord, summary)
                results[coord] = summary

    return results


# ---------------------------------------------------------------------------
# Query lattice + interpolation
# ---------------------------------------------------------------------------

def _query_indices(n: int, target: int = 8) -> list[int]:
    """Return up to ``target`` evenly spaced indices, always including both ends."""
    if n <= target:
        return list(range(n))
    return sorted({round(i * (n - 1) / (target - 1)) for i in range(target)})


def _build_weights(
    rows: int,
    cols: int,
    sparse: dict[tuple[int, int], dict[str, float] | None],
) -> tuple[list[tuple[int, int, dict[str, float]]], list[list[list[tuple[float, int]]]]] | None:
    """Precompute inverse-distance weights for the nearest 4 valid query points.

    Weights are independent of the weather key, so they are built once per
    grid cell and reused for both irradiance and wind.
    """
    points = [(ri, cj, data) for (ri, cj), data in sparse.items() if data is not None]
    if not points:
        return None

    weights: list[list[list[tuple[float, int]]]] = []
    for ri in range(rows):
        row: list[list[tuple[float, int]]] = []
        for cj in range(cols):
            nearest = sorted(
                (math.hypot(ri - qri, cj - qcj), idx)
                for idx, (qri, qcj, _) in enumerate(points)
            )[:4]
            if nearest[0][0] < 0.001:
                row.append([(1.0, nearest[0][1])])
            else:
                inv = [(1.0 / dist, idx) for dist, idx in nearest]
                total = sum(weight for weight, _ in inv)
                row.append([(weight / total, idx) for weight, idx in inv])
        weights.append(row)

    return points, weights


# ---------------------------------------------------------------------------
# Grid result cache (10 min TTL)
# ---------------------------------------------------------------------------

_GRID_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_GRID_CACHE_TTL = 10 * 60
_GRID_CACHE_MAX = 32
_GRID_CACHE_LOCK = threading.Lock()


def _grid_cache_get(key: tuple[Any, ...]) -> dict[str, Any] | None:
    with _GRID_CACHE_LOCK:
        entry = _GRID_CACHE.get(key)
        if entry and time.time() - entry[0] < _GRID_CACHE_TTL:
            return entry[1]
        if entry:
            _GRID_CACHE.pop(key, None)
    return None


def _grid_cache_set(key: tuple[Any, ...], value: dict[str, Any]) -> None:
    with _GRID_CACHE_LOCK:
        if len(_GRID_CACHE) >= _GRID_CACHE_MAX:
            oldest = min(_GRID_CACHE, key=lambda k: _GRID_CACHE[k][0])
            _GRID_CACHE.pop(oldest, None)
        _GRID_CACHE[key] = (time.time(), value)


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def compute_grid(
    north: float,
    south: float,
    east: float,
    west: float,
    resolution: float | None = None,
    include_components: bool = False,
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

    # Cache key uses the final (capped) resolution, so equivalent grids share
    # one entry instead of being fetched and stored under different keys.
    cache_key = (
        round(north, 3), round(south, 3), round(east, 3), round(west, 3),
        round(resolution, 4), bool(include_components),
    )
    cached = _grid_cache_get(cache_key)
    if cached is not None:
        return cached

    # Fixed lattice (~8 × 8 points) independent of viewport aspect ratio.
    qindices = [
        (ri, cj)
        for ri in _query_indices(rows)
        for cj in _query_indices(cols)
    ]
    qcoords = [(lats[ri], lngs[cj]) for ri, cj in qindices]

    fetched = _fetch_points(qcoords)
    sparse: dict[tuple[int, int], dict[str, float] | None] = {
        (ri, cj): fetched.get((lats[ri], lngs[cj])) for ri, cj in qindices
    }

    prepared = _build_weights(rows, cols, sparse)
    if prepared is None:
        # Do not cache or render a fabricated latitude-only gradient when
        # every weather lookup failed.
        raise RuntimeError("No weather data available for this viewport")
    points, weights = prepared

    solar: list[list[float]] | None = [] if include_components else None
    wind: list[list[float]] | None = [] if include_components else None
    potential: list[list[float]] = []

    for ri in range(rows):
        pot_row: list[float] = []
        solar_row: list[float] = []
        wind_row: list[float] = []
        for cj in range(cols):
            pt = sparse.get((ri, cj))
            if pt is not None:
                irr, wnd = pt["avg_irr"], pt["avg_wind"]
            else:
                cell = weights[ri][cj]
                irr = sum(w * points[idx][2]["avg_irr"] for w, idx in cell)
                wnd = sum(w * points[idx][2]["avg_wind"] for w, idx in cell)

            ss = score_solar(lats[ri], irr)
            sw = score_wind(wnd)
            if include_components:
                solar_row.append(ss)
                wind_row.append(sw)
            pot_row.append(round(ss * 0.6 + sw * 0.4, 1))

        potential.append(pot_row)
        if include_components:
            solar.append(solar_row)  # type: ignore[union-attr]
            wind.append(wind_row)    # type: ignore[union-attr]

    result: dict[str, Any] = {
        "bounds": {
            "north": round(lats[0], 4),
            "south": round(lats[-1], 4),
            "east": round(lngs[-1], 4),
            "west": round(lngs[0], 4),
        },
        "resolution": round(resolution, 4),
        "rows": rows,
        "cols": cols,
        "potential": potential,
        "vmin": 0,
        "vmax": 100,
    }
    if include_components:
        result["solar"] = solar
        result["wind"] = wind

    _grid_cache_set(cache_key, result)
    return result
