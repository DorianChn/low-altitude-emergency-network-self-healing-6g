"""Phase 8 experimental D optimizer copied from the frozen Phase 5 implementation.

Source file SHA-256: 11162120c657a529db4a81649998cb00250be206935ba216458a96f988486525
Only candidate cap, switch suppression/tie-break, energy tie-break, and rescue
lexicographic priority are exposed as experiment switches. Feasibility, full
sortie energy, return-to-station reserve, radio/backhaul constraints and the
runtime actuator are inherited unchanged.
"""

from __future__ import annotations

import math
from .energy_budget import sortie_energy_wh
from .engine import distance_km, evaluate_network
from .models import Network, Position
from .optimizer import ControlDecision, NetworkDiagnosis, RescuePriorityOptimizer, current_snapshot_by_id
from .models import NetworkSnapshot
from .policies import GreedyRelayPolicy

SOURCE_OPTIMIZER_SHA256 = "11162120c657a529db4a81649998cb00250be206935ba216458a96f988486525"


class Phase8RescuePriorityOptimizer(RescuePriorityOptimizer):
    def __init__(
        self,
        config,
        *,
        candidate_limit: int = 64,
        suppress_switch_without_rescue_gain: bool = True,
        energy_tiebreak_enabled: bool = True,
        rescue_priority_enabled: bool = True,
        switch_penalty_weight: float = 1.0,
    ) -> None:
        super().__init__(config)
        if candidate_limit < 1 or switch_penalty_weight < 0:
            raise ValueError("candidate_limit must be positive and switch penalty non-negative")
        self.candidate_limit = candidate_limit
        self.suppress_switch_without_rescue_gain = suppress_switch_without_rescue_gain
        self.energy_tiebreak_enabled = energy_tiebreak_enabled
        self.rescue_priority_enabled = rescue_priority_enabled
        self.switch_penalty_weight = switch_penalty_weight

    def _optimize(
        self,
        network: Network,
        current_snapshot: NetworkSnapshot,
        diagnosis: NetworkDiagnosis,
        battery_wh: float,
        trigger: str,
    ) -> ControlDecision:
        self.last_planned_sortie_energy_wh = 0.0
        if not any(station.healthy for station in network.stations):
            return self._infeasible(diagnosis, trigger, "no_healthy_base_station")
        if not network.drone_backhaul_available:
            return self._infeasible(diagnosis, trigger, "drone_backhaul_temporarily_unavailable")
        if battery_wh <= self.config.reserve_wh:
            return self._infeasible(diagnosis, trigger, "battery_at_or_below_reserve")

        if self.reference_target is None:
            self.reference_target = GreedyRelayPolicy(
                network.config.policy_search_grid_km
            ).plan(network).destination

        start = network.drone.position
        healthy_stations = tuple(station for station in network.stations if station.healthy)
        rescue_targets = [
            user
            for user in network.users
            if user.group == "rescue" and not current_snapshot_by_id(current_snapshot, user.id)
        ]
        if rescue_targets:
            targets = rescue_targets
        else:
            disconnected = set(diagnosis.disconnected_user_ids)
            targets = [user for user in network.users if user.id in disconnected]
        grid_positions = self._candidate_grid_positions(network)
        geometrically_feasible = []
        for point in grid_positions:
            if not any(
                distance_km(point.x_km, point.y_km, station.x_km, station.y_km)
                <= network.drone_spec.backhaul_radius_km
                for station in healthy_stations
            ):
                continue
            potential = sum(
                distance_km(point.x_km, point.y_km, user.x_km, user.y_km)
                <= network.drone_spec.access_radius_km
                for user in (rescue_targets if rescue_targets else targets)
            )
            if potential:
                geometrically_feasible.append(
                    (
                        -potential,
                        distance_km(start.x_km, start.y_km, point.x_km, point.y_km),
                        point.x_km,
                        point.y_km,
                        point,
                    )
                )
        target_positions = [entry[-1] for entry in sorted(geometrically_feasible)[: self.candidate_limit]]
        target_positions.extend(self._feasible_relay_positions(network, targets, healthy_stations))
        if rescue_targets:
            target_positions.extend(self._rescue_cluster_positions(network, rescue_targets, healthy_stations))
        target_positions.append(start)
        if self.reference_target is not None:
            target_positions.append(self.reference_target)
        if self.last_target is not None:
            target_positions.append(self.last_target)
        target_positions = self._unique_positions(target_positions)

        infeasible: set[str] = set()
        candidate_ranks: dict[tuple[int, int], tuple[float, ...]] = {}
        candidate_energies: dict[tuple[int, int], float] = {}
        time_step_s = self.config.time_step_s
        move_limit = network.drone_spec.speed_km_per_s * time_step_s
        rescue_count = sum(user.group == "rescue" for user in network.users)
        horizon = self.config.prediction_horizon_steps
        best_position: Position | None = None
        best_rank: tuple[float, ...] | None = None
        for target in target_positions:
            if not self._route_preserves_any_backhaul(
                network,
                start,
                target,
                healthy_stations,
                move_limit,
            ):
                infeasible.add("no_backhaul_preserving_route_to_target")
                continue
            # Handover between healthy stations is allowed along the path. The
            # old check incorrectly required one station to cover both ends.
            route_stations = healthy_stations

            target_distance = distance_km(start.x_km, start.y_km, target.x_km, target.y_km)
            target_flight_ticks = math.ceil(target_distance / max(move_limit, 1e-12))
            target_return_distance = min(
                distance_km(target.x_km, target.y_km, station.x_km, station.y_km)
                for station in healthy_stations
            )
            target_return_ticks = math.ceil(target_return_distance / max(move_limit, 1e-12))
            full_sortie_energy = sortie_energy_wh(
                self.config,
                network,
                target,
                service_steps=horizon,
            )
            if full_sortie_energy is None or battery_wh - full_sortie_energy < self.config.reserve_wh - 1e-9:
                infeasible.add("full_target_sortie_energy_would_violate_reserve")
                continue

            remaining = battery_wh
            position = start
            rescue_user_ticks = 0
            ordinary_user_ticks = 0
            latency_user_ms = 0.0
            first_full_recovery_step: int | None = None
            feasible = True
            for depth in range(horizon):
                dx = target.x_km - position.x_km
                dy = target.y_km - position.y_km
                distance_to_target = math.hypot(dx, dy)
                step_distance = min(distance_to_target, move_limit)
                if distance_to_target <= 1e-12:
                    next_position = target
                else:
                    next_position = Position(
                        position.x_km + dx / distance_to_target * step_distance,
                        position.y_km + dy / distance_to_target * step_distance,
                    )
                forecast = evaluate_network(
                    network,
                    drone_position=(next_position.x_km, next_position.y_km),
                    drone_active=True,
                )
                relaying = any(
                    outcome.connected and outcome.path_kind == "drone_relay"
                    for outcome in forecast.outcomes
                )
                operation_power = self.config.hover_power_w + (
                    self.config.relay_power_w if relaying else 0.0
                )
                step_energy = (
                    step_distance * self.config.movement_wh_per_km
                    + operation_power * time_step_s / 3600.0
                )
                remaining -= step_energy
                if remaining < self.config.reserve_wh - 1e-9:
                    infeasible.add("battery_reserve_would_be_violated")
                    feasible = False
                    break

                return_distance = min(
                    distance_km(next_position.x_km, next_position.y_km, station.x_km, station.y_km)
                    for station in healthy_stations
                )
                return_ticks = math.ceil(
                    return_distance / max(move_limit, 1e-12)
                )
                return_energy = (
                    return_distance * self.config.movement_wh_per_km
                    + (self.config.hover_power_w + self.config.relay_power_w)
                    * return_ticks
                    * time_step_s
                    / 3600.0
                )
                if remaining - return_energy < self.config.reserve_wh - 1e-9:
                    infeasible.add("return_energy_reserve_would_be_violated")
                    feasible = False
                    break

                rescue_now = sum(
                    outcome.connected and outcome.group == "rescue" for outcome in forecast.outcomes
                )
                ordinary_now = sum(
                    outcome.connected and outcome.group != "rescue" for outcome in forecast.outcomes
                )
                rescue_user_ticks += rescue_now
                ordinary_user_ticks += ordinary_now
                latency_user_ms += sum(
                    outcome.latency_ms or 0.0 for outcome in forecast.outcomes if outcome.connected
                )
                if rescue_count and rescue_now == rescue_count and first_full_recovery_step is None:
                    first_full_recovery_step = depth + 1
                position = next_position

            if not feasible:
                continue

            target_snapshot = evaluate_network(
                network,
                drone_position=(target.x_km, target.y_km),
                drone_active=True,
            )
            target_rescue_count = sum(
                outcome.connected and outcome.group == "rescue" for outcome in target_snapshot.outcomes
            )
            predicted_recovery_distance = self._first_full_rescue_distance(
                network,
                start,
                target,
                route_stations,
                rescue_count,
            )
            final_snapshot = evaluate_network(
                network,
                drone_position=(position.x_km, position.y_km),
                drone_active=True,
            )
            final_rescue_count = sum(
                outcome.connected and outcome.group == "rescue" for outcome in final_snapshot.outcomes
            )
            travel_ticks = math.ceil(distance_km(start.x_km, start.y_km, target.x_km, target.y_km) / max(move_limit, 1e-12))
            predicted_recovery_ticks = (
                first_full_recovery_step
                if first_full_recovery_step is not None
                else (
                    math.ceil(predicted_recovery_distance / max(move_limit, 1e-12))
                    if predicted_recovery_distance is not None
                    else None
                )
            )
            switches = int(
                self.last_target is not None
                and distance_km(
                    self.last_target.x_km,
                    self.last_target.y_km,
                    target.x_km,
                    target.y_km,
                ) > self.config.base.policy_search_grid_km / 2.0
            )
            projected_progress_km = max(
                0.0,
                target_distance
                - distance_km(position.x_km, position.y_km, target.x_km, target.y_km),
            )
            rank = (
                float(rescue_user_ticks if self.rescue_priority_enabled else rescue_user_ticks + ordinary_user_ticks),
                float(predicted_recovery_ticks is not None) if self.rescue_priority_enabled else float(ordinary_user_ticks),
                -float(predicted_recovery_ticks if predicted_recovery_ticks is not None else 10**9),
                float(target_rescue_count),
                float(final_rescue_count),
                projected_progress_km,
                float(ordinary_user_ticks),
                -latency_user_ms,
                -full_sortie_energy if self.energy_tiebreak_enabled else 0.0,
                -target_distance,
                -float(switches) * self.switch_penalty_weight,
            )
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_position = target
            candidate_key = (round(target.x_km / 0.005), round(target.y_km / 0.005))
            candidate_ranks[candidate_key] = rank
            candidate_energies[candidate_key] = full_sortie_energy

        if self.last_target is None and self.reference_target is not None:
            reference_rank = candidate_ranks.get(
                (
                    round(self.reference_target.x_km / 0.005),
                    round(self.reference_target.y_km / 0.005),
                )
            )
            if reference_rank is not None:
                best_position = self.reference_target
                best_rank = reference_rank

        if best_position is not None and best_rank is not None and self.last_target is not None:
            held_rank = candidate_ranks.get(
                (round(self.last_target.x_km / 0.005), round(self.last_target.y_km / 0.005))
            )
            rescue_tier_improves = False
            if held_rank is not None and best_position != self.last_target:
                rescue_tier_improves = (
                    (
                        best_rank[0] > held_rank[0]
                        or best_rank[1] > held_rank[1]
                        or best_rank[3] > held_rank[3]
                        or best_rank[4] > held_rank[4]
                    )
                    if self.rescue_priority_enabled
                    else best_rank[0] > held_rank[0]
                )
                if self.suppress_switch_without_rescue_gain and not rescue_tier_improves:
                    # Keep a committed route unless projected rescue service
                    # improves. Recovery time still ranks candidate targets,
                    # but a small frozen-state estimate alone cannot justify
                    # a route switch under mobile users.
                    best_position = self.last_target
                    best_rank = held_rank

        if best_position is None:
            reason = self._select_infeasible_reason(infeasible)
            return self._infeasible(diagnosis, trigger, reason, tuple(sorted(infeasible)))

        previous_target = self.last_target
        if previous_target is not None and distance_km(
            previous_target.x_km,
            previous_target.y_km,
            best_position.x_km,
            best_position.y_km,
        ) > self.config.base.policy_search_grid_km / 2.0:
            self.target_switch_count += 1
        self.last_target = best_position
        best_key = (round(best_position.x_km / 0.005), round(best_position.y_km / 0.005))
        self.last_planned_sortie_energy_wh = candidate_energies[best_key]
        dx = best_position.x_km - start.x_km
        dy = best_position.y_km - start.y_km
        distance_to_target = math.hypot(dx, dy)
        heading = (dx / distance_to_target, dy / distance_to_target) if distance_to_target > 1e-12 else (0.0, 0.0)
        destination = Position(
            start.x_km + heading[0] * min(distance_to_target, move_limit),
            start.y_km + heading[1] * min(distance_to_target, move_limit),
        )
        return ControlDecision(
            deploy=True,
            heading_x=heading[0],
            heading_y=heading[1],
            destination=destination,
            reason="lexicographic_rescue_action_selected",
            trigger=trigger,
            decision_made=True,
            # For compatibility with the existing replay API this field holds
            # only the primary rescue-user-tick objective, not a weighted sum.
            objective_score=float(best_rank[0]) if best_rank else None,
            infeasible_reasons=tuple(sorted(infeasible)),
            diagnosis=diagnosis,
        )

