from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import requests

from backend.twin.config import TwinConfig, load_config, write_config
from backend.twin.core import SCENARIOS, DigitalTwinEngine
from backend.paths import resource_path
from backend.static_serving import mount_frontend

CONFIG_PATH = resource_path("config/default_config.yaml")


class ScenarioRequest(BaseModel):
    name: str


class StepRequest(BaseModel):
    steps: int = 1


class LocationRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude in decimal degrees")
    lng: float = Field(..., ge=-180, le=180, description="Longitude in decimal degrees")
    servers: int = Field(50_000, gt=0, description="Number of servers")
    ai_intensity: float = Field(0.70, ge=0, le=1, description="AI workload fraction")


class HeatmapGridRequest(BaseModel):
    north: float = Field(..., ge=-90, le=90)
    south: float = Field(..., ge=-90, le=90)
    east: float = Field(..., ge=-180, le=180)
    west: float = Field(..., ge=-180, le=180)
    resolution: float | None = None


class SimulateLocationRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    scenario: str = "normal"
    servers: int = Field(50_000, gt=0)
    ai_intensity: float = Field(0.72, ge=0, le=1)


class TwinRuntime:
    def __init__(self, config: TwinConfig) -> None:
        self.config = config
        self.engine = DigitalTwinEngine(config)
        self.state: dict[str, Any] = self.engine.simulate_step()
        self.clients: set[WebSocket] = set()
        self._loop_task: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._ticker())

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            self.state = self.engine.simulate_step()
            await self.broadcast(self.state)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for client in self.clients:
            try:
                await client.send_json(payload)
            except Exception:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)


runtime = TwinRuntime(load_config(CONFIG_PATH))
app = FastAPI(title="Hyperscale AI Data Center Digital Twin")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    await runtime.start()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    return runtime.state


@app.get("/api/scenarios")
def list_scenarios() -> dict[str, list[str]]:
    return {"scenarios": list(SCENARIOS.keys())}


@app.post("/api/scenario")
def set_scenario(payload: ScenarioRequest) -> dict[str, Any]:
    runtime.engine.set_scenario(payload.name)
    runtime.state = runtime.engine.simulate_step()
    return {"status": "ok", "scenario": payload.name, "state": runtime.state}


@app.post("/api/simulate")
def simulate(payload: StepRequest) -> dict[str, Any]:
    for _ in range(max(1, payload.steps)):
        runtime.state = runtime.engine.simulate_step()
    return {"status": "ok", "state": runtime.state}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return runtime.config.model_dump()


@app.put("/api/config")
def update_config(payload: dict[str, Any]) -> dict[str, Any]:
    runtime.config = TwinConfig.model_validate(payload)
    write_config(CONFIG_PATH, runtime.config)
    runtime.engine.update_config(runtime.config)
    runtime.state = runtime.engine.simulate_step()
    return {"status": "ok", "config": runtime.config.model_dump(), "state": runtime.state}


