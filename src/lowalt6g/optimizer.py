"""Rolling-horizon beam-search controller for dynamic UAV relay scheduling.

This is a deterministic online optimizer. It is not a trained machine-learning
model: each replan searches a finite set of short movement sequences against the
current observed network state and configured objective/constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics

from .config import StationConfig
from .dynamic_config import DynamicExperimentConfig
from .energy_budget import return_energy_wh, sortie_energy_wh
from .engine import distance_km, evaluate_network
from .models import Network, NetworkSnapshot, Position, User
from .policies import GreedyRelayPolicy


@dataclass(frozen=True)
class NetworkDiagnosis:
    failed_station_ids: tuple[str, ...]
    disconnected_user_ids: tuple[str, ...]
    uncovered_user_ids: tuple[str, ...]
    capacity_blocked_user_ids: tuple[str, ...]
    disconnected_rescue_ids: tuple[str, ...]
    congested_resource_ids: tuple[str, ...]
    drone_backhaul_available: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "failed_station_ids": list(self.failed_station_ids),
            "disconnected_user_ids": list(self.disconnected_user_ids),
            "uncovered_user_ids": list(self.uncovered_user_ids),
            "capacity_blocked_user_ids": list(self.capacity_blocked_user_ids),
            "disconnected_rescue_ids": list(self.disconnected_rescue_ids),
            "congested_resource_ids": list(self.congested_resource_ids),
            "drone_backhaul_available": self.drone_backhaul_available,
        }


@dataclass(frozen=True)
class ControlDecision:
    deploy: bool
    heading_x: float
    heading_y: float
    destination: Position | None
    reason: str
    trigger: str
    decision_made: bool
    objective_score: float | None
    infeasible_reasons: tuple[str, ...]
    diagnosis: NetworkDiagnosis
    decision_time_ms: float = 0.0

    def to_event(self, time_s: int) -> dict[str, object]:
        return {
            "time_s": time_s,
            "event_type": "optimizer_decision" if self.decision_made else "optimizer_hold",
            "reason": self.reason,
            "trigger": self.trigger,
            "deploy": self.deploy,
            "heading": [round(self.heading_x, 6), round(self.heading_y, 6)],
            "destination_km": (
                [round(self.destination.x_km, 6), round(self.destination.y_km, 6)]
                if self.destination
                else None
            ),
            "objective_score": round(self.objective_score, 6) if self.objective_score is not None else None,
            "decision_time_ms": round(self.decision_time_ms, 6),
            "infeasible_reasons": list(self.infeasible_reasons),
            "diagnosis": self.diagnosis.to_dict(),
        }


def diagnose_network(
    network: Network,
    snapshot: NetworkSnapshot,
    congestion_threshold: float,
) -> NetworkDiagnosis:
    """Classify failures, disconnected users, coverage gaps, and congestion."""
    by_id = {outcome.user_id: outcome for outcome in snapshot.outcomes}
    return NetworkDiagnosis(
        failed_station_ids=tuple(sorted(station.id for station in network.stations if not station.healthy)),
        disconnected_user_ids=tuple(sorted(key for key, item in by_id.items() if not item.connected)),
        uncovered_user_ids=tuple(sorted(key for key, item in by_id.items() if not item.covered)),
        capacity_blocked_user_ids=tuple(
            sorted(key for key, item in by_id.items() if item.covered and not item.connected)
        ),
        disconnected_rescue_ids=tuple(
            sorted(key for key, item in by_id.items() if item.group == "rescue" and not item.connected)
        ),
        congested_resource_ids=tuple(
            sorted(
                key
                for key, utilization in snapshot.resource_utilization.items()
                if utilization >= congestion_threshold
            )
        ),
        drone_backhaul_available=network.drone_backhaul_available,
    )


@dataclass(frozen=True)
class _BeamNode:
    position: Position
    battery_wh: float
    cumulative_score: float
    first_heading: tuple[float, float] | None


_DIAGONAL = 1.0 / math.sqrt(2.0)
_HEADINGS: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (1.0, 0.0),
    (-1.0, 0.0),
    (0.0, 1.0),
    (0.0, -1.0),
    (_DIAGONAL, _DIAGONAL),
    (_DIAGONAL, -_DIAGONAL),
    (-_DIAGONAL, _DIAGONAL),
    (-_DIAGONAL, -_DIAGONAL),
)


class RollingHorizonOptimizer:
    """Beam-search an H-step control sequence and execute only its first move."""

    name = "rolling_horizon_mpc"

    def __init__(self, config: DynamicExperimentConfig) -> None:
        self.config = config
        self.last_signature: tuple[object, ...] | None = None
        self.last_decision_time_s: int | None = None
        self.heading = (0.0, 0.0)
        self.deployed = False

    def observe(
        self,
        time_s: int,
        network: Network,
        snapshot: NetworkSnapshot,
        diagnosis: NetworkDiagnosis,
        battery_wh: float,
    ) -> ControlDecision:
        signature = self._state_signature(network, snapshot, diagnosis)
        if self.last_signature is None:
            trigger = "initial_observation"
        elif signature != self.last_signature:
            trigger = "network_state_changed"
        elif self.last_decision_time_s is None or time_s - self.last_decision_time_s >= self._periodic_replan_interval_s():
            trigger = "periodic_replan"
        else:
            return ControlDecision(
                deploy=self.deployed,
                heading_x=self.heading[0],
                heading_y=self.heading[1],
                destination=None,
                reason="hold_previous_action",
                trigger="state_unchanged",
                decision_made=False,
                objective_score=None,
                infeasible_reasons=(),
                diagnosis=diagnosis,
            )

        self.last_signature = signature
        self.last_decision_time_s = time_s
        decision = self._optimize(network, snapshot, diagnosis, battery_wh, trigger)
        self.heading = (decision.heading_x, decision.heading_y)
        self.deployed = decision.deploy
        return decision

    def _periodic_replan_interval_s(self) -> int:
        return self.config.decision_interval_s

    def _optimize(
        self,
        network: Network,
        current_snapshot: NetworkSnapshot,
        diagnosis: NetworkDiagnosis,
        battery_wh: float,
        trigger: str,
    ) -> ControlDecision:
        if not any(station.healthy for station in network.stations):
            return self._infeasible(diagnosis, trigger, "no_healthy_base_station")
        if not network.drone_backhaul_available:
            return self._infeasible(diagnosis, trigger, "drone_backhaul_temporarily_unavailable")
        if battery_wh <= self.config.reserve_wh:
            return self._infeasible(diagnosis, trigger, "battery_at_or_below_reserve")

        start = network.drone.position
        healthy_stations = tuple(station for station in network.stations if station.healthy)
        rescue_targets = [
            user for user in network.users if user.group == "rescue" and not current_snapshot_by_id(current_snapshot, user.id)
        ]
        # Coverage failures can include users whose data demand is blocked by
        # capacity; use all disconnected users only after the rescue queue clears.
        if rescue_targets:
            targets = rescue_targets
        else:
            disconnected = set(diagnosis.disconnected_user_ids)
            targets = [user for user in network.users if user.id in disconnected]
        target_positions = self._feasible_relay_positions(network, targets, healthy_stations)

        beam = [_BeamNode(start, battery_wh, 0.0, None)]
        infeasible: set[str] = set()
        time_step_s = self.config.time_step_s
        move_limit = network.drone_spec.speed_km_per_s * time_step_s

        for _depth in range(self.config.prediction_horizon_steps):
            candidates: list[_BeamNode] = []
            seen: set[tuple[int, int, int]] = set()
            for node in beam:
                for heading in self._action_headings(node.position, target_positions):
                    x = node.position.x_km + heading[0] * move_limit
                    y = node.position.y_km + heading[1] * move_limit
                    if not (0 <= x <= network.config.city_width_km and 0 <= y <= network.config.city_height_km):
                        infeasible.add("city_boundary")
                        continue
                    position = Position(x, y)
                    if not any(
                        distance_km(x, y, station.x_km, station.y_km)
                        <= network.drone_spec.backhaul_radius_km
                        for station in healthy_stations
                    ):
                        infeasible.add("no_backhaul_link_at_candidate_position")
                        continue

                    forecast = evaluate_network(
                        network,
                        drone_position=(x, y),
                        drone_active=True,
                    )
                    relay_in_use = any(
                        outcome.connected and outcome.path_kind == "drone_relay"
                        for outcome in forecast.outcomes
                    )
                    movement_energy = distance_km(
                        node.position.x_km,
                        node.position.y_km,
                        position.x_km,
                        position.y_km,
                    ) * self.config.movement_wh_per_km
                    operation_power = self.config.hover_power_w + (
                        self.config.relay_power_w if relay_in_use else 0.0
                    )
                    energy = movement_energy + operation_power * time_step_s / 3600.0
                    remaining = node.battery_wh - energy
                    if remaining < self.config.reserve_wh - 1e-9:
                        infeasible.add("battery_reserve_would_be_violated")
                        continue
                    return_energy = return_energy_wh(self.config, network, position)
                    if return_energy is None or remaining - return_energy < self.config.reserve_wh - 1e-9:
                        infeasible.add("return_energy_reserve_would_be_violated")
                        continue

                    reward = self._step_reward(
                        network,
                        forecast,
                        node.position,
                        position,
                        target_positions,
                        energy,
                    )
                    first_heading = node.first_heading if node.first_heading is not None else heading
                    key = (
                        round(x / 0.01),
                        round(y / 0.01),
                        round(remaining / 2.0),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(
                        _BeamNode(position, remaining, node.cumulative_score + reward, first_heading)
                    )
            if not candidates:
                break
            candidates.sort(
                key=lambda node: (
                    node.cumulative_score,
                    node.battery_wh,
                    -node.position.x_km,
                    -node.position.y_km,
                ),
                reverse=True,
            )
            beam = candidates[: self.config.beam_width]

        if not beam or beam[0].first_heading is None:
            reason = self._select_infeasible_reason(infeasible)
            return self._infeasible(diagnosis, trigger, reason, tuple(sorted(infeasible)))

        best = beam[0]
        move_limit = network.drone_spec.speed_km_per_s * self.config.time_step_s
        destination = Position(
            start.x_km + best.first_heading[0] * move_limit,
            start.y_km + best.first_heading[1] * move_limit,
        )
        return ControlDecision(
            deploy=True,
            heading_x=best.first_heading[0],
            heading_y=best.first_heading[1],
            destination=destination,
            reason="rolling_horizon_action_selected",
            trigger=trigger,
            decision_made=True,
            objective_score=best.cumulative_score,
            infeasible_reasons=tuple(sorted(infeasible)),
            diagnosis=diagnosis,
        )

    def _step_reward(
        self,
        network: Network,
        snapshot: NetworkSnapshot,
        previous: Position,
        candidate: Position,
        target_positions: tuple[Position, ...],
        energy_wh: float,
    ) -> float:
        rescue_count = sum(user.group == "rescue" for user in network.users)
        connected = sum(outcome.connected for outcome in snapshot.outcomes)
        rescue_connected = sum(
            outcome.connected for outcome in snapshot.outcomes if outcome.group == "rescue"
        )
        mean_latency = sum(
            outcome.latency_ms or 0.0
            for outcome in snapshot.outcomes
            if outcome.connected
        ) / max(connected, 1)
        latency_fraction = min(mean_latency / 200.0, 1.0)
        reward = self.config.rescue_service_weight * rescue_connected / max(rescue_count, 1)
        reward += self.config.connection_weight * connected / max(len(network.users), 1)
        if rescue_connected == rescue_count:
            reward += self.config.recovery_bonus
        reward -= self.config.latency_penalty_weight * latency_fraction
        reward -= self.config.energy_penalty_weight * energy_wh / self.config.battery_capacity_wh
        if target_positions:
            before = min(
                distance_km(previous.x_km, previous.y_km, target.x_km, target.y_km)
                for target in target_positions
            )
            after = min(
                distance_km(candidate.x_km, candidate.y_km, target.x_km, target.y_km)
                for target in target_positions
            )
            control_distance = network.drone_spec.speed_km_per_s * self.config.time_step_s
            progress_per_step = max(-1.0, min(1.0, (before - after) / max(control_distance, 1e-9)))
            reward += self.config.rescue_progress_weight * progress_per_step
        return reward

    def _feasible_relay_positions(
        self,
        network: Network,
        users: list[User],
        stations: tuple[StationConfig, ...],
    ) -> tuple[Position, ...]:
        """Return user-aware relay points at the nearest feasible access/backhaul intersection."""
        points: dict[tuple[int, int], Position] = {}
        for user in users:
            for station in stations:
                dx = user.x_km - station.x_km
                dy = user.y_km - station.y_km
                separation = math.hypot(dx, dy)
                if separation > network.drone_spec.backhaul_radius_km + network.drone_spec.access_radius_km:
                    continue
                if separation <= network.drone_spec.backhaul_radius_km:
                    point = Position(user.x_km, user.y_km)
                else:
                    ratio = network.drone_spec.backhaul_radius_km / separation
                    point = Position(station.x_km + dx * ratio, station.y_km + dy * ratio)
                if not (
                    0 <= point.x_km <= network.config.city_width_km
                    and 0 <= point.y_km <= network.config.city_height_km
                ):
                    continue
                if distance_km(point.x_km, point.y_km, user.x_km, user.y_km) > network.drone_spec.access_radius_km + 1e-9:
                    continue
                points[(round(point.x_km / 0.005), round(point.y_km / 0.005))] = point
        return tuple(points[key] for key in sorted(points))

    @staticmethod
    def _action_headings(
        current: Position,
        targets: tuple[Position, ...],
    ) -> tuple[tuple[float, float], ...]:
        """Combine local compass moves with direct pursuit vectors to feasible relay points."""
        directions = list(_HEADINGS)
        seen = {(round(x, 6), round(y, 6)) for x, y in directions}
        for target in targets:
            dx = target.x_km - current.x_km
            dy = target.y_km - current.y_km
            distance = math.hypot(dx, dy)
            if distance <= 1e-9:
                continue
            direction = (dx / distance, dy / distance)
            direction_key = (round(direction[0], 6), round(direction[1], 6))
            if direction_key not in seen:
                directions.append(direction)
                seen.add(direction_key)
        return tuple(directions)

    def _state_signature(
        self,
        network: Network,
        snapshot: NetworkSnapshot,
        diagnosis: NetworkDiagnosis,
    ) -> tuple[object, ...]:
        quantum = self.config.position_signature_quantum_km
        positions = tuple(
            (user.id, round(user.x_km / quantum), round(user.y_km / quantum), round(user.demand_mbps, 3))
            for user in network.users
        )
        utilizations = tuple(
            (key, round(value / 0.1)) for key, value in sorted(snapshot.resource_utilization.items())
        )
        return (
            tuple((station.id, station.healthy) for station in network.stations),
            network.drone_backhaul_available,
            diagnosis.disconnected_user_ids,
            diagnosis.congested_resource_ids,
            positions,
            utilizations,
        )

    def _infeasible(
        self,
        diagnosis: NetworkDiagnosis,
        trigger: str,
        reason: str,
        detail_reasons: tuple[str, ...] = (),
    ) -> ControlDecision:
        self.deployed = False
        self.heading = (0.0, 0.0)
        return ControlDecision(
            deploy=False,
            heading_x=0.0,
            heading_y=0.0,
            destination=None,
            reason=reason,
            trigger=trigger,
            decision_made=True,
            objective_score=None,
            infeasible_reasons=detail_reasons or (reason,),
            diagnosis=diagnosis,
        )

    @staticmethod
    def _select_infeasible_reason(reasons: set[str]) -> str:
        preferred = (
            "battery_reserve_would_be_violated",
            "return_energy_reserve_would_be_violated",
            "no_backhaul_link_at_candidate_position",
            "city_boundary",
        )
        return next((reason for reason in preferred if reason in reasons), "no_feasible_mpc_action")


class RescuePriorityOptimizer(RollingHorizonOptimizer):
    """Lexicographic MPC variant with explicit rescue-service priority.

    This remains deterministic optimization, not a trained model. It evaluates
    reachable grid and rescue-cluster targets over a short frozen-state horizon,
    then executes only the first movement and re-plans on material changes.
    """

    name = "lexicographic_rescue_mpc"

    def __init__(self, config: DynamicExperimentConfig) -> None:
        super().__init__(config)
        self.last_target: Position | None = None
        self.reference_target: Position | None = None
        self.last_planned_sortie_energy_wh = 0.0
        self.target_switch_count = 0

    def _state_signature(
        self,
        network: Network,
        snapshot: NetworkSnapshot,
        diagnosis: NetworkDiagnosis,
    ) -> tuple[object, ...]:
        # Re-plan immediately on changes to service, failures, backhaul or
        # material load; coarse rescue-position buckets avoid re-optimizing
        # on every small random-walk step.
        connected_counts = (
            sum(outcome.connected and outcome.group == "rescue" for outcome in snapshot.outcomes),
            sum(outcome.connected and outcome.group != "rescue" for outcome in snapshot.outcomes),
        )
        rescue_users = [user for user in network.users if user.group == "rescue"]
        rescue_centroid = (
            (
                round(statistics.fmean(user.x_km for user in rescue_users) / 0.5),
                round(statistics.fmean(user.y_km for user in rescue_users) / 0.5),
            )
            if rescue_users
            else None
        )
        offered_load = tuple(
            (
                group,
                round(sum(user.demand_mbps for user in network.users if user.group == group) / 0.25),
            )
            for group in ("rescue", "normal")
        )
        return (
            tuple((station.id, station.healthy) for station in network.stations),
            network.drone_backhaul_available,
            round(network.drone_backhaul_capacity_mbps, 3)
            if network.drone_backhaul_capacity_mbps is not None
            else None,
            connected_counts,
            diagnosis.congested_resource_ids,
            rescue_centroid,
            offered_load,
        )

    def _periodic_replan_interval_s(self) -> int:
        # The global target search is costlier than C's local beam expansion;
        # environment/service signature changes still trigger immediately.
        return max(60, self.config.decision_interval_s)

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
        target_positions = [entry[-1] for entry in sorted(geometrically_feasible)[:64]]
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
                float(rescue_user_ticks),
                float(predicted_recovery_ticks is not None),
                -float(predicted_recovery_ticks if predicted_recovery_ticks is not None else 10**9),
                float(target_rescue_count),
                float(final_rescue_count),
                projected_progress_km,
                float(ordinary_user_ticks),
                -latency_user_ms,
                -full_sortie_energy,
                -target_distance,
                -float(switches),
            )
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_position = target
            candidate_ranks[(round(target.x_km / 0.005), round(target.y_km / 0.005))] = rank

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
                    best_rank[0] > held_rank[0]
                    or best_rank[1] > held_rank[1]
                    or best_rank[3] > held_rank[3]
                    or best_rank[4] > held_rank[4]
                )
                if not rescue_tier_improves:
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
        self.last_planned_sortie_energy_wh = -best_rank[8]
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

    @staticmethod
    def _route_preserves_any_backhaul(
        network: Network,
        start: Position,
        target: Position,
        healthy_stations: tuple[StationConfig, ...],
        move_limit_km: float,
    ) -> bool:
        """Check the planned straight route against the union of healthy BS links."""
        if not healthy_stations or move_limit_km <= 0:
            return False
        distance = distance_km(start.x_km, start.y_km, target.x_km, target.y_km)
        ticks = max(1, math.ceil(distance / move_limit_km))
        for tick in range(ticks + 1):
            along = min(distance, tick * move_limit_km)
            ratio = along / distance if distance > 1e-12 else 0.0
            x = start.x_km + (target.x_km - start.x_km) * ratio
            y = start.y_km + (target.y_km - start.y_km) * ratio
            if min(
                distance_km(x, y, station.x_km, station.y_km)
                for station in healthy_stations
            ) > network.drone_spec.backhaul_radius_km + 1e-9:
                return False
        return True

    @staticmethod
    def _candidate_grid_positions(network: Network) -> list[Position]:
        step = network.config.policy_search_grid_km

        def axis(limit: float) -> tuple[float, ...]:
            count = int(math.floor(limit / step))
            values = [index * step for index in range(count + 1)]
            if not math.isclose(values[-1], limit, abs_tol=1e-9):
                values.append(limit)
            return tuple(values)

        return [
            Position(x, y)
            for x in axis(network.config.city_width_km)
            for y in axis(network.config.city_height_km)
        ]

    def _first_full_rescue_distance(
        self,
        network: Network,
        start: Position,
        target: Position,
        route_stations: tuple[StationConfig, ...],
        rescue_count: int,
    ) -> float | None:
        """Estimate first along-route point with a feasible full rescue service."""
        if rescue_count == 0:
            return 0.0
        dx = target.x_km - start.x_km
        dy = target.y_km - start.y_km
        route_length = math.hypot(dx, dy)
        if route_length <= 1e-12:
            unit = (0.0, 0.0)
        else:
            unit = (dx / route_length, dy / route_length)
        rescue_users = [user for user in network.users if user.group == "rescue"]
        best: float | None = None
        for station in route_stations:
            interval: tuple[float, float] | None = (0.0, route_length)
            circles = [
                (station.x_km, station.y_km, network.drone_spec.backhaul_radius_km),
                *(
                    (user.x_km, user.y_km, network.drone_spec.access_radius_km)
                    for user in rescue_users
                ),
            ]
            for cx, cy, radius in circles:
                circle_interval = _line_circle_interval(
                    start.x_km,
                    start.y_km,
                    unit[0],
                    unit[1],
                    route_length,
                    cx,
                    cy,
                    radius,
                )
                if circle_interval is None or interval is None:
                    interval = None
                    break
                interval = (max(interval[0], circle_interval[0]), min(interval[1], circle_interval[1]))
                if interval[0] > interval[1] + 1e-9:
                    interval = None
                    break
            if interval is None:
                continue
            low, high = interval
            probes = sorted({low, (low + high) / 2.0, high})
            for distance in probes:
                point = Position(start.x_km + unit[0] * distance, start.y_km + unit[1] * distance)
                snapshot = evaluate_network(
                    network,
                    drone_position=(point.x_km, point.y_km),
                    drone_active=True,
                )
                served = sum(
                    outcome.connected and outcome.group == "rescue" for outcome in snapshot.outcomes
                )
                if served == rescue_count:
                    best = distance if best is None else min(best, distance)
                    break
        return best

    def _rescue_cluster_positions(
        self,
        network: Network,
        rescue_users: list[User],
        stations: tuple[StationConfig, ...],
    ) -> tuple[Position, ...]:
        """Add feasible pair-intersection points serving two rescue users."""
        radius = network.drone_spec.access_radius_km
        pairs = sorted(
            [
                (
                    distance_km(left.x_km, left.y_km, right.x_km, right.y_km),
                    left,
                    right,
                )
                for index, left in enumerate(rescue_users)
                for right in rescue_users[index + 1 :]
            ],
            key=lambda pair: (pair[0], pair[1].id, pair[2].id),
        )
        points: list[Position] = []
        for separation, left, right in pairs[:12]:
            if separation <= 1e-9 or separation > 2.0 * radius:
                continue
            dx = (right.x_km - left.x_km) / separation
            dy = (right.y_km - left.y_km) / separation
            half = separation / 2.0
            height = math.sqrt(max(0.0, radius * radius - half * half))
            mx = (left.x_km + right.x_km) / 2.0
            my = (left.y_km + right.y_km) / 2.0
            for sign in (-1.0, 1.0):
                point = Position(mx - sign * dy * height, my + sign * dx * height)
                if not (0 <= point.x_km <= network.config.city_width_km):
                    continue
                if not (0 <= point.y_km <= network.config.city_height_km):
                    continue
                if any(
                    distance_km(point.x_km, point.y_km, station.x_km, station.y_km)
                    <= network.drone_spec.backhaul_radius_km
                    for station in stations
                ):
                    points.append(point)
        if rescue_users:
            for station in stations:
                centroid = Position(
                    sum(user.x_km for user in rescue_users) / len(rescue_users),
                    sum(user.y_km for user in rescue_users) / len(rescue_users),
                )
                station_distance = distance_km(
                    centroid.x_km, centroid.y_km, station.x_km, station.y_km
                )
                if station_distance > network.drone_spec.backhaul_radius_km and station_distance > 0:
                    ratio = network.drone_spec.backhaul_radius_km / station_distance
                    centroid = Position(
                        station.x_km + (centroid.x_km - station.x_km) * ratio,
                        station.y_km + (centroid.y_km - station.y_km) * ratio,
                    )
                if not (
                    0 <= centroid.x_km <= network.config.city_width_km
                    and 0 <= centroid.y_km <= network.config.city_height_km
                ):
                    continue
                covered = sum(
                    distance_km(centroid.x_km, centroid.y_km, user.x_km, user.y_km) <= radius
                    for user in rescue_users
                )
                if covered >= 2 and distance_km(
                    centroid.x_km, centroid.y_km, station.x_km, station.y_km
                ) <= network.drone_spec.backhaul_radius_km + 1e-9:
                    points.append(centroid)
        return self._unique_positions(points)

    @staticmethod
    def _unique_positions(positions: list[Position] | tuple[Position, ...]) -> list[Position]:
        unique: dict[tuple[int, int], Position] = {}
        for point in positions:
            unique.setdefault((round(point.x_km / 0.005), round(point.y_km / 0.005)), point)
        return [unique[key] for key in sorted(unique)]


def current_snapshot_by_id(snapshot: NetworkSnapshot, user_id: str) -> bool:
    return next(
        (outcome.connected for outcome in snapshot.outcomes if outcome.user_id == user_id),
        False,
    )


def _line_circle_interval(
    start_x: float,
    start_y: float,
    unit_x: float,
    unit_y: float,
    route_length: float,
    center_x: float,
    center_y: float,
    radius: float,
) -> tuple[float, float] | None:
    """Return the route-distance interval inside a circle, clipped to route."""
    dx = center_x - start_x
    dy = center_y - start_y
    projection = dx * unit_x + dy * unit_y
    perpendicular_sq = max(0.0, dx * dx + dy * dy - projection * projection)
    remainder = radius * radius - perpendicular_sq
    if remainder < -1e-9:
        return None
    half_chord = math.sqrt(max(0.0, remainder))
    low = max(0.0, projection - half_chord)
    high = min(route_length, projection + half_chord)
    return (low, high) if low <= high + 1e-9 else None
