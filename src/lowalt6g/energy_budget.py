"""Shared, conservative sortie-energy estimates used by dynamic planners."""

from __future__ import annotations

import math

from .dynamic_config import DynamicExperimentConfig
from .engine import distance_km
from .models import Network, Position


def return_energy_wh(
    config: DynamicExperimentConfig,
    network: Network,
    position: Position,
) -> float | None:
    """Bound energy needed to reach the nearest healthy station and land.

    The estimate includes movement energy and hover/relay electronics power for
    every return-flight time step. Relay power is reserved conservatively even
    when the return route is expected to stop forwarding user traffic.
    """
    healthy = tuple(station for station in network.stations if station.healthy)
    if not healthy:
        return None
    distance = min(
        distance_km(position.x_km, position.y_km, station.x_km, station.y_km)
        for station in healthy
    )
    move_per_tick = network.drone_spec.speed_km_per_s * config.time_step_s
    if move_per_tick <= 0:
        return None
    return_ticks = math.ceil(distance / move_per_tick)
    flight_power_w = config.hover_power_w + config.relay_power_w
    return (
        distance * config.movement_wh_per_km
        + flight_power_w * return_ticks * config.time_step_s / 3600.0
    )


def sortie_energy_wh(
    config: DynamicExperimentConfig,
    network: Network,
    destination: Position,
    *,
    service_steps: int | None = None,
) -> float | None:
    """Estimate a full reach, service, and return sortie in Wh.

    The same rates are used across controllers. Hover and relay power are both
    budgeted for every outbound, service, and return tick. This is intentionally
    conservative and makes the planning envelope auditable and common to B', C,
    and D; the runtime actuator still accounts for measured tick activity.
    """
    healthy = tuple(station for station in network.stations if station.healthy)
    if not healthy:
        return None
    start = network.drone.position
    outbound = distance_km(start.x_km, start.y_km, destination.x_km, destination.y_km)
    returning = min(
        distance_km(destination.x_km, destination.y_km, station.x_km, station.y_km)
        for station in healthy
    )
    move_per_tick = network.drone_spec.speed_km_per_s * config.time_step_s
    if move_per_tick <= 0:
        return None
    outbound_ticks = math.ceil(outbound / move_per_tick)
    return_ticks = math.ceil(returning / move_per_tick)
    service_tick_count = config.prediction_horizon_steps if service_steps is None else service_steps
    total_flight_ticks = outbound_ticks + service_tick_count + return_ticks
    return (
        (outbound + returning) * config.movement_wh_per_km
        + (config.hover_power_w + config.relay_power_w)
        * total_flight_ticks
        * config.time_step_s
        / 3600.0
    )
