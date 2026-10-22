"""Distance-, capacity-, priority-, and latency-constrained link evaluation."""

from __future__ import annotations

import math
from collections import defaultdict

from .models import Link, Network, NetworkSnapshot, PathCandidate, UserOutcome


def distance_km(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def evaluate_network(
    network: Network,
    *,
    drone_position: tuple[float, float] | None = None,
    drone_active: bool | None = None,
) -> NetworkSnapshot:
    """Evaluate radio reachability, allocate capacity, and estimate latency.

    Spatial coverage means a user has at least one feasible distance-limited path.
    Connection success additionally requires the full configured user demand to
    fit within every resource on the selected path.
    """
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
            if direct_distance <= station.coverage_radius_km:
                link = Link(
                    source_id=station.id,
                    target_id=user.id,
                    kind="access",
                    distance_km=direct_distance,
                    max_distance_km=station.coverage_radius_km,
                    capacity_mbps=station.capacity_mbps,
                )
                paths.append(
                    _path(network, "direct", station.id, (link,), (f"station:{station.id}",))
                )
                all_links[(link.source_id, link.target_id, link.kind)] = link

            if not use_drone or not network.drone_backhaul_available:
                continue
            access_distance = distance_km(drone_x, drone_y, user.x_km, user.y_km)
            backhaul_distance = distance_km(drone_x, drone_y, station.x_km, station.y_km)
            if (
                access_distance <= network.drone_spec.access_radius_km
                and backhaul_distance <= network.drone_spec.backhaul_radius_km
            ):
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
                paths.append(
                    _path(
                        network,
                        "drone_relay",
                        station.id,
                        (backhaul, access),
                        (
                            f"station:{station.id}",
                            f"drone:{network.drone_spec.id}",
                            *(
                                (f"backhaul:{network.drone_spec.id}",)
                                if network.drone_backhaul_capacity_mbps is not None
                                else ()
                            ),
                        ),
                    )
                )
                all_links[(access.source_id, access.target_id, access.kind)] = access
                all_links[(backhaul.source_id, backhaul.target_id, backhaul.kind)] = backhaul
        paths_by_user[user.id] = sorted(
            paths,
            key=lambda candidate: (candidate.base_latency_ms, candidate.station_id, candidate.kind),
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
                    user_id=user.id,
                    group=user.group,
                    priority=user.priority,
                    covered=bool(paths_by_user[user.id]),
                    connected=False,
                    path_kind=None,
                    distance_km=None,
                    latency_ms=None,
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
                user_id=user.id,
                group=user.group,
                priority=user.priority,
                covered=True,
                connected=True,
                path_kind=candidate.kind,
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


def _path(
    network: Network,
    kind: str,
    station_id: str,
    links: tuple[Link, ...],
    resources: tuple[str, ...],
) -> PathCandidate:
    distance = sum(link.distance_km for link in links)
    relay_delay = network.latency.relay_processing_ms if kind == "drone_relay" else 0.0
    base_latency = network.latency.base_latency_ms + (
        distance * network.latency.propagation_ms_per_km
    ) + relay_delay
    return PathCandidate(kind, station_id, links, resources, distance, base_latency)


def _queue_delay(used_mbps: float, capacity_mbps: float, network: Network) -> float:
    utilization = min(used_mbps / capacity_mbps, 1.0)
    denominator = max(1.0 - utilization, 0.05)
    delay = network.latency.congestion_delay_factor_ms * utilization / denominator
    return min(delay, network.latency.max_queue_delay_ms)
