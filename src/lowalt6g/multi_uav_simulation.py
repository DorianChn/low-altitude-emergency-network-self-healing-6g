"""Matched-trace dynamic execution for Phase 10's F/G fleet policies."""

from __future__ import annotations

from dataclasses import replace
import math
import statistics
import time
from typing import Any

from .dynamic_config import DynamicEventSpec, DynamicExperimentConfig
from .dynamic_simulation import (
    DynamicRun,
    _SafeStaticGridController,
    _apply_event,
    _run_one,
)
from .dynamic_world import DynamicWorldTrace, apply_world_state, build_world_trace
from .engine import distance_km
from .multi_uav import (
    FleetSnapshot,
    MultiUAVOptions,
    UAVState,
    advance_fleet,
    apply_decision,
    create_fleet,
    evaluate_fleet,
    plan_fleet,
    update_uav_link_and_task_state,
)
from .scenario import build_network


def run_single_bprime(
    config: DynamicExperimentConfig,
    seed: int,
    trace: DynamicWorldTrace,
) -> DynamicRun:
    """Run the existing single-UAV B′ controller without changing its behavior."""

    network_config = replace(config.base, seed=seed)
    network = build_network(network_config)
    network.drone.battery_wh = config.initial_battery_wh
    network.drone_backhaul_capacity_mbps = config.initial_backhaul_capacity_mbps
    return _run_one(
        config,
        seed,
        trace,
        _SafeStaticGridController(config),
    )


