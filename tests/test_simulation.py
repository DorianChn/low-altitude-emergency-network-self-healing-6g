from dataclasses import replace
from pathlib import Path

import pytest

from lowalt6g.config import SimulationConfig, load_config
from lowalt6g.engine import evaluate_network
from lowalt6g.policies import GreedyRelayPolicy
from lowalt6g.scenario import build_network
from lowalt6g.simulation import benchmark, run_simulation


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "disaster_scenario.toml"


def test_default_scenario_has_three_stations_and_two_failures() -> None:
    config = load_config(DEFAULT_CONFIG)
    assert len(config.stations) == 3
    assert sum(not station.healthy for station in config.stations) == 2
    assert sum(user.group == "rescue" for user in build_network(config).users) == 8


def test_same_seed_reproduces_user_locations_and_metrics() -> None:
    config = load_config(DEFAULT_CONFIG)
    users_a = build_network(config).users
    users_b = build_network(config).users
    assert users_a == users_b
    assert benchmark(config) == benchmark(config)


def test_different_seed_changes_generated_user_locations() -> None:
    config = load_config(DEFAULT_CONFIG)
    other = replace(config, seed=config.seed + 1)
    assert build_network(config).users != build_network(other).users


def test_rule_based_relay_improves_rescue_service_and_recovers_network() -> None:
    config = load_config(DEFAULT_CONFIG)
    runs = benchmark(config)
    baseline = runs["no_recovery"].metrics
    recovery = runs["rule_based_uav_relay"].metrics
    assert baseline["rescue_user_service_success_rate"] < 1.0
    assert recovery["rescue_user_service_success_rate"] > baseline["rescue_user_service_success_rate"]
    assert recovery["network_recovery_time_s"] is not None
    assert recovery["final_rescue_users_connected"] == config.rescue_user_count
    assert recovery["average_communication_latency_ms"] is not None


def test_capacity_congestion_respects_rescue_priority() -> None:
    config = load_config(DEFAULT_CONFIG)
    station_only = replace(
        config,
        stations=tuple(replace(station, healthy=station.id == "bs-west", capacity_mbps=36.0) for station in config.stations),
        rescue_demand_mbps=4.0,
        normal_demand_mbps=4.0,
        drone=replace(config.drone, capacity_mbps=100.0),
    )
    network = build_network(station_only)
    snapshot = evaluate_network(network, drone_position=(4.0, 5.0), drone_active=True)
    rescue = [outcome for outcome in snapshot.outcomes if outcome.group == "rescue" and outcome.covered]
    normals = [outcome for outcome in snapshot.outcomes if outcome.group == "normal" and outcome.covered]
    assert all(outcome.connected for outcome in rescue)
    assert any(not outcome.connected for outcome in normals)


def test_config_rejects_non_divisible_duration() -> None:
    config = load_config(DEFAULT_CONFIG)
    invalid: SimulationConfig = replace(config, duration_s=config.duration_s + 1)
    with pytest.raises(ValueError, match="divisible"):
        invalid.validate()


def test_recovery_time_is_from_discrete_simulation_ticks() -> None:
    config = load_config(DEFAULT_CONFIG)
    result = run_simulation(config, GreedyRelayPolicy(config.policy_search_grid_km))
    recovery_time = result.metrics["network_recovery_time_s"]
    assert recovery_time is None or recovery_time % config.time_step_s == 0
