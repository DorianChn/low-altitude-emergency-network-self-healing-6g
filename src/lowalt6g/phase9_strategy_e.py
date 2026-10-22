"""Reactive event-driven recovery controller introduced in Phase 9.

The controller uses only the current network state supplied by the simulator.
It does not inspect the exogenous event schedule or any future trace frames.
Planning delegates to the Phase 8 rescue-priority optimizer, retaining its
radio, capacity, speed, energy, return-reserve, and runtime-actuator checks.
"""

from __future__ import annotations

from dataclasses import replace
import math
import time
from typing import Any

from .dynamic_config import DynamicExperimentConfig
from .energy_budget import return_energy_wh, sortie_energy_wh
from .engine import distance_km, evaluate_network
from .models import Network, NetworkSnapshot, Position
from .optimizer import ControlDecision, NetworkDiagnosis
from .phase8_d_optimizer import Phase8RescuePriorityOptimizer
from .policies import GreedyRelayPolicy


class EventDrivenController:
    """Replan on material observable transitions, with dedupe and cooldown.

    Fault and rescue-service-loss transitions bypass cooldown. Softer capacity,
    ordinary-service, and battery-margin events use ``cooldown_s``. Identical
    observed state transitions are de-duplicated. A post-compute deadline drops
    an over-budget result and issues a safe no-deploy decision; Python execution
    itself is synchronous, so this deadline is an output watchdog, not a hard
    preemption guarantee.
    """

    strategy_id = "E_event_driven_rescue_recovery"
    strategy_name = "Event-driven rescue recovery"
    phase9_event_driven = True

    def __init__(
        self,
        config: DynamicExperimentConfig,
        *,
        cooldown_s: int = 20,
        decision_timeout_ms: float = 500.0,
        candidate_limit: int = 64,
        rescue_loss_threshold: int = 1,
        battery_reserve_margin_alert_wh: float = 25.0,
    ) -> None:
        if cooldown_s < 0 or decision_timeout_ms <= 0 or candidate_limit < 1:
            raise ValueError("cooldown must be non-negative and timeout/candidate limit positive")
        if rescue_loss_threshold < 1 or battery_reserve_margin_alert_wh < 0:
            raise ValueError("rescue loss threshold must be positive and battery alert margin non-negative")
        # Do not even retain the future exogenous timetable in the policy
        # configuration passed to its planner.
        self.config = replace(config, events=())
        self.planning_config = self.config
        self.cooldown_s = cooldown_s
        self.decision_timeout_ms = decision_timeout_ms
        self.rescue_loss_threshold = rescue_loss_threshold
        self.battery_reserve_margin_alert_wh = battery_reserve_margin_alert_wh
        self.optimizer = Phase8RescuePriorityOptimizer(self.planning_config, candidate_limit=candidate_limit)
        self.last_state: dict[str, Any] | None = None
        self.last_observed_time_s: int | None = None
        self.last_decision: ControlDecision | None = None
        self.last_trigger_time_s: int | None = None
        self.last_trigger_fingerprints: set[tuple[object, ...]] = set()
        self.pending_action_start: dict[str, Any] | None = None
        self.timeline_events: list[dict[str, object]] = []
        self.event_triggered_decision_count = 0
        self.event_suppressed_count = 0
        self.event_deduplicated_count = 0
        self.timeout_count = 0
        self.invalid_action_filtered_count = 0
        self.event_trigger_counts: dict[str, int] = {}

    def observe(
        self,
        time_s: int,
        network: Network,
        snapshot: NetworkSnapshot,
        diagnosis: NetworkDiagnosis,
        battery_wh: float,
    ) -> ControlDecision:
        state = self._observable_state(network, snapshot, diagnosis, battery_wh)
        before = self.last_state
        categories, critical = self._changed_categories(before, state)
        self.last_state = state

        if not categories:
            if self.last_observed_time_s == time_s:
                self.event_deduplicated_count += 1
                self.event_suppressed_count += 1
                self.timeline_events.append(
                    self._suppressed_record(
                        time_s,
                        [],
                        "duplicate_observation_same_simulation_tick",
                        state,
                    )
                )
            self.last_observed_time_s = time_s
            return self._hold(diagnosis, "no_material_observable_change", network)
        self.last_observed_time_s = time_s

        fingerprint = (time_s, *self._fingerprint(state, categories))
        if fingerprint in self.last_trigger_fingerprints:
            self.event_deduplicated_count += 1
            self.event_suppressed_count += 1
            self.timeline_events.append(
                self._suppressed_record(
                    time_s,
                    categories,
                    "duplicate_observable_event",
                    state,
                )
            )
            return self._hold(diagnosis, "duplicate_event_suppressed", network)

        if (
            not critical
            and self.last_trigger_time_s is not None
            and time_s - self.last_trigger_time_s < self.cooldown_s
        ):
            self.last_trigger_fingerprints.add(fingerprint)
            self.event_suppressed_count += 1
            self.timeline_events.append(
                self._suppressed_record(
                    time_s,
                    categories,
                    "soft_event_cooldown",
                    state,
                )
            )
            return self._hold(diagnosis, "soft_event_cooldown", network)

        self.last_trigger_fingerprints.add(fingerprint)
        self.last_trigger_time_s = time_s
        trigger = "event:" + "+".join(categories)
        self.event_triggered_decision_count += 1
        for category in categories:
            self.event_trigger_counts[category] = self.event_trigger_counts.get(category, 0) + 1

        target_before = self.optimizer.last_target
        optimizer_state_before = (
            self.optimizer.last_target,
            self.optimizer.reference_target,
            self.optimizer.last_planned_sortie_energy_wh,
            self.optimizer.target_switch_count,
        )
        decision_start = time.perf_counter()
        decision = self._plan(time_s, network, snapshot, diagnosis, battery_wh, trigger)
        wall_ms = (time.perf_counter() - decision_start) * 1000.0
        if wall_ms > self.decision_timeout_ms and decision.reason != "decision_timeout_safe_no_deploy":
            self.timeout_count += 1
            self.invalid_action_filtered_count += 1
            self.timeline_events.append(
                self._decision_record(
                    time_s=time_s,
                    categories=categories,
                    trigger=trigger,
                    state=state,
                    snapshot=snapshot,
                    decision=ControlDecision(
                        deploy=False,
                        heading_x=0.0,
                        heading_y=0.0,
                        destination=None,
                        reason="decision_timeout_safe_no_deploy",
                        trigger=trigger,
                        decision_made=True,
                        objective_score=None,
                        infeasible_reasons=("decision_timeout_safe_no_deploy",),
                        diagnosis=diagnosis,
                    ),
                    wall_ms=wall_ms,
                    target_before=target_before,
                    target_after=target_before,
                    timeout=True,
                )
            )
            decision = ControlDecision(
                deploy=False,
                heading_x=0.0,
                heading_y=0.0,
                destination=None,
                reason="decision_timeout_safe_no_deploy",
                trigger=trigger,
                decision_made=True,
                objective_score=None,
                infeasible_reasons=("decision_timeout_safe_no_deploy",),
                diagnosis=diagnosis,
            )
            # A late result must not leave any planned route or switch count committed.
            (
                self.optimizer.last_target,
                self.optimizer.reference_target,
                self.optimizer.last_planned_sortie_energy_wh,
                self.optimizer.target_switch_count,
            ) = optimizer_state_before
        else:
            target_after = self.optimizer.last_target
            self.timeline_events.append(
                self._decision_record(
                    time_s=time_s,
                    categories=categories,
                    trigger=trigger,
                    state=state,
                    snapshot=snapshot,
                    decision=decision,
                    wall_ms=wall_ms,
                    target_before=target_before,
                    target_after=target_after,
                    timeout=False,
                )
            )

        self.optimizer.last_signature = tuple(categories)
        self.optimizer.last_decision_time_s = time_s
        self.optimizer.heading = (decision.heading_x, decision.heading_y)
        self.optimizer.deployed = decision.deploy
        self.last_decision = decision
        self.pending_action_start = {
            "decision_time_s": time_s,
            "due_time_s": time_s + self.planning_config.time_step_s,
            "deploy": decision.deploy,
            "target_position_km": self._position_tuple(self.optimizer.last_target),
            "reason": decision.reason,
        }
        return decision

    def _plan(
        self,
        time_s: int,
        network: Network,
        snapshot: NetworkSnapshot,
        diagnosis: NetworkDiagnosis,
        battery_wh: float,
        trigger: str,
    ) -> ControlDecision:
        if not any(station.healthy for station in network.stations):
            return self._failed(diagnosis, "no_healthy_base_station", trigger)
        if not network.drone_backhaul_available:
            return self._failed(diagnosis, "drone_backhaul_temporarily_unavailable", trigger)
        if battery_wh <= self.config.reserve_wh:
            return self._failed(diagnosis, "battery_at_or_below_reserve", trigger)

        # If all traffic already has a ground path, stop the relay and preserve
        # energy rather than running an optimizer with no unmet service demand.
        ground_snapshot = evaluate_network(network, drone_active=False)
        if all(outcome.connected for outcome in ground_snapshot.outcomes):
            self.invalid_action_filtered_count += 1
            return self._failed(diagnosis, "ground_network_restored_no_uav_action_needed", trigger)

        if trigger == "event:initial_observation":
            return self._initial_shared_safe_grid_action(network, diagnosis, battery_wh, trigger)

        optimizer_state_before = (
            self.optimizer.last_target,
            self.optimizer.reference_target,
            self.optimizer.last_planned_sortie_energy_wh,
            self.optimizer.target_switch_count,
        )
        decision = self.optimizer._optimize(network, snapshot, diagnosis, battery_wh, trigger)
        selected = self.optimizer.last_target
        if decision.deploy and selected is not None and distance_km(
            network.drone.x_km,
            network.drone.y_km,
            selected.x_km,
            selected.y_km,
        ) <= 1e-9:
            at_target = evaluate_network(
                network,
                drone_position=(selected.x_km, selected.y_km),
                drone_active=True,
            )
            effective_relay = any(
                outcome.connected and outcome.path_kind == "drone_relay"
                for outcome in at_target.outcomes
            )
            if not effective_relay:
                (
                    self.optimizer.last_target,
                    self.optimizer.reference_target,
                    self.optimizer.last_planned_sortie_energy_wh,
                    self.optimizer.target_switch_count,
                ) = optimizer_state_before
                self.invalid_action_filtered_count += 1
                return self._failed(diagnosis, "optimizer_selected_no_effective_movement_or_relay", trigger)
        return decision

    def _initial_shared_safe_grid_action(
        self,
        network: Network,
        diagnosis: NetworkDiagnosis,
        battery_wh: float,
        trigger: str,
    ) -> ControlDecision:
        """Use B′'s audited one-shot grid warm start, then respond to events."""
        target = GreedyRelayPolicy(network.config.policy_search_grid_km).plan(network).destination
        if target is None:
            return self._failed(diagnosis, "grid_search_found_no_target", trigger)
        healthy_stations = tuple(station for station in network.stations if station.healthy)
        has_backhaul = any(
            distance_km(target.x_km, target.y_km, station.x_km, station.y_km)
            <= network.drone_spec.backhaul_radius_km + 1e-9
            for station in healthy_stations
        )
        energy = sortie_energy_wh(self.planning_config, network, target)
        if not has_backhaul:
            return self._failed(diagnosis, "target_has_no_backhaul", trigger)
        if energy is None or battery_wh - energy < self.planning_config.reserve_wh - 1e-9:
            return self._failed(diagnosis, "shared_sortie_energy_budget_would_violate_reserve", trigger)
        if distance_km(network.drone.x_km, network.drone.y_km, target.x_km, target.y_km) <= 1e-9:
            at_target = evaluate_network(
                network,
                drone_position=(target.x_km, target.y_km),
                drone_active=True,
            )
            if not any(outcome.connected and outcome.path_kind == "drone_relay" for outcome in at_target.outcomes):
                self.invalid_action_filtered_count += 1
                return self._failed(diagnosis, "grid_warm_start_has_no_effective_movement_or_relay", trigger)
        self.optimizer.reference_target = target
        self.optimizer.last_target = target
        self.optimizer.last_planned_sortie_energy_wh = energy
        return ControlDecision(
            deploy=True,
            heading_x=0.0,
            heading_y=0.0,
            destination=target,
            reason="phase9_shared_safe_grid_warm_start",
            trigger=trigger,
            decision_made=True,
            objective_score=None,
            infeasible_reasons=(),
            diagnosis=diagnosis,
        )

    def _observable_state(
        self,
        network: Network,
        snapshot: NetworkSnapshot,
        diagnosis: NetworkDiagnosis,
        battery_wh: float,
    ) -> dict[str, Any]:
        rescue_connected = frozenset(
            outcome.user_id
            for outcome in snapshot.outcomes
            if outcome.group == "rescue" and outcome.connected
        )
        rescue_total = sum(user.group == "rescue" for user in network.users)
        disconnected_normal = frozenset(
            outcome.user_id
            for outcome in snapshot.outcomes
            if outcome.group != "rescue" and not outcome.connected
        )
        cell_km = max(float(network.config.policy_search_grid_km), 1e-6)
        rescue_position_cells = tuple(
            sorted(
                (
                    user.id,
                    math.floor(user.x_km / cell_km),
                    math.floor(user.y_km / cell_km),
                )
                for user in network.users
                if user.group == "rescue"
            )
        )
        traffic_demand_signature = tuple(
            sorted((user.id, round(user.demand_mbps, 3)) for user in network.users)
        )
        healthy_stations = tuple((station.id, station.healthy) for station in network.stations)
        backhaul_capacity = network.drone_backhaul_capacity_mbps
        return_energy = return_energy_wh(self.planning_config, network, network.drone.position)
        margin = (
            battery_wh - self.planning_config.reserve_wh - return_energy
            if return_energy is not None
            else float("-inf")
        )
        return {
            "station_health": healthy_stations,
            "backhaul_available": network.drone_backhaul_available,
            "backhaul_capacity_mbps": round(backhaul_capacity, 3) if backhaul_capacity is not None else None,
            "rescue_connected_ids": rescue_connected,
            "rescue_disconnected_count": max(0, rescue_total - len(rescue_connected)),
            "rescue_position_cells": rescue_position_cells,
            "traffic_demand_signature": traffic_demand_signature,
            "normal_disconnected_ids": disconnected_normal,
            "battery_wh": round(battery_wh, 6),
            "congested_resources": frozenset(diagnosis.congested_resource_ids),
            "battery_margin_wh": margin,
            "battery_reserve_margin_critical": margin <= self.battery_reserve_margin_alert_wh,
        }

    def _changed_categories(
        self,
        previous: dict[str, Any] | None,
        current: dict[str, Any],
    ) -> tuple[list[str], bool]:
        if previous is None:
            return ["initial_observation"], True

        categories: list[str] = []
        if current["station_health"] != previous["station_health"]:
            categories.append("station_health_change")
        if (
            current["backhaul_available"] != previous["backhaul_available"]
            or current["backhaul_capacity_mbps"] != previous["backhaul_capacity_mbps"]
        ):
            categories.append("backhaul_state_change")
        if current["rescue_position_cells"] != previous["rescue_position_cells"]:
            categories.append("rescue_position_cell_change")
        if current["traffic_demand_signature"] != previous["traffic_demand_signature"]:
            categories.append("traffic_demand_change")
        rescue_loss = current["rescue_disconnected_count"] - previous["rescue_disconnected_count"]
        if rescue_loss >= self.rescue_loss_threshold:
            categories.append("rescue_service_loss")
        elif rescue_loss < 0:
            categories.append("rescue_service_restored")
        new_congestion = current["congested_resources"] - previous["congested_resources"]
        if new_congestion:
            categories.append("congestion_onset")
        elif current["congested_resources"] != previous["congested_resources"]:
            categories.append("congestion_cleared")
        normal_loss = len(current["normal_disconnected_ids"]) - len(previous["normal_disconnected_ids"])
        if normal_loss > 0:
            categories.append("ordinary_service_loss")
        if (
            not previous["battery_reserve_margin_critical"]
            and current["battery_reserve_margin_critical"]
        ):
            categories.append("battery_return_reserve_margin_critical")

        critical = any(
            category in {
                "station_health_change",
                "backhaul_state_change",
                "rescue_service_loss",
            }
            for category in categories
        )
        return categories, critical

    def _fingerprint(self, state: dict[str, Any], categories: list[str]) -> tuple[object, ...]:
        return (
            tuple(categories),
            state["station_health"],
            state["backhaul_available"],
            state["backhaul_capacity_mbps"],
            state["rescue_disconnected_count"],
            state["rescue_position_cells"],
            state["traffic_demand_signature"],
            tuple(sorted(state["congested_resources"])),
            state["battery_reserve_margin_critical"]
            if "battery_return_reserve_margin_critical" in categories
            else None,
        )

    def _decision_record(
        self,
        *,
        time_s: int,
        categories: list[str],
        trigger: str,
        state: dict[str, Any],
        snapshot: NetworkSnapshot,
        decision: ControlDecision,
        wall_ms: float,
        target_before: Position | None,
        target_after: Position | None,
        timeout: bool,
    ) -> dict[str, object]:
        rescue_connected = [
            outcome.user_id
            for outcome in snapshot.outcomes
            if outcome.group == "rescue" and outcome.connected
        ]
        return {
            "time_s": time_s,
            "event_type": "phase9_decision_timeline",
            "event_occurrence_time_s": None if categories == ["initial_observation"] else time_s,
            "event_occurrence_basis": (
                "initial_observation_no_new_event"
                if categories == ["initial_observation"]
                else "observable_simulator_state_transition_at_tick"
            ),
            "controller_first_observation_time_s": time_s,
            "event_detection_delay_s": None if categories == ["initial_observation"] else 0,
            "replanning_trigger_time_s": time_s,
            "decision_completed_sim_time_s": time_s,
            "action_accepted_sim_time_s": time_s,
            "action_motion_start_due_time_s": time_s + self.planning_config.time_step_s,
            "event_changes": list(categories),
            "rescue_connected_before_ids": sorted(rescue_connected),
            "rescue_connected_before_count": len(rescue_connected),
            "rescue_disconnected_count": state["rescue_disconnected_count"],
            "rescue_position_cells": state["rescue_position_cells"],
            "traffic_demand_signature": state["traffic_demand_signature"],
            "battery_wh_before_decision": state["battery_wh"],
            "target_before_km": self._position_tuple(target_before),
            "target_after_km": self._position_tuple(target_after),
            "target_changed": target_before != target_after,
            "next_step_destination_km": self._position_tuple(decision.destination),
            "decision_reason": decision.reason,
            "infeasible_reasons": list(decision.infeasible_reasons),
            "planner_wall_ms": round(wall_ms, 6),
            "decision_timeout_ms": self.decision_timeout_ms,
            "decision_timed_out": timeout,
            "decision": {
                key: value
                for key, value in decision.to_event(time_s).items()
                if key != "diagnosis"
            },
        }

    @staticmethod
    def _suppressed_record(
        time_s: int,
        categories: list[str],
        reason: str,
        state: dict[str, Any],
    ) -> dict[str, object]:
        return {
            "time_s": time_s,
            "event_type": "phase9_replan_suppressed",
            "controller_first_observation_time_s": time_s,
            "event_detection_delay_s": 0,
            "event_changes": list(categories),
            "suppression_reason": reason,
            "rescue_disconnected_count": state["rescue_disconnected_count"],
            "backhaul_available": state["backhaul_available"],
        }

    def _hold(self, diagnosis: NetworkDiagnosis, reason: str, network: Network) -> ControlDecision:
        if self.last_decision is None:
            return self._failed(diagnosis, reason, "event_filter")
        held = replace(
            self.last_decision,
            decision_made=False,
            trigger=reason,
            decision_time_ms=0.0,
            diagnosis=diagnosis,
        )
        # The MPC exposes a one-step waypoint in ControlDecision.destination.
        # Repeating that waypoint on unchanged ticks makes the aircraft stop
        # after one step. Keep issuing the committed terminal target instead;
        # the simulator actuator still clamps movement and checks return reserve
        # and backhaul feasibility on every tick.
        target = self.optimizer.last_target
        if held.deploy and target is not None:
            return replace(held, destination=target)
        return held

    @staticmethod
    def _failed(diagnosis: NetworkDiagnosis, reason: str, trigger: str) -> ControlDecision:
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

    @staticmethod
    def _position_tuple(position: Position | None) -> list[float] | None:
        return (
            [round(position.x_km, 6), round(position.y_km, 6)]
            if position is not None
            else None
        )

    def drain_timeline_events(self) -> list[dict[str, object]]:
        events = self.timeline_events
        self.timeline_events = []
        return events
