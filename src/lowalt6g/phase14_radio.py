"""Phase 14 radio-model adapter, isolated from frozen experiment sources.

The historical evaluators remain byte-for-byte unchanged. This adapter
temporarily routes Phase 14 runs through the selected radio model, and restores
all imported evaluator references before returning.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
import time
from typing import Iterator

from . import engine as legacy_engine
from . import multi_uav as multi_uav_module
from . import multi_uav_simulation as multi_uav_simulation_module
from . import dynamic_simulation as dynamic_simulation_module
from . import optimizer as optimizer_module
from .engine import _path, _queue_delay, distance_km
from .models import Link, Network, NetworkSnapshot, PathCandidate, Position, UserOutcome
from .radio_link import LinkBudgetV1, RadioLinkModel


_ACTIVE_MODEL: ContextVar[RadioLinkModel | None] = ContextVar("phase14_radio_model", default=None)
_PLAN_TIMINGS: ContextVar[list[float] | None] = ContextVar("phase14_plan_timings", default=None)
_LEGACY_EVALUATE_NETWORK = legacy_engine.evaluate_network
_LEGACY_EVALUATE_FLEET = multi_uav_module.evaluate_fleet


def _assess(
    model: RadioLinkModel,
    profile_id: str,
    distance: float,
    max_distance: float,
    source_id: str,
    target_id: str,
    *,
    tolerance_km: float = 0.0,
) -> bool:
    return model.assess(
        profile_id,
        distance,
        max_distance,
        source_id,
        target_id,
        tolerance_km=tolerance_km,
    ).feasible


def evaluate_network_link_budget(
    network: Network,
    model: LinkBudgetV1,
    *,
    drone_position: tuple[float, float] | None = None,
    drone_active: bool | None = None,
) -> NetworkSnapshot:
    """Same capacity/priority/latency rules as engine.py with radio gating."""
    drone_x, drone_y = drone_position or (network.drone.x_km, network.drone.y_km)
    use_drone = network.drone.active if drone_active is None else drone_active
    healthy_stations = tuple(station for station in network.stations if station.healthy)
    resource_capacity: dict[str, float] = {
        f"station:{station.id}": station.capacity_mbps for station in healthy_stations
    }
    if use_drone:
        resource_capacity[f"drone:{network.drone_spec.id}"] = network.drone_spec.capacity_mbps
        if network.drone_backhaul_capacity_mbps is not None:
            resource_capacity[f"backhaul:{network.drone_spec.id}"] = network.drone_backhaul_capacity_mbps

    paths_by_user: dict[str, list[PathCandidate]] = {}
    all_links: dict[tuple[str, str, str], Link] = {}
    for user in network.users:
        paths: list[PathCandidate] = []
        for station in healthy_stations:
            direct_distance = distance_km(station.x_km, station.y_km, user.x_km, user.y_km)
            if _assess(
                model, "base_access", direct_distance, station.coverage_radius_km,
                station.id, user.id,
            ):
                link = Link(
                    source_id=station.id,
                    target_id=user.id,
                    kind="access",
                    distance_km=direct_distance,
                    max_distance_km=station.coverage_radius_km,
                    capacity_mbps=station.capacity_mbps,
                )
                paths.append(_path(network, "direct", station.id, (link,), (f"station:{station.id}",)))
                all_links[(link.source_id, link.target_id, link.kind)] = link

            if not use_drone or not network.drone_backhaul_available:
                continue
            access_distance = distance_km(drone_x, drone_y, user.x_km, user.y_km)
            backhaul_distance = distance_km(drone_x, drone_y, station.x_km, station.y_km)
            access_ok = _assess(
                model, "uav_access", access_distance, network.drone_spec.access_radius_km,
                network.drone_spec.id, user.id,
            )
            backhaul_ok = _assess(
                model, "backhaul", backhaul_distance, network.drone_spec.backhaul_radius_km,
                station.id, network.drone_spec.id,
            )
            if not (access_ok and backhaul_ok):
                continue
            access = Link(
                source_id=network.drone_spec.id,
                target_id=user.id,
                kind="drone_access",
                distance_km=access_distance,
                max_distance_km=network.drone_spec.access_radius_km,
                capacity_mbps=network.drone_spec.capacity_mbps,
            )
            backhaul = Link(
                source_id=station.id,
                target_id=network.drone_spec.id,
                kind="backhaul",
                distance_km=backhaul_distance,
                max_distance_km=network.drone_spec.backhaul_radius_km,
                capacity_mbps=min(
                    station.capacity_mbps,
                    network.drone_backhaul_capacity_mbps
                    if network.drone_backhaul_capacity_mbps is not None
                    else station.capacity_mbps,
                ),
            )
            resources = (
                f"station:{station.id}",
                f"drone:{network.drone_spec.id}",
                *(
                    (f"backhaul:{network.drone_spec.id}",)
                    if network.drone_backhaul_capacity_mbps is not None
                    else ()
                ),
            )
            paths.append(_path(network, "drone_relay", station.id, (backhaul, access), resources))
            all_links[(access.source_id, access.target_id, access.kind)] = access
            all_links[(backhaul.source_id, backhaul.target_id, backhaul.kind)] = backhaul
        paths_by_user[user.id] = sorted(
            paths, key=lambda path: (path.base_latency_ms, path.station_id, path.kind)
        )

    remaining = dict(resource_capacity)
    used: dict[str, float] = defaultdict(float)
    selected: dict[str, PathCandidate] = {}
    for user in sorted(network.users, key=lambda item: (-item.priority, item.id)):
        for candidate in paths_by_user[user.id]:
            if all(remaining.get(resource, 0.0) + 1e-9 >= user.demand_mbps for resource in candidate.resources):
                selected[user.id] = candidate
                for resource in candidate.resources:
                    remaining[resource] -= user.demand_mbps
                    used[resource] += user.demand_mbps
                break

    outcomes: list[UserOutcome] = []
    for user in network.users:
        candidate = selected.get(user.id)
        if candidate is None:
            outcomes.append(
                UserOutcome(
                    user_id=user.id, group=user.group, priority=user.priority,
                    covered=bool(paths_by_user[user.id]), connected=False,
                    path_kind=None, distance_km=None, latency_ms=None,
                    serving_station_id=None,
                )
            )
            continue
        queue_delay = sum(
            _queue_delay(used.get(resource, 0.0), resource_capacity[resource], network)
            for resource in candidate.resources
        )
        outcomes.append(
            UserOutcome(
                user_id=user.id, group=user.group, priority=user.priority,
                covered=True, connected=True, path_kind=candidate.kind,
                distance_km=candidate.distance_km,
                latency_ms=candidate.base_latency_ms + queue_delay,
                serving_station_id=candidate.station_id,
            )
        )
    utilization = {
        resource: (used.get(resource, 0.0) / capacity if capacity else 0.0)
        for resource, capacity in resource_capacity.items()
    }
    return NetworkSnapshot(
        outcomes=tuple(outcomes),
        links=tuple(all_links[key] for key in sorted(all_links)),
        resource_utilization=utilization,
    )


def evaluate_fleet_link_budget(
    network: Network,
    uavs,
    model: LinkBudgetV1,
    *,
    positions=None,
    active_ids: set[str] | None = None,
):
    """Fleet evaluator matching the legacy allocator while applying radio tests."""
    from .multi_uav import FleetSnapshot, FleetUserOutcome, _Path, _queue_delay as queue_delay

    units = tuple(sorted(uavs, key=lambda item: item.id))
    active = active_ids if active_ids is not None else {unit.id for unit in units if unit.active}
    position_map = positions or {}
    healthy = tuple(station for station in network.stations if station.healthy)
    capacities = {f"station:{station.id}": station.capacity_mbps for station in healthy}
    for unit in units:
        if unit.id in active:
            capacities[f"uav:{unit.id}"] = unit.access_capacity_mbps
            if unit.backhaul_capacity_mbps is not None:
                capacities[f"backhaul:{unit.id}"] = unit.backhaul_capacity_mbps

    paths_by_user = {}
    relay_candidates = {}
    for user in network.users:
        paths = []
        relays = set()
        for station in healthy:
            direct = distance_km(station.x_km, station.y_km, user.x_km, user.y_km)
            if _assess(model, "base_access", direct, station.coverage_radius_km, station.id, user.id, tolerance_km=1e-9):
                paths.append(
                    _Path(
                        station_id=station.id, uav_id=None, kind="direct", distance_km=direct,
                        base_latency_ms=network.latency.base_latency_ms + direct * network.latency.propagation_ms_per_km,
                        resources=(f"station:{station.id}",),
                    )
                )
            for unit in units:
                if unit.id not in active or not unit.access_link_available:
                    continue
                if not network.drone_backhaul_available or not unit.backhaul_link_available:
                    continue
                position = position_map.get(unit.id, unit.position)
                access_distance = distance_km(position.x_km, position.y_km, user.x_km, user.y_km)
                backhaul_distance = distance_km(position.x_km, position.y_km, station.x_km, station.y_km)
                access_ok = _assess(
                    model, "uav_access", access_distance, network.drone_spec.access_radius_km,
                    unit.id, user.id, tolerance_km=1e-9,
                )
                backhaul_ok = _assess(
                    model, "backhaul", backhaul_distance, network.drone_spec.backhaul_radius_km,
                    station.id, unit.id, tolerance_km=1e-9,
                )
                if not (access_ok and backhaul_ok):
                    continue
                resources = [f"station:{station.id}", f"uav:{unit.id}"]
                if unit.backhaul_capacity_mbps is not None:
                    resources.append(f"backhaul:{unit.id}")
                path_distance = access_distance + backhaul_distance
                paths.append(
                    _Path(
                        station_id=station.id, uav_id=unit.id, kind="uav_relay",
                        distance_km=path_distance,
                        base_latency_ms=(
                            network.latency.base_latency_ms
                            + path_distance * network.latency.propagation_ms_per_km
                            + network.latency.relay_processing_ms
                        ),
                        resources=tuple(resources),
                    )
                )
                relays.add(unit.id)
        paths.sort(key=lambda path: (path.base_latency_ms, path.station_id, path.uav_id or "", path.kind))
        paths_by_user[user.id] = paths
        relay_candidates[user.id] = relays

    remaining = dict(capacities)
    used = {resource: 0.0 for resource in capacities}
    selected = {}
    capacity_blocked = []
    for user in sorted(network.users, key=lambda item: (-item.priority, item.id)):
        candidates = paths_by_user[user.id]
        chosen = next(
            (path for path in candidates if all(remaining.get(resource, 0.0) + 1e-9 >= user.demand_mbps for resource in path.resources)),
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

    outcomes = []
    for user in network.users:
        path = selected.get(user.id)
        candidates = paths_by_user[user.id]
        if path is None:
            outcomes.append(
                FleetUserOutcome(
                    user_id=user.id, group=user.group, priority=user.priority,
                    covered=bool(candidates), connected=False, path_kind=None,
                    latency_ms=None, serving_station_id=None, serving_uav_id=None,
                )
            )
            continue
        queue = sum(queue_delay(used.get(resource, 0.0), capacities[resource], network) for resource in path.resources)
        outcomes.append(
            FleetUserOutcome(
                user_id=user.id, group=user.group, priority=user.priority,
                covered=True, connected=True, path_kind=path.kind,
                latency_ms=path.base_latency_ms + queue,
                serving_station_id=path.station_id, serving_uav_id=path.uav_id,
            )
        )
    utilization = {resource: used[resource] / capacity if capacity > 0 else 0.0 for resource, capacity in capacities.items()}
    return FleetSnapshot(
        outcomes=tuple(outcomes), resource_utilization=utilization,
        resource_capacity_mbps=capacities, resource_used_mbps=used,
        relay_candidate_count_by_user={user_id: len(values) for user_id, values in relay_candidates.items()},
        capacity_blocked_user_ids=tuple(sorted(capacity_blocked)),
    )


def _single_dispatch(network: Network, **kwargs):
    model = _ACTIVE_MODEL.get()
    if model is None or model.model_id == "legacy_distance":
        return _LEGACY_EVALUATE_NETWORK(network, **kwargs)
    return evaluate_network_link_budget(network, model, **kwargs)  # type: ignore[arg-type]


def _fleet_dispatch(network: Network, uavs, **kwargs):
    model = _ACTIVE_MODEL.get()
    if model is None or model.model_id == "legacy_distance":
        return _LEGACY_EVALUATE_FLEET(network, uavs, **kwargs)
    return evaluate_fleet_link_budget(network, uavs, model, **kwargs)  # type: ignore[arg-type]


@contextmanager
def radio_model_context(model: RadioLinkModel) -> Iterator[dict[str, list[float]]]:
    """Temporarily route existing Phase 10 execution through a Phase 14 model."""
    token = _ACTIVE_MODEL.set(model)
    timing_values: list[float] = []
    timing_token = _PLAN_TIMINGS.set(timing_values)
    original_plan = multi_uav_module.plan_fleet

    def timed_plan(*args, **kwargs):
        started = time.perf_counter()
        decision = original_plan(*args, **kwargs)
        timing_values.append((time.perf_counter() - started) * 1000.0)
        return decision

    patches = [
        (dynamic_simulation_module, "evaluate_network", _single_dispatch),
        (optimizer_module, "evaluate_network", _single_dispatch),
        (multi_uav_module, "evaluate_fleet", _fleet_dispatch),
        (multi_uav_simulation_module, "evaluate_fleet", _fleet_dispatch),
        (multi_uav_module, "plan_fleet", timed_plan),
        (multi_uav_simulation_module, "plan_fleet", timed_plan),
    ]
    originals = [(module, name, getattr(module, name)) for module, name, _replacement in patches]
    try:
        for module, name, replacement in patches:
            setattr(module, name, replacement)
        yield {"plan_compute_ms": timing_values}
    finally:
        for module, name, original in originals:
            setattr(module, name, original)
        _PLAN_TIMINGS.reset(timing_token)
        _ACTIVE_MODEL.reset(token)
