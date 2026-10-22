from __future__ import annotations

from dataclasses import replace

from lowalt6g.dynamic_config import load_dynamic_config
from lowalt6g.dynamic_world import build_world_trace
from lowalt6g.models import DroneState, Network, Position, User
from lowalt6g.multi_uav import (
    MultiUAVOptions,
    UAVState,
    evaluate_fleet,
    plan_fleet,
)
from lowalt6g.multi_uav_simulation import run_fleet_policy
from lowalt6g.scenario import build_network


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def _small_network(*, backhaul: bool = True, rescue_demand: float = 8.0) -> Network:
    source = load_dynamic_config(ROOT / "configs/phase5/severe_persistent_faults.toml")
    base = source.base
    station = replace(
        base.stations[0],
        id="healthy-shared",
        x_km=5.0,
        y_km=5.0,
        coverage_radius_km=1.0,
        capacity_mbps=10.0,
        healthy=True,
    )
    drone_spec = replace(
        base.drone,
        x_km=6.5,
        y_km=5.0,
        access_radius_km=2.0,
        backhaul_radius_km=2.0,
        capacity_mbps=10.0,
    )
    changed_base = replace(base, stations=(station,), drone=drone_spec)
    return Network(
        config=changed_base,
        stations=(station,),
        users=(
            User("rescue-1", 8.0, 5.0, rescue_demand, 100, "rescue"),
            User("rescue-2", 8.0, 5.0, rescue_demand, 100, "rescue"),
            User("normal-1", 8.0, 5.0, 4.0, 1, "normal"),
        ),
        drone_spec=drone_spec,
        drone=DroneState(drone_spec.x_km, drone_spec.y_km),
        latency=base.latency,
        drone_backhaul_available=backhaul,
        drone_backhaul_capacity_mbps=None,
    )


def _uavs(network: Network) -> list[UAVState]:
    return [
        UAVState(
            id="uav-1",
            position=Position(6.5, 5.0),
            target_position=None,
            battery_wh=500.0,
            reserve_wh=50.0,
            access_capacity_mbps=10.0,
            backhaul_capacity_mbps=None,
            active=True,
        ),
        UAVState(
            id="uav-2",
            position=Position(6.5, 5.0),
            target_position=None,
            battery_wh=500.0,
            reserve_wh=50.0,
            access_capacity_mbps=10.0,
            backhaul_capacity_mbps=None,
            active=True,
        ),
    ]


def test_fleet_service_is_unique_and_base_capacity_is_shared() -> None:
    network = _small_network()
    snapshot = evaluate_fleet(network, _uavs(network))

    assert len({outcome.user_id for outcome in snapshot.outcomes}) == len(network.users)
    assert sum(outcome.connected for outcome in snapshot.outcomes) == 1
    assert snapshot.resource_used_mbps["station:healthy-shared"] == 8.0
    assert snapshot.resource_used_mbps["station:healthy-shared"] <= 10.0
    assert all(
        snapshot.resource_used_mbps.get(f"uav:{unit.id}", 0.0)
        <= unit.access_capacity_mbps
        for unit in _uavs(network)
    )
    served = [outcome for outcome in snapshot.outcomes if outcome.connected]
    assert served[0].group == "rescue"  # rescue priority uses the common budget first
    assert served[0].serving_uav_id in {"uav-1", "uav-2"}


def test_backhaul_outage_prevents_relay_service() -> None:
    network = _small_network(backhaul=False)
    snapshot = evaluate_fleet(network, _uavs(network))

    assert not any(outcome.connected for outcome in snapshot.outcomes)
    assert snapshot.relay_candidate_count_by_user["rescue-1"] == 0
    assert all(value == 0.0 for value in snapshot.resource_used_mbps.values())


def test_joint_search_timeout_retains_safe_targets_with_reason() -> None:
    config = load_dynamic_config(ROOT / "configs/phase5/severe_persistent_faults.toml")
    network = build_network(config.base)
    units = _uavs(_small_network())
    options = MultiUAVOptions(decision_timeout_ms=0.0)

    decision = plan_fleet(
        "G_centralized_coordination", network, units, config, options
    )

    assert decision.timed_out
    assert decision.reason == "decision_timeout"
    assert decision.infeasible_reason
    assert set(decision.targets) == {unit.id for unit in units}
    assert all(
        target is None or 0 <= target.x_km <= network.config.city_width_km
        for target in decision.targets.values()
    )


def test_short_fleet_run_keeps_speed_battery_separation_and_capacity_limits() -> None:
    original = load_dynamic_config(ROOT / "configs/phase5/severe_persistent_faults.toml")
    short = replace(
        original,
        base=replace(original.base, duration_s=60),
        events=tuple(event for event in original.events if event.time_s <= 60),
    )
    trace = build_world_trace(short, 94000)
    result = run_fleet_policy(
        short,
        94000,
        trace,
        fleet_size=2,
        strategy_id="G_centralized_coordination",
        options=MultiUAVOptions(),
    )
    metrics = result["metrics"]

    assert result["world_trace_sha256"] == trace.trace_sha256
    assert metrics["speed_violation_count"] == 0
    assert metrics["boundary_violation_count"] == 0
    assert metrics["separation_violation_count"] == 0
    assert metrics["resource_capacity_violation_count"] == 0
    assert metrics["duplicate_user_service_count"] == 0
    assert all(
        battery >= 50.0 - 1e-9
        for battery in metrics["uav_battery_minimum_wh_by_id"].values()
    )
