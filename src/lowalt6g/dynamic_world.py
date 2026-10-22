"""Seeded exogenous event and user-mobility traces shared by all strategies."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import random

from .dynamic_config import DynamicEventSpec, DynamicExperimentConfig
from .models import Network, User
from .scenario import build_network


@dataclass(frozen=True)
class DynamicWorldTrace:
    seed: int
    user_positions_by_tick: tuple[dict[str, tuple[float, float]], ...]
    events_by_time: dict[int, tuple[DynamicEventSpec, ...]]
    environment_event_log: tuple[dict[str, object], ...]
    trace_sha256: str


def build_world_trace(config: DynamicExperimentConfig, seed: int) -> DynamicWorldTrace:
    """Generate one complete mobility trace before running any policy.

    Pre-generating exogenous positions means strategy decisions cannot consume
    random numbers and accidentally change the world seen by another strategy.
    """
    seeded_base = replace(config.base, seed=seed)
    initial = build_network(seeded_base)
    positions = {user.id: [user.x_km, user.y_km] for user in initial.users}
    user_groups = {user.id: user.group for user in initial.users}
    rng = random.Random(seed ^ 0xA5A5_19C3)
    by_time: dict[int, list[DynamicEventSpec]] = {}
    log: list[dict[str, object]] = []
    for event in config.events:
        by_time.setdefault(event.time_s, []).append(event)
        log.append(
            {
                "time_s": event.time_s,
                "event_type": event.event_type,
                "target_id": event.target_id,
                "value": event.value,
                "source": "configured_event_schedule",
            }
        )

    position_frames: list[dict[str, tuple[float, float]]] = []
    frame_hashes: list[str] = []
    mobility_events: dict[int, list[DynamicEventSpec]] = {}
    for event in config.events:
        if event.event_type == "user_mobility_change":
            mobility_events.setdefault(event.time_s, []).append(event)
    normal_mobility = config.mobility_axis_max_km_per_tick
    rescue_mobility = (
        config.rescue_mobility_axis_max_km_per_tick
        if config.rescue_mobility_axis_max_km_per_tick is not None
        else config.mobility_axis_max_km_per_tick
    )
    for tick in range(seeded_base.duration_s // seeded_base.time_step_s + 1):
        time_s = tick * seeded_base.time_step_s
        for event in mobility_events.get(time_s, ()):
            assert event.value is not None
            if event.target_id == "city":
                normal_mobility = event.value
                rescue_mobility = event.value
            elif event.target_id == "rescue":
                rescue_mobility = event.value
            else:
                normal_mobility = event.value
        moved_count = 0
        if tick:
            for user_id in sorted(positions):
                x, y = positions[user_id]
                mobility_limit = (
                    rescue_mobility if user_groups[user_id] == "rescue" else normal_mobility
                )
                dx = rng.uniform(
                    -mobility_limit,
                    mobility_limit,
                )
                dy = rng.uniform(
                    -mobility_limit,
                    mobility_limit,
                )
                next_x = min(max(x + dx, 0.0), seeded_base.city_width_km)
                next_y = min(max(y + dy, 0.0), seeded_base.city_height_km)
                if next_x != x or next_y != y:
                    moved_count += 1
                positions[user_id] = [next_x, next_y]
            frame_payload = [
                (user_id, round(value[0], 6), round(value[1], 6))
                for user_id, value in sorted(positions.items())
            ]
            frame_hash = hashlib.sha256(
                json.dumps(frame_payload, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            frame_hashes.append(frame_hash)
            log.append(
                {
                    "time_s": time_s,
                    "event_type": "user_mobility_update",
                    "target_id": "all_users",
                    "moved_user_count": moved_count,
                    "positions_sha256": frame_hash,
                    "source": "seeded_random_walk",
                }
            )
        position_frames.append(
            {user_id: (value[0], value[1]) for user_id, value in sorted(positions.items())}
        )

    log.sort(key=lambda event: (int(event["time_s"]), str(event["event_type"]), str(event.get("target_id", ""))))
    trace_payload = {
        "seed": seed,
        "events": log,
        "frame_hashes": frame_hashes,
    }
    trace_hash = hashlib.sha256(
        json.dumps(trace_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return DynamicWorldTrace(
        seed=seed,
        user_positions_by_tick=tuple(position_frames),
        events_by_time={time: tuple(items) for time, items in by_time.items()},
        environment_event_log=tuple(log),
        trace_sha256=trace_hash,
    )


def apply_world_state(
    network: Network,
    base_users: dict[str, User],
    trace: DynamicWorldTrace,
    tick: int,
    traffic_multiplier: float | dict[str, float],
) -> None:
    """Set current user coordinates and offered load from the shared trace."""
    frame = trace.user_positions_by_tick[tick]
    def group_multiplier(group: str) -> float:
        if isinstance(traffic_multiplier, dict):
            return traffic_multiplier.get("city", 1.0) * traffic_multiplier.get(group, 1.0)
        return traffic_multiplier

    network.users = tuple(
        replace(
            base_users[user_id],
            x_km=position[0],
            y_km=position[1],
            demand_mbps=base_users[user_id].demand_mbps * group_multiplier(base_users[user_id].group),
        )
        for user_id, position in sorted(frame.items())
    )
