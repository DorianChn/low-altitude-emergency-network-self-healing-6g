from dataclasses import replace
from pathlib import Path

import pytest

from lowalt6g.config import load_config
from lowalt6g.dynamic_config import DynamicEventSpec, load_dynamic_config
from lowalt6g.dynamic_simulation import _apply_event, run_seed_experiment
from lowalt6g.dynamic_world import build_world_trace
from lowalt6g.engine import evaluate_network
from lowalt6g.scenario import build_network


ROOT = Path(__file__).resolve().parents[1]
PHASE5_CONFIGS = ROOT / "configs" / "phase5"
SEVERE_CONFIG = PHASE5_CONFIGS / "severe_persistent_faults.toml"
DYNAMIC_CONFIG = PHASE5_CONFIGS / "dynamic_failures.toml"
MOBILITY_CONFIG = PHASE5_CONFIGS / "high_mobility_rescue.toml"
LOAD_CONFIG = PHASE5_CONFIGS / "high_load_backhaul_limit.toml"


def test_phase5_scenes_have_disjoint_development_and_held_out_seeds() -> None:
    configs = [
        load_dynamic_config(path)
        for path in (SEVERE_CONFIG, DYNAMIC_CONFIG, MOBILITY_CONFIG, LOAD_CONFIG)
    ]
    assert all(len(config.development_seeds) == 5 for config in configs)
    assert all(len(config.validation_seeds) == 20 for config in configs)
    assert all(not set(config.development_seeds) & set(config.validation_seeds) for config in configs)
    assert len({seed for config in configs for seed in config.development_seeds}) == 20
    assert len({seed for config in configs for seed in config.validation_seeds}) == 80


def test_severe_scene_has_persistent_station_failures_and_no_repair_events() -> None:
    config = load_dynamic_config(SEVERE_CONFIG)
    assert sum(station.healthy for station in config.base.stations) == 1
    assert not any(event.event_type == "station_recovery" for event in config.events)
    experiment = run_seed_experiment(
        config,
        config.validation_seeds[0],
        include_d=True,
        include_bprime=True,
    )
    assert set(experiment.strategies) == {
        "A_no_recovery",
        "B_phase1_static_grid",
        "Bprime_static_grid_shared_safety",
        "C_rolling_horizon_mpc",
        "D_lexicographic_rescue_priority",
    }
    assert not any(event["event_type"] == "station_recovery" for event in experiment.environment_events)
    assert experiment.strategies["A_no_recovery"].metrics["network_recovery_success"] == 0
    assert experiment.strategies["A_no_recovery"].metrics["ground_only_rescue_recovery_time_s"] is None


def test_dynamic_scene_replans_on_backhaul_and_station_failures() -> None:
    config = load_dynamic_config(DYNAMIC_CONFIG)
    initial = build_network(config.base)
    initial_snapshot = evaluate_network(initial, drone_active=False)
    initial_rescue_connected = sum(
        outcome.connected for outcome in initial_snapshot.outcomes if outcome.group == "rescue"
    )
    assert initial_rescue_connected < config.base.rescue_user_count

    experiment = run_seed_experiment(config, config.validation_seeds[0], include_d=True)
    d_run = experiment.strategies["D_lexicographic_rescue_priority"]
    decisions = [event for event in d_run.event_log if event["event_type"] == "optimizer_decision"]
    outage = [event for event in decisions if event["time_s"] == 180]
    all_stations_down = [event for event in decisions if event["time_s"] == 220]
    assert outage and outage[0]["reason"] == "drone_backhaul_temporarily_unavailable"
    assert all_stations_down and all_stations_down[0]["reason"] == "no_healthy_base_station"
    assert outage[0]["trigger"] == "network_state_changed"
    assert any(
        item["event_type"] == "station_failure" and item["time_s"] == 220
        for item in experiment.environment_events
    )


def test_d_uses_backhaul_handover_route_instead_of_holding_at_start() -> None:
    config = load_dynamic_config(DYNAMIC_CONFIG)
    experiment = run_seed_experiment(config, 6510, include_d=True)
    first = next(
        event
        for event in experiment.strategies["D_lexicographic_rescue_priority"].event_log
        if event["event_type"] == "optimizer_decision" and event["time_s"] == 0
    )
    assert first["reason"] == "lexicographic_rescue_action_selected"
    assert first["planning_target_km"] != [config.base.drone.x_km, config.base.drone.y_km]


