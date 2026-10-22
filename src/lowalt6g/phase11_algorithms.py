"""Additional, isolated fleet baselines for Phase 11.

H is a sequential marginal-coverage planner, I is a bounded whole-user
resource assignment at fixed UAV positions, and J is a bounded beam search
over the same per-UAV shortlist used by Phase 10's G strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
import time

from .dynamic_config import DynamicExperimentConfig
from .engine import distance_km
from .models import Network, Position
from .multi_uav import (
    FleetDecision,
    FleetSnapshot,
    FleetUserOutcome,
    MultiUAVOptions,
    UAVState,
    _Path,
    _SearchTimeout,
    _candidate_positions,
    _current_hold_target,
    _has_relay_route,
    _queue_delay,
    _rank_individual_actions,
    _sortie_energy_wh,
    _targets_separated,
    evaluate_fleet,
)


@dataclass(frozen=True)
class Phase11Plan:
    decision: FleetDecision
    snapshot: FleetSnapshot | None = None
    search_nodes: int = 0


@dataclass(frozen=True)
class _AssignmentState:
    remaining: tuple[float, ...]
    assignments: tuple[_Path | None, ...]
    rescue_served: int
    rescue_priority: int
    total_served: int
    base_latency: float


def plan_h_marginal_greedy(
    network: Network,
    uavs: list[UAVState],
    config: DynamicExperimentConfig,
    options: MultiUAVOptions,
) -> Phase11Plan:
    """Choose UAV locations in sequence, re-evaluating shared resources.

    Every accepted location is evaluated jointly with already selected UAVs
    through the shared Phase 10 network allocator. A location that adds no
    rescue or total service is rejected in favor of the no-op action.
    """

    strategy_id = "H_marginal_rescue_greedy"
    started = time.perf_counter()
    deadline = started + options.decision_timeout_ms / 1000.0
    hold = {unit.id: _current_hold_target(unit) for unit in uavs}
    if not any(station.healthy for station in network.stations):
        return _result(
            strategy_id, hold, "no_healthy_base_station",
            "no_healthy_end_to_end_endpoint", started,
        )

    candidates = _candidate_positions(network, uavs, options)
    healthy = tuple(station for station in network.stations if station.healthy)
    targets = dict(hold)
    evaluations = 0
    collisions = 0
    selected_any = False
    timed_out = False
    reason = "sequential_marginal_targets_selected"
    infeasible: str | None = None
    rescue_users = [user for user in network.users if user.group == "rescue"]
    if not rescue_users:
        rescue_users = list(network.users)

    for unit in sorted(uavs, key=lambda item: item.id):
        best_score: tuple[float, ...] | None = None
        best_target: Position | None = None
        trial_targets = dict(targets)
        trial_targets[unit.id] = _current_hold_target(unit)
        prior_active = _active_ids(uavs, trial_targets)
        prior_positions = _positions_for(uavs, trial_targets, prior_active)
        before = evaluate_fleet(
            network, uavs, positions=prior_positions, active_ids=prior_active
        )
        before_rescue = _connected_count(before, "rescue")
        before_total = _connected_count(before)
        no_op_score = _h_score(
            before, unit, unit.position, 0.0,
            before_rescue, before_total,
        )
        best_score = no_op_score

        for candidate in candidates:
            if time.perf_counter() >= deadline:
                timed_out = True
                break
            if not _has_relay_route(network, candidate, rescue_users, healthy):
                continue
            estimate = _sortie_energy_wh(
                config, network, unit, candidate, options.sortie_service_budget_steps
            )
            if estimate is None or unit.battery_wh - estimate < unit.reserve_wh - 1e-9:
                continue
            trial_targets = dict(targets)
            trial_targets[unit.id] = candidate
            if not _targets_separated(uavs, trial_targets, options.min_separation_km):
                collisions += 1
                continue
            active = _active_ids(uavs, trial_targets)
            positions = _positions_for(uavs, trial_targets, active)
            snapshot = evaluate_fleet(
                network, uavs, positions=positions, active_ids=active
            )
            evaluations += 1
            score = _h_score(
                snapshot, unit, candidate, estimate,
                before_rescue, before_total,
            )
            if score > best_score:
                best_score = score
                best_target = candidate
        if best_target is not None:
            targets[unit.id] = best_target
            selected_any = True
        if timed_out:
            reason = "decision_timeout_safe_partial_plan"
            infeasible = "candidate_evaluation_deadline_exceeded; selected safe targets retained"
            break

    if not selected_any and infeasible is None:
        reason = "no_marginal_service_gain"
        infeasible = (
            "no feasible candidate adds a unique rescue or total connection under shared "
            "station/UAV capacity, backhaul, spacing and sortie-reserve constraints"
        )
    decision = FleetDecision(
        strategy_id=strategy_id,
        targets=targets,
        reason=reason,
        infeasible_reason=infeasible,
        objective=None,
        candidate_evaluations=evaluations,
        collision_rejections=collisions,
        timed_out=timed_out,
        compute_ms=(time.perf_counter() - started) * 1000.0,
    )
    return Phase11Plan(decision, search_nodes=evaluations)


def _h_score(
    after: FleetSnapshot,
    unit: UAVState,
    target: Position,
    energy_cost: float,
    before_rescue: int,
    before_total: int,
) -> tuple[float, ...]:
    rescue = _connected_count(after, "rescue")
    total = _connected_count(after)
    rescue_latency = sum(
        float(item.latency_ms or 0.0)
        for item in after.outcomes
        if item.connected and item.group == "rescue"
    )
    latency = sum(float(item.latency_ms or 0.0) for item in after.outcomes if item.connected)
    movement = distance_km(
        unit.position.x_km, unit.position.y_km, target.x_km, target.y_km
    ) if energy_cost > 0.0 else 0.0
    old_target = unit.target_position or unit.position
    changed = float(
        distance_km(old_target.x_km, old_target.y_km, target.x_km, target.y_km) > 0.15
    ) if energy_cost > 0.0 else 0.0
    rescue_total = sum(item.group == "rescue" for item in after.outcomes)
    return (
        float(rescue - before_rescue),
        float(rescue),
        float(rescue == rescue_total),
        float(total - before_total),
        float(total),
        -energy_cost,
        -movement,
        -rescue_latency,
        -latency,
        -changed,
        -target.x_km,
        -target.y_km,
    )

def plan_i_constrained_matching(
    network: Network,
    uavs: list[UAVState],
    config: DynamicExperimentConfig,
    options: MultiUAVOptions,
    *,
    beam_width: int = 64,
    max_expansions: int = 6000,
) -> Phase11Plan:
    """Assign whole users to feasible existing paths; do not move UAVs.

    This is a bounded beam search for a generalized capacitated bipartite
    assignment. Every user is either unserved or assigned to one complete
    direct/UAV path; the path simultaneously consumes the shared base-station
    pool and, when relayed, that UAV's access and backhaul budgets.
    """

    strategy_id = "I_constrained_user_assignment"
    started = time.perf_counter()
    deadline = started + options.decision_timeout_ms / 1000.0
    hold = {unit.id: _current_hold_target(unit) for unit in uavs}
    healthy = tuple(station for station in network.stations if station.healthy)
    if not healthy:
        return _result(
            strategy_id, hold, "no_healthy_base_station",
            "no_healthy_end_to_end_endpoint", started,
        )

    eligible: set[str] = set()
    for unit in uavs:
        budget = _sortie_energy_wh(
            config, network, unit, unit.position, options.sortie_service_budget_steps
        )
        if budget is not None and unit.battery_wh - budget >= unit.reserve_wh - 1e-9:
            eligible.add(unit.id)
    capacities: dict[str, float] = {
        f"station:{station.id}": station.capacity_mbps for station in healthy
    }
    by_id = {unit.id: unit for unit in uavs}
    for unit in uavs:
        if unit.id not in eligible:
            continue
        capacities[f"uav:{unit.id}"] = unit.access_capacity_mbps
        if unit.backhaul_capacity_mbps is not None:
            capacities[f"backhaul:{unit.id}"] = unit.backhaul_capacity_mbps
    resource_names = tuple(sorted(capacities))
    base_remaining = tuple(capacities[name] for name in resource_names)
    resource_index = {name: index for index, name in enumerate(resource_names)}

    path_by_user: dict[str, tuple[_Path, ...]] = {}
    relay_count: dict[str, int] = {}
    for user in network.users:
        routes: list[_Path] = []
        relays: set[str] = set()
        for station in healthy:
            direct = distance_km(
                station.x_km, station.y_km, user.x_km, user.y_km
            )
            if direct <= station.coverage_radius_km + 1e-9:
                routes.append(
                    _Path(
                        station.id, None, "direct", direct,
                        network.latency.base_latency_ms
                        + direct * network.latency.propagation_ms_per_km,
                        (f"station:{station.id}",),
                    )
                )
            for unit in uavs:
                if (
                    unit.id not in eligible
                    or not unit.access_link_available
                    or not unit.backhaul_link_available
                    or not network.drone_backhaul_available
                ):
                    continue
                access = distance_km(
                    unit.position.x_km, unit.position.y_km, user.x_km, user.y_km
                )
                backhaul = distance_km(
                    unit.position.x_km, unit.position.y_km,
                    station.x_km, station.y_km,
                )
                if (
                    access > network.drone_spec.access_radius_km + 1e-9
                    or backhaul > network.drone_spec.backhaul_radius_km + 1e-9
                ):
                    continue
                resources = [f"station:{station.id}", f"uav:{unit.id}"]
                if unit.backhaul_capacity_mbps is not None:
                    resources.append(f"backhaul:{unit.id}")
                combined = access + backhaul
                routes.append(
                    _Path(
                        station.id, unit.id, "uav_relay", combined,
                        network.latency.base_latency_ms
                        + combined * network.latency.propagation_ms_per_km
                        + network.latency.relay_processing_ms,
                        tuple(resources),
                    )
                )
                relays.add(unit.id)
        routes.sort(
            key=lambda path: (
                path.base_latency_ms, path.station_id, path.uav_id or "", path.kind
            )
        )
        path_by_user[user.id] = tuple(routes)
        relay_count[user.id] = len(relays)

    ordered_users = sorted(
        network.users,
        key=lambda user: (user.group != "rescue", -user.priority, user.id),
    )
    beam = [_AssignmentState(base_remaining, (), 0, 0, 0, 0.0)]
    expansions = 0
    timed_out = False
    for user in ordered_users:
        expanded: list[_AssignmentState] = []
        routes = path_by_user[user.id]
        for state in beam:
            if time.perf_counter() >= deadline or expansions >= max_expansions:
                timed_out = True
                break
            expanded.append(
                _AssignmentState(
                    state.remaining, state.assignments + (None,),
                    state.rescue_served, state.rescue_priority, state.total_served,
                    state.base_latency,
                )
            )
            expansions += 1
            for route in routes:
                if time.perf_counter() >= deadline or expansions >= max_expansions:
                    timed_out = True
                    break
                needed = [resource_index[key] for key in route.resources]
                if any(state.remaining[index] + 1e-9 < user.demand_mbps for index in needed):
                    continue
                left = list(state.remaining)
                for index in needed:
                    left[index] -= user.demand_mbps
                rescue = user.group == "rescue"
                expanded.append(
                    _AssignmentState(
                        tuple(left),
                        state.assignments + (route,),
                        state.rescue_served + int(rescue),
                        state.rescue_priority + (user.priority if rescue else 0),
                        state.total_served + 1,
                        state.base_latency + route.base_latency_ms,
                    )
                )
                expansions += 1
            if timed_out:
                break
        if not expanded:
            break
        expanded.sort(key=_assignment_sort_key)
        beam = _deduplicate_assignment_states(expanded, beam_width)
        if timed_out:
            # Keep the best complete assignment for the users processed so far;
            # the unprocessed suffix remains explicitly unserved.
            break

    best = max(beam, key=lambda state: _assignment_score(state))
    assignments = {
        user.id: route
        for user, route in zip(ordered_users, best.assignments, strict=False)
        if route is not None
    }
    assigned_uavs = {route.uav_id for route in assignments.values() if route.uav_id}
    active = {unit.id for unit in uavs if unit.active} | set(assigned_uavs)
    snapshot = _assignment_snapshot(
        network, uavs, assignments, path_by_user, active, capacities, relay_count
    )
    targets = {
        unit.id: (
            unit.position if unit.id in assigned_uavs
            else _current_hold_target(unit)
        )
        for unit in uavs
    }
    if timed_out:
        reason = "assignment_budget_exhausted_feasible_partial_matching"
        infeasible = "assignment beam/node or decision-time budget exhausted; partial safe assignment returned"
    elif assignments:
        reason = "bounded_rescue_first_user_resource_assignment"
        infeasible = None
    else:
        reason = "no_user_resource_assignment"
        infeasible = (
            "no feasible end-to-end path or remaining shared capacity can satisfy a whole-user demand"
        )
    decision = FleetDecision(
        strategy_id=strategy_id,
        targets=targets,
        reason=reason,
        infeasible_reason=infeasible,
        objective=tuple(float(value) for value in _assignment_score(best)[:4]),
        candidate_evaluations=expansions,
        collision_rejections=0,
        timed_out=timed_out,
        compute_ms=(time.perf_counter() - started) * 1000.0,
    )
    return Phase11Plan(decision, snapshot=snapshot, search_nodes=expansions)


def _assignment_sort_key(state: _AssignmentState) -> tuple:
    score = _assignment_score(state)
    choices = []
    for route in state.assignments:
        choices.append(
            ("~", "~", "~") if route is None
            else (route.station_id, route.uav_id or "", route.kind)
        )
    # Lower latency and deterministic path IDs break equal service scores.
    return (-score[0], -score[1], -score[2], -score[3], state.base_latency, tuple(choices))


def _assignment_score(state: _AssignmentState) -> tuple[float, ...]:
    return (
        float(state.rescue_served),
        float(state.rescue_priority),
        float(state.total_served),
        -state.base_latency,
    )


def _deduplicate_assignment_states(
    states: list[_AssignmentState], width: int
) -> list[_AssignmentState]:
    kept: list[_AssignmentState] = []
    seen: set[tuple] = set()
    for state in states:
        signature = (
            tuple(round(value, 6) for value in state.remaining),
            state.rescue_served,
            state.rescue_priority,
            state.total_served,
        )
        if signature in seen:
            continue
        seen.add(signature)
        kept.append(state)
        if len(kept) >= width:
            break
    return kept


def _assignment_snapshot(
    network: Network,
    uavs: list[UAVState],
    assignments: dict[str, _Path],
    path_by_user: dict[str, tuple[_Path, ...]],
    active: set[str],
    all_capacities: dict[str, float],
    relay_count: dict[str, int],
) -> FleetSnapshot:
    capacities = {
        key: value for key, value in all_capacities.items()
        if not key.startswith("uav:") and not key.startswith("backhaul:")
    }
    for unit in uavs:
        if unit.id not in active:
            continue
        capacities[f"uav:{unit.id}"] = unit.access_capacity_mbps
        if unit.backhaul_capacity_mbps is not None:
            capacities[f"backhaul:{unit.id}"] = unit.backhaul_capacity_mbps
    used = {key: 0.0 for key in capacities}
    user_by_id = {user.id: user for user in network.users}
    for user_id, route in assignments.items():
        demand = user_by_id[user_id].demand_mbps
        for resource in route.resources:
            used[resource] += demand
    outcomes: list[FleetUserOutcome] = []
    blocked: list[str] = []
    for user in network.users:
        route = assignments.get(user.id)
        if route is None:
            if path_by_user.get(user.id):
                blocked.append(user.id)
            outcomes.append(
                FleetUserOutcome(
                    user.id, user.group, user.priority, bool(path_by_user.get(user.id)),
                    False, None, None, None, None,
                )
            )
            continue
        delay = sum(
            _queue_delay(used[resource], capacities[resource], network)
            for resource in route.resources
        )
        outcomes.append(
            FleetUserOutcome(
                user.id, user.group, user.priority, True, True, route.kind,
                route.base_latency_ms + delay, route.station_id, route.uav_id,
            )
        )
    utilization = {
        resource: used[resource] / capacity if capacity > 0 else 0.0
        for resource, capacity in capacities.items()
    }
    return FleetSnapshot(
        tuple(outcomes), utilization, capacities, used, relay_count, tuple(sorted(blocked))
    )


def plan_j_budgeted_joint_beam(
    network: Network,
    uavs: list[UAVState],
    config: DynamicExperimentConfig,
    options: MultiUAVOptions,
    *,
    beam_width: int = 16,
) -> Phase11Plan:
    """Search G's exact per-UAV shortlist with a bounded deterministic beam."""

    strategy_id = "J_budgeted_joint_beam"
    started = time.perf_counter()
    deadline = started + options.decision_timeout_ms / 1000.0
    hold = {unit.id: _current_hold_target(unit) for unit in uavs}
    if not any(station.healthy for station in network.stations):
        return _result(
            strategy_id, hold, "no_healthy_base_station",
            "no_healthy_end_to_end_endpoint", started,
        )
    base = evaluate_fleet(network, uavs, active_ids=set())
    candidates = _candidate_positions(network, uavs, options)
    rankings: dict[str, list[tuple[tuple[float, ...], Position | None]]] = {}
    ranking_evaluations = 0
    try:
        for unit in sorted(uavs, key=lambda item: item.id):
            ranked, count = _rank_individual_actions(
                network, uavs, unit, candidates, base, config, options, deadline
            )
            rankings[unit.id] = ranked
            ranking_evaluations += count
        ordered = sorted(uavs, key=lambda item: item.id)
        action_lists: list[list[Position | None]] = []
        for unit in ordered:
            actions: list[Position | None] = [None]
            for _, candidate in rankings.get(unit.id, []):
                if candidate is None:
                    continue
                if all(
                    distance_km(candidate.x_km, candidate.y_km, prior.x_km, prior.y_km) > 1e-6
                    for prior in actions if prior is not None
                ):
                    actions.append(candidate)
                if len(actions) >= options.candidate_limit + 1:
                    break
            action_lists.append(actions)
    except _SearchTimeout:
        return _result(
            strategy_id, hold, "decision_timeout", "ranking_deadline_exceeded; safe hold retained",
            started, evaluations=ranking_evaluations, timed_out=True,
        )

    beam: list[tuple[tuple[Position | None, ...], tuple[float, ...]]] = [((), ())]
    search_evaluations = 0
    search_nodes = 0
    collisions = 0
    budget_exhausted = False
    fully_expanded = True
    for depth, actions in enumerate(action_lists):
        expanded: list[tuple[tuple[Position | None, ...], tuple[float, ...]]] = []
        for prior, _ in beam:
            for action in actions:
                if time.perf_counter() >= deadline or search_evaluations >= options.max_joint_combinations:
                    budget_exhausted = True
                    fully_expanded = False
                    break
                search_nodes += 1
                partial = prior + (action,)
                targets = {
                    unit.id: partial[index] if index < len(partial) else _current_hold_target(unit)
                    for index, unit in enumerate(ordered)
                }
                if not _targets_separated(ordered, targets, options.min_separation_km):
                    collisions += 1
                    continue
                active = _active_ids(ordered, targets)
                positions = _positions_for(ordered, targets, active)
                score = _joint_score(
                    network, ordered, targets, active, positions, config, options
                )
                if score is None:
                    continue
                search_evaluations += 1
                expanded.append((partial, score))
            if budget_exhausted:
                break
        if not expanded:
            fully_expanded = False
            break
        expanded.sort(key=lambda item: item[1], reverse=True)
        beam = expanded[:beam_width]
        if budget_exhausted:
            break

    if not beam:
        reason = "decision_timeout" if budget_exhausted else "no_feasible_joint_assignment"
        infeasible = "beam search exhausted its node/time budget or found no safe feasible plan"
        decision = FleetDecision(
            strategy_id, hold, reason, infeasible, None,
            ranking_evaluations + search_evaluations, collisions,
            budget_exhausted, (time.perf_counter() - started) * 1000.0,
        )
        return Phase11Plan(decision, search_nodes=search_nodes)

    best_actions, best_score = max(beam, key=lambda item: item[1])
    targets = {
        unit.id: best_actions[index] if index < len(best_actions) else _current_hold_target(unit)
        for index, unit in enumerate(ordered)
    }
    if budget_exhausted or not fully_expanded:
        reason = "bounded_beam_safe_partial_search"
        infeasible = "joint search budget ended before every UAV level was fully expanded"
    else:
        reason = "bounded_joint_beam_plan_selected"
        infeasible = None
    decision = FleetDecision(
        strategy_id,
        targets,
        reason,
        infeasible,
        best_score,
        ranking_evaluations + search_evaluations,
        collisions,
        budget_exhausted,
        (time.perf_counter() - started) * 1000.0,
    )
    return Phase11Plan(decision, search_nodes=search_nodes)


