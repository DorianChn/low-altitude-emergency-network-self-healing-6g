"""Configuration parsing and validation for reproducible simulations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import tomllib
from typing import Any


Region = tuple[float, float, float, float]


@dataclass(frozen=True)
class StationConfig:
    id: str
    x_km: float
    y_km: float
    coverage_radius_km: float
    capacity_mbps: float
    healthy: bool


@dataclass(frozen=True)
class DroneConfig:
    id: str
    x_km: float
    y_km: float
    access_radius_km: float
    backhaul_radius_km: float
    capacity_mbps: float
    speed_km_per_s: float


@dataclass(frozen=True)
class LatencyConfig:
    base_latency_ms: float
    propagation_ms_per_km: float
    relay_processing_ms: float
    congestion_delay_factor_ms: float
    max_queue_delay_ms: float


@dataclass(frozen=True)
class SimulationConfig:
    scenario_name: str
    city_width_km: float
    city_height_km: float
    duration_s: int
    time_step_s: int
    seed: int
    normal_user_count: int
    rescue_user_count: int
    normal_priority: int
    rescue_priority: int
    normal_region_km: Region
    rescue_region_km: Region
    normal_demand_mbps: float
    rescue_demand_mbps: float
    stations: tuple[StationConfig, ...]
    drone: DroneConfig
    latency: LatencyConfig
    policy_search_grid_km: float

    def validate(self) -> None:
        if not self.scenario_name.strip():
            raise ValueError("scenario_name must not be empty")
        if self.city_width_km <= 0 or self.city_height_km <= 0:
            raise ValueError("city dimensions must be positive")
        if self.duration_s < 0 or self.time_step_s <= 0:
            raise ValueError("duration_s must be non-negative and time_step_s positive")
        if self.duration_s % self.time_step_s:
            raise ValueError("duration_s must be divisible by time_step_s")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.normal_user_count < 0 or self.rescue_user_count <= 0:
            raise ValueError("normal_user_count must be non-negative and rescue_user_count positive")
        if self.normal_priority < 0 or self.rescue_priority <= self.normal_priority:
            raise ValueError("rescue_priority must be greater than normal_priority")
        if self.normal_demand_mbps <= 0 or self.rescue_demand_mbps <= 0:
            raise ValueError("user traffic demands must be positive")
        if not self.stations:
            raise ValueError("at least one base station is required")
        station_ids = [station.id for station in self.stations]
        if len(station_ids) != len(set(station_ids)):
            raise ValueError("base station IDs must be unique")
        for station in self.stations:
            _validate_position(station.id, station.x_km, station.y_km, self.city_width_km, self.city_height_km)
            if station.coverage_radius_km <= 0 or station.capacity_mbps <= 0:
                raise ValueError(f"station {station.id} must have positive range and capacity")
        _validate_position(self.drone.id, self.drone.x_km, self.drone.y_km, self.city_width_km, self.city_height_km)
        if min(
            self.drone.access_radius_km,
            self.drone.backhaul_radius_km,
            self.drone.capacity_mbps,
            self.drone.speed_km_per_s,
        ) <= 0:
            raise ValueError("drone ranges, capacity, and speed must be positive")
        _validate_region("normal_region_km", self.normal_region_km, self.city_width_km, self.city_height_km)
        _validate_region("rescue_region_km", self.rescue_region_km, self.city_width_km, self.city_height_km)
        if self.policy_search_grid_km <= 0:
            raise ValueError("policy search grid must be positive")
        if min(
            self.latency.base_latency_ms,
            self.latency.propagation_ms_per_km,
            self.latency.relay_processing_ms,
            self.latency.congestion_delay_factor_ms,
            self.latency.max_queue_delay_ms,
        ) < 0:
            raise ValueError("latency parameters must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly copy of the full effective configuration."""
        return asdict(self)


def load_config(path: str | Path) -> SimulationConfig:
    """Load a TOML scenario file and validate all model parameters."""
    with Path(path).open("rb") as source:
        raw = tomllib.load(source)

    sim = raw["simulation"]
    latency = raw["latency"]
    drone = raw["drone"]
    config = SimulationConfig(
        scenario_name=raw["scenario_name"],
        city_width_km=float(sim["city_width_km"]),
        city_height_km=float(sim["city_height_km"]),
        duration_s=int(sim["duration_s"]),
        time_step_s=int(sim["time_step_s"]),
        seed=int(sim["seed"]),
        normal_user_count=int(sim["normal_user_count"]),
        rescue_user_count=int(sim["rescue_user_count"]),
        normal_priority=int(sim["normal_priority"]),
        rescue_priority=int(sim["rescue_priority"]),
        normal_region_km=_region(sim["normal_region_km"]),
        rescue_region_km=_region(sim["rescue_region_km"]),
        normal_demand_mbps=float(sim["normal_demand_mbps"]),
        rescue_demand_mbps=float(sim["rescue_demand_mbps"]),
        stations=tuple(
            StationConfig(
                id=str(station["id"]),
                x_km=float(station["x_km"]),
                y_km=float(station["y_km"]),
                coverage_radius_km=float(station["coverage_radius_km"]),
                capacity_mbps=float(station["capacity_mbps"]),
                healthy=bool(station["healthy"]),
            )
            for station in raw["stations"]
        ),
        drone=DroneConfig(
            id=str(drone["id"]),
            x_km=float(drone["x_km"]),
            y_km=float(drone["y_km"]),
            access_radius_km=float(drone["access_radius_km"]),
            backhaul_radius_km=float(drone["backhaul_radius_km"]),
            capacity_mbps=float(drone["capacity_mbps"]),
            speed_km_per_s=float(drone["speed_km_per_s"]),
        ),
        latency=LatencyConfig(
            base_latency_ms=float(latency["base_latency_ms"]),
            propagation_ms_per_km=float(latency["propagation_ms_per_km"]),
            relay_processing_ms=float(latency["relay_processing_ms"]),
            congestion_delay_factor_ms=float(latency["congestion_delay_factor_ms"]),
            max_queue_delay_ms=float(latency["max_queue_delay_ms"]),
        ),
        policy_search_grid_km=float(raw["policy"]["search_grid_km"]),
    )
    config.validate()
    return config


def _region(value: Any) -> Region:
    if len(value) != 4:
        raise ValueError("region must be [x_min, x_max, y_min, y_max]")
    return tuple(float(item) for item in value)  # type: ignore[return-value]


def _validate_region(name: str, region: Region, width: float, height: float) -> None:
    x_min, x_max, y_min, y_max = region
    if not (0 <= x_min <= x_max <= width and 0 <= y_min <= y_max <= height):
        raise ValueError(f"{name} must lie within the city bounds")


def _validate_position(name: str, x: float, y: float, width: float, height: float) -> None:
    if not (0 <= x <= width and 0 <= y <= height):
        raise ValueError(f"{name} position must lie within the city bounds")
