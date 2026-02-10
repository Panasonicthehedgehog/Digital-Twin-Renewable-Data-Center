from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import TwinConfig


@dataclass(frozen=True)
class ScenarioEffect:
    load_multiplier: float = 1.0
    temperature_offset_c: float = 0.0
    solar_factor: float = 1.0
    wind_factor: float = 1.0
    grid_factor: float = 1.0


SCENARIOS: dict[str, ScenarioEffect] = {
    "normal": ScenarioEffect(),
    "heatwave": ScenarioEffect(load_multiplier=1.07, temperature_offset_c=11.0, solar_factor=0.95, wind_factor=0.85),
    "dunkelflaute": ScenarioEffect(load_multiplier=1.02, temperature_offset_c=2.0, solar_factor=0.12, wind_factor=0.2),
    "grid_restriction": ScenarioEffect(grid_factor=0.55),
    "ai_load_spike": ScenarioEffect(load_multiplier=1.45),
    "combined_stress": ScenarioEffect(load_multiplier=1.5, temperature_offset_c=12.0, solar_factor=0.18, wind_factor=0.25, grid_factor=0.5),
}


class DigitalTwinEngine:
    """Research-grade but simplified data center digital twin.

    Modeling assumptions:
    - IT load is derived from server count and AI intensity, modulated with deterministic diurnal curves.
    - Cooling load follows a COP-based relation with ambient temperature sensitivity.
    - Hydrogen acts as a bridging buffer after battery discharge and before load shedding/failure.
    - Renewable generation is weather-derived and bounded by installed capacities.

    Limitations:
    - Single-node energy balance (no AC power-flow or N-1 topology constraints).
    - Weather model uses synthetic profiles; provider adapters can replace this module.
    - Battery degradation and electrolyzer dynamics are abstracted.
    """

    def __init__(self, config: TwinConfig) -> None:
        self.config = config
        self.scenario = "normal"
        self.rng = random.Random(config.weather.seed)
        self.current_time = datetime.now(UTC).replace(second=0, microsecond=0)
        self.step_index = 0
        self.battery_soc = config.energy.battery_initial_soc
        self.hydrogen_soc = 1.0 if config.energy.hydrogen_capacity_kwh > 0 else 0.0
        self.last_state: dict[str, Any] = {}

    def set_scenario(self, name: str) -> None:
        if name not in SCENARIOS:
            raise ValueError(f"Unknown scenario: {name}")
        self.scenario = name

    def update_config(self, config: TwinConfig) -> None:
        self.config = config
        self.rng = random.Random(config.weather.seed)
        self.battery_soc = min(self.battery_soc, 1.0)
        self.hydrogen_soc = min(self.hydrogen_soc, 1.0 if config.energy.hydrogen_capacity_kwh > 0 else 0.0)

    def simulate_step(self) -> dict[str, Any]:
        effect = SCENARIOS[self.scenario]
        dt_hours = self.config.simulation.timestep_minutes / 60
        day_progress = ((self.current_time.hour * 60) + self.current_time.minute) / (24 * 60)

        base_temp = 19 + 8 * math.sin(2 * math.pi * (day_progress - 0.2))
        base_wind = 5 + 2 * math.sin(2 * math.pi * (day_progress + 0.1))
        solar_shape = max(0.0, math.sin(math.pi * day_progress))

        noise = 0.0 if self.config.simulation.deterministic_mode else self.rng.uniform(-0.04, 0.04)

        ambient_temp = base_temp + effect.temperature_offset_c
        wind_speed = max(0.0, (base_wind * effect.wind_factor) * (1 + noise))
        solar_irradiance = 980 * solar_shape * effect.solar_factor

        topology = self.config.topology
        load_cfg = self.config.load
        energy_cfg = self.config.energy

        n_servers = topology.blocks * topology.halls_per_block * topology.racks_per_hall * topology.servers_per_rack
        utilization = min(1.0, load_cfg.ai_intensity * effect.load_multiplier * (0.85 + 0.2 * solar_shape))

        it_load_kw = n_servers * load_cfg.base_server_kw * utilization
        cooling_kw = max(0.0, it_load_kw / load_cfg.cooling_cop) * (1 + max(0.0, ambient_temp - 25) * 0.018)
        infra_kw = it_load_kw * load_cfg.infrastructure_overhead_ratio
        facility_kw = it_load_kw + cooling_kw + infra_kw

        solar_kw = energy_cfg.solar_capacity_kw * min(1.0, solar_irradiance / 1000)
        wind_kw = energy_cfg.wind_capacity_kw * min(1.0, wind_speed / 12)
        renewables_kw = solar_kw + wind_kw

        available_grid_kw = energy_cfg.grid_capacity_kw * energy_cfg.grid_curtailment_factor * effect.grid_factor

        deficit_kw = facility_kw - renewables_kw
        battery_kw = 0.0
        hydrogen_kw = 0.0
        grid_kw = 0.0

        if deficit_kw > 0:
            battery_energy_available = self.battery_soc * energy_cfg.battery_capacity_kwh
            battery_kw = min(deficit_kw, energy_cfg.battery_max_power_kw, battery_energy_available / dt_hours if dt_hours else 0)
            self.battery_soc = max(0.0, self.battery_soc - (battery_kw * dt_hours) / max(1e-6, energy_cfg.battery_capacity_kwh))
            deficit_kw -= battery_kw

            hydrogen_energy_available = self.hydrogen_soc * energy_cfg.hydrogen_capacity_kwh * energy_cfg.hydrogen_roundtrip_efficiency
            hydrogen_kw = min(
                deficit_kw,
                energy_cfg.hydrogen_max_discharge_kw,
                hydrogen_energy_available / dt_hours if dt_hours else 0,
            )
            hydrogen_energy_drawn = hydrogen_kw * dt_hours / max(1e-6, energy_cfg.hydrogen_roundtrip_efficiency)
            self.hydrogen_soc = max(0.0, self.hydrogen_soc - hydrogen_energy_drawn / max(1e-6, energy_cfg.hydrogen_capacity_kwh))
            deficit_kw -= hydrogen_kw

            grid_kw = min(max(deficit_kw, 0.0), available_grid_kw)
            deficit_kw -= grid_kw
        else:
            surplus = abs(deficit_kw)
            battery_headroom = (1 - self.battery_soc) * energy_cfg.battery_capacity_kwh
            charge_kw = min(surplus, energy_cfg.battery_max_power_kw, battery_headroom / dt_hours if dt_hours else 0)
            self.battery_soc = min(1.0, self.battery_soc + (charge_kw * dt_hours) / max(1e-6, energy_cfg.battery_capacity_kwh))

        unmet_kw = max(0.0, deficit_kw)
        failed = unmet_kw > 1e-6

        rack_map = []
        for block in range(topology.blocks):
            halls = []
            for hall in range(topology.halls_per_block):
                racks = []
                for rack in range(topology.racks_per_hall):
                    local_stress = min(1.0, utilization * (0.8 + ((rack + hall) % 5) * 0.05) + max(0, ambient_temp - 28) * 0.012)
                    racks.append({"id": f"b{block+1}-h{hall+1}-r{rack+1}", "stress": round(local_stress, 3), "load_kw": round(it_load_kw / (topology.blocks * topology.halls_per_block * topology.racks_per_hall), 3)})
                halls.append({"id": f"b{block+1}-h{hall+1}", "stress": round(sum(r['stress'] for r in racks) / len(racks), 3), "racks": racks})
            rack_map.append({"id": f"block-{block+1}", "halls": halls})

        self.last_state = {
            "timestamp": self.current_time.isoformat(),
            "scenario": self.scenario,
            "topology": topology.model_dump(),
            "weather": {
                "ambient_temp_c": round(ambient_temp, 2),
                "wind_speed_ms": round(wind_speed, 2),
                "solar_irradiance_wm2": round(solar_irradiance, 2),
            },
            "loads": {
                "it_kw": round(it_load_kw, 2),
                "cooling_kw": round(cooling_kw, 2),
                "infra_kw": round(infra_kw, 2),
                "facility_kw": round(facility_kw, 2),
                "utilization": round(utilization, 3),
            },
            "energy": {
                "solar_kw": round(solar_kw, 2),
                "wind_kw": round(wind_kw, 2),
                "renewables_kw": round(renewables_kw, 2),
                "battery_kw": round(battery_kw, 2),
                "battery_soc": round(self.battery_soc, 3),
                "hydrogen_kw": round(hydrogen_kw, 2),
                "hydrogen_soc": round(self.hydrogen_soc, 3),
                "grid_kw": round(grid_kw, 2),
                "grid_capacity_kw": round(available_grid_kw, 2),
                "unmet_kw": round(unmet_kw, 2),
            },
            "system": {
                "stress_index": round(min(1.0, (facility_kw / max(1.0, renewables_kw + grid_kw + battery_kw + hydrogen_kw))), 3),
                "hydrogen_bridge_active": hydrogen_kw > 0,
                "failed": failed,
                "failure_reason": "Power deficit not served" if failed else None,
            },
            "hierarchy": rack_map,
        }
        self.current_time += timedelta(minutes=self.config.simulation.timestep_minutes)
        self.step_index += 1
        return self.last_state
