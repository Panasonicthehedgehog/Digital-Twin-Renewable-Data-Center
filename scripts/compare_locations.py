#!/usr/bin/env python3
"""Compare two data center locations: normal vs. Dunkelflaute.

Usage:
    .venv/bin/python scripts/compare_locations.py

Requires the backend to be running on http://localhost:8000.
"""

from __future__ import annotations

import sys
from typing import Any

import requests

API_BASE = "http://localhost:8000"

LOCATIONS = [
    {"name": "Stockholm, SE", "lat": 59.3293, "lng": 18.0686},
    {"name": "Frankfurt, DE", "lat": 50.1109, "lng": 8.6821},
]

SCENARIOS = ["normal", "dunkelflaute"]

SERVERS = 50_000
AI_INTENSITY = 0.72


def run_simulation(lat: float, lng: float, scenario: str) -> dict[str, Any]:
    resp = requests.post(
        f"{API_BASE}/api/simulate/location",
        json={
            "lat": lat,
            "lng": lng,
            "scenario": scenario,
            "servers": SERVERS,
            "ai_intensity": AI_INTENSITY,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def print_horizontal_line(width: int) -> None:
    print("─" * width)


def main() -> None:
    # Health check
    try:
        requests.get(f"{API_BASE}/health", timeout=3)
    except requests.ConnectionError:
        print("Backend nicht erreichbar. Starte mit: .venv/bin/uvicorn backend.app:app")
        sys.exit(1)

    results: list[dict[str, Any]] = []
    for loc in LOCATIONS:
        for scenario in SCENARIOS:
            print(f"Simuliere {loc['name']} ({scenario}) ...", end=" ", flush=True)
            data = run_simulation(loc["lat"], loc["lng"], scenario)
            results.append((loc["name"], scenario, data))
            print("OK")

    print()

    # Summary table
    header = f"{'Standort':<20} {'Szenario':<16} {'REF %':>8} {'CUE g/kWh':>12} {'CO₂ kg':>10} {'Grid g/kWh':>12} {'Ausfälle':>9}"
    print_horizontal_line(len(header))
    print(header)
    print_horizontal_line(len(header))

    for name, scenario, data in results:
        t = data["totals"]
        g = data["grid"]
        ref = t["ref_pct"]
        cue = t["cue_g_per_kwh"]
        co2_kg = round(t["co2_g"] / 1000, 1)
        ci = g["carbon_intensity_g_per_kwh"]
        failed = t["failed_steps"]
        print(f"{name:<20} {scenario:<16} {ref:>7.1f}% {cue:>10.1f}  {co2_kg:>8.1f}  {ci:>10.1f}  {failed:>8}")
    print_horizontal_line(len(header))

    print()

    # Daily breakdown for each scenario (Markdown table for presentation)
    for name, scenario, data in results:
        print(f"\n## {name} – {scenario}\n")
        daily_h = f"{'Tag':<6} {'REF %':>8} {'CUE g/kWh':>12} {'IT MWh':>10} {'Grid MWh':>10} {'Ren. MWh':>10}"
        print(daily_h)
        print("─" * len(daily_h))
        for day in data["daily"]:
            print(f"{day['day']:<6} {day['ref_pct']:>7.1f}% {day['cue_g_per_kwh']:>10.1f}  {day['it_kwh']/1000:>8.1f}  {day['grid_kwh']/1000:>8.1f}  {day['renewable_kwh']/1000:>8.1f}")


if __name__ == "__main__":
    main()
