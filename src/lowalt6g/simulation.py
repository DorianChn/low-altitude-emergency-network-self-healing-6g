"""Discrete-time simulation and derived performance metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .config import SimulationConfig
from .engine import evaluate_network
from .models import Network, Position
from .policies import GreedyRelayPolicy, PolicyPlan, move_toward
from .scenario import build_network


class RecoveryPolicy(Protocol):
    name: str

    def plan(self, network: Network) -> PolicyPlan: ...


@dataclass(frozen=True)
class SimulationResult:
    policy: str
    metrics: dict[str, int | float | None]
    policy_details: dict[str, int | float | str | None]

    def to_dict(self) -> dict[str, object]:
        return {
            "policy": self.policy,
            "policy_details": self.policy_details,
            "metrics": self.metrics,
        }


def run_simulation(config: SimulationConfig, policy: RecoveryPolicy) -> SimulationResult:
    network = build_network(config)
    plan = policy.plan(network)
    if plan.deploy_drone:
        network.drone.active = True

    tick_count = config.duration_s // config.time_step_s + 1
    total_users = len(network.users)
    rescue_total = sum(user.group == "rescue" for user in network.users)
    covered_samples = 0
    connected_samples = 0
    rescue_connected_samples = 0
    latency_sum_ms = 0.0
    latency_samples = 0
    recovery_time_s: int | None = None
    final_snapshot = None

    for tick in range(tick_count):
        time_s = tick * config.time_step_s
        if plan.deploy_drone and tick > 0 and plan.destination is not None:
            move_toward(network, plan.destination, config.time_step_s)
        snapshot = evaluate_network(network)
        final_snapshot = snapshot
        covered_samples += sum(outcome.covered for outcome in snapshot.outcomes)
        connected_samples += sum(outcome.connected for outcome in snapshot.outcomes)
        rescue_connected = sum(
            outcome.connected for outcome in snapshot.outcomes if outcome.group == "rescue"
        )
        rescue_connected_samples += rescue_connected
        latencies = [
            outcome.latency_ms
            for outcome in snapshot.outcomes
            if outcome.connected and outcome.latency_ms is not None
        ]
        latency_sum_ms += sum(latencies)
        latency_samples += len(latencies)
        if recovery_time_s is None and rescue_connected == rescue_total:
            recovery_time_s = time_s

    assert final_snapshot is not None
    final_rescue_connected = sum(
        outcome.connected for outcome in final_snapshot.outcomes if outcome.group == "rescue"
    )
    final_covered = sum(outcome.covered for outcome in final_snapshot.outcomes)
    final_connected = sum(outcome.connected for outcome in final_snapshot.outcomes)
    observed_users = total_users * tick_count
    metrics: dict[str, int | float | None] = {
        "network_coverage_rate": _rate(covered_samples, observed_users),
        "user_connection_success_rate": _rate(connected_samples, observed_users),
        "rescue_user_service_success_rate": _rate(rescue_connected_samples, rescue_total * tick_count),
        "network_recovery_time_s": recovery_time_s,
        "average_communication_latency_ms": round(latency_sum_ms / latency_samples, 6)
        if latency_samples
        else None,
        "latency_sample_count": latency_samples,
        "evaluation_ticks": tick_count,
        "user_count": total_users,
        "rescue_user_count": rescue_total,
        "final_coverage_rate": _rate(final_covered, total_users),
        "final_connection_success_rate": _rate(final_connected, total_users),
        "final_rescue_users_connected": final_rescue_connected,
        "final_rescue_users_total": rescue_total,
        "final_active_link_count": len(final_snapshot.links),
    }
    details: dict[str, int | float | str | None] = {
        "drone_deployed": int(plan.deploy_drone),
        "dispatch_time_s": 0 if plan.deploy_drone else None,
        "target_x_km": plan.destination.x_km if plan.destination else None,
        "target_y_km": plan.destination.y_km if plan.destination else None,
        "final_drone_x_km": round(network.drone.x_km, 6),
        "final_drone_y_km": round(network.drone.y_km, 6),
        "search_grid_km": getattr(policy, "grid_km", None),
    }
    return SimulationResult(policy=plan.name, metrics=metrics, policy_details=details)


def benchmark(config: SimulationConfig) -> dict[str, SimulationResult]:
    """Run both the no-recovery baseline and the rule-based relay strategy."""
    baseline = run_simulation(config, _NoRecovery())
    recovery = run_simulation(config, GreedyRelayPolicy(config.policy_search_grid_km))
    return {"no_recovery": baseline, "rule_based_uav_relay": recovery}


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


class _NoRecovery:
    name = "no_recovery"

    def plan(self, network: Network) -> PolicyPlan:
        return PolicyPlan(name=self.name, deploy_drone=False, destination=None)
