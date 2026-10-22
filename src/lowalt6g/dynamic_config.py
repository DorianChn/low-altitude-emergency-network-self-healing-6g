"""Dynamic experiment settings kept separate from the Phase 1 TOML schema."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from .config import SimulationConfig, load_config


SUPPORTED_EVENTS = {
    "station_failure",
    "station_recovery",
    "traffic_change",
    "backhaul_failure",
    "backhaul_recovery",
    "backhaul_capacity_change",
    "user_mobility_change",
}


@dataclass(frozen=True)
class DynamicEventSpec:
    time_s: int
    event_type: str
    target_id: str
    value: float | None = None


@dataclass(frozen=True)
class DynamicExperimentConfig:
    scenario_path: Path
    base: SimulationConfig
    seeds: tuple[int, ...]
    events: tuple[DynamicEventSpec, ...]
    mobility_axis_max_km_per_tick: float
    decision_interval_s: int
    prediction_horizon_steps: int
    beam_width: int
    position_signature_quantum_km: float
    battery_capacity_wh: float
    initial_battery_wh: float
    reserve_wh: float
    movement_wh_per_km: float
    hover_power_w: float
    relay_power_w: float
    congestion_threshold: float
    rescue_service_weight: float
    connection_weight: float
    recovery_bonus: float
    latency_penalty_weight: float
    energy_penalty_weight: float
    rescue_progress_weight: float
    rescue_mobility_axis_max_km_per_tick: float | None = None
    initial_backhaul_capacity_mbps: float | None = None
    development_seeds: tuple[int, ...] = ()
    validation_seeds: tuple[int, ...] = ()

    @property
    def duration_s(self) -> int:
        return self.base.duration_s

    @property
    def time_step_s(self) -> int:
        return self.base.time_step_s

    def validate(self) -> None:
        self.base.validate()
        if len(self.seeds) < 1 or any(seed < 0 for seed in self.seeds):
            raise ValueError("at least one non-negative seed is required")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("experiment seeds must be unique")
        if self.mobility_axis_max_km_per_tick < 0:
            raise ValueError("mobility limit must be non-negative")
        if self.rescue_mobility_axis_max_km_per_tick is not None and self.rescue_mobility_axis_max_km_per_tick < 0:
            raise ValueError("rescue mobility limit must be non-negative")
        if self.initial_backhaul_capacity_mbps is not None and self.initial_backhaul_capacity_mbps <= 0:
            raise ValueError("initial backhaul capacity must be positive")
        if self.development_seeds and (
            min(self.development_seeds) < 0 or len(set(self.development_seeds)) != len(self.development_seeds)
        ):
            raise ValueError("development seeds must be unique and non-negative")
        if self.validation_seeds and (
            min(self.validation_seeds) < 0 or len(set(self.validation_seeds)) != len(self.validation_seeds)
        ):
            raise ValueError("validation seeds must be unique and non-negative")
        if set(self.development_seeds) & set(self.validation_seeds):
            raise ValueError("development and validation seeds must not overlap")
        if self.decision_interval_s <= 0 or self.decision_interval_s % self.time_step_s:
            raise ValueError("decision_interval_s must be a positive multiple of time_step_s")
        if self.prediction_horizon_steps < 1 or self.beam_width < 1:
            raise ValueError("prediction horizon and beam width must be positive")
        if self.position_signature_quantum_km <= 0:
            raise ValueError("position signature quantum must be positive")
        if not (0 < self.reserve_wh < self.initial_battery_wh <= self.battery_capacity_wh):
            raise ValueError("energy requires 0 < reserve < initial battery <= battery capacity")
        if min(self.movement_wh_per_km, self.hover_power_w, self.relay_power_w) < 0:
            raise ValueError("energy rates must be non-negative")
        if not 0 <= self.congestion_threshold <= 1:
            raise ValueError("congestion threshold must be between zero and one")
        if min(
            self.rescue_service_weight,
            self.connection_weight,
            self.recovery_bonus,
            self.latency_penalty_weight,
            self.energy_penalty_weight,
            self.rescue_progress_weight,
        ) < 0:
            raise ValueError("objective weights must be non-negative")
        station_ids = {station.id for station in self.base.stations}
        for event in self.events:
            if event.event_type not in SUPPORTED_EVENTS:
                raise ValueError(f"unsupported event type: {event.event_type}")
            if event.time_s < 0 or event.time_s > self.duration_s:
                raise ValueError(f"event time out of simulation range: {event.time_s}")
            if event.time_s % self.time_step_s:
                raise ValueError(f"event time {event.time_s} must align with the simulation step")
            if event.event_type.startswith("station_") and event.target_id not in station_ids:
                raise ValueError(f"event references unknown station: {event.target_id}")
            if event.event_type.startswith("backhaul_") and event.target_id != self.base.drone.id:
                raise ValueError(f"backhaul event target must be {self.base.drone.id}")
            if event.event_type == "traffic_change":
                if event.target_id not in {"city", "rescue", "normal"}:
                    raise ValueError("traffic_change target_id must be city, rescue, or normal")
                if event.value is None or event.value <= 0:
                    raise ValueError("traffic_change requires a positive multiplier")
            if event.event_type == "user_mobility_change":
                if event.target_id not in {"city", "rescue", "normal"}:
                    raise ValueError("user_mobility_change target_id must be city, rescue, or normal")
                if event.value is None or event.value < 0:
                    raise ValueError("user_mobility_change requires a non-negative km-per-tick value")
            if event.event_type == "backhaul_capacity_change":
                if event.target_id != self.base.drone.id:
                    raise ValueError(f"backhaul capacity event target must be {self.base.drone.id}")
                if event.value is None or event.value <= 0:
                    raise ValueError("backhaul_capacity_change requires a positive capacity in Mbps")
        if tuple(sorted(self.events, key=lambda item: item.time_s)) != self.events:
            raise ValueError("events must be ordered by time_s")


def load_dynamic_config(path: str | Path) -> DynamicExperimentConfig:
    source_path = Path(path).resolve()
    with source_path.open("rb") as source:
        raw = tomllib.load(source)
    base_path = (source_path.parent / raw["base_scenario"]).resolve()
    base = load_config(base_path)
    experiment = raw["experiment"]
    energy = raw["energy"]
    optimizer = raw["optimizer"]
    config = DynamicExperimentConfig(
        scenario_path=base_path,
        base=base,
        seeds=tuple(int(seed) for seed in experiment["seeds"]),
        events=tuple(
            DynamicEventSpec(
                time_s=int(event["time_s"]),
                event_type=str(event["type"]),
                target_id=str(event["target_id"]),
                value=float(event["value"]) if "value" in event else None,
            )
            for event in raw.get("events", [])
        ),
        mobility_axis_max_km_per_tick=float(experiment["mobility_axis_max_km_per_tick"]),
        decision_interval_s=int(optimizer["decision_interval_s"]),
        prediction_horizon_steps=int(optimizer["prediction_horizon_steps"]),
        beam_width=int(optimizer["beam_width"]),
        position_signature_quantum_km=float(optimizer["position_signature_quantum_km"]),
        battery_capacity_wh=float(energy["battery_capacity_wh"]),
        initial_battery_wh=float(energy["initial_battery_wh"]),
        reserve_wh=float(energy["reserve_wh"]),
        movement_wh_per_km=float(energy["movement_wh_per_km"]),
        hover_power_w=float(energy["hover_power_w"]),
        relay_power_w=float(energy["relay_power_w"]),
        congestion_threshold=float(optimizer["congestion_threshold"]),
        rescue_service_weight=float(optimizer["rescue_service_weight"]),
        connection_weight=float(optimizer["connection_weight"]),
        recovery_bonus=float(optimizer["recovery_bonus"]),
        latency_penalty_weight=float(optimizer["latency_penalty_weight"]),
        energy_penalty_weight=float(optimizer["energy_penalty_weight"]),
        rescue_progress_weight=float(optimizer["rescue_progress_weight"]),
        rescue_mobility_axis_max_km_per_tick=(
            float(experiment["rescue_mobility_axis_max_km_per_tick"])
            if "rescue_mobility_axis_max_km_per_tick" in experiment
            else None
        ),
        initial_backhaul_capacity_mbps=(
            float(raw["network"]["initial_backhaul_capacity_mbps"])
            if "network" in raw and "initial_backhaul_capacity_mbps" in raw["network"]
            else None
        ),
        development_seeds=tuple(int(seed) for seed in raw.get("phase5", {}).get("development_seeds", [])),
        validation_seeds=tuple(int(seed) for seed in raw.get("phase5", {}).get("validation_seeds", [])),
    )
    config.validate()
    return config