def run_fleet_policy(
    config: DynamicExperimentConfig,
    seed: int,
    trace: DynamicWorldTrace,
    *,
    fleet_size: int,
    strategy_id: str,
    options: MultiUAVOptions,
) -> dict[str, Any]:
    """Run F or G against a caller-supplied, shared exogenous world trace."""

    if strategy_id not in {"F_independent_greedy", "G_centralized_coordination"}:
        raise ValueError(f"unsupported fleet strategy {strategy_id}")
    if trace.seed != seed:
        raise ValueError("world trace seed does not match the run seed")
    options.validate(config.time_step_s)
    seeded_config = replace(config.base, seed=seed)
    network = build_network(seeded_config)
    network.drone.battery_wh = config.initial_battery_wh
    network.drone_backhaul_capacity_mbps = config.initial_backhaul_capacity_mbps
    base_users = {user.id: user for user in network.users}
    uavs = create_fleet(
        network,
        config,
        fleet_size,
        minimum_separation_km=options.min_separation_km,
    )
    traffic_multiplier: float | dict[str, float] = 1.0
    tick_count = seeded_config.duration_s // seeded_config.time_step_s + 1
    rescue_total = sum(user.group == "rescue" for user in network.users)
    normal_total = sum(user.group == "normal" for user in network.users)
    rescue_connected_samples = 0
    normal_connected_samples = 0
    all_connected_samples = 0
    rescue_sample_count = 0
    normal_sample_count = 0
    all_sample_count = 0
    relay_rescue_user_seconds = 0.0
    relay_rescue_user_seconds_by_uav = {unit.id: 0.0 for unit in uavs}
    ground_only_rescue_user_seconds = 0.0
    latencies: list[float] = []
    recovery_time_s: int | None = None
    sustained_recovery_time_s: int | None = None
    sustained_start_s: int | None = None
    sustained_ticks = 0
    sustained_required_ticks = math.ceil(30 / seeded_config.time_step_s) + 1
    total_energy_wh = 0.0
    minimum_battery_by_uav = {unit.id: unit.battery_wh for unit in uavs}
    event_log: list[dict[str, object]] = []
    state_timeline: list[dict[str, object]] = []
    previous_snapshot: FleetSnapshot | None = None
    last_plan_time_s: int | None = None
    previous_target_by_uav: dict[str, tuple[float, float] | None] = {
        unit.id: None for unit in uavs
    }
    decision_compute_ms: list[float] = []
    decision_count = 0
    infeasible_decision_reasons: dict[str, int] = {}
    timeout_count = 0
    candidate_evaluation_count = 0
    collision_rejection_count = 0
    capacity_blocked_user_ticks = 0
    duplicate_relay_opportunity_user_ticks = 0
    duplicate_user_service_count = 0
    speed_violation_count = 0
    boundary_violation_count = 0
    separation_violation_count = 0
    resource_capacity_violation_count = 0
    safety_action_count = 0
    task_assignment_count = 0
    movement_distance_km = 0.0

    for tick in range(tick_count):
        time_s = tick * seeded_config.time_step_s
        if tick and previous_snapshot is not None:
            movement_records = advance_fleet(
                network,
                uavs,
                config,
                options,
                previous_snapshot,
                time_s,
            )
            for record in movement_records:
                total_energy_wh += float(record["energy_consumed_wh"])
                movement_distance_km += float(record["moved_km"])
                unit = next(item for item in uavs if item.id == record["uav_id"])
                minimum_battery_by_uav[unit.id] = min(
                    minimum_battery_by_uav[unit.id], unit.battery_wh
                )
                if record.get("safety_action"):
                    safety_action_count += 1
                if float(record["moved_km"]) > network.drone_spec.speed_km_per_s * seeded_config.time_step_s + 1e-9:
                    speed_violation_count += 1
                if not _within_bounds(network, unit):
                    boundary_violation_count += 1
                event_log.append(
                    {
                        "time_s": time_s,
                        "event_type": "uav_action_execution",
                        **record,
                    }
                )
            separation_violation_count += _count_active_separation_violations(
                uavs, options.min_separation_km
            )

        current_events = trace.events_by_time.get(time_s, ())
        for event in current_events:
            traffic_multiplier = _apply_event(network, event, traffic_multiplier)
            for unit in uavs:
                unit.backhaul_link_available = network.drone_backhaul_available
                unit.backhaul_capacity_mbps = network.drone_backhaul_capacity_mbps
            event_log.append(
                {
                    "time_s": time_s,
                    "event_type": "environment_event_applied",
                    "environment_event_type": event.event_type,
                    "target_id": event.target_id,
                    "value": event.value,
                    "event_occurrence_time_s": time_s,
                }
            )

        apply_world_state(network, base_users, trace, tick, traffic_multiplier)
        observed_snapshot = evaluate_fleet(network, uavs)
        rescue_before = _connected_ids(observed_snapshot, group="rescue")
        critical_event = any(
            event.event_type
            in {
                "station_failure",
                "station_recovery",
                "backhaul_failure",
                "backhaul_recovery",
                "backhaul_capacity_change",
                "traffic_change",
                "user_mobility_change",
            }
            for event in current_events
        )
        should_plan = (
            tick == 0
            or (last_plan_time_s is not None and time_s - last_plan_time_s >= options.replan_interval_s)
            or critical_event
        )
        if should_plan:
            decision = plan_fleet(strategy_id, network, uavs, config, options)
            decision_count += 1
            decision_compute_ms.append(decision.compute_ms)
            candidate_evaluation_count += decision.candidate_evaluations
            collision_rejection_count += decision.collision_rejections
            timeout_count += int(decision.timed_out)
            if decision.infeasible_reason:
                infeasible_decision_reasons[decision.infeasible_reason] = (
                    infeasible_decision_reasons.get(decision.infeasible_reason, 0) + 1
                )
            assignments = apply_decision(uavs, decision)
            task_assignment_count += sum(
                bool(item["target_changed"]) for item in assignments
            )
            after_decision = evaluate_fleet(network, uavs)
            rescue_after = _connected_ids(after_decision, group="rescue")
            event_log.append(
                {
                    "time_s": time_s,
                    "event_type": "fleet_decision",
                    "strategy_id": strategy_id,
                    "trigger": "initial" if tick == 0 else "observable_event" if critical_event else "periodic",
                    "reason": decision.reason,
                    "infeasible_reason": decision.infeasible_reason,
                    "objective": list(decision.objective) if decision.objective is not None else None,
                    "decision_compute_ms": round(decision.compute_ms, 6),
                    "candidate_evaluations": decision.candidate_evaluations,
                    "collision_rejections": decision.collision_rejections,
                    "timed_out": decision.timed_out,
                    "rescue_connected_before_ids": rescue_before,
                    "rescue_connected_after_ids": rescue_after,
                    "uav_assignments": assignments,
                    "environment_events_at_observation": [
                        {
                            "event_type": event.event_type,
                            "target_id": event.target_id,
                            "value": event.value,
                        }
                        for event in current_events
                    ],
                }
            )
            last_plan_time_s = time_s
            snapshot = after_decision
        else:
            snapshot = observed_snapshot

        update_uav_link_and_task_state(network, uavs, snapshot, time_s)
        outcome_by_id = snapshot.outcome_map()
        connected_rescue = sum(
            outcome.connected for outcome in snapshot.outcomes if outcome.group == "rescue"
        )
        connected_normal = sum(
            outcome.connected for outcome in snapshot.outcomes if outcome.group == "normal"
        )
        connected_total = sum(outcome.connected for outcome in snapshot.outcomes)
        rescue_connected_samples += connected_rescue
        normal_connected_samples += connected_normal
        all_connected_samples += connected_total
        rescue_sample_count += rescue_total
        normal_sample_count += normal_total
        all_sample_count += len(network.users)
        capacity_blocked_user_ticks += len(snapshot.capacity_blocked_user_ids)
        duplicate_relay_opportunity_user_ticks += sum(
            max(0, count - 1)
            for count in snapshot.relay_candidate_count_by_user.values()
        )
        duplicate_user_service_count += max(0, len(snapshot.outcomes) - len(outcome_by_id))
        resource_capacity_violation_count += sum(
            used > snapshot.resource_capacity_mbps.get(resource, 0.0) + 1e-9
            for resource, used in snapshot.resource_used_mbps.items()
        )
        for value in snapshot.resource_utilization.values():
            if value > 1.0 + 1e-9:
                resource_capacity_violation_count += 1
        for outcome in snapshot.outcomes:
            if outcome.connected and outcome.latency_ms is not None:
                latencies.append(float(outcome.latency_ms))
            if outcome.group == "rescue" and outcome.connected and outcome.serving_uav_id:
                if time_s < seeded_config.duration_s:
                    relay_rescue_user_seconds += seeded_config.time_step_s
                    relay_rescue_user_seconds_by_uav[outcome.serving_uav_id] += seeded_config.time_step_s
        ground_snapshot = evaluate_fleet(network, uavs, active_ids=set())
        ground_rescue = sum(
            outcome.connected for outcome in ground_snapshot.outcomes if outcome.group == "rescue"
        )
        ground_only_rescue_user_seconds += (
            ground_rescue * seeded_config.time_step_s
            if time_s < seeded_config.duration_s
            else 0.0
        )
        if recovery_time_s is None and connected_rescue == rescue_total:
            recovery_time_s = time_s
            event_log.append(
                {
                    "time_s": time_s,
                    "event_type": "first_full_rescue_recovery",
                    "rescue_connected_ids": _connected_ids(snapshot, group="rescue"),
                    "uav_relayed_rescue_ids": sorted(
                        outcome.user_id
                        for outcome in snapshot.outcomes
                        if outcome.group == "rescue"
                        and outcome.connected
                        and outcome.serving_uav_id is not None
                    ),
                }
            )
        if connected_rescue == rescue_total:
            if sustained_ticks == 0:
                sustained_start_s = time_s
            sustained_ticks += 1
            if sustained_recovery_time_s is None and sustained_ticks >= sustained_required_ticks:
                sustained_recovery_time_s = sustained_start_s
        else:
            sustained_ticks = 0
            sustained_start_s = None

        state_timeline.append(
            {
                "time_s": time_s,
                "healthy_station_ids": sorted(
                    station.id for station in network.stations if station.healthy
                ),
                "backhaul_available": network.drone_backhaul_available,
                "rescue_connected_ids": _connected_ids(snapshot, group="rescue"),
                "normal_connected_count": connected_normal,
                "capacity_blocked_user_ids": list(snapshot.capacity_blocked_user_ids),
                "resource_utilization": {
                    key: round(value, 8)
                    for key, value in sorted(snapshot.resource_utilization.items())
                },
                "uavs": [
                    {
                        "uav_id": unit.id,
                        "position_km": [round(unit.position.x_km, 6), round(unit.position.y_km, 6)],
                        "target_position_km": (
                            [round(unit.target_position.x_km, 6), round(unit.target_position.y_km, 6)]
                            if unit.target_position is not None
                            else None
                        ),
                        "battery_wh": round(unit.battery_wh, 6),
                        "active": unit.active,
                        "task_status": unit.task_status,
                        "served_user_ids": sorted(unit.served_user_ids),
                    }
                    for unit in uavs
                ],
            }
        )
        previous_snapshot = snapshot

    recovery_or_censor = recovery_time_s if recovery_time_s is not None else seeded_config.duration_s
    relay_hours = relay_rescue_user_seconds / 3600.0
    ordered_latency = sorted(latencies)
    metrics: dict[str, Any] = {
        "rescue_user_service_success_rate": rescue_connected_samples / rescue_sample_count,
        "normal_user_connection_success_rate": normal_connected_samples / normal_sample_count,
        "user_connection_success_rate": all_connected_samples / all_sample_count,
        "first_full_recovery_success": int(recovery_time_s is not None),
        "first_full_recovery_time_s": recovery_time_s,
        "first_full_recovery_or_censor_time_s": recovery_or_censor,
        "sustained_30s_recovery_success": int(sustained_recovery_time_s is not None),
        "sustained_30s_recovery_time_s": sustained_recovery_time_s,
        "uav_energy_total_wh": total_energy_wh,
        "uav_energy_by_id_wh": {
            unit.id: unit.energy_consumed_wh for unit in uavs
        },
        "uav_rescue_user_seconds_by_id": relay_rescue_user_seconds_by_uav,
        "uav_rescue_user_seconds": relay_rescue_user_seconds,
        "ground_only_rescue_user_seconds": ground_only_rescue_user_seconds,
        "energy_wh_per_uav_rescue_user_hour": total_energy_wh / relay_hours if relay_hours > 0 else None,
        "average_latency_ms": statistics.fmean(latencies) if latencies else None,
        "p95_latency_ms": _nearest_rank(ordered_latency, 0.95),
        "latency_sample_count": len(latencies),
        "task_assignment_count": task_assignment_count,
        "target_switch_count": sum(unit.target_switch_count for unit in uavs),
        "duplicate_relay_opportunity_user_ticks": duplicate_relay_opportunity_user_ticks,
        "capacity_blocked_user_ticks": capacity_blocked_user_ticks,
        "movement_distance_total_km": movement_distance_km,
        "coordination_decision_count": decision_count,
        "coordination_compute_total_ms": sum(decision_compute_ms),
        "coordination_compute_mean_ms": statistics.fmean(decision_compute_ms) if decision_compute_ms else 0.0,
        "coordination_compute_p95_ms": _nearest_rank(sorted(decision_compute_ms), 0.95),
        "candidate_evaluation_count": candidate_evaluation_count,
        "collision_rejection_count": collision_rejection_count,
        "decision_timeout_count": timeout_count,
        "infeasible_decision_count": sum(infeasible_decision_reasons.values()),
        "infeasible_decision_reasons": dict(sorted(infeasible_decision_reasons.items())),
        "safety_action_count": safety_action_count,
        "speed_violation_count": speed_violation_count,
        "boundary_violation_count": boundary_violation_count,
        "separation_violation_count": separation_violation_count,
        "resource_capacity_violation_count": resource_capacity_violation_count,
        "duplicate_user_service_count": duplicate_user_service_count,
        "uav_battery_remaining_wh_by_id": {unit.id: unit.battery_wh for unit in uavs},
        "uav_battery_minimum_wh_by_id": minimum_battery_by_uav,
        "uav_fleet_size": len(uavs),
        "evaluation_ticks": tick_count,
        "recovery_success_count": int(recovery_time_s is not None),
        "recovery_total_count": 1,
        "sustained_success_count": int(sustained_recovery_time_s is not None),
        "sustained_total_count": 1,
    }
    return {
        "strategy_id": strategy_id,
        "strategy_name": "独立贪心双/三无人机" if strategy_id == "F_independent_greedy" else "集中式协同双/三无人机",
        "fleet_size": len(uavs),
        "world_trace_sha256": trace.trace_sha256,
        "metrics": metrics,
        "latency_samples_ms": latencies,
        "event_log": event_log,
        "state_timeline": state_timeline,
        "uavs": [
            {
                "uav_id": unit.id,
                "initial_position_km": unit.trajectory[0]["position_km"] if unit.trajectory else None,
                "final_position_km": [round(unit.position.x_km, 6), round(unit.position.y_km, 6)],
                "target_position_km": (
                    [round(unit.target_position.x_km, 6), round(unit.target_position.y_km, 6)]
                    if unit.target_position is not None
                    else None
                ),
                "battery_remaining_wh": round(unit.battery_wh, 8),
                "reserve_wh": unit.reserve_wh,
                "active": unit.active,
                "access_link_available": unit.access_link_available,
                "backhaul_link_available": unit.backhaul_link_available,
                "task": unit.task,
                "task_status": unit.task_status,
                "served_user_ids": sorted(unit.served_user_ids),
                "trajectory": unit.trajectory,
                "energy_log": unit.energy_log,
            }
            for unit in uavs
        ],
    }


def _connected_ids(snapshot: FleetSnapshot, *, group: str) -> list[str]:
    return sorted(
        outcome.user_id
        for outcome in snapshot.outcomes
        if outcome.group == group and outcome.connected
    )


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    index = max(0, math.ceil(percentile * len(values)) - 1)
    return round(float(values[index]), 6)


def _within_bounds(network, unit: UAVState) -> bool:
    return (
        0 <= unit.position.x_km <= network.config.city_width_km
        and 0 <= unit.position.y_km <= network.config.city_height_km
    )


def _count_active_separation_violations(
    uavs: list[UAVState], minimum_separation_km: float
) -> int:
    active = [unit for unit in uavs if unit.active]
    count = 0
    for index, first in enumerate(active):
        for second in active[index + 1 :]:
            if distance_km(
                first.position.x_km,
                first.position.y_km,
                second.position.x_km,
                second.position.y_km,
            ) < minimum_separation_km - 1e-9:
                count += 1
    return count

