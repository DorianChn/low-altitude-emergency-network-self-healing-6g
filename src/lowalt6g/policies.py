"""Recovery policies; the rule-based policy is a benchmark, not an AI claim."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .engine import evaluate_network
from .models import Network, Position


@dataclass(frozen=True)
class PolicyPlan:
    name: str
    deploy_drone: bool
    destination: Position | None = None


class NoRecoveryPolicy:
    name = "no_recovery"

    def plan(self, network: Network) -> PolicyPlan:
        return PolicyPlan(name=self.name, deploy_drone=False)


class GreedyRelayPolicy:
    """Choose the grid point that serves most rescue, then total, users."""

    name = "rule_based_uav_relay"

    def __init__(self, grid_km: float) -> None:
        if grid_km <= 0:
            raise ValueError("grid_km must be positive")
        self.grid_km = grid_km

    def plan(self, network: Network) -> PolicyPlan:
        best_position: Position | None = None
        best_score: tuple[int, int, int, int, float, float] | None = None
        x_values = _axis(network.config.city_width_km, self.grid_km)
        y_values = _axis(network.config.city_height_km, self.grid_km)
        for x in x_values:
            for y in y_values:
                snapshot = evaluate_network(network, drone_position=(x, y), drone_active=True)
                rescue_connected = sum(
                    outcome.connected for outcome in snapshot.outcomes if outcome.group == "rescue"
                )
                total_connected = sum(outcome.connected for outcome in snapshot.outcomes)
                rescue_covered = sum(
                    outcome.covered for outcome in snapshot.outcomes if outcome.group == "rescue"
                )
                total_covered = sum(outcome.covered for outcome in snapshot.outcomes)
                served_latencies = [
                    outcome.latency_ms
                    for outcome in snapshot.outcomes
                    if outcome.connected and outcome.latency_ms is not None
                ]
                mean_latency = sum(served_latencies) / len(served_latencies) if served_latencies else math.inf
                distance_from_start = math.hypot(
                    x - network.drone.x_km, y - network.drone.y_km
                )
                score = (
                    rescue_connected,
                    total_connected,
                    rescue_covered,
                    total_covered,
                    -mean_latency,
                    -distance_from_start,
                )
                if best_score is None or score > best_score:
                    best_score = score
                    best_position = Position(x, y)
        return PolicyPlan(name=self.name, deploy_drone=True, destination=best_position)


def move_toward(network: Network, destination: Position, duration_s: int) -> None:
    """Advance the drone along a straight path at its configured speed."""
    dx = destination.x_km - network.drone.x_km
    dy = destination.y_km - network.drone.y_km
    distance = math.hypot(dx, dy)
    max_distance = network.drone_spec.speed_km_per_s * duration_s
    if distance <= max_distance or distance == 0:
        network.drone.x_km = destination.x_km
        network.drone.y_km = destination.y_km
        return
    ratio = max_distance / distance
    network.drone.x_km += dx * ratio
    network.drone.y_km += dy * ratio


def _axis(limit: float, step: float) -> tuple[float, ...]:
    count = int(math.floor(limit / step))
    values = [index * step for index in range(count + 1)]
    if not math.isclose(values[-1], limit, abs_tol=1e-9):
        values.append(limit)
    return tuple(values)
