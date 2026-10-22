"""Timestamped dynamic simulation harness and matched-policy execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import statistics
import time

from .config import SimulationConfig
from .dynamic_config import DynamicEventSpec, DynamicExperimentConfig
from .dynamic_world import DynamicWorldTrace, apply_world_state, build_world_trace
from .energy_budget import return_energy_wh, sortie_energy_wh
from .engine import distance_km, evaluate_network
from .models import Network, NetworkSnapshot, Position
from .optimizer import (
    ControlDecision,
    NetworkDiagnosis,
    RescuePriorityOptimizer,
    RollingHorizonOptimizer,
    diagnose_network,
)
from .policies import GreedyRelayPolicy
from .scenario import build_network


@dataclass(frozen=True)
class DynamicRun:
    strategy_id: str
    strategy_name: str
    metrics: dict[str, int | float | str | None]
    event_log: tuple[dict[str, object], ...]
    latency_samples_ms: tuple[float, ...]
    state_snapshots: tuple[dict[str, object], ...] = ()

    def to_dict(self, *, include_latency_samples: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "metrics": self.metrics,
            "event_log": list(self.event_log),
        }
        if include_latency_samples:
            result["latency_samples_ms"] = list(self.latency_samples_ms)
        return result

    def to_replay_dict(self) -> dict[str, object]:
        """Serialize detailed per-tick state for the dedicated replay artifact."""
        replay_events = [
            {key: value for key, value in event.items() if key != "diagnosis"}
            for event in self.event_log
        ]
        return {
            **self.to_dict(),
            "event_log": replay_events,
            "state_snapshots": list(self.state_snapshots),
        }


@dataclass(frozen=True)
class SeedExperiment:
    seed: int
    trace_sha256: str
    environment_events: tuple[dict[str, object], ...]
    strategies: dict[str, DynamicRun]

    def to_dict(self, *, include_latency_samples: bool = False) -> dict[str, object]:
        return {
            "seed": self.seed,
            "world_trace_sha256": self.trace_sha256,
            "environment_events": list(self.environment_events),
            "strategies": {
                key: run.to_dict(include_latency_samples=include_latency_samples)
                for key, run in self.strategies.items()
            },
        }


class _Controller:
    strategy_id: str
    strategy_name: str

    def observe(
        self,
        time_s: int,
        network: Network,
        snapshot: NetworkSnapshot,
        diagnosis: NetworkDiagnosis,
        battery_wh: float,
    ) -> ControlDecision:
        raise NotImplementedError


class _NoRecoveryController(_Controller):
    strategy_id = "A_no_recovery"
    strategy_name = "No recovery"

    def observe(self, time_s, network, snapshot, diagnosis, battery_wh):
        return ControlDecision(
            deploy=False,
            heading_x=0.0,
            heading_y=0.0,
            destination=None,
            reason="baseline_no_deployment",
            trigger="baseline",
            decision_made=False,
            objective_score=None,
            infeasible_reasons=(),
            diagnosis=diagnosis,
        )


class _StaticGridController(_Controller):
    """Phase 1 strategy: one full-grid target search, then no replanning."""

    strategy_id = "B_phase1_static_grid"
    strategy_name = "Phase 1 static grid rule"

    def __init__(self, config: DynamicExperimentConfig) -> None:
        self.config = config
        self.initialized = False
        self.decision = None

    def observe(self, time_s, network, snapshot, diagnosis, battery_wh):
        if self.initialized:
            assert self.decision is not None
            return replace(
                self.decision,
                decision_made=False,
                trigger="static_plan_kept",
                decision_time_ms=0.0,
                diagnosis=diagnosis,
            )
        self.initialized = True
        if not any(station.healthy for station in network.stations):
            self.decision = _failed_decision(diagnosis, "no_healthy_base_station", "initial_static_search")
            return self.decision
        started = time.perf_counter()
        plan = GreedyRelayPolicy(network.config.policy_search_grid_km).plan(network)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        target = plan.destination
        if target is None:
            self.decision = _failed_decision(diagnosis, "grid_search_found_no_target", "initial_static_search")
            return self.decision
        healthy_stations = tuple(station for station in network.stations if station.healthy)
        nearest_station = min(
            healthy_stations,
            key=lambda station: distance_km(target.x_km, target.y_km, station.x_km, station.y_km),
        )
        target_backhaul_distance = distance_km(
            target.x_km,
            target.y_km,
            nearest_station.x_km,
            nearest_station.y_km,
        )
        route_distance = distance_km(
            network.drone.x_km,
            network.drone.y_km,
            target.x_km,
            target.y_km,
        )
        estimated_energy = (
            route_distance + target_backhaul_distance
        ) * self.config.movement_wh_per_km + self.config.reserve_wh
        if target_backhaul_distance > network.drone_spec.backhaul_radius_km:
            self.decision = _failed_decision(diagnosis, "target_has_no_backhaul", "initial_static_search")
        elif estimated_energy > battery_wh:
            self.decision = _failed_decision(
                diagnosis,
                "battery_budget_cannot_reach_target_and_keep_return_reserve",
                "initial_static_search",
            )
        else:
            self.decision = ControlDecision(
                deploy=True,
                heading_x=0.0,
                heading_y=0.0,
                destination=target,
                reason="phase1_grid_target_selected",
                trigger="one_time_static_grid_search",
                decision_made=True,
                objective_score=None,
                infeasible_reasons=(),
                diagnosis=diagnosis,
                decision_time_ms=elapsed_ms,
            )
        return self.decision


class _SafeStaticGridController(_Controller):
    """Historical grid target with the shared Phase 5 sortie-energy envelope."""

    strategy_id = "Bprime_static_grid_shared_safety"
    strategy_name = "Static grid with shared sortie constraints"

    def __init__(self, config: DynamicExperimentConfig) -> None:
        self.config = config
        self.initialized = False
        self.decision: ControlDecision | None = None
        self.planned_sortie_energy_wh: float | None = None
        self.planning_battery_wh: float | None = None

    def observe(self, time_s, network, snapshot, diagnosis, battery_wh):
        if self.initialized:
            assert self.decision is not None
            return replace(
                self.decision,
                decision_made=False,
                trigger="static_plan_kept",
                decision_time_ms=0.0,
                diagnosis=diagnosis,
            )
        self.initialized = True
        if not any(station.healthy for station in network.stations):
            self.decision = _failed_decision(diagnosis, "no_healthy_base_station", "initial_static_search")
            return self.decision
        started = time.perf_counter()
        target = GreedyRelayPolicy(network.config.policy_search_grid_km).plan(network).destination
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if target is None:
            self.decision = _failed_decision(diagnosis, "grid_search_found_no_target", "initial_static_search")
            return self.decision
        has_backhaul = any(
            distance_km(target.x_km, target.y_km, station.x_km, station.y_km)
            <= network.drone_spec.backhaul_radius_km + 1e-9
            for station in network.stations
            if station.healthy
        )
        energy = sortie_energy_wh(self.config, network, target)
        self.planned_sortie_energy_wh = energy
        self.planning_battery_wh = battery_wh
        if not has_backhaul:
            self.decision = _failed_decision(diagnosis, "target_has_no_backhaul", "initial_static_search")
        elif energy is None or battery_wh - energy < self.config.reserve_wh - 1e-9:
            self.decision = _failed_decision(
                diagnosis,
                "shared_sortie_energy_budget_would_violate_reserve",
                "initial_static_search",
            )
        else:
            self.decision = ControlDecision(
                deploy=True,
                heading_x=0.0,
                heading_y=0.0,
                destination=target,
                reason="static_grid_target_selected_with_shared_safety",
                trigger="one_time_static_grid_search",
                decision_made=True,
                objective_score=None,
                infeasible_reasons=(),
                diagnosis=diagnosis,
                decision_time_ms=elapsed_ms,
            )
        return replace(self.decision, decision_time_ms=elapsed_ms)


class _MPCController(_Controller):
    strategy_id = "C_rolling_horizon_mpc"
    strategy_name = "Rolling horizon optimizer"

    def __init__(self, config: DynamicExperimentConfig) -> None:
        self.optimizer = RollingHorizonOptimizer(config)

    def observe(self, time_s, network, snapshot, diagnosis, battery_wh):
        return self.optimizer.observe(time_s, network, snapshot, diagnosis, battery_wh)


class _RescuePriorityController(_Controller):
    strategy_id = "D_lexicographic_rescue_priority"
    strategy_name = "Lexicographic rescue-priority MPC"

    def __init__(self, config: DynamicExperimentConfig) -> None:
        self.optimizer = RescuePriorityOptimizer(config)

    def observe(self, time_s, network, snapshot, diagnosis, battery_wh):
        return self.optimizer.observe(time_s, network, snapshot, diagnosis, battery_wh)


def run_seed_experiment(
    config: DynamicExperimentConfig,
    seed: int,
    trace: DynamicWorldTrace | None = None,
    *,
    include_d: bool = False,
    include_bprime: bool = False,
    include_e: bool = False,
    e_cooldown_s: int = 20,
) -> SeedExperiment:
    """Run selected policies against identical exogenous events and mobility."""
    trace = trace or build_world_trace(config, seed)
    if trace.seed != seed:
        raise ValueError("world trace seed does not match the requested experiment seed")
    controllers: tuple[_Controller, ...] = (
        _NoRecoveryController(),
        _StaticGridController(config),
    ) + ((_SafeStaticGridController(config),) if include_bprime else ()) + (
        _MPCController(config),
    ) + ((_RescuePriorityController(config),) if include_d else ())
    if include_e:
        from .phase9_strategy_e import EventDrivenController

        controllers += (EventDrivenController(config, cooldown_s=e_cooldown_s),)
    runs = {
        controller.strategy_id: _run_one(config, seed, trace, controller)
        for controller in controllers
    }
    return SeedExperiment(seed, trace.trace_sha256, trace.environment_event_log, runs)


def build_seed_replay_payload(config: DynamicExperimentConfig, seed: int) -> dict[str, object]:
    """Run all policies against one shared trace and capture every network tick."""
    trace = build_world_trace(config, seed)
    seeded_config = replace(config.base, seed=seed)
    controllers = (
        _NoRecoveryController(),
        _StaticGridController(config),
        _MPCController(config),
    )
    runs = {
        controller.strategy_id: _run_one(config, seed, trace, controller, capture_snapshots=True)
        for controller in controllers
    }
    return {
        "schema_version": "1.0",
        "model_scope": "abstract_6g_research_simulation_not_real_network_test",
        "mode": "precomputed_offline_replay",
        "live_stream": False,
        "seed": seed,
        "world_trace_sha256": trace.trace_sha256,
        "time_step_s": seeded_config.time_step_s,
        "duration_s": seeded_config.duration_s,
        "configuration": {
            "base": seeded_config.to_dict(),
            "dynamic": {
                "events": [
                    {
                        "time_s": event.time_s,
                        "event_type": event.event_type,
                        "target_id": event.target_id,
                        "value": event.value,
                    }
                    for event in config.events
                ],
                "mobility_axis_max_km_per_tick": config.mobility_axis_max_km_per_tick,
                "battery_capacity_wh": config.battery_capacity_wh,
                "initial_battery_wh": config.initial_battery_wh,
                "reserve_wh": config.reserve_wh,
                "movement_wh_per_km": config.movement_wh_per_km,
                "hover_power_w": config.hover_power_w,
                "relay_power_w": config.relay_power_w,
                "decision_interval_s": config.decision_interval_s,
                "prediction_horizon_steps": config.prediction_horizon_steps,
                "beam_width": config.beam_width,
                "congestion_threshold": config.congestion_threshold,
                "rescue_service_weight": config.rescue_service_weight,
                "connection_weight": config.connection_weight,
                "recovery_bonus": config.recovery_bonus,
                "latency_penalty_weight": config.latency_penalty_weight,
                "energy_penalty_weight": config.energy_penalty_weight,
                "rescue_progress_weight": config.rescue_progress_weight,
            },
        },
        "environment_events": list(trace.environment_event_log),
        "strategies": {key: run.to_replay_dict() for key, run in runs.items()},
    }


def _run_one(
    config: DynamicExperimentConfig,
    seed: int,
    trace: DynamicWorldTrace,
    controller: _Controller,
    *,
    capture_snapshots: bool = False,
) -> DynamicRun:
    seeded_config = replace(config.base, seed=seed)
    network = build_network(seeded_config)
    base_users = {user.id: user for user in network.users}
    network.drone.battery_wh = config.initial_battery_wh
    network.drone_backhaul_capacity_mbps = config.initial_backhaul_capacity_mbps
    events_at_time = trace.events_by_time
    dynamic_event_log: list[dict[str, object]] = []
    state_snapshots: list[dict[str, object]] = []
    decision_times_ms: list[float] = []
    controller_observe_total_ms = 0.0
    latency_samples_ms: list[float] = []
    reason_counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    covered_samples = 0
    connected_samples = 0
    rescue_connected_samples = 0
    ground_rescue_connected_samples = 0
    rescue_total = sum(user.group == "rescue" for user in network.users)
    total_users = len(network.users)
    recovery_time_s: int | None = None
    ground_only_recovery_time_s: int | None = None
    drone_contributed_recovery_time_s: int | None = None
    recovery_cause: str | None = None
    sustained_recovery_time_s: int | None = None
    sustained_recovery_start_s: int | None = None
    sustained_recovery_ticks = 0
    sustained_recovery_required_ticks = math.ceil(30 / seeded_config.time_step_s) + 1
    latency_sum_ms = 0.0
    final_snapshot: NetworkSnapshot | None = None
    minimum_battery_wh = config.initial_battery_wh
    total_energy_consumed_wh = 0.0
    drone_rescue_user_seconds = 0.0
    drone_extra_rescue_user_seconds = 0.0
    ground_rescue_user_seconds = 0.0
    traffic_multiplier: float | dict[str, float] = 1.0
    last_snapshot: NetworkSnapshot | None = None
    last_decision: ControlDecision | None = None
    tick_count = seeded_config.duration_s // seeded_config.time_step_s + 1
    phase9_enabled = bool(getattr(controller, "phase9_event_driven", False))

    for tick in range(tick_count):
        time_s = tick * seeded_config.time_step_s
        movement_record = None
        if tick and last_decision is not None and last_snapshot is not None:
            movement_record = _advance_drone(
                network,
                last_decision,
                last_snapshot,
                config,
                time_s,
            )
            total_energy_consumed_wh += movement_record["energy_consumed_wh"]
            minimum_battery_wh = min(minimum_battery_wh, float(network.drone.battery_wh or 0.0))
            if movement_record["event"] is not None:
                dynamic_event_log.append(movement_record["event"])
                event_counts[str(movement_record["event"]["event_type"])] = (
                    event_counts.get(str(movement_record["event"]["event_type"]), 0) + 1
                )
            if phase9_enabled:
                pending_action = getattr(controller, "pending_action_start", None)
                if pending_action is not None and pending_action.get("due_time_s") == time_s:
                    dynamic_event_log.append(
                        {
                            "time_s": time_s,
                            "event_type": "phase9_action_execution_started",
                            "decision_time_s": pending_action.get("decision_time_s"),
                            "action_deploy": pending_action.get("deploy"),
                            "target_position_km": pending_action.get("target_position_km"),
                            "decision_reason": pending_action.get("reason"),
                            "moved_km": round(float(movement_record["moved_km"]), 8),
                            "energy_consumed_wh": round(float(movement_record["energy_consumed_wh"]), 8),
                            "position_after_km": [round(network.drone.x_km, 6), round(network.drone.y_km, 6)],
                            "battery_after_wh": round(float(network.drone.battery_wh or 0.0), 8),
                            "runtime_safety_event": (
                                movement_record["event"].get("reason")
                                if movement_record["event"] is not None
                                else None
                            ),
                        }
                    )
                    controller.pending_action_start = None
        applied_environment_events = events_at_time.get(time_s, ())
        environment_event_records = [
            {
                "time_s": time_s,
                "event_type": "phase9_environment_event_applied",
                "environment_event_type": event.event_type,
                "target_id": event.target_id,
                "value": event.value,
                "event_occurrence_time_s": time_s,
                "event_source": "configured_current_tick_event",
            }
            for event in applied_environment_events
        ] if phase9_enabled else []
        dynamic_event_log.extend(environment_event_records)
        for event in applied_environment_events:
            traffic_multiplier = _apply_event(network, event, traffic_multiplier)

        apply_world_state(network, base_users, trace, tick, traffic_multiplier)
        pre_decision_snapshot = evaluate_network(network)
        diagnosis = diagnose_network(network, pre_decision_snapshot, config.congestion_threshold)
        started = time.perf_counter()
        decision = controller.observe(
            time_s,
            network,
            pre_decision_snapshot,
            diagnosis,
            float(network.drone.battery_wh or 0.0),
        )
        measured_ms = (time.perf_counter() - started) * 1000.0
        phase9_timeline_records: list[dict[str, object]] = []
        if phase9_enabled:
            phase9_timeline_records = controller.drain_timeline_events()
            linked_environment_events = [
                {
                    "event_type": event.event_type,
                    "target_id": event.target_id,
                    "value": event.value,
                    "time_s": time_s,
                }
                for event in applied_environment_events
            ]
            if linked_environment_events:
                for record in phase9_timeline_records:
                    record["environment_events_at_observation"] = linked_environment_events
                    record["event_occurrence_time_s"] = time_s
                    record["event_occurrence_basis"] = "current_tick_environment_event_log"
            if linked_environment_events and not phase9_timeline_records:
                phase9_timeline_records.append(
                    {
                        "time_s": time_s,
                        "event_type": "phase9_replan_suppressed",
                        "controller_first_observation_time_s": time_s,
                        "event_occurrence_time_s": time_s,
                        "event_detection_delay_s": 0,
                        "environment_events_at_observation": linked_environment_events,
                        "suppression_reason": "environment_event_produced_no_material_observable_state_change",
                    }
                )
            for record in phase9_timeline_records:
                record["controller_observe_wall_ms"] = round(measured_ms, 6)
                if record.get("event_type") == "phase9_decision_timeline":
                    record["algorithm_compute_wall_ms"] = round(measured_ms, 6)
                    decision_record = record.get("decision")
                    if isinstance(decision_record, dict):
                        decision_record["decision_time_ms"] = round(measured_ms, 6)
        controller_observe_total_ms += measured_ms
        if decision.decision_made:
            decision = replace(decision, decision_time_ms=measured_ms)
            decision_times_ms.append(measured_ms)
            decision_event = decision.to_event(time_s)
            if controller.strategy_id in {
                "D_lexicographic_rescue_priority",
                "Bprime_static_grid_shared_safety",
            }:
                optimizer = getattr(controller, "optimizer", None)
                target = getattr(optimizer, "last_target", None) or decision.destination
                successful_plan = decision.deploy
                decision_event["planning_target_km"] = (
                    [round(target.x_km, 6), round(target.y_km, 6)]
                    if successful_plan and target is not None
                    else None
                )
                decision_event["planned_sortie_energy_wh"] = (
                    round(
                        getattr(
                            optimizer,
                            "last_planned_sortie_energy_wh",
                            getattr(controller, "planned_sortie_energy_wh", 0.0),
                        ),
                        6,
                    )
                    if successful_plan
                    else None
                )
                decision_event["planning_battery_wh"] = (
                    round(
                        getattr(controller, "planning_battery_wh", None)
                        if getattr(controller, "planning_battery_wh", None) is not None
                        else float(network.drone.battery_wh or 0.0),
                        6,
                    )
                    if successful_plan
                    else None
                )
                if controller.strategy_id == "D_lexicographic_rescue_priority":
                    decision_event["target_switch_count"] = controller.optimizer.target_switch_count
            dynamic_event_log.append(decision_event)
            event_counts["optimizer_decision"] = event_counts.get("optimizer_decision", 0) + 1
            if decision.reason not in {
                "rolling_horizon_action_selected",
                "lexicographic_rescue_action_selected",
                "phase9_shared_safe_grid_warm_start",
                "phase1_grid_target_selected",
                "static_grid_target_selected_with_shared_safety",
                "baseline_no_deployment",
            }:
                reason_counts[decision.reason] = reason_counts.get(decision.reason, 0) + 1
        network.drone.active = decision.deploy
        snapshot = evaluate_network(network)
        if phase9_enabled:
            rescue_connected_after = [
                outcome.user_id
                for outcome in snapshot.outcomes
                if outcome.group == "rescue" and outcome.connected
            ]
            for record in phase9_timeline_records:
                record["rescue_connected_after_ids"] = sorted(rescue_connected_after)
                record["rescue_connected_after_count"] = len(rescue_connected_after)
                record["drone_position_after_km"] = [round(network.drone.x_km, 6), round(network.drone.y_km, 6)]
                record["battery_wh_after_decision"] = round(float(network.drone.battery_wh or 0.0), 6)
                dynamic_event_log.append(record)
        final_snapshot = snapshot
        last_snapshot = snapshot
        last_decision = decision

        if capture_snapshots:
            state_snapshots.append(
                _serialize_state_snapshot(
                    time_s=time_s,
                    network=network,
                    snapshot=snapshot,
                    decision=decision,
                    diagnosis=diagnosis,
                    traffic_multiplier=traffic_multiplier,
                )
            )

        covered_samples += sum(outcome.covered for outcome in snapshot.outcomes)
        connected_samples += sum(outcome.connected for outcome in snapshot.outcomes)
        rescue_connected = sum(
            outcome.connected for outcome in snapshot.outcomes if outcome.group == "rescue"
        )
        ground_only_snapshot = evaluate_network(network, drone_active=False)
        ground_rescue_connected = sum(
            outcome.connected
            for outcome in ground_only_snapshot.outcomes
            if outcome.group == "rescue"
        )
        uav_rescue_connected = sum(
            outcome.connected
            and outcome.group == "rescue"
            and outcome.path_kind == "drone_relay"
            for outcome in snapshot.outcomes
        )
        rescue_connected_samples += rescue_connected
        ground_rescue_connected_samples += ground_rescue_connected
        if time_s < seeded_config.duration_s:
            interval_s = seeded_config.time_step_s
            drone_rescue_user_seconds += uav_rescue_connected * interval_s
            ground_rescue_user_seconds += ground_rescue_connected * interval_s
            drone_extra_rescue_user_seconds += max(
                0, rescue_connected - ground_rescue_connected
            ) * interval_s
        current_latencies = [
            float(outcome.latency_ms)
            for outcome in snapshot.outcomes
            if outcome.connected and outcome.latency_ms is not None
        ]
        latency_samples_ms.extend(current_latencies)
        latency_sum_ms += sum(current_latencies)
        if ground_only_recovery_time_s is None and ground_rescue_connected == rescue_total:
            ground_only_recovery_time_s = time_s
        if recovery_time_s is None and rescue_connected == rescue_total:
            recovery_time_s = time_s
            if ground_rescue_connected == rescue_total:
                recovery_cause = "ground_network_sufficient"
            elif uav_rescue_connected > 0:
                recovery_cause = "uav_assisted"
                drone_contributed_recovery_time_s = time_s
            else:
                recovery_cause = "concurrent_capacity_or_route_effect"
            dynamic_event_log.append(
                {
                    "time_s": time_s,
                    "event_type": "network_recovery",
                    "recovery_cause": recovery_cause,
                    "rescue_users_connected": rescue_connected,
                    "rescue_users_total": rescue_total,
                    "ground_only_rescue_users_connected": ground_rescue_connected,
                    "uav_relayed_rescue_users": uav_rescue_connected,
                }
            )
        if rescue_connected == rescue_total:
            if sustained_recovery_ticks == 0:
                sustained_recovery_start_s = time_s
            sustained_recovery_ticks += 1
            if (
                sustained_recovery_time_s is None
                and sustained_recovery_ticks >= sustained_recovery_required_ticks
            ):
                sustained_recovery_time_s = sustained_recovery_start_s
        else:
            sustained_recovery_ticks = 0
            sustained_recovery_start_s = None

        if movement_record is not None and (
            movement_record["moved_km"] > 0 or movement_record["energy_consumed_wh"] > 0
        ):
            dynamic_event_log.append(
                {
                    "time_s": time_s,
                    "event_type": "drone_state_update",
                    "position_km": [round(network.drone.x_km, 6), round(network.drone.y_km, 6)],
                    "moved_km": round(float(movement_record["moved_km"]), 8),
                    "energy_consumed_wh": round(float(movement_record["energy_consumed_wh"]), 8),
                    "battery_remaining_wh": round(float(network.drone.battery_wh or 0.0), 8),
                    "active": network.drone.active,
                }
            )

    assert final_snapshot is not None
    sample_total = total_users * tick_count
    rescue_samples = rescue_total * tick_count
    final_covered = sum(outcome.covered for outcome in final_snapshot.outcomes)
    final_connected = sum(outcome.connected for outcome in final_snapshot.outcomes)
    final_rescue_connected = sum(
        outcome.connected for outcome in final_snapshot.outcomes if outcome.group == "rescue"
    )
    rescue_service_energy_denominator_hours = drone_rescue_user_seconds / 3600.0
    recovery_or_censoring_time_s = (
        recovery_time_s if recovery_time_s is not None else seeded_config.duration_s
    )
    metrics: dict[str, int | float | str | None] = {
        "network_coverage_rate": _rate(covered_samples, sample_total),
        "user_connection_success_rate": _rate(connected_samples, sample_total),
        "rescue_user_service_success_rate": _rate(rescue_connected_samples, rescue_samples),
        "ground_only_rescue_service_success_rate": _rate(ground_rescue_connected_samples, rescue_samples),
        "network_recovery_time_s": recovery_time_s,
        "ground_only_rescue_recovery_time_s": ground_only_recovery_time_s,
        "drone_contributed_recovery_time_s": drone_contributed_recovery_time_s,
        "network_recovery_cause": recovery_cause,
        "network_recovery_or_censoring_time_s": recovery_or_censoring_time_s,
        "network_recovery_censored": int(recovery_time_s is None),
        "network_recovery_success": int(recovery_time_s is not None),
        "sustained_rescue_recovery_time_s": sustained_recovery_time_s,
        "sustained_rescue_recovery_success": int(sustained_recovery_time_s is not None),
        "average_latency_ms": round(latency_sum_ms / len(latency_samples_ms), 6)
        if latency_samples_ms
        else None,
        "p95_latency_ms": _percentile(latency_samples_ms, 0.95),
        "latency_sample_count": len(latency_samples_ms),
        "drone_energy_consumed_wh": round(total_energy_consumed_wh, 6),
        "drone_rescue_user_seconds": round(drone_rescue_user_seconds, 6),
        "drone_extra_rescue_user_seconds": round(drone_extra_rescue_user_seconds, 6),
        "ground_rescue_user_seconds": round(ground_rescue_user_seconds, 6),
        "drone_energy_wh_per_rescue_user_hour": round(
            total_energy_consumed_wh / rescue_service_energy_denominator_hours,
            6,
        )
        if rescue_service_energy_denominator_hours > 0
        else None,
        "drone_battery_remaining_wh": round(float(network.drone.battery_wh or 0.0), 6),
        "drone_battery_minimum_wh": round(minimum_battery_wh, 6),
        "drone_deployed": int(any(event.get("event_type") == "drone_state_update" for event in dynamic_event_log)
                               or any(run_event.get("event_type") == "optimizer_decision" and run_event.get("deploy") for run_event in dynamic_event_log)),
        "algorithm_decision_count": len(decision_times_ms),
        "target_switch_count": getattr(
            getattr(controller, "optimizer", None),
            "target_switch_count",
            0 if controller.strategy_id in {
                "A_no_recovery",
                "B_phase1_static_grid",
                "Bprime_static_grid_shared_safety",
            } else None,
        ),
        "algorithm_decision_total_ms": round(sum(decision_times_ms), 6),
        "controller_observe_total_ms": round(controller_observe_total_ms, 6),
        "algorithm_decision_mean_ms": round(statistics.fmean(decision_times_ms), 6)
        if decision_times_ms
        else 0.0,
        "algorithm_decision_p95_ms": _percentile(decision_times_ms, 0.95),
        "replan_count": max(
            0,
            len(decision_times_ms)
            - (1 if controller.strategy_id in {"C_rolling_horizon_mpc", "D_lexicographic_rescue_priority", "E_event_driven_rescue_recovery"} else 0),
        )
        if controller.strategy_id in {"C_rolling_horizon_mpc", "D_lexicographic_rescue_priority", "E_event_driven_rescue_recovery"}
        else 0,
        "infeasible_decision_count": sum(reason_counts.values()),
        "infeasible_decision_reasons": dict(sorted(reason_counts.items())),
        "evaluation_ticks": tick_count,
        "user_count": total_users,
        "rescue_user_count": rescue_total,
        "final_coverage_rate": _rate(final_covered, total_users),
        "final_connection_success_rate": _rate(final_connected, total_users),
        "final_rescue_users_connected": final_rescue_connected,
        "final_rescue_users_total": rescue_total,
        "final_drone_position_km": [round(network.drone.x_km, 6), round(network.drone.y_km, 6)],
        "traffic_event_count": sum(event.event_type == "traffic_change" for event in config.events),
        "dynamic_event_count": len(config.events),
    }
    if phase9_enabled:
        dynamic_event_log.sort(key=lambda event: int(event["time_s"]))
        metrics.update(
            {
                "event_triggered_decision_count": controller.event_triggered_decision_count,
                "event_suppressed_count": controller.event_suppressed_count,
                "event_deduplicated_count": controller.event_deduplicated_count,
                "decision_timeout_count": controller.timeout_count,
                "invalid_action_filtered_count": controller.invalid_action_filtered_count,
                "event_trigger_counts": dict(sorted(controller.event_trigger_counts.items())),
            }
        )
    else:
        dynamic_event_log.sort(key=lambda event: (int(event["time_s"]), str(event["event_type"])))
    return DynamicRun(
        strategy_id=controller.strategy_id,
        strategy_name=controller.strategy_name,
        metrics=metrics,
        event_log=tuple(dynamic_event_log),
        latency_samples_ms=tuple(latency_samples_ms),
        state_snapshots=tuple(state_snapshots),
    )


def _serialize_state_snapshot(
    *,
    time_s: int,
    network: Network,
    snapshot: NetworkSnapshot,
    decision: ControlDecision,
    diagnosis: NetworkDiagnosis,
    traffic_multiplier: float,
) -> dict[str, object]:
    outcomes = {outcome.user_id: outcome for outcome in snapshot.outcomes}
    users: list[dict[str, object]] = []
    for user in network.users:
        outcome = outcomes[user.id]
        users.append(
            {
                "id": user.id,
                "group": user.group,
                "priority": user.priority,
                "x_km": round(user.x_km, 6),
                "y_km": round(user.y_km, 6),
                "demand_mbps": round(user.demand_mbps, 6),
                "covered": outcome.covered,
                "connected": outcome.connected,
                "path_kind": outcome.path_kind,
                "serving_station_id": outcome.serving_station_id,
                "latency_ms": round(outcome.latency_ms, 6) if outcome.latency_ms is not None else None,
            }
        )

    stations = [
        {
            "id": station.id,
            "x_km": station.x_km,
            "y_km": station.y_km,
            "healthy": station.healthy,
            "capacity_mbps": station.capacity_mbps,
            "coverage_radius_km": station.coverage_radius_km,
        }
        for station in network.stations
    ]
    drone = {
        "id": network.drone_spec.id,
        "x_km": round(network.drone.x_km, 6),
        "y_km": round(network.drone.y_km, 6),
        "active": network.drone.active,
        "battery_wh": round(float(network.drone.battery_wh or 0.0), 6),
        "capacity_mbps": network.drone_spec.capacity_mbps,
        "access_radius_km": network.drone_spec.access_radius_km,
        "backhaul_radius_km": network.drone_spec.backhaul_radius_km,
        "backhaul_available": network.drone_backhaul_available,
        "backhaul_capacity_mbps": network.drone_backhaul_capacity_mbps,
    }
    links: list[dict[str, str]] = []
    for user in network.users:
        outcome = outcomes[user.id]
        if not outcome.connected or outcome.serving_station_id is None:
            continue
        if outcome.path_kind == "drone_relay":
            links.extend(
                (
                    {
                        "source_id": outcome.serving_station_id,
                        "target_id": network.drone_spec.id,
                        "kind": "backhaul",
                        "user_id": user.id,
                    },
                    {
                        "source_id": network.drone_spec.id,
                        "target_id": user.id,
                        "kind": "drone_access",
                        "user_id": user.id,
                    },
                )
            )
        else:
            links.append(
                {
                    "source_id": outcome.serving_station_id,
                    "target_id": user.id,
                    "kind": "access",
                    "user_id": user.id,
                }
            )

    links = list({
        (link["source_id"], link["target_id"], link["kind"]): link for link in links
    }.values())
    decision_event = decision.to_event(time_s)
    decision_event.pop("diagnosis", None)
    decision_event["decision_made"] = decision.decision_made
    serialized: dict[str, object] = {
        "time_s": time_s,
        "stations": stations,
        "drone": drone,
        "users": users,
        "links": links,
        "resource_utilization": {
            key: round(value, 6) for key, value in sorted(snapshot.resource_utilization.items())
        },
        "decision": decision_event,
        "diagnosis": diagnosis.to_dict(),
    }
    if isinstance(traffic_multiplier, dict):
        serialized["traffic_multipliers"] = {
            key: round(value, 6) for key, value in sorted(traffic_multiplier.items())
        }
    else:
        serialized["traffic_multiplier"] = round(traffic_multiplier, 6)
    return serialized


def _apply_event(
    network: Network,
    event: DynamicEventSpec,
    multiplier: float | dict[str, float],
) -> float | dict[str, float]:
    if event.event_type in {"station_failure", "station_recovery"}:
        healthy = event.event_type == "station_recovery"
        network.stations = tuple(
            replace(station, healthy=healthy) if station.id == event.target_id else station
            for station in network.stations
        )
    elif event.event_type == "backhaul_failure":
        network.drone_backhaul_available = False
    elif event.event_type == "backhaul_recovery":
        network.drone_backhaul_available = True
    elif event.event_type == "backhaul_capacity_change":
        assert event.value is not None
        network.drone_backhaul_capacity_mbps = event.value
    elif event.event_type == "traffic_change":
        assert event.value is not None
        if event.target_id == "city":
            if isinstance(multiplier, dict):
                multiplier = {**multiplier, "city": event.value}
            else:
                multiplier = event.value
        elif isinstance(multiplier, dict):
            multiplier = {**multiplier, event.target_id: event.value}
        else:
            multiplier = {
                "city": multiplier,
                "rescue": event.value if event.target_id == "rescue" else 1.0,
                "normal": event.value if event.target_id == "normal" else 1.0,
            }
    return multiplier


def _advance_drone(
    network: Network,
    decision: ControlDecision,
    previous_snapshot: NetworkSnapshot,
    config: DynamicExperimentConfig,
    time_s: int,
) -> dict[str, object]:
    battery = float(network.drone.battery_wh or 0.0)
    if not network.drone.active or battery <= config.reserve_wh:
        return {"moved_km": 0.0, "energy_consumed_wh": 0.0, "event": None}

    interval_s = config.time_step_s
    relaying = any(
        outcome.connected and outcome.path_kind == "drone_relay"
        for outcome in previous_snapshot.outcomes
    )
    idle_power = config.hover_power_w + (config.relay_power_w if relaying else 0.0)
    operation_energy = idle_power * interval_s / 3600.0
    if battery - operation_energy <= config.reserve_wh:
        consumed = max(0.0, battery - config.reserve_wh)
        network.drone.battery_wh = config.reserve_wh
        network.drone.active = False
        event = {
            "time_s": time_s,
            "event_type": "drone_energy_reserve_shutdown",
            "reason": "next_interval_would_consume_protected_reserve",
            "battery_remaining_wh": round(config.reserve_wh, 8),
        }
        return {"moved_km": 0.0, "energy_consumed_wh": consumed, "event": event}

    if decision.destination is not None:
        dx = decision.destination.x_km - network.drone.x_km
        dy = decision.destination.y_km - network.drone.y_km
        distance = math.hypot(dx, dy)
        if distance == 0:
            heading = (0.0, 0.0)
        else:
            heading = (dx / distance, dy / distance)
        desired_distance = min(distance, network.drone_spec.speed_km_per_s * interval_s)
    else:
        magnitude = math.hypot(decision.heading_x, decision.heading_y)
        heading = (
            (decision.heading_x / magnitude, decision.heading_y / magnitude)
            if magnitude
            else (0.0, 0.0)
        )
        desired_distance = network.drone_spec.speed_km_per_s * interval_s if magnitude else 0.0

    remaining_after_operation = battery - operation_energy
    max_energy_distance = (
        max(0.0, remaining_after_operation - config.reserve_wh) / config.movement_wh_per_km
        if config.movement_wh_per_km > 0
        else desired_distance
    )
    desired_distance = min(desired_distance, max_energy_distance)
    healthy_stations = tuple(station for station in network.stations if station.healthy)

    def feasible(distance: float) -> bool:
        x = network.drone.x_km + heading[0] * distance
        y = network.drone.y_km + heading[1] * distance
        if not (0 <= x <= network.config.city_width_km and 0 <= y <= network.config.city_height_km):
            return False
        if not healthy_stations:
            return distance <= 1e-12
        return_distances = [distance_km(x, y, station.x_km, station.y_km) for station in healthy_stations]
        nearest_return = min(return_distances)
        return_energy = return_energy_wh(config, network, Position(x, y))
        return (
            nearest_return <= network.drone_spec.backhaul_radius_km
            and return_energy is not None
            and remaining_after_operation
            - distance * config.movement_wh_per_km
            - return_energy
            >= config.reserve_wh - 1e-9
        )

    movement = desired_distance
    if not feasible(movement):
        lower, upper = 0.0, movement
        for _ in range(24):
            midpoint = (lower + upper) / 2.0
            if feasible(midpoint):
                lower = midpoint
            else:
                upper = midpoint
        movement = lower if feasible(lower) else 0.0

    network.drone.x_km += heading[0] * movement
    network.drone.y_km += heading[1] * movement
    movement_energy = movement * config.movement_wh_per_km
    consumed = operation_energy + movement_energy
    network.drone.battery_wh = max(config.reserve_wh, battery - consumed)
    return {
        "moved_km": movement,
        "energy_consumed_wh": consumed,
        "event": None,
    }


def _failed_decision(
    diagnosis: NetworkDiagnosis,
    reason: str,
    trigger: str,
) -> ControlDecision:
    return ControlDecision(
        deploy=False,
        heading_x=0.0,
        heading_y=0.0,
        destination=None,
        reason=reason,
        trigger=trigger,
        decision_made=True,
        objective_score=None,
        infeasible_reasons=(reason,),
        diagnosis=diagnosis,
    )


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 6)
