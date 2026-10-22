"""Matched-trace execution for Phase 11 policies H, I and J.

The execution and metric definitions intentionally follow the frozen Phase 10
fleet runner. This module is isolated so the Phase 10 implementation and its
source hash remain unchanged.
"""

from __future__ import annotations

from dataclasses import replace
import math
import statistics

from .dynamic_config import DynamicExperimentConfig
from .dynamic_simulation import _apply_event
from .dynamic_world import DynamicWorldTrace, apply_world_state
from .engine import distance_km
from .multi_uav import (
    FleetDecision,
    FleetSnapshot,
    MultiUAVOptions,
    UAVState,
    advance_fleet,
    apply_decision,
    create_fleet,
    evaluate_fleet,
    update_uav_link_and_task_state,
)
from .multi_uav_simulation import (
    _connected_ids,
    _count_active_separation_violations,
    _nearest_rank,
    _within_bounds,
)
from .phase11_algorithms import (
    Phase11Plan,
    plan_h_marginal_greedy,
    plan_i_constrained_matching,
    plan_j_budgeted_joint_beam,
)
from .scenario import build_network


POLICY_IDS = {
    "H_marginal_rescue_greedy",
    "I_constrained_user_assignment",
    "J_budgeted_joint_beam",
}


def run_phase11_policy(
    config: DynamicExperimentConfig,
    seed: int,
    trace: DynamicWorldTrace,
    *,
    fleet_size: int,
    strategy_id: str,
    options: MultiUAVOptions,
    assignment_beam_width: int = 64,
    assignment_max_expansions: int = 6000,
    joint_beam_width: int = 16,
) -> dict:
    """Run one of the new policies using the same world trace as F/G."""

    if strategy_id not in POLICY_IDS:
        raise ValueError(f"unsupported Phase 11 strategy: {strategy_id}")
    if trace.seed != seed:
        raise ValueError("world trace seed does not match the run seed")
    options.validate(config.time_step_s)
    seeded_config = replace(config.base, seed=seed)
    network = build_network(seeded_config)
    network.drone.battery_wh = config.initial_battery_wh
    network.drone_backhaul_capacity_mbps = config.initial_backhaul_capacity_mbps
    base_users = {user.id: user for user in network.users}
    uavs = create_fleet(
        network, config, fleet_size,
        minimum_separation_km=options.min_separation_km,
    )
    traffic_multiplier: float | dict[str, float] = 1.0
    tick_count = seeded_config.duration_s // seeded_config.time_step_s + 1
    rescue_total = sum(user.group == "rescue" for user in network.users)
    normal_total = sum(user.group == "normal" for user in network.users)
    rescue_connected_samples = normal_connected_samples = all_connected_samples = 0
    rescue_sample_count = normal_sample_count = all_sample_count = 0
    relay_rescue_user_seconds = 0.0
    relay_rescue_user_seconds_by_uav = {unit.id: 0.0 for unit in uavs}
    uav_service_user_ticks_by_id = {unit.id: 0 for unit in uavs}
    uav_connected_user_ticks_by_id = {unit.id: 0 for unit in uavs}
    uav_relayed_user_ticks_by_id = {unit.id: 0 for unit in uavs}
    ground_only_rescue_user_seconds = 0.0
    latencies: list[float] = []
    recovery_time_s: int | None = None
    sustained_recovery_time_s: int | None = None
    sustained_start_s: int | None = None
    sustained_ticks = 0
    sustained_required_ticks = math.ceil(30 / seeded_config.time_step_s) + 1
    total_energy_wh = 0.0
    minimum_battery_by_uav = {unit.id: unit.battery_wh for unit in uavs}
    event_log: list[dict] = []
    state_timeline: list[dict] = []
    previous_snapshot: FleetSnapshot | None = None
    last_plan_time_s: int | None = None
    decision_compute_ms: list[float] = []
    decision_count = 0
    infeasible_decision_reasons: dict[str, int] = {}
    timeout_count = candidate_evaluation_count = search_node_count = 0
    collision_rejection_count = capacity_blocked_user_ticks = 0
    duplicate_relay_opportunity_user_ticks = duplicate_user_service_count = 0
    speed_violation_count = boundary_violation_count = 0
    separation_violation_count = resource_capacity_violation_count = 0
    safety_action_count = task_assignment_count = 0
    uav_activation_count = uav_task_allocation_decision_count = 0
    movement_distance_km = movement_without_assignment_km = 0.0
    station_utilization_samples: list[float] = []
    uav_utilization_samples: list[float] = []

    for tick in range(tick_count):
        time_s = tick * seeded_config.time_step_s
        if tick and previous_snapshot is not None:
            movement_records = advance_fleet(
                network, uavs, config, options, previous_snapshot, time_s
            )
            prior_serving = {
                unit.id: any(
                    outcome.connected and outcome.serving_uav_id == unit.id
                    for outcome in previous_snapshot.outcomes
                )
                for unit in uavs
            }
            for record in movement_records:
                moved = float(record["moved_km"])
                total_energy_wh += float(record["energy_consumed_wh"])
                movement_distance_km += moved
                if not prior_serving.get(str(record["uav_id"]), False):
                    movement_without_assignment_km += moved
                unit = next(item for item in uavs if item.id == record["uav_id"])
                minimum_battery_by_uav[unit.id] = min(
                    minimum_battery_by_uav[unit.id], unit.battery_wh
                )
                if record.get("safety_action"):
                    safety_action_count += 1
                if moved > network.drone_spec.speed_km_per_s * seeded_config.time_step_s + 1e-9:
                    speed_violation_count += 1
                if not _within_bounds(network, unit):
                    boundary_violation_count += 1
                event_log.append({"time_s": time_s, "event_type": "uav_action_execution", **record})
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
            event.event_type in {
                "station_failure", "station_recovery", "backhaul_failure",
                "backhaul_recovery", "backhaul_capacity_change", "traffic_change",
                "user_mobility_change",
            }
            for event in current_events
        )
        should_plan = (
            strategy_id == "I_constrained_user_assignment"
            or tick == 0
            or (
                last_plan_time_s is not None
                and time_s - last_plan_time_s >= options.replan_interval_s
            )
            or critical_event
        )
        if should_plan:
            plan = _plan(
                strategy_id, network, uavs, config, options,
                assignment_beam_width=assignment_beam_width,
                assignment_max_expansions=assignment_max_expansions,
                joint_beam_width=joint_beam_width,
            )
            decision = plan.decision
            decision_count += 1
            decision_compute_ms.append(decision.compute_ms)
            candidate_evaluation_count += decision.candidate_evaluations
            search_node_count += plan.search_nodes
            collision_rejection_count += decision.collision_rejections
            timeout_count += int(decision.timed_out)
            if decision.infeasible_reason:
                infeasible_decision_reasons[decision.infeasible_reason] = (
                    infeasible_decision_reasons.get(decision.infeasible_reason, 0) + 1
                )
            active_before_decision = {unit.id: unit.active for unit in uavs}
            assignments = apply_decision(uavs, decision)
            task_assignment_count += sum(bool(item["target_changed"]) for item in assignments)
            uav_activation_count += sum(
                not active_before_decision[unit.id] and unit.active for unit in uavs
            )
            snapshot = plan.snapshot or evaluate_fleet(network, uavs)
            uav_task_allocation_decision_count += len({
                outcome.serving_uav_id for outcome in snapshot.outcomes
                if outcome.connected and outcome.serving_uav_id is not None
            })
            rescue_after = _connected_ids(snapshot, group="rescue")
            event_log.append(
                {
                    "time_s": time_s,
                    "event_type": "fleet_decision",
                    "strategy_id": strategy_id,
                    "trigger": (
                        "resource_assignment_update" if strategy_id == "I_constrained_user_assignment"
                        else "initial" if tick == 0
                        else "observable_event" if critical_event else "periodic"
                    ),
                    "reason": decision.reason,
                    "infeasible_reason": decision.infeasible_reason,
                    "objective": list(decision.objective) if decision.objective is not None else None,
                    "decision_compute_ms": round(decision.compute_ms, 6),
                    "candidate_evaluations": decision.candidate_evaluations,
                    "search_nodes": plan.search_nodes,
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
            max(0, count - 1) for count in snapshot.relay_candidate_count_by_user.values()
        )
        duplicate_user_service_count += max(0, len(snapshot.outcomes) - len(outcome_by_id))
        resource_capacity_violation_count += sum(
            used > snapshot.resource_capacity_mbps.get(resource, 0.0) + 1e-9
            for resource, used in snapshot.resource_used_mbps.items()
        )
        resource_capacity_violation_count += sum(
            value > 1.0 + 1e-9 for value in snapshot.resource_utilization.values()
        )
        station_util = [
            value for key, value in snapshot.resource_utilization.items()
            if key.startswith("station:")
        ]
        uav_util = [
            value for key, value in snapshot.resource_utilization.items()
            if key.startswith("uav:")
        ]
        if station_util:
            station_utilization_samples.append(statistics.fmean(station_util))
        if uav_util:
            uav_utilization_samples.append(statistics.fmean(uav_util))
        for outcome in snapshot.outcomes:
            if outcome.connected and outcome.latency_ms is not None:
                latencies.append(float(outcome.latency_ms))
            if outcome.connected and outcome.serving_uav_id:
                uav_connected_user_ticks_by_id[outcome.serving_uav_id] += 1
                uav_relayed_user_ticks_by_id[outcome.serving_uav_id] += 1
            if outcome.group == "rescue" and outcome.connected and outcome.serving_uav_id:
                uav_service_user_ticks_by_id[outcome.serving_uav_id] += 1
                if time_s < seeded_config.duration_s:
                    relay_rescue_user_seconds += seeded_config.time_step_s
                    relay_rescue_user_seconds_by_uav[outcome.serving_uav_id] += seeded_config.time_step_s
        ground_snapshot = evaluate_fleet(network, uavs, active_ids=set())
        ground_rescue = sum(
            outcome.connected for outcome in ground_snapshot.outcomes
            if outcome.group == "rescue"
        )
        if time_s < seeded_config.duration_s:
            ground_only_rescue_user_seconds += ground_rescue * seeded_config.time_step_s

        if recovery_time_s is None and connected_rescue == rescue_total:
            recovery_time_s = time_s
            event_log.append(
                {
                    "time_s": time_s,
                    "event_type": "first_full_rescue_recovery",
                    "rescue_connected_ids": _connected_ids(snapshot, group="rescue"),
                    "uav_relayed_rescue_ids": sorted(
                        outcome.user_id for outcome in snapshot.outcomes
                        if outcome.group == "rescue" and outcome.connected
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
                            if unit.target_position is not None else None
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

    recovery_or_censor = (
        recovery_time_s if recovery_time_s is not None else seeded_config.duration_s
    )
    relay_hours = relay_rescue_user_seconds / 3600.0
    ordered_latency = sorted(latencies)
    metrics = {
        "rescue_user_service_success_rate": rescue_connected_samples / rescue_sample_count,
        "normal_user_connection_success_rate": normal_connected_samples / normal_sample_count,
        "user_connection_success_rate": all_connected_samples / all_sample_count,
        "first_full_recovery_success": int(recovery_time_s is not None),
        "first_full_recovery_time_s": recovery_time_s,
        "first_full_recovery_or_censor_time_s": recovery_or_censor,
        "sustained_30s_recovery_success": int(sustained_recovery_time_s is not None),
        "sustained_30s_recovery_time_s": sustained_recovery_time_s,
        "uav_energy_total_wh": total_energy_wh,
        "uav_energy_by_id_wh": {unit.id: unit.energy_consumed_wh for unit in uavs},
        "uav_rescue_user_seconds_by_id": relay_rescue_user_seconds_by_uav,
        "uav_rescue_user_seconds": relay_rescue_user_seconds,
        "ground_only_rescue_user_seconds": ground_only_rescue_user_seconds,
        "energy_wh_per_uav_rescue_user_hour": (
            total_energy_wh / relay_hours if relay_hours > 0 else None
        ),
        "average_latency_ms": statistics.fmean(latencies) if latencies else None,
        "p95_latency_ms": _nearest_rank(ordered_latency, 0.95),
        "latency_sample_count": len(latencies),
        "task_assignment_count": task_assignment_count,
        "uav_activation_count": uav_activation_count,
        "uav_task_allocation_decision_count": uav_task_allocation_decision_count,
        "target_switch_count": sum(unit.target_switch_count for unit in uavs),
        "uav_service_user_ticks_by_id": uav_service_user_ticks_by_id,
        "uav_connected_user_ticks_by_id": uav_connected_user_ticks_by_id,
        "uav_relayed_user_ticks_by_id": uav_relayed_user_ticks_by_id,
        "uav_relayed_user_ticks_total": sum(uav_relayed_user_ticks_by_id.values()),
        "duplicate_relay_opportunity_user_ticks": duplicate_relay_opportunity_user_ticks,
        "capacity_blocked_user_ticks": capacity_blocked_user_ticks,
        "movement_distance_total_km": movement_distance_km,
        "movement_without_assignment_km": movement_without_assignment_km,
        "base_station_mean_utilization": (
            statistics.fmean(station_utilization_samples) if station_utilization_samples else 0.0
        ),
        "uav_mean_utilization": (
            statistics.fmean(uav_utilization_samples) if uav_utilization_samples else 0.0
        ),
        "coordination_decision_count": decision_count,
        "coordination_compute_total_ms": sum(decision_compute_ms),
        "coordination_compute_mean_ms": (
            statistics.fmean(decision_compute_ms) if decision_compute_ms else 0.0
        ),
        "coordination_compute_p95_ms": _nearest_rank(sorted(decision_compute_ms), 0.95),
        "candidate_evaluation_count": candidate_evaluation_count,
        "search_node_count": search_node_count,
        "collision_rejection_count": collision_rejection_count,
        "decision_timeout_count": timeout_count,
        "compute_budget_overrun_count": sum(
            value > options.decision_timeout_ms for value in decision_compute_ms
        ),
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
        "user_count": len(network.users),
        "rescue_user_count": rescue_total,
        "evaluation_ticks": tick_count,
        "recovery_success_count": int(recovery_time_s is not None),
        "recovery_total_count": 1,
        "sustained_success_count": int(sustained_recovery_time_s is not None),
        "sustained_total_count": 1,
    }
    return {
        "strategy_id": strategy_id,
        "strategy_name": {
            "H_marginal_rescue_greedy": "边际救援覆盖顺序贪心",
            "I_constrained_user_assignment": "固定位置约束感知用户匹配",
            "J_budgeted_joint_beam": "受限预算联合束搜索",
        }[strategy_id],
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
                    if unit.target_position is not None else None
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


def _plan(
    strategy_id: str,
    network,
    uavs: list[UAVState],
    config: DynamicExperimentConfig,
    options: MultiUAVOptions,
    *,
    assignment_beam_width: int,
    assignment_max_expansions: int,
    joint_beam_width: int,
) -> Phase11Plan:
    if strategy_id == "H_marginal_rescue_greedy":
        return plan_h_marginal_greedy(network, uavs, config, options)
    if strategy_id == "I_constrained_user_assignment":
        return plan_i_constrained_matching(
            network, uavs, config, options,
            beam_width=assignment_beam_width,
            max_expansions=assignment_max_expansions,
        )
    return plan_j_budgeted_joint_beam(
        network, uavs, config, options, beam_width=joint_beam_width
    )
