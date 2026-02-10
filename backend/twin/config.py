from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class TopologyConfig(BaseModel):
    blocks: int = Field(default=1, ge=1)
    halls_per_block: int = Field(default=2, ge=1)
    racks_per_hall: int = Field(default=8, ge=1)
    servers_per_rack: int = Field(default=32, ge=1)


class LoadConfig(BaseModel):
    ai_intensity: float = Field(default=0.72, ge=0.05, le=1.0)
    base_server_kw: float = Field(default=0.45, gt=0)
    training_burst_multiplier: float = Field(default=1.45, ge=1.0)
    cooling_cop: float = Field(default=3.4, gt=0)
    infrastructure_overhead_ratio: float = Field(default=0.08, ge=0)


class EnergyConfig(BaseModel):
    grid_capacity_kw: float = Field(default=16000, gt=0)
    grid_curtailment_factor: float = Field(default=1.0, gt=0, le=1)
    solar_capacity_kw: float = Field(default=7000, ge=0)
    wind_capacity_kw: float = Field(default=5000, ge=0)
    battery_capacity_kwh: float = Field(default=12000, ge=0)
    battery_max_power_kw: float = Field(default=6000, ge=0)
    battery_initial_soc: float = Field(default=0.65, ge=0, le=1)
    hydrogen_capacity_kwh: float = Field(default=25000, ge=0)
    hydrogen_max_discharge_kw: float = Field(default=3500, ge=0)
    hydrogen_roundtrip_efficiency: float = Field(default=0.45, gt=0, le=1)


class WeatherConfig(BaseModel):
    latitude: float = 52.52
    longitude: float = 13.405
    timezone: str = "UTC"
    seed: int = 42


class SimulationConfig(BaseModel):
    timestep_minutes: int = Field(default=15, ge=1)
    deterministic_mode: bool = True


class TwinConfig(BaseModel):
    topology: TopologyConfig = Field(default_factory=TopologyConfig)
    load: LoadConfig = Field(default_factory=LoadConfig)
    energy: EnergyConfig = Field(default_factory=EnergyConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)


def load_config(path: str | Path) -> TwinConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle) or {}
    return TwinConfig.model_validate(data)


def write_config(path: str | Path, config: TwinConfig) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config.model_dump(), handle, sort_keys=False)
