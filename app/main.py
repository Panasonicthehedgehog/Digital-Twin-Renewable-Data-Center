from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


class RackTelemetry(BaseModel):
    id: str
    inletTempC: float | None = None
    cpuUtilization: float | None = Field(default=None, ge=0, le=1)
    maxKw: float | None = None


class HallTelemetry(BaseModel):
    id: str
    pue: float | None = None
    racks: list[RackTelemetry] = Field(default_factory=list)


class RenewableTelemetry(BaseModel):
    id: str
    type: str | None = None
    capacityKw: float | None = None
    outputKw: float | None = None


class BatteryTelemetry(BaseModel):
    id: str
    soc: float | None = Field(default=None, ge=0, le=1)


class TelemetryPayload(BaseModel):
    halls: list[HallTelemetry] = Field(default_factory=list)
    renewables: list[RenewableTelemetry] = Field(default_factory=list)
    batteries: list[BatteryTelemetry] = Field(default_factory=list)
    weather: dict[str, Any] = Field(default_factory=dict)
    grid: dict[str, Any] = Field(default_factory=dict)


DEFAULT_STATE: dict[str, Any] = {
    "halls": [
        {
            "id": "hall-a",
            "pue": 1.19,
            "racks": [
                {"id": "a-r1", "maxKw": 28, "inletTempC": 24.5, "cpuUtilization": 0.72},
                {"id": "a-r2", "maxKw": 30, "inletTempC": 25.1, "cpuUtilization": 0.64},
                {"id": "a-r3", "maxKw": 27, "inletTempC": 23.8, "cpuUtilization": 0.81},
            ],
        },
        {
            "id": "hall-b",
            "pue": 1.24,
            "racks": [
                {"id": "b-r1", "maxKw": 32, "inletTempC": 26.2, "cpuUtilization": 0.67},
                {"id": "b-r2", "maxKw": 31, "inletTempC": 25.6, "cpuUtilization": 0.74},
                {"id": "b-r3", "maxKw": 29, "inletTempC": 26.8, "cpuUtilization": 0.69},
            ],
        },
    ],
    "renewables": [
        {"id": "solar-west", "type": "solar", "capacityKw": 20000, "outputKw": 14500},
        {"id": "solar-east", "type": "solar", "capacityKw": 12000, "outputKw": 8300},
        {"id": "wind-1", "type": "wind", "capacityKw": 18000, "outputKw": 9200},
    ],
    "batteries": [{"id": "bess-1", "capacityKwh": 60000, "soc": 0.68, "maxDischargeKw": 10000}],
    "weather": {"ambientTempC": 29.4, "ghiWm2": 801, "windSpeedMs": 8.2, "condition": "partly_cloudy"},
    "grid": {"co2IntensityGPerKwh": 313, "priceEurPerMwh": 142},
}


def _build_aggregates(state: dict[str, Any]) -> dict[str, float]:
    it_load = 0.0
    facility_load = 0.0
    for hall in state["halls"]:
        hall_it = sum((rack.get("maxKw", 0) * rack.get("cpuUtilization", 0)) for rack in hall.get("racks", []))
        it_load += hall_it
        facility_load += hall_it * hall.get("pue", 1.2)

    renewable_kw = sum(asset.get("outputKw", 0) for asset in state["renewables"])
    battery_discharge_kw = sum(
        battery.get("maxDischargeKw", 0) * battery.get("soc", 0) for battery in state.get("batteries", [])
    )
    coverage = renewable_kw / facility_load if facility_load else 0

    return {
        "itLoadKw": round(it_load, 2),
        "facilityLoadKw": round(facility_load, 2),
        "renewableKw": round(renewable_kw, 2),
        "batteryDischargeKw": round(battery_discharge_kw, 2),
        "renewableCoverage": round(coverage, 3),
    }


class TwinStateStore:
    def __init__(self) -> None:
        import copy

        self.state: dict[str, Any] = copy.deepcopy(DEFAULT_STATE)
        self.last_update = datetime.now(timezone.utc)

    def apply(self, payload: TelemetryPayload) -> None:
        for incoming_hall in payload.halls:
            hall = next((item for item in self.state["halls"] if item["id"] == incoming_hall.id), None)
            incoming_data = incoming_hall.model_dump(exclude_none=True)
            if hall is None:
                self.state["halls"].append(incoming_data)
            else:
                hall.update({k: v for k, v in incoming_data.items() if k != "racks"})
                for incoming_rack in incoming_data.get("racks", []):
                    rack = next((item for item in hall.get("racks", []) if item["id"] == incoming_rack["id"]), None)
                    if rack is None:
                        hall.setdefault("racks", []).append(incoming_rack)
                    else:
                        rack.update(incoming_rack)

        for incoming_renewable in payload.renewables:
            renewable = next((item for item in self.state["renewables"] if item["id"] == incoming_renewable.id), None)
            incoming_data = incoming_renewable.model_dump(exclude_none=True)
            if renewable is None:
                self.state["renewables"].append(incoming_data)
            else:
                renewable.update(incoming_data)

        for incoming_battery in payload.batteries:
            battery = next((item for item in self.state["batteries"] if item["id"] == incoming_battery.id), None)
            incoming_data = incoming_battery.model_dump(exclude_none=True)
            if battery is None:
                self.state["batteries"].append(incoming_data)
            else:
                battery.update(incoming_data)

        if payload.weather:
            self.state["weather"].update(payload.weather)
        if payload.grid:
            self.state["grid"].update(payload.grid)

        self.last_update = datetime.now(timezone.utc)

    def export(self) -> dict[str, Any]:
        export_state = dict(self.state)
        export_state["aggregates"] = _build_aggregates(self.state)
        export_state["lastUpdate"] = self.last_update.isoformat()
        return export_state


store = TwinStateStore()
app = FastAPI(title="Hyperscaler Digital Twin Pipeline")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/state")
def get_state() -> dict[str, Any]:
    return store.export()


@app.post("/api/v1/telemetry")
def ingest_telemetry(payload: TelemetryPayload) -> dict[str, Any]:
    store.apply(payload)
    return {"status": "accepted", "updatedAt": store.last_update.isoformat()}


@app.post("/api/v1/telemetry/bulk")
def ingest_bulk(items: list[TelemetryPayload]) -> dict[str, Any]:
    for item in items:
        store.apply(item)
    return {"status": "accepted", "events": len(items), "updatedAt": store.last_update.isoformat()}