def test_high_mobility_trace_is_reproducible_and_moves_rescue_group_more() -> None:
    config = load_dynamic_config(MOBILITY_CONFIG)
    seed = config.validation_seeds[0]
    trace = build_world_trace(config, seed)
    assert trace.trace_sha256 == build_world_trace(config, seed).trace_sha256

    start_tick = 12
    end_tick = 40
    distances_by_group = {"rescue": [], "normal": []}
    first = trace.user_positions_by_tick[start_tick]
    last = trace.user_positions_by_tick[end_tick]
    base_users = {user.id: user for user in build_network(replace(config.base, seed=seed)).users}
    for user_id, user in base_users.items():
        x0, y0 = first[user_id]
        x1, y1 = last[user_id]
        distances_by_group[user.group].append(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)
    rescue_mean = sum(distances_by_group["rescue"]) / len(distances_by_group["rescue"])
    normal_mean = sum(distances_by_group["normal"]) / len(distances_by_group["normal"])
    assert rescue_mean > normal_mean * 3
    assert any(event["event_type"] == "user_mobility_change" for event in trace.environment_event_log)


def test_backhaul_capacity_is_a_real_shared_network_constraint() -> None:
    base = load_config(ROOT / "configs" / "disaster_scenario.toml")
    network = build_network(base)
    network.stations = tuple(
        replace(station, healthy=station.id == "bs-west", coverage_radius_km=0.1)
        for station in network.stations
    )
    network.users = tuple(
        replace(user, x_km=4.0, y_km=5.0, demand_mbps=10.0, priority=10, group="rescue")
        for user in network.users[:4]
    )
    network.drone.x_km = 2.0
    network.drone.y_km = 5.0
    network.drone.active = True
    network.drone_backhaul_capacity_mbps = 15.0

    snapshot = evaluate_network(network)
    assert sum(outcome.connected for outcome in snapshot.outcomes) == 1
    assert snapshot.resource_utilization["backhaul:uav-relay-1"] == pytest.approx(10.0 / 15.0)

    _apply_event(
        network,
        DynamicEventSpec(20, "backhaul_capacity_change", "uav-relay-1", 25.0),
        1.0,
    )
    assert network.drone_backhaul_capacity_mbps == 25.0


def test_phase5_service_attribution_and_energy_units_are_consistent() -> None:
    config = load_dynamic_config(SEVERE_CONFIG)
    experiment = run_seed_experiment(
        config,
        config.validation_seeds[0],
        include_d=True,
        include_bprime=True,
    )
    for run in experiment.strategies.values():
        metrics = run.metrics
        assert 0.0 <= metrics["ground_only_rescue_service_success_rate"] <= 1.0
        assert metrics["drone_extra_rescue_user_seconds"] <= metrics["drone_rescue_user_seconds"] + 1e-9
        if metrics["drone_rescue_user_seconds"]:
            expected = metrics["drone_energy_consumed_wh"] / (
                metrics["drone_rescue_user_seconds"] / 3600.0
            )
            assert metrics["drone_energy_wh_per_rescue_user_hour"] == pytest.approx(expected)
        else:
            assert metrics["drone_energy_wh_per_rescue_user_hour"] is None
        if metrics["network_recovery_time_s"] is None:
            assert metrics["network_recovery_censored"] == 1
            assert metrics["network_recovery_or_censoring_time_s"] == config.duration_s


def test_shared_runtime_energy_safety_holds_for_phase5_controllers() -> None:
    config = load_dynamic_config(SEVERE_CONFIG)
    experiment = run_seed_experiment(
        config,
        config.validation_seeds[1],
        include_d=True,
        include_bprime=True,
    )
    maximum_distance = config.base.drone.speed_km_per_s * config.time_step_s
    for run in experiment.strategies.values():
        assert run.metrics["drone_battery_minimum_wh"] >= config.reserve_wh - 1e-9
        for event in run.event_log:
            if event["event_type"] == "drone_state_update":
                assert event["moved_km"] <= maximum_distance + 1e-8
                assert event["battery_remaining_wh"] >= config.reserve_wh - 1e-9