def _joint_score(
    network: Network,
    units: list[UAVState],
    targets: dict[str, Position | None],
    active: set[str],
    positions: dict[str, Position],
    config: DynamicExperimentConfig,
    options: MultiUAVOptions,
) -> tuple[float, ...] | None:
    energy = 0.0
    movement = 0.0
    switches = 0
    for unit in units:
        target = targets.get(unit.id, _current_hold_target(unit))
        destination = target if target is not None else unit.position
        if unit.id in active:
            estimate = _sortie_energy_wh(
                config, network, unit, destination, options.sortie_service_budget_steps
            )
            if estimate is None or unit.battery_wh - estimate < unit.reserve_wh - 1e-9:
                return None
            energy += estimate
        movement += distance_km(
            unit.position.x_km, unit.position.y_km,
            destination.x_km, destination.y_km,
        )
        old = unit.target_position or unit.position
        switches += int(
            distance_km(old.x_km, old.y_km, destination.x_km, destination.y_km) > 0.15
        )
    snapshot = evaluate_fleet(network, units, positions=positions, active_ids=active)
    outcomes = snapshot.outcomes
    rescue = sum(item.connected for item in outcomes if item.group == "rescue")
    rescue_total = sum(item.group == "rescue" for item in outcomes)
    total = sum(item.connected for item in outcomes)
    rescue_latency = sum(
        float(item.latency_ms or 0.0)
        for item in outcomes if item.connected and item.group == "rescue"
    )
    all_latency = sum(float(item.latency_ms or 0.0) for item in outcomes if item.connected)
    by_id = {unit.id: unit for unit in units}
    arrivals = [
        distance_km(
            by_id[item.serving_uav_id].position.x_km,
            by_id[item.serving_uav_id].position.y_km,
            (targets[item.serving_uav_id] or by_id[item.serving_uav_id].position).x_km,
            (targets[item.serving_uav_id] or by_id[item.serving_uav_id].position).y_km,
        ) / network.drone_spec.speed_km_per_s
        for item in outcomes
        if item.group == "rescue" and item.connected and item.serving_uav_id is not None
    ]
    stable = tuple(
        coordinate
        for unit in units
        for coordinate in (
            -(targets[unit.id] or unit.position).x_km,
            -(targets[unit.id] or unit.position).y_km,
        )
    )
    return (
        float(rescue),
        float(rescue == rescue_total),
        -max(arrivals, default=0.0),
        float(total),
        -rescue_latency,
        -all_latency,
        -energy,
        -movement,
        -float(switches),
        *stable,
    )


def _result(
    strategy_id: str,
    targets: dict[str, Position | None],
    reason: str,
    infeasible: str | None,
    started: float,
    *,
    evaluations: int = 0,
    timed_out: bool = False,
) -> Phase11Plan:
    return Phase11Plan(
        FleetDecision(
            strategy_id, targets, reason, infeasible, None, evaluations, 0,
            timed_out, (time.perf_counter() - started) * 1000.0,
        )
    )


def _active_ids(
    units: list[UAVState], targets: dict[str, Position | None]
) -> set[str]:
    return {
        unit.id for unit in units
        if unit.active or targets.get(unit.id) is not None
    }


def _positions_for(
    units: list[UAVState],
    targets: dict[str, Position | None],
    active: set[str],
) -> dict[str, Position]:
    return {
        unit.id: targets.get(unit.id) or unit.position
        for unit in units if unit.id in active
    }


def _connected_count(snapshot: FleetSnapshot, group: str | None = None) -> int:
    return sum(
        item.connected for item in snapshot.outcomes
        if group is None or item.group == group
    )