@app.post("/api/location/analyze")
async def analyze_location(payload: LocationRequest) -> dict[str, Any]:
    """Analyse a geographic location for hyperscaler data centre suitability.

    Fetches real weather data from Open-Meteo, performs reverse geocoding via
    Nominatim, and returns multi-dimensional scores plus a 7-day energy simulation.
    """
    from backend.twin.location_scorer import analyze_location as _analyze

    try:
        result = _analyze(
            lat=payload.lat,
            lng=payload.lng,
            servers=payload.servers,
            ai_intensity=payload.ai_intensity,
        )
        return result
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="External weather API timeout. Please retry.")
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"External API error: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/simulate/location")
async def simulate_location(payload: SimulateLocationRequest) -> dict[str, Any]:
    """Simulate data center operation at a specific geographic location.

    Fetches real 7-day weather from Open-Meteo and the regional grid mix from
    the WRI power plant database, then runs the digital twin engine with
    location-specific data. Returns accumulated REF, CUE, and daily breakdown.
    """
    from backend.twin.location_scorer import (
        fetch_weather_hourly,
        compute_grid_carbon_intensity,
        get_regional_plant_stats,
        get_location_info,
    )

    if payload.scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail=f"Unknown scenario: {payload.scenario}")

    try:
        loc_info = get_location_info(payload.lat, payload.lng)
        hourly_weather = fetch_weather_hourly(payload.lat, payload.lng)
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="External weather API timeout. Please retry.")
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"External API error: {exc}")

    regional = get_regional_plant_stats(payload.lat, payload.lng)
    carbon_intensity = compute_grid_carbon_intensity(regional["fuel_mw"])

    # Resample hourly → 15-min steps (repeat each hour 4×)
    weather_15min: list[tuple[float, float, float]] = []
    for entry in hourly_weather:
        for _ in range(4):
            weather_15min.append(entry)

    # Build engine with location-specific config
    import math

    config = load_config(CONFIG_PATH)
    config.energy.carbon_intensity_g_per_kwh = carbon_intensity
    config.load.ai_intensity = payload.ai_intensity

    topo = config.topology
    racks_total = topo.blocks * topo.halls_per_block * topo.racks_per_hall
    topo.servers_per_rack = max(1, math.ceil(payload.servers / racks_total))
    actual_servers = racks_total * topo.servers_per_rack

    DEFAULT_SERVERS = 1024
    scale = actual_servers / DEFAULT_SERVERS
    energy = config.energy
    energy.grid_capacity_kw = round(energy.grid_capacity_kw * scale)
    energy.solar_capacity_kw = round(energy.solar_capacity_kw * scale)
    energy.wind_capacity_kw = round(energy.wind_capacity_kw * scale)
    energy.battery_capacity_kwh = round(energy.battery_capacity_kwh * scale)
    energy.battery_max_power_kw = round(energy.battery_max_power_kw * scale)
    energy.hydrogen_capacity_kwh = round(energy.hydrogen_capacity_kwh * scale)
    energy.hydrogen_max_discharge_kw = round(energy.hydrogen_max_discharge_kw * scale)

    engine = DigitalTwinEngine(config)
    engine.set_scenario(payload.scenario)
    engine.set_carbon_intensity(carbon_intensity)
    engine.set_weather(weather_15min)

    # Run simulation for 7 days (672 steps)
    total_steps = 7 * 24 * 4
    states: list[dict[str, Any]] = []
    for _ in range(total_steps):
        states.append(engine.simulate_step())

    # Aggregate totals from final state
    final = states[-1]
    cum = final["cumulative"]
    metrics = final["metrics"]

    # Daily breakdown
    steps_per_day = 24 * 4
    daily = []
    for d in range(7):
        day_states = states[d * steps_per_day : (d + 1) * steps_per_day]
        day_prev_cum = states[d * steps_per_day - 1]["cumulative"] if d > 0 else {
            "it_kwh": 0, "facility_kwh": 0, "renewable_kwh": 0, "grid_kwh": 0, "co2_g": 0
        }
        day_cum = day_states[-1]["cumulative"]
        day_it = day_cum["it_kwh"] - day_prev_cum["it_kwh"]
        day_facility = day_cum["facility_kwh"] - day_prev_cum["facility_kwh"]
        day_renewable = day_cum["renewable_kwh"] - day_prev_cum["renewable_kwh"]
        day_grid = day_cum["grid_kwh"] - day_prev_cum["grid_kwh"]
        day_co2 = day_cum["co2_g"] - day_prev_cum["co2_g"]
        daily.append({
            "day": d + 1,
            "ref_pct": round(min(100.0, day_renewable / day_facility * 100), 1) if day_facility > 0 else 0.0,
            "cue_g_per_kwh": round(day_co2 / day_it, 1) if day_it > 0 else 0.0,
            "it_kwh": round(day_it, 1),
            "facility_kwh": round(day_facility, 1),
            "renewable_kwh": round(day_renewable, 1),
            "grid_kwh": round(day_grid, 1),
        })

    failed_steps = sum(1 for s in states if s["system"]["failed"])

    return {
        "location": {
            "lat": payload.lat,
            "lng": payload.lng,
            **loc_info,
        },
        "scenario": payload.scenario,
        "grid": {
            "renewable_fraction_pct": round(
                regional["renewable_mw"] / regional["total_mw"] * 100
                if regional["total_mw"] > 0 else 0.0, 1
            ),
            "carbon_intensity_g_per_kwh": carbon_intensity,
            "total_regional_mw": round(regional["total_mw"], 1),
            "plant_count": regional["plant_count"],
        },
        "totals": {
            "hours_simulated": 168,
            "it_kwh": cum["it_kwh"],
            "facility_kwh": cum["facility_kwh"],
            "renewable_kwh": cum["renewable_kwh"],
            "grid_kwh": cum["grid_kwh"],
            "battery_kwh": cum["battery_kwh"],
            "hydrogen_kwh": cum["hydrogen_kwh"],
            "co2_g": cum["co2_g"],
            "ref_pct": metrics["ref_pct"],
            "cue_g_per_kwh": metrics["cue_g_per_kwh"],
            "failed_steps": failed_steps,
        },
        "daily": daily,
    }


@app.post("/api/heatmap/grid")
def heatmap_grid(payload: HeatmapGridRequest) -> dict[str, Any]:
    """Return a grid of renewable-potential scores for a bounding box.

    Used by the frontend to render a clickable heatmap overlay.
    """
    from backend.twin.heatmap import compute_grid

    try:
        return compute_grid(
            north=payload.north,
            south=payload.south,
            east=payload.east,
            west=payload.west,
            resolution=payload.resolution,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.websocket("/ws/state")
async def ws_state(websocket: WebSocket) -> None:
    await websocket.accept()
    runtime.clients.add(websocket)
    await websocket.send_json(runtime.state)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        runtime.clients.discard(websocket)


# Serve the built frontend (single-port desktop build). No-op in dev when the
# build is absent; the Vite dev server serves the frontend there instead.
mount_frontend(app, resource_path("frontend/dist"))
