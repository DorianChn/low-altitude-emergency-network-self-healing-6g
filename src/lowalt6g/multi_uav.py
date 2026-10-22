"""Fleet state, shared-resource network evaluation, and F/G placement policies.

This module is an extension alongside the single-UAV engine. It leaves the
historical single-drone Network and policy contracts unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
import math
import time
from typing import Iterable

from .dynamic_config import DynamicExperimentConfig
from .engine import distance_km
from .models import Network, Position


@dataclass(frozen=True)
class MultiUAVOptions:
    grid_spacing_km: float = 1.0
    candidate_limit: int = 6
    min_separation_km: float = 0.75
    replan_interval_s: int = 60
    decision_timeout_ms: float = 2000.0
    max_joint_combinations: int = 512
    sortie_service_budget_steps: int = 3

    def validate(self, time_step_s: int) -> None:
        if self.grid_spacing_km <= 0:
            raise ValueError("grid_spacing_km must be positive")
        if self.candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")
        if self.min_separation_km <= 0:
            raise ValueError("min_separation_km must be positive")
        if self.replan_interval_s <= 0 or self.replan_interval_s % time_step_s:
            raise ValueError("replan_interval_s must be a positive time-step multiple")
        if self.decision_timeout_ms < 0 or self.max_joint_combinations < 1:
            raise ValueError("search limits must be non-negative and positive respectively")
        if self.sortie_service_budget_steps < 1:
            raise ValueError("sortie_service_budget_steps must be positive")


@dataclass
class UAVState:
    """One simulated UAV with independent position, battery, task and logs."""

    id: str
    position: Position
    target_position: Position | None
    battery_wh: float
    reserve_wh: float
    access_capacity_mbps: float
    backhaul_capacity_mbps: float | None
    access_link_available: bool = True
    backhaul_link_available: bool = True
    active: bool = False
    task: str = "standby"
    task_status: str = "standby"
    served_user_ids: set[str] = field(default_factory=set)
    trajectory: list[dict[str, object]] = field(default_factory=list)
    energy_log: list[dict[str, object]] = field(default_factory=list)
    energy_consumed_wh: float = 0.0
    target_switch_count: int = 0


@dataclass(frozen=True)
class FleetUserOutcome:
    user_id: str
    group: str
    priority: int
    covered: bool
    connected: bool
    path_kind: str | None
    latency_ms: float | None
    serving_station_id: str | None
    serving_uav_id: str | None


@dataclass(frozen=True)
class FleetSnapshot:
    outcomes: tuple[FleetUserOutcome, ...]
    resource_utilization: dict[str, float]
    resource_capacity_mbps: dict[str, float]
    resource_used_mbps: dict[str, float]
    relay_candidate_count_by_user: dict[str, int]
    capacity_blocked_user_ids: tuple[str, ...]

    def outcome_map(self) -> dict[str, FleetUserOutcome]:
        return {outcome.user_id: outcome for outcome in self.outcomes}


@dataclass(frozen=True)
class FleetDecision:
    strategy_id: str
    targets: dict[str, Position | None]
    reason: str
    infeasible_reason: str | None
    objective: tuple[float, ...] | None
    candidate_evaluations: int
    collision_rejections: int
    timed_out: bool
    compute_ms: float


@dataclass(frozen=True)
class _Path:
    station_id: str
    uav_id: str | None
    kind: str
    distance_km: float
    base_latency_ms: float
    resources: tuple[str, ...]


def create_fleet(
    network: Network,
    config: DynamicExperimentConfig,
    count: int,
    *,
    minimum_separation_km: float,
) -> list[UAVState]:
    """Create a deterministic staged fleet near the legacy UAV start point."""

    if count < 1:
        raise ValueError("fleet size must be positive")
    width = network.config.city_width_km
    height = network.config.city_height_km
    origin = Position(network.drone_spec.x_km, network.drone_spec.y_km)
    spacing = minimum_separation_km + 0.25
    staging: list[Position] = []
    ring = 0
    while len(staging) < count:
        if ring == 0:
            offsets = ((0.0, 0.0),)
        else:
            offsets = tuple(
                (dx * spacing, dy * spacing)
                for dx in range(-ring, ring + 1)
                for dy in range(-ring, ring + 1)
                if max(abs(dx), abs(dy)) == ring
            )
        candidates = [
            Position(round(origin.x_km + dx, 6), round(origin.y_km + dy, 6))
            for dx, dy in offsets
            if 0 <= origin.x_km + dx <= width and 0 <= origin.y_km + dy <= height
        ]
        candidates.sort(
            key=lambda point: (
                distance_km(origin.x_km, origin.y_km, point.x_km, point.y_km),
                point.x_km,
                point.y_km,
            )
        )
        for candidate in candidates:
            if all(
                distance_km(
                    candidate.x_km,
                    candidate.y_km,
                    existing.x_km,
                    existing.y_km,
                )
                >= minimum_separation_km - 1e-9
                for existing in staging
            ):
                staging.append(candidate)
                if len(staging) == count:
                    break
        ring += 1
        if ring > 2 * math.ceil(max(width, height) / max(spacing, 1e-6)):
            raise ValueError("cannot place fleet within the configured city boundary")

    return [
        UAVState(
            id=network.drone_spec.id if index == 0 else f"uav-relay-{index + 1}",
            position=position,
            target_position=None,
            battery_wh=config.initial_battery_wh,
            reserve_wh=config.reserve_wh,
            access_capacity_mbps=network.drone_spec.capacity_mbps,
            backhaul_capacity_mbps=network.drone_backhaul_capacity_mbps,
        )
        for index, position in enumerate(staging)
    ]


def evaluate_fleet(
    network: Network,
    uavs: Iterable[UAVState],
    *,
    positions: dict[str, Position] | None = None,
    active_ids: set[str] | None = None,
) -> FleetSnapshot:
    """Allocate each user once against shared station and per-UAV capacity.

    Every relayed user consumes the serving station's one shared capacity
    budget, the serving UAV's access capacity, and (when configured) that
    UAV's backhaul budget. This is an aggregate-capacity abstraction; it does
    not model co-channel interference between UAVs.
    """

    units = tuple(sorted(uavs, key=lambda item: item.id))
    active = active_ids if active_ids is not None else {unit.id for unit in units if unit.active}
    position_map = positions or {}
    healthy = tuple(station for station in network.stations if station.healthy)
    capacities: dict[str, float] = {
        f"station:{station.id}": station.capacity_mbps for station in healthy
    }
    by_id = {unit.id: unit for unit in units}
    for unit in units:
        if unit.id not in active:
            continue
        capacities[f"uav:{unit.id}"] = unit.access_capacity_mbps
        if unit.backhaul_capacity_mbps is not None:
            capacities[f"backhaul:{unit.id}"] = unit.backhaul_capacity_mbps

    paths_by_user: dict[str, list[_Path]] = {}
    relay_candidates: dict[str, set[str]] = {}
    for user in network.users:
        paths: list[_Path] = []
        relays: set[str] = set()
        for station in healthy:
            direct_distance = distance_km(
                station.x_km, station.y_km, user.x_km, user.y_km
            )
            if direct_distance <= station.coverage_radius_km + 1e-9:
                paths.append(
                    _Path(
                        station_id=station.id,
                        uav_id=None,
                        kind="direct",
                        distance_km=direct_distance,
                        base_latency_ms=(
                            network.latency.base_latency_ms
                            + direct_distance * network.latency.propagation_ms_per_km
                        ),
                        resources=(f"station:{station.id}",),
                    )
                )
            for unit in units:
                if unit.id not in active or not unit.access_link_available:
                    continue
                if not network.drone_backhaul_available or not unit.backhaul_link_available:
                    continue
                position = position_map.get(unit.id, unit.position)
                access_distance = distance_km(
                    position.x_km, position.y_km, user.x_km, user.y_km
                )
                backhaul_distance = distance_km(
                    position.x_km, position.y_km, station.x_km, station.y_km
                )
                if (
                    access_distance > network.drone_spec.access_radius_km + 1e-9
                    or backhaul_distance > network.drone_spec.backhaul_radius_km + 1e-9
                ):
                    continue
                resources = [f"station:{station.id}", f"uav:{unit.id}"]
                if unit.backhaul_capacity_mbps is not None:
                    resources.append(f"backhaul:{unit.id}")
                distance = access_distance + backhaul_distance
                paths.append(
                    _Path(
                        station_id=station.id,
                        uav_id=unit.id,
                        kind="uav_relay",
                        distance_km=distance,
                        base_latency_ms=(
                            network.latency.base_latency_ms
                            + distance * network.latency.propagation_ms_per_km
                            + network.latency.relay_processing_ms
                        ),
                        resources=tuple(resources),
                    )
                )
                relays.add(unit.id)
        paths.sort(
            key=lambda path: (
                path.base_latency_ms,
                path.station_id,
                path.uav_id or "",
                path.kind,
            )
        )
        paths_by_user[user.id] = paths
        relay_candidates[user.id] = relays

    remaining = dict(capacities)
    used: dict[str, float] = {resource: 0.0 for resource in capacities}
    selected: dict[str, _Path] = {}
    capacity_blocked: list[str] = []
    for user in sorted(network.users, key=lambda item: (-item.priority, item.id)):
        candidates = paths_by_user[user.id]
        chosen = next(
            (
                path
                for path in candidates
                if all(
                    remaining.get(resource, 0.0) + 1e-9 >= user.demand_mbps
                    for resource in path.resources
                )
            ),
            None,
        )
        if chosen is None:
            if candidates:
                capacity_blocked.append(user.id)
            continue
        selected[user.id] = chosen
        for resource in chosen.resources:
            remaining[resource] -= user.demand_mbps
            used[resource] += user.demand_mbps

    outcomes: list[FleetUserOutcome] = []
    for user in network.users:
        path = selected.get(user.id)
        candidates = paths_by_user[user.id]
        if path is None:
            outcomes.append(
                FleetUserOutcome(
                    user_id=user.id,
                    group=user.group,
                    priority=user.priority,
                    covered=bool(candidates),
                    connected=False,
                    path_kind=None,
                    latency_ms=None,
                    serving_station_id=None,
                    serving_uav_id=None,
                )
            )
            continue
        queue_delay = sum(
            _queue_delay(used.get(resource, 0.0), capacities[resource], network)
            for resource in path.resources
        )
        outcomes.append(
            FleetUserOutcome(
                user_id=user.id,
                group=user.group,
                priority=user.priority,
                covered=True,
                connected=True,
                path_kind=path.kind,
                latency_ms=path.base_latency_ms + queue_delay,
                serving_station_id=path.station_id,
                serving_uav_id=path.uav_id,
            )
        )

    utilization = {
        resource: used[resource] / capacity if capacity > 0 else 0.0
        for resource, capacity in capacities.items()
    }
    return FleetSnapshot(
        outcomes=tuple(outcomes),
        resource_utilization=utilization,
        resource_capacity_mbps=capacities,
        resource_used_mbps=used,
        relay_candidate_count_by_user={
            user_id: len(values) for user_id, values in relay_candidates.items()
        },
        capacity_blocked_user_ids=tuple(sorted(capacity_blocked)),
    )


def plan_fleet(
    strategy_id: str,
    network: Network,
    uavs: list[UAVState],
    config: DynamicExperimentConfig,
    options: MultiUAVOptions,
) -> FleetDecision:
    """Run F (independent greedy + safety arbitration) or G (joint search)."""

    options.validate(config.time_step_s)
    if strategy_id not in {"F_independent_greedy", "G_centralized_coordination"}:
        raise ValueError(f"unsupported multi-UAV strategy: {strategy_id}")
    started = time.perf_counter()
    if not any(station.healthy for station in network.stations):
        return FleetDecision(
            strategy_id,
            {unit.id: _current_hold_target(unit) for unit in uavs},
            "no_healthy_base_station",
            "no_healthy_backhaul_endpoint",
            None,
            0,
            0,
            False,
            (time.perf_counter() - started) * 1000.0,
        )

    deadline = started + options.decision_timeout_ms / 1000.0
    candidate_positions = _candidate_positions(network, uavs, options)
    evaluations = 0
    try:
        rankings: dict[str, list[tuple[tuple[float, ...], Position | None]]] = {}
        base_snapshot = evaluate_fleet(network, uavs, active_ids=set())
        base_rescue_connected = sum(
            outcome.connected
            for outcome in base_snapshot.outcomes
            if outcome.group == "rescue"
        )
        for unit in sorted(uavs, key=lambda item: item.id):
            ranking, used_evaluations = _rank_individual_actions(
                network,
                uavs,
                unit,
                candidate_positions,
                base_snapshot,
                config,
                options,
                deadline,
            )
            rankings[unit.id] = ranking
            evaluations += used_evaluations
        if strategy_id == "F_independent_greedy":
            targets, conflicts = _independent_actions(
                uavs, rankings, options.min_separation_km
            )
            reason = "independent_greedy_targets_selected"
            infeasible = None
            objective = None
            timed_out = False
        else:
            targets, objective, joint_evaluations, conflicts = _joint_actions(
                network,
                uavs,
                rankings,
                config,
                options,
                deadline,
            )
            evaluations += joint_evaluations
            if objective is None:
                reason = "decision_timeout" if time.perf_counter() >= deadline else "no_feasible_joint_assignment"
                infeasible = "joint_search_budget_or_safety_constraints"
                timed_out = reason == "decision_timeout"
            else:
                reason = "joint_lexicographic_assignment_selected"
                infeasible = None
                timed_out = False
        any_relay_candidate = any(
            target is not None
            for ranking in rankings.values()
            for _, target in ranking
        )
        if (
            base_rescue_connected < sum(user.group == "rescue" for user in network.users)
            and not any_relay_candidate
        ):
            targets = {unit.id: _current_hold_target(unit) for unit in uavs}
            reason = "no_feasible_relay_path_for_unserved_rescue_users"
            infeasible = "no candidate satisfies healthy backhaul, access range, spacing and sortie reserve"
            objective = None
            timed_out = False
    except _SearchTimeout:
        targets = {unit.id: _current_hold_target(unit) for unit in uavs}
        objective = None
        conflicts = 0
        reason = "decision_timeout"
        infeasible = "planning_deadline_exceeded; prior safe targets retained"
        timed_out = True

    if strategy_id == "F_independent_greedy" and infeasible is None and not any(
        target is not None for target in targets.values()
    ):
        reason = "no_individually_feasible_service_gain"
        infeasible = "no_candidate_adds_service_within_route_energy_and_spacing_constraints"
    return FleetDecision(
        strategy_id=strategy_id,
        targets=targets,
        reason=reason,
        infeasible_reason=infeasible,
        objective=objective,
        candidate_evaluations=evaluations,
        collision_rejections=conflicts,
        timed_out=timed_out,
        compute_ms=(time.perf_counter() - started) * 1000.0,
    )


def _rank_individual_actions(
    network: Network,
    uavs: list[UAVState],
    unit: UAVState,
    candidates: list[Position],
    base_snapshot: FleetSnapshot,
    config: DynamicExperimentConfig,
    options: MultiUAVOptions,
    deadline: float,
) -> tuple[list[tuple[tuple[float, ...], Position | None]], int]:
    evaluations = 0
    base_rescue = sum(
        outcome.connected for outcome in base_snapshot.outcomes if outcome.group == "rescue"
    )
    base_total = sum(outcome.connected for outcome in base_snapshot.outcomes)
    if unit.active:
        hold_snapshot = evaluate_fleet(
            network,
            uavs,
            positions={unit.id: unit.position},
            active_ids={unit.id},
        )
        hold_rescue = sum(
            outcome.connected for outcome in hold_snapshot.outcomes if outcome.group == "rescue"
        )
        hold_total = sum(outcome.connected for outcome in hold_snapshot.outcomes)
        hold_latency = sum(
            float(outcome.latency_ms or 0.0)
            for outcome in hold_snapshot.outcomes
            if outcome.connected
        )
        hold_score = _single_score(
            hold_rescue, 0.0, hold_total, hold_latency, 0.0, 0.0, unit.position
        )
        actions: list[tuple[tuple[float, ...], Position | None]] = [(hold_score, None)]
        evaluations += 1
    else:
        ground_latency = 0.0
        actions = [
            (
                _single_score(
                    base_rescue, 0.0, base_total, ground_latency, 0.0, 0.0, unit.position
                ),
                None,
            )
        ]

    rescue_users = tuple(user for user in network.users if user.group == "rescue")
    healthy = tuple(station for station in network.stations if station.healthy)
    for candidate in candidates:
        if time.perf_counter() >= deadline:
            raise _SearchTimeout
        if not _has_relay_route(network, candidate, rescue_users, healthy):
            continue
        estimate = _sortie_energy_wh(
            config, network, unit, candidate, options.sortie_service_budget_steps
        )
        if estimate is None or unit.battery_wh - estimate < unit.reserve_wh - 1e-9:
            continue
        snapshot = evaluate_fleet(
            network,
            uavs,
            positions={unit.id: candidate},
            active_ids={unit.id},
        )
        evaluations += 1
        rescue = sum(
            outcome.connected for outcome in snapshot.outcomes if outcome.group == "rescue"
        )
        total = sum(outcome.connected for outcome in snapshot.outcomes)
        latency = sum(
            float(outcome.latency_ms or 0.0)
            for outcome in snapshot.outcomes
            if outcome.connected
        )
        travel = distance_km(
            unit.position.x_km,
            unit.position.y_km,
            candidate.x_km,
            candidate.y_km,
        )
        actions.append(
            (
                _single_score(
                    rescue,
                    travel / network.drone_spec.speed_km_per_s,
                    total,
                    latency,
                    estimate,
                    travel,
                    candidate,
                ),
                candidate,
            )
        )
    actions.sort(key=lambda item: item[0], reverse=True)
    # A null action is a real option: leave a grounded UAV on standby or hold
    # the current position, rather than launching for no service gain.
    return actions, evaluations


def _single_score(
    rescue: int,
    arrival_time_s: float,
    total: int,
    latency: float,
    energy: float,
    travel: float,
    position: Position,
) -> tuple[float, ...]:
    return (
        float(rescue),
        -arrival_time_s,
        float(total),
        -latency,
        -energy,
        -travel,
        -position.x_km,
        -position.y_km,
    )


def _independent_actions(
    uavs: list[UAVState],
    rankings: dict[str, list[tuple[tuple[float, ...], Position | None]]],
    minimum_separation_km: float,
) -> tuple[dict[str, Position | None], int]:
    chosen: dict[str, Position | None] = {}
    conflicts = 0
    ordered = sorted(uavs, key=lambda item: item.id)
    for unit in ordered:
        options = rankings.get(unit.id, [])
        accepted = False
        for _, target in options:
            trial = dict(chosen)
            trial[unit.id] = target
            if _targets_separated(ordered, trial, minimum_separation_km):
                chosen[unit.id] = target
                accepted = True
                break
            conflicts += 1
        if not accepted:
            chosen[unit.id] = _current_hold_target(unit)
        # Future independent choices initially stand by at their current
        # locations; active units continue to hold. This lets the safety
        # arbiter reject a crossing route before committing this target.
    return chosen, conflicts


def _joint_actions(
    network: Network,
    uavs: list[UAVState],
    rankings: dict[str, list[tuple[tuple[float, ...], Position | None]]],
    config: DynamicExperimentConfig,
    options: MultiUAVOptions,
    deadline: float,
) -> tuple[dict[str, Position | None], tuple[float, ...] | None, int, int]:
    ordered = sorted(uavs, key=lambda item: item.id)
    action_lists: list[list[Position | None]] = []
    for unit in ordered:
        unique: list[Position | None] = [None]
        for _, candidate in rankings.get(unit.id, []):
            if candidate is None:
                continue
            if all(
                distance_km(candidate.x_km, candidate.y_km, prior.x_km, prior.y_km) > 1e-6
                for prior in unique
                if prior is not None
            ):
                unique.append(candidate)
            if len(unique) >= options.candidate_limit + 1:
                break
        action_lists.append(unique)

    best_targets: dict[str, Position | None] | None = None
    best_score: tuple[float, ...] | None = None
    evaluations = 0
    conflicts = 0
    for actions in product(*action_lists):
        if time.perf_counter() >= deadline:
            raise _SearchTimeout
        if evaluations >= options.max_joint_combinations:
            break
        targets = {unit.id: action for unit, action in zip(ordered, actions, strict=True)}
        if not _targets_separated(ordered, targets, options.min_separation_km):
            conflicts += 1
            continue
        active_ids = {
            unit.id
            for unit, action in zip(ordered, actions, strict=True)
            if action is not None or unit.active
        }
        positions = {
            unit.id: (
                action
                if action is not None
                else unit.position
            )
            for unit, action in zip(ordered, actions, strict=True)
            if unit.id in active_ids
        }
        energy_cost = 0.0
        movement_cost = 0.0
        switch_cost = 0
        feasible = True
        for unit, action in zip(ordered, actions, strict=True):
            destination = action if action is not None else unit.position
            if unit.id in active_ids:
                estimate = _sortie_energy_wh(
                    config,
                    network,
                    unit,
                    destination,
                    options.sortie_service_budget_steps,
                )
                if estimate is None or unit.battery_wh - estimate < unit.reserve_wh - 1e-9:
                    feasible = False
                    break
                energy_cost += estimate
            movement_cost += distance_km(
                unit.position.x_km,
                unit.position.y_km,
                destination.x_km,
                destination.y_km,
            )
            old_target = unit.target_position or unit.position
            new_target = destination
            if distance_km(
                old_target.x_km,
                old_target.y_km,
                new_target.x_km,
                new_target.y_km,
            ) > 0.15:
                switch_cost += 1
        if not feasible:
            continue
        snapshot = evaluate_fleet(
            network,
            uavs,
            positions=positions,
            active_ids=active_ids,
        )
        evaluations += 1
        outcomes = snapshot.outcomes
        rescue = sum(outcome.connected for outcome in outcomes if outcome.group == "rescue")
        rescue_total = sum(outcome.group == "rescue" for outcome in outcomes)
        total = sum(outcome.connected for outcome in outcomes)
        rescue_latency = sum(
            float(outcome.latency_ms or 0.0)
            for outcome in outcomes
            if outcome.group == "rescue" and outcome.connected
        )
        all_latency = sum(
            float(outcome.latency_ms or 0.0)
            for outcome in outcomes
            if outcome.connected
        )
        uav_by_id = {unit.id: unit for unit in ordered}
        rescue_arrival_times = [
            distance_km(
                uav_by_id[outcome.serving_uav_id].position.x_km,
                uav_by_id[outcome.serving_uav_id].position.y_km,
                (targets[outcome.serving_uav_id] or uav_by_id[outcome.serving_uav_id].position).x_km,
                (targets[outcome.serving_uav_id] or uav_by_id[outcome.serving_uav_id].position).y_km,
            )
            / network.drone_spec.speed_km_per_s
            for outcome in outcomes
            if outcome.group == "rescue"
            and outcome.connected
            and outcome.serving_uav_id is not None
        ]
        estimated_full_rescue_arrival_s = max(rescue_arrival_times, default=0.0)
        # Lexicographic objective: rescue count and completeness; estimated
        # time for all currently assigned rescue links to become reachable;
        # total unique connections; latency; energy; movement; target churn.
        stable_positions = tuple(
            value
            for unit, action in zip(ordered, actions, strict=True)
            for value in (
                -(action or unit.position).x_km,
                -(action or unit.position).y_km,
            )
        )
        score = (
            float(rescue),
            float(rescue == rescue_total),
            -estimated_full_rescue_arrival_s,
            float(total),
            -rescue_latency,
            -all_latency,
            -energy_cost,
            -movement_cost,
            -float(switch_cost),
            *stable_positions,
        )
        if best_score is None or score > best_score:
            best_score = score
            best_targets = targets
    if best_targets is None:
        return (
            {unit.id: _current_hold_target(unit) for unit in ordered},
            None,
            evaluations,
            conflicts,
        )
    return best_targets, best_score, evaluations, conflicts


def apply_decision(uavs: list[UAVState], decision: FleetDecision) -> list[dict[str, object]]:
    """Commit planned terminal targets; movement still happens next tick."""

    records: list[dict[str, object]] = []
    for unit in sorted(uavs, key=lambda item: item.id):
        target = decision.targets.get(unit.id, _current_hold_target(unit))
        old_target = unit.target_position or unit.position
        if target is None:
            unit.target_position = unit.position if unit.active else None
            unit.task = "hold" if unit.active else "standby"
            unit.task_status = "holding" if unit.active else "standby"
        else:
            unit.active = True
            if distance_km(
                old_target.x_km,
                old_target.y_km,
                target.x_km,
                target.y_km,
            ) > 0.15:
                unit.target_switch_count += 1
            unit.target_position = target
            if distance_km(
                unit.position.x_km,
                unit.position.y_km,
                target.x_km,
                target.y_km,
            ) > 1e-6:
                unit.task = "relay_deployment"
                unit.task_status = "awaiting_movement"
            else:
                unit.task = "relay_service"
                unit.task_status = "holding_target"
        records.append(
            {
                "uav_id": unit.id,
                "target_position_km": (
                    [round(target.x_km, 6), round(target.y_km, 6)]
                    if target is not None
                    else None
                ),
                "target_changed": bool(
                    target is not None
                    and distance_km(
                        old_target.x_km,
                        old_target.y_km,
                        target.x_km,
                        target.y_km,
                    ) > 0.15
                ),
            }
        )
    return records


def advance_fleet(
    network: Network,
    uavs: list[UAVState],
    config: DynamicExperimentConfig,
    options: MultiUAVOptions,
    previous_snapshot: FleetSnapshot,
    time_s: int,
) -> list[dict[str, object]]:
    """Advance all UAVs one tick under speed, boundary, spacing and reserve guards."""

    active_before = {unit.id for unit in uavs if unit.active}
    served_by_uav: dict[str, bool] = {
        unit.id: any(outcome.serving_uav_id == unit.id for outcome in previous_snapshot.outcomes)
        for unit in uavs
    }
    proposed: dict[str, Position] = {}
    base_records: dict[str, dict[str, object]] = {}
    for unit in sorted(uavs, key=lambda item: item.id):
        if not unit.active:
            proposed[unit.id] = unit.position
            base_records[unit.id] = _empty_movement_record(unit, time_s)
            continue
        goal = unit.target_position or unit.position
        max_move = network.drone_spec.speed_km_per_s * config.time_step_s
        distance = distance_km(
            unit.position.x_km,
            unit.position.y_km,
            goal.x_km,
            goal.y_km,
        )
        move = min(distance, max_move)
        if distance > 0:
            ratio = move / distance
            candidate = Position(
                unit.position.x_km + (goal.x_km - unit.position.x_km) * ratio,
                unit.position.y_km + (goal.y_km - unit.position.y_km) * ratio,
            )
        else:
            candidate = unit.position
        if not _inside_city(network, candidate):
            candidate = unit.position
            move = 0.0
        relay_wh = config.relay_power_w if served_by_uav[unit.id] else 0.0
        operation_wh = (config.hover_power_w + relay_wh) * config.time_step_s / 3600.0
        movement_wh = move * config.movement_wh_per_km
        return_budget = _return_energy_wh(config, network, candidate)
        safety_reason = None
        if (
            return_budget is None
            or unit.battery_wh - operation_wh - movement_wh - return_budget
            < unit.reserve_wh - 1e-9
        ):
            # A low-battery UAV heads toward the nearest healthy station rather
            # than continuing to its service target. If none exists, it holds
            # safely and the run records the unavailable return path.
            nearest = _nearest_healthy_position(network, unit.position)
            if nearest is not None:
                goal = nearest
                distance = distance_km(
                    unit.position.x_km,
                    unit.position.y_km,
                    goal.x_km,
                    goal.y_km,
                )
                move = min(distance, max_move)
                ratio = move / distance if distance else 0.0
                candidate = Position(
                    unit.position.x_km + (goal.x_km - unit.position.x_km) * ratio,
                    unit.position.y_km + (goal.y_km - unit.position.y_km) * ratio,
                )
                movement_wh = move * config.movement_wh_per_km
                return_budget = _return_energy_wh(config, network, candidate)
                safety_reason = "return_to_station_due_to_reserve_budget"
            else:
                candidate = unit.position
                move = 0.0
                movement_wh = 0.0
                return_budget = None
                safety_reason = "no_healthy_station_for_return"
        if (
            unit.battery_wh - operation_wh - movement_wh < unit.reserve_wh - 1e-9
            or (return_budget is not None and unit.battery_wh - operation_wh - movement_wh - return_budget < unit.reserve_wh - 1e-9)
        ):
            candidate = unit.position
            move = 0.0
            movement_wh = 0.0
            if unit.battery_wh - operation_wh < unit.reserve_wh - 1e-9:
                operation_wh = max(0.0, unit.battery_wh - unit.reserve_wh)
                unit.active = False
                unit.task_status = "safe_shutdown_at_reserve"
                safety_reason = "safe_shutdown_before_reserve_violation"
        proposed[unit.id] = candidate
        base_records[unit.id] = {
            "time_s": time_s,
            "uav_id": unit.id,
            "position_before_km": [round(unit.position.x_km, 6), round(unit.position.y_km, 6)],
            "position_after_km": [round(candidate.x_km, 6), round(candidate.y_km, 6)],
            "moved_km": move,
            "movement_energy_wh": movement_wh,
            "hover_energy_wh": operation_wh - relay_wh * config.time_step_s / 3600.0,
            "relay_energy_wh": relay_wh * config.time_step_s / 3600.0,
            "energy_consumed_wh": movement_wh + operation_wh,
            "battery_before_wh": unit.battery_wh,
            "safety_action": safety_reason,
            "active_before": unit.id in active_before,
        }

    conflicts: set[str] = set()
    ordered = sorted(uavs, key=lambda item: item.id)
    for i, first in enumerate(ordered):
        if first.id not in active_before:
            continue
        for second in ordered[i + 1 :]:
            if second.id not in active_before:
                continue
            if _segment_min_distance(first.position, proposed[first.id], second.position, proposed[second.id]) < options.min_separation_km - 1e-9:
                conflicts.update((first.id, second.id))
    for uav_id in conflicts:
        unit = next(item for item in uavs if item.id == uav_id)
        proposed[uav_id] = unit.position
        record = base_records[uav_id]
        record["position_after_km"] = [round(unit.position.x_km, 6), round(unit.position.y_km, 6)]
        record["moved_km"] = 0.0
        record["movement_energy_wh"] = 0.0
        record["energy_consumed_wh"] = float(record["hover_energy_wh"]) + float(record["relay_energy_wh"])
        record["safety_action"] = "movement_blocked_by_minimum_separation"

    records: list[dict[str, object]] = []
    for unit in ordered:
        record = base_records[unit.id]
        before = unit.position
        after = proposed[unit.id]
        energy = float(record["energy_consumed_wh"])
        unit.position = after
        unit.battery_wh = max(unit.reserve_wh, unit.battery_wh - energy)
        unit.energy_consumed_wh += energy
        unit.energy_log.append(
            {
                "time_s": time_s,
                "movement_wh": round(float(record["movement_energy_wh"]), 8),
                "hover_wh": round(float(record["hover_energy_wh"]), 8),
                "relay_wh": round(float(record["relay_energy_wh"]), 8),
                "total_wh": round(energy, 8),
                "battery_remaining_wh": round(unit.battery_wh, 8),
            }
        )
        if unit.active:
            unit.task_status = "moving" if distance_km(after.x_km, after.y_km, (unit.target_position or after).x_km, (unit.target_position or after).y_km) > 1e-6 else "at_target"
        else:
            unit.task_status = "safe_shutdown_at_reserve" if unit.battery_wh <= unit.reserve_wh + 1e-9 else unit.task_status
        record.update(
            {
                "position_before_km": [round(before.x_km, 6), round(before.y_km, 6)],
                "position_after_km": [round(after.x_km, 6), round(after.y_km, 6)],
                "battery_after_wh": round(unit.battery_wh, 8),
                "active_after": unit.active,
            }
        )
        records.append(record)
    return records


def update_uav_link_and_task_state(
    network: Network,
    uavs: list[UAVState],
    snapshot: FleetSnapshot,
    time_s: int,
) -> None:
    assignments: dict[str, set[str]] = {unit.id: set() for unit in uavs}
    for outcome in snapshot.outcomes:
        if outcome.connected and outcome.serving_uav_id is not None:
            assignments[outcome.serving_uav_id].add(outcome.user_id)
    healthy = tuple(station for station in network.stations if station.healthy)
    for unit in uavs:
        unit.served_user_ids = assignments[unit.id]
        unit.access_link_available = any(
            distance_km(unit.position.x_km, unit.position.y_km, user.x_km, user.y_km)
            <= network.drone_spec.access_radius_km + 1e-9
            for user in network.users
        )
        unit.backhaul_link_available = bool(network.drone_backhaul_available) and any(
            distance_km(unit.position.x_km, unit.position.y_km, station.x_km, station.y_km)
            <= network.drone_spec.backhaul_radius_km + 1e-9
            for station in healthy
        )
        if not unit.active:
            unit.task_status = "standby" if unit.battery_wh > unit.reserve_wh else "safe_shutdown_at_reserve"
        elif not network.drone_backhaul_available:
            unit.task_status = "waiting_for_backhaul_recovery"
        elif not healthy:
            unit.task_status = "no_healthy_backhaul_endpoint"
        elif unit.served_user_ids:
            unit.task = "relay_service"
            unit.task_status = "relaying"
        elif unit.target_position is not None and distance_km(
            unit.position.x_km,
            unit.position.y_km,
            unit.target_position.x_km,
            unit.target_position.y_km,
        ) > 1e-6:
            unit.task_status = "transit_to_target"
        else:
            unit.task_status = "holding_without_assigned_users"
        unit.trajectory.append(
            {
                "time_s": time_s,
                "position_km": [round(unit.position.x_km, 6), round(unit.position.y_km, 6)],
                "target_position_km": (
                    [round(unit.target_position.x_km, 6), round(unit.target_position.y_km, 6)]
                    if unit.target_position is not None
                    else None
                ),
                "battery_wh": round(unit.battery_wh, 6),
                "active": unit.active,
                "access_link_available": unit.access_link_available,
                "backhaul_link_available": unit.backhaul_link_available,
                "task": unit.task,
                "task_status": unit.task_status,
                "served_user_ids": sorted(unit.served_user_ids),
            }
        )


def _candidate_positions(
    network: Network,
    uavs: list[UAVState],
    options: MultiUAVOptions,
) -> list[Position]:
    width = network.config.city_width_km
    height = network.config.city_height_km
    spacing = options.grid_spacing_km
    xs = _axis_values(width, spacing)
    ys = _axis_values(height, spacing)
    positions: dict[tuple[int, int], Position] = {}

    def add(x: float, y: float) -> None:
        if 0 <= x <= width and 0 <= y <= height:
            point = Position(round(x, 6), round(y, 6))
            positions[(round(point.x_km * 1_000_000), round(point.y_km * 1_000_000))] = point

    for x in xs:
        for y in ys:
            add(x, y)
    for user in network.users:
        add(user.x_km, user.y_km)
    for unit in uavs:
        add(unit.position.x_km, unit.position.y_km)
        if unit.target_position is not None:
            add(unit.target_position.x_km, unit.target_position.y_km)
    healthy = tuple(station for station in network.stations if station.healthy)
    for station in healthy:
        add(station.x_km, station.y_km)
        for user in network.users:
            separation = distance_km(station.x_km, station.y_km, user.x_km, user.y_km)
            max_span = network.drone_spec.access_radius_km + network.drone_spec.backhaul_radius_km
            if separation <= 1e-12 or separation > max_span + 1e-9:
                continue
            ratio = network.drone_spec.access_radius_km / max_span
            add(
                user.x_km + (station.x_km - user.x_km) * ratio,
                user.y_km + (station.y_km - user.y_km) * ratio,
            )
    return [positions[key] for key in sorted(positions)]


def _axis_values(maximum: float, spacing: float) -> list[float]:
    count = int(math.floor(maximum / spacing))
    values = [round(index * spacing, 6) for index in range(count + 1)]
    if not values or values[-1] < maximum - 1e-9:
        values.append(round(maximum, 6))
    return values


def _has_relay_route(
    network: Network,
    position: Position,
    users,
    stations,
) -> bool:
    if not network.drone_backhaul_available:
        return False
    return any(
        distance_km(position.x_km, position.y_km, user.x_km, user.y_km)
        <= network.drone_spec.access_radius_km + 1e-9
        and distance_km(position.x_km, position.y_km, station.x_km, station.y_km)
        <= network.drone_spec.backhaul_radius_km + 1e-9
        for user in users
        for station in stations
    )


def _sortie_energy_wh(
    config: DynamicExperimentConfig,
    network: Network,
    unit: UAVState,
    destination: Position,
    service_steps: int,
) -> float | None:
    healthy = tuple(station for station in network.stations if station.healthy)
    if not healthy:
        return None
    outbound = distance_km(
        unit.position.x_km,
        unit.position.y_km,
        destination.x_km,
        destination.y_km,
    )
    returning = min(
        distance_km(destination.x_km, destination.y_km, station.x_km, station.y_km)
        for station in healthy
    )
    step_distance = network.drone_spec.speed_km_per_s * config.time_step_s
    if step_distance <= 0:
        return None
    outbound_ticks = math.ceil(outbound / step_distance)
    return_ticks = math.ceil(returning / step_distance)
    service_ticks = max(1, service_steps)
    energy = (outbound + returning) * config.movement_wh_per_km
    energy += (
        (config.hover_power_w + config.relay_power_w)
        * (outbound_ticks + service_ticks + return_ticks)
        * config.time_step_s
        / 3600.0
    )
    return energy


def _return_energy_wh(
    config: DynamicExperimentConfig,
    network: Network,
    position: Position,
) -> float | None:
    healthy = tuple(station for station in network.stations if station.healthy)
    if not healthy:
        return None
    distance = min(
        distance_km(position.x_km, position.y_km, station.x_km, station.y_km)
        for station in healthy
    )
    step_distance = network.drone_spec.speed_km_per_s * config.time_step_s
    if step_distance <= 0:
        return None
    ticks = math.ceil(distance / step_distance)
    return distance * config.movement_wh_per_km + (
        (config.hover_power_w + config.relay_power_w)
        * ticks
        * config.time_step_s
        / 3600.0
    )


def _targets_separated(
    uavs: list[UAVState],
    targets: dict[str, Position | None],
    minimum_separation_km: float,
) -> bool:
    active: list[tuple[UAVState, Position]] = []
    for unit in sorted(uavs, key=lambda item: item.id):
        target = targets.get(unit.id, _current_hold_target(unit))
        if target is None and not unit.active:
            continue
        destination = target if target is not None else unit.position
        if unit.active or target is not None:
            active.append((unit, destination))
    for index, (first, first_target) in enumerate(active):
        for second, second_target in active[index + 1 :]:
            if distance_km(
                first_target.x_km,
                first_target.y_km,
                second_target.x_km,
                second_target.y_km,
            ) < minimum_separation_km - 1e-9:
                return False
            if _segment_min_distance(
                first.position,
                first_target,
                second.position,
                second_target,
            ) < minimum_separation_km - 1e-9:
                return False
    return True


def _segment_min_distance(
    first_start: Position,
    first_end: Position,
    second_start: Position,
    second_end: Position,
) -> float:
    rx = first_start.x_km - second_start.x_km
    ry = first_start.y_km - second_start.y_km
    vx = (first_end.x_km - first_start.x_km) - (second_end.x_km - second_start.x_km)
    vy = (first_end.y_km - first_start.y_km) - (second_end.y_km - second_start.y_km)
    speed_sq = vx * vx + vy * vy
    t = 0.0 if speed_sq <= 1e-18 else max(0.0, min(1.0, -(rx * vx + ry * vy) / speed_sq))
    return math.hypot(rx + t * vx, ry + t * vy)


def _inside_city(network: Network, position: Position) -> bool:
    return (
        0 <= position.x_km <= network.config.city_width_km
        and 0 <= position.y_km <= network.config.city_height_km
    )


def _nearest_healthy_position(network: Network, position: Position) -> Position | None:
    healthy = [station for station in network.stations if station.healthy]
    if not healthy:
        return None
    station = min(
        healthy,
        key=lambda item: distance_km(position.x_km, position.y_km, item.x_km, item.y_km),
    )
    return Position(station.x_km, station.y_km)


def _current_hold_target(unit: UAVState) -> Position | None:
    return unit.position if unit.active else None


def _empty_movement_record(unit: UAVState, time_s: int) -> dict[str, object]:
    point = [round(unit.position.x_km, 6), round(unit.position.y_km, 6)]
    return {
        "time_s": time_s,
        "uav_id": unit.id,
        "position_before_km": point,
        "position_after_km": point,
        "moved_km": 0.0,
        "movement_energy_wh": 0.0,
        "hover_energy_wh": 0.0,
        "relay_energy_wh": 0.0,
        "energy_consumed_wh": 0.0,
        "battery_before_wh": unit.battery_wh,
        "battery_after_wh": unit.battery_wh,
        "safety_action": None,
        "active_before": False,
        "active_after": False,
    }


def _queue_delay(used_mbps: float, capacity_mbps: float, network: Network) -> float:
    utilization = min(used_mbps / capacity_mbps, 1.0) if capacity_mbps else 0.0
    denominator = max(1.0 - utilization, 0.05)
    delay = network.latency.congestion_delay_factor_ms * utilization / denominator
    return min(delay, network.latency.max_queue_delay_ms)


class _SearchTimeout(RuntimeError):
    pass

