"""Core simulation entities and network evaluation result types."""

from __future__ import annotations

from dataclasses import dataclass

from .config import DroneConfig, LatencyConfig, SimulationConfig, StationConfig


@dataclass(frozen=True)
class User:
    id: str
    x_km: float
    y_km: float
    demand_mbps: float
    priority: int
    group: str


@dataclass(frozen=True)
class Position:
    x_km: float
    y_km: float


@dataclass
class DroneState:
    x_km: float
    y_km: float
    active: bool = False
    battery_wh: float | None = None

    @property
    def position(self) -> Position:
        return Position(self.x_km, self.y_km)


@dataclass
class Network:
    config: SimulationConfig
    stations: tuple[StationConfig, ...]
    users: tuple[User, ...]
    drone_spec: DroneConfig
    drone: DroneState
    latency: LatencyConfig
    drone_backhaul_available: bool = True
    drone_backhaul_capacity_mbps: float | None = None


@dataclass(frozen=True)
class Link:
    source_id: str
    target_id: str
    kind: str
    distance_km: float
    max_distance_km: float
    capacity_mbps: float


@dataclass(frozen=True)
class PathCandidate:
    kind: str
    station_id: str
    links: tuple[Link, ...]
    resources: tuple[str, ...]
    distance_km: float
    base_latency_ms: float


@dataclass(frozen=True)
class UserOutcome:
    user_id: str
    group: str
    priority: int
    covered: bool
    connected: bool
    path_kind: str | None
    distance_km: float | None
    latency_ms: float | None
    serving_station_id: str | None = None


@dataclass(frozen=True)
class NetworkSnapshot:
    outcomes: tuple[UserOutcome, ...]
    links: tuple[Link, ...]
    resource_utilization: dict[str, float]
