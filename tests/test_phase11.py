from dataclasses import replace
from pathlib import Path

from lowalt6g.dynamic_config import load_dynamic_config
from lowalt6g.engine import distance_km
from lowalt6g.models import Position
from lowalt6g.multi_uav import MultiUAVOptions, create_fleet
from lowalt6g.phase11_algorithms import (
    plan_h_marginal_greedy,
    plan_i_constrained_matching,
    plan_j_budgeted_joint_beam,
)
from lowalt6g.phase11_experiments import (
    load_plan,
    validate_seed_plan,
    verify_phase10_baseline,
)
from lowalt6g.phase11_simulation import run_phase11_policy
from lowalt6g.scenario import build_network


ROOT = Path(__file__).resolve().parents[1]
SEVERE = ROOT / "configs/phase5/severe_persistent_faults.toml"
DYNAMIC = ROOT / "configs/phase5/dynamic_failures.toml"


def _network_and_fleet(count: int = 2):
    config = load_dynamic_config(SEVERE)
    network = build_network(replace(config.base, seed=95000))
    network.drone.battery_wh = config.initial_battery_wh
    network.drone_backhaul_capacity_mbps = config.initial_backhaul_capacity_mbps
    uavs = create_fleet(network, config, count, minimum_separation_km=0.75)
    return config, network, uavs


def test_phase11_i_assigns_each_user_once_and_obeys_shared_capacity():
    config, network, uavs = _network_and_fleet(3)
    plan = plan_i_constrained_matching(network, uavs, config, MultiUAVOptions())

    snapshot = plan.snapshot
    assert snapshot is not None
    user_ids = [outcome.user_id for outcome in snapshot.outcomes]
    assert len(user_ids) == len(set(user_ids)) == len(network.users)
    assert all(
        snapshot.resource_used_mbps[name] <= capacity + 1e-9
        for name, capacity in snapshot.resource_capacity_mbps.items()
    )
    assert all(value <= 1.0 + 1e-9 for value in snapshot.resource_utilization.values())
    assert set(plan.decision.targets) == {unit.id for unit in uavs}
    for unit in uavs:
        target = plan.decision.targets[unit.id]
        assert target is None or target == unit.position


def test_phase11_i_does_not_claim_relay_service_without_backhaul():
    config, network, uavs = _network_and_fleet(2)
    network.drone_backhaul_available = False
    plan = plan_i_constrained_matching(network, uavs, config, MultiUAVOptions())

    assert plan.snapshot is not None
    assert all(
        not outcome.connected or outcome.serving_uav_id is None
        for outcome in plan.snapshot.outcomes
    )


def test_phase11_joint_planners_respect_city_energy_and_separation():
    config, network, uavs = _network_and_fleet(3)
    options = MultiUAVOptions()
    for planner in (plan_h_marginal_greedy, plan_j_budgeted_joint_beam):
        plan = planner(network, uavs, config, options)
        targets = plan.decision.targets
        for unit in uavs:
            target = targets[unit.id]
            if target is None:
                continue
            assert 0 <= target.x_km <= network.config.city_width_km
            assert 0 <= target.y_km <= network.config.city_height_km
        deployed = [
            (unit, targets[unit.id] or unit.position)
            for unit in uavs if unit.active or targets[unit.id] is not None
        ]
        for index, (left, left_target) in enumerate(deployed):
            for right, right_target in deployed[index + 1 :]:
                assert distance_km(
                    left_target.x_km, left_target.y_km,
                    right_target.x_km, right_target.y_km,
                ) >= options.min_separation_km - 1e-9


def test_phase11_reports_no_healthy_endpoint_and_j_timeout_safely():
    config, network, uavs = _network_and_fleet(2)
    network.stations = tuple(replace(station, healthy=False) for station in network.stations)
    for planner in (plan_h_marginal_greedy, plan_i_constrained_matching, plan_j_budgeted_joint_beam):
        plan = planner(network, uavs, config, MultiUAVOptions())
        assert plan.decision.reason == "no_healthy_base_station"
        assert plan.decision.infeasible_reason

    config, network, uavs = _network_and_fleet(2)
    options = MultiUAVOptions(decision_timeout_ms=0.0)
    plan = plan_j_budgeted_joint_beam(network, uavs, config, options)
    assert plan.decision.timed_out
    assert all(
        target is None or target == next(u for u in uavs if u.id == unit_id).position
        for unit_id, target in plan.decision.targets.items()
    )


def test_phase11_simulation_uses_real_trace_and_emits_recovery_metrics():
    config = load_dynamic_config(DYNAMIC)
    seed = 95010
    from lowalt6g.dynamic_world import build_world_trace

    trace = build_world_trace(config, seed)
    result = run_phase11_policy(
        config,
        seed,
        trace,
        fleet_size=2,
        strategy_id="J_budgeted_joint_beam",
        options=MultiUAVOptions(),
    )
    metrics = result["metrics"]
    assert result["world_trace_sha256"] == trace.trace_sha256
    assert metrics["evaluation_ticks"] > 1
    assert metrics["recovery_total_count"] == 1
    assert metrics["sustained_total_count"] == 1
    assert metrics["latency_sample_count"] == len(result["latency_samples_ms"])
    assert metrics["resource_capacity_violation_count"] == 0
    assert metrics["duplicate_user_service_count"] == 0
    assert metrics["coordination_decision_count"] >= 1


def test_phase11_seed_partitions_are_disjoint_and_phase10_artifacts_are_intact():
    validate_seed_plan(load_plan())
    audit = verify_phase10_baseline()
    assert audit["phase10_confirmation_seed_rows"] == 80
    assert audit["phase10_confirmation_policy_runs"] == 400
    assert audit["phase10_artifact_hash_mismatches"] == 0
    assert audit["phase10_matched_trace_mismatches"] == 0
