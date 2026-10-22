"""Create deterministic city users and network state from configuration."""

from __future__ import annotations

import random

from .config import SimulationConfig
from .models import DroneState, Network, User


def build_network(config: SimulationConfig) -> Network:
    """Generate fixed user locations with independent, seed-derived streams."""
    config.validate()
    normal_rng = random.Random(config.seed)
    rescue_rng = random.Random(config.seed ^ 0x9E3779B9)
    users: list[User] = []

    for index in range(config.normal_user_count):
        x, y = _sample(normal_rng, config.normal_region_km)
        users.append(
            User(
                id=f"normal-{index + 1:03d}",
                x_km=x,
                y_km=y,
                demand_mbps=config.normal_demand_mbps,
                priority=config.normal_priority,
                group="normal",
            )
        )
    for index in range(config.rescue_user_count):
        x, y = _sample(rescue_rng, config.rescue_region_km)
        users.append(
            User(
                id=f"rescue-{index + 1:03d}",
                x_km=x,
                y_km=y,
                demand_mbps=config.rescue_demand_mbps,
                priority=config.rescue_priority,
                group="rescue",
            )
        )

    return Network(
        config=config,
        stations=config.stations,
        users=tuple(users),
        drone_spec=config.drone,
        drone=DroneState(config.drone.x_km, config.drone.y_km),
        latency=config.latency,
    )


def _sample(rng: random.Random, region: tuple[float, float, float, float]) -> tuple[float, float]:
    x_min, x_max, y_min, y_max = region
    return rng.uniform(x_min, x_max), rng.uniform(y_min, y_max)
