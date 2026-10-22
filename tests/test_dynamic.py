from dataclasses import replace
from pathlib import Path

import pytest

from lowalt6g.dynamic_config import DynamicEventSpec, load_dynamic_config
from lowalt6g.dynamic_simulation import _apply_event, build_seed_replay_payload, run_seed_experiment
from lowalt6g.dynamic_world import apply_world_state, build_world_trace
from lowalt6g.engine import distance_km, evaluate_network
from lowalt6g.optimizer import RollingHorizonOptimizer, diagnose_network
from lowalt6g.scenario import build_network


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_CONFIG = ROOT / "configs" / "dynamic_scenario.toml"


def test_dynamic_trace_and_event_timestamps_are_seed_reproducible() -> None:
    config = load_dynamic_config(DYNAMIC_CONFIG)
    first = build_world_trace(config, 2026)
    repeated = build_world_trace(config, 2026)
    other = build_world_trace(config, 2027)

    assert first.trace_sha256 == repeated.trace_sha256
    assert first.user_positions_by_tick == repeated.user_positions_by_tick
    assert first.trace_sha256 != other.trace_sha256
    configured = [event for event in first.environment_event_log if event["source"] == "configured_event_schedule"]
    assert len(configured) == len(config.events)
    assert all(isinstance(event["time_s"], int) for event in first.environment_event_log)
    assert [event["time_s"] for event in first.environment_event_log] == sorted(
        event["time_s"] for event in first.environment_event_log
    )
    assert {event["event_type"] for event in configured} >= {
        "station_failure",
        "station_recovery",
        "traffic_change",
        "backhaul_failure",
        "backhaul_recovery",
    }


def test_dynamic_events_mutate_station_backhaul_and_load_state() -> None:
    config = load_dynamic_config(DYNAMIC_CONFIG)
    network = build_network(config.base)
    original_demand = network.users[0].demand_mbps

    _apply_event(network, DynamicEventSpec(10, "station_failure", "bs-east"), 1.0)
    assert not next(station for station in network.stations if station.id == "bs-east").healthy
    _apply_event(network, DynamicEventSpec(20, "station_recovery", "bs-east"), 1.0)
    assert next(station for station in network.stations if station.id == "bs-east").healthy
    _apply_event(network, DynamicEventSpec(30, "backhaul_failure", network.drone_spec.id), 1.0)
    assert not network.drone_backhaul_available
    _apply_event(network, DynamicEventSpec(40, "backhaul_recovery", network.drone_spec.id), 1.0)
    assert network.drone_backhaul_available
    multiplier = _apply_event(network, DynamicEventSpec(50, "traffic_change", "city", 1.4), 1.0)
    assert multiplier == 1.4
    trace = build_world_trace(config, config.base.seed)
    base_users = {user.id: user for user in network.users}
    apply_world_state(network, base_users, trace, 0, multiplier)
    assert network.users[0].demand_mbps == pytest.approx(original_demand * 1.4)


def test_optimizer_diagnoses_failure_and_returns_explained_feasible_action() -> None:
    config = load_dynamic_config(DYNAMIC_CONFIG)
    network = build_network(config.base)
    snapshot = evaluate_network(network)
    diagnosis = diagnose_network(network, snapshot, config.congestion_threshold)

    assert diagnosis.failed_station_ids == tuple(
        sorted(station.id for station in network.stations if not station.healthy)
    )
    assert set(diagnosis.disconnected_rescue_ids) <= set(diagnosis.disconnected_user_ids)

    decision = RollingHorizonOptimizer(config).observe(0, network, snapshot, diagnosis, config.initial_battery_wh)
    assert decision.decision_made
    assert decision.reason
    if not decision.deploy:
        assert decision.infeasible_reasons
        return

    assert decision.destination is not None
    destination = decision.destination
    move = distance_km(network.drone.x_km, network.drone.y_km, destination.x_km, destination.y_km)
    assert move <= network.drone_spec.speed_km_per_s * config.time_step_s + 1e-9
    assert 0 <= destination.x_km <= network.config.city_width_km
    assert 0 <= destination.y_km <= network.config.city_height_km
    healthy = [station for station in network.stations if station.healthy]
    assert min(distance_km(destination.x_km, destination.y_km, station.x_km, station.y_km) for station in healthy) <= network.drone_spec.backhaul_radius_km + 1e-9

    forecast = evaluate_network(
        network,
        drone_position=(destination.x_km, destination.y_km),
        drone_active=True,
    )
    assert all(value <= 1.0 + 1e-9 for value in forecast.resource_utilization.values())
    relaying = any(outcome.connected and outcome.path_kind == "drone_relay" for outcome in forecast.outcomes)
    energy = (
        move * config.movement_wh_per_km
        + (config.hover_power_w + (config.relay_power_w if relaying else 0.0)) * config.time_step_s / 3600.0
    )
    remaining = config.initial_battery_wh - energy
    nearest_return = min(
        distance_km(destination.x_km, destination.y_km, station.x_km, station.y_km)
        for station in healthy
    )
    assert remaining >= config.reserve_wh - 1e-9
    assert remaining - nearest_return * config.movement_wh_per_km >= config.reserve_wh - 1e-9


def test_matched_three_policy_run_respects_speed_and_battery_constraints() -> None:
    config = load_dynamic_config(DYNAMIC_CONFIG)
    experiment = run_seed_experiment(config, 2026)
    assert set(experiment.strategies) == {
        "A_no_recovery",
        "B_phase1_static_grid",
        "C_rolling_horizon_mpc",
    }
    assert experiment.trace_sha256 == build_world_trace(config, 2026).trace_sha256

    for run in experiment.strategies.values():
        metrics = run.metrics
        assert metrics["drone_battery_minimum_wh"] >= config.reserve_wh - 1e-9
        assert metrics["drone_battery_remaining_wh"] <= config.initial_battery_wh + 1e-9
        for event in run.event_log:
            if event["event_type"] != "drone_state_update":
                continue
            assert event["moved_km"] <= config.base.drone.speed_km_per_s * config.time_step_s + 1e-8
            assert event["battery_remaining_wh"] >= config.reserve_wh - 1e-9
            x, y = event["position_km"]
            assert 0 <= x <= config.base.city_width_km
            assert 0 <= y <= config.base.city_height_km


def test_seed_replay_contains_actual_timestamped_network_state_for_each_policy() -> None:
    config = load_dynamic_config(DYNAMIC_CONFIG)
    replay = build_seed_replay_payload(config, 2026)

    assert replay["mode"] == "precomputed_offline_replay"
    assert replay["live_stream"] is False
    assert replay["world_trace_sha256"] == build_world_trace(config, 2026).trace_sha256
    strategies = replay["strategies"]
    assert isinstance(strategies, dict)
    assert set(strategies) == {
        "A_no_recovery",
        "B_phase1_static_grid",
        "C_rolling_horizon_mpc",
    }

    for strategy_id, run in strategies.items():
        snapshots = run["state_snapshots"]
        assert len(snapshots) == config.duration_s // config.time_step_s + 1
        assert [frame["time_s"] for frame in snapshots] == list(
            range(0, config.duration_s + config.time_step_s, config.time_step_s)
        )
        assert all(len(frame["users"]) == config.base.normal_user_count + config.base.rescue_user_count for frame in snapshots)
        assert all(isinstance(user["connected"], bool) for frame in snapshots for user in frame["users"])
        assert all(isinstance(frame["decision"].get("decision_made"), bool) for frame in snapshots)

        at_start = snapshots[0]
        start_health = {station["id"]: station["healthy"] for station in at_start["stations"]}
        assert start_health == {"bs-west": True, "bs-central": False, "bs-east": False}
        at_60s = snapshots[6]
        assert next(station for station in at_60s["stations"] if station["id"] == "bs-west")["healthy"] is False

        drone_states = [frame["drone"] for frame in snapshots]
        assert all(config.reserve_wh - 1e-9 <= drone["battery_wh"] <= config.initial_battery_wh + 1e-9 for drone in drone_states)
        assert all(0 <= drone["x_km"] <= config.base.city_width_km for drone in drone_states)
        assert all(0 <= drone["y_km"] <= config.base.city_height_km for drone in drone_states)

        metrics = run["metrics"]
        connected = sum(user["connected"] for frame in snapshots for user in frame["users"])
        expected_rate = connected / (len(snapshots) * len(snapshots[0]["users"]))
        assert metrics["user_connection_success_rate"] == pytest.approx(expected_rate, abs=1e-6)
        assert all("event_type" in event and "time_s" in event for event in run["event_log"])


def test_benchmark_rejects_fewer_than_twenty_seeds() -> None:
    from lowalt6g.experiment import run_dynamic_benchmark

    config = load_dynamic_config(DYNAMIC_CONFIG)
    with pytest.raises(ValueError, match="at least 20 fixed seeds"):
        run_dynamic_benchmark(replace(config, seeds=(2026,)))


def test_unrecovered_run_is_null_and_excluded_from_recovery_time_mean() -> None:
    from lowalt6g.experiment import _aggregate

    config = load_dynamic_config(DYNAMIC_CONFIG)
    short_base = replace(config.base, duration_s=60)
    short_events = tuple(event for event in config.events if event.time_s <= short_base.duration_s)
    short_config = replace(config, base=short_base, events=short_events)
    experiment = run_seed_experiment(short_config, 2026)
    aggregate = _aggregate([experiment])

    for strategy_id in ("A_no_recovery", "B_phase1_static_grid", "C_rolling_horizon_mpc"):
        assert experiment.strategies[strategy_id].metrics["network_recovery_time_s"] is None
        recovery = aggregate[strategy_id]["network_recovery"]
        assert recovery["recovered_runs"] == 0
        assert recovery["unrecovered_runs"] == 1
        assert recovery["recovered_only_time_s"]["n"] == 0
        assert recovery["recovered_only_time_s"]["mean"] is None


def test_phase4_strategy_uses_same_seed_and_preserves_runtime_safety() -> None:
    config = load_dynamic_config(DYNAMIC_CONFIG)
    experiment = run_seed_experiment(config, 3000, include_d=True)

    assert experiment.trace_sha256 == build_world_trace(config, 3000).trace_sha256
    assert set(experiment.strategies) == {
        "A_no_recovery",
        "B_phase1_static_grid",
        "C_rolling_horizon_mpc",
        "D_lexicographic_rescue_priority",
    }
    a = experiment.strategies["A_no_recovery"]
    b = experiment.strategies["B_phase1_static_grid"]
    d = experiment.strategies["D_lexicographic_rescue_priority"]
    assert a.metrics["network_recovery_time_s"] == 520
    assert a.metrics["sustained_rescue_recovery_time_s"] >= a.metrics["network_recovery_time_s"]
    assert b.metrics["sustained_rescue_recovery_time_s"] >= b.metrics["network_recovery_time_s"]
    assert d.metrics["controller_observe_total_ms"] >= d.metrics["algorithm_decision_total_ms"]
    assert d.metrics["replan_count"] == d.metrics["algorithm_decision_count"] - 1
    assert d.metrics["infeasible_decision_count"] == sum(
        d.metrics["infeasible_decision_reasons"].values()
    )

    rescue_events = [
        event
        for event in experiment.environment_events
        if event["event_type"] == "station_recovery"
    ]
    assert any(event["time_s"] == 520 and event["target_id"] == "bs-central" for event in rescue_events)

    for run in experiment.strategies.values():
        assert run.metrics["drone_battery_minimum_wh"] >= config.reserve_wh - 1e-9
        for event in run.event_log:
            if event["event_type"] != "drone_state_update":
                continue
            assert event["moved_km"] <= config.base.drone.speed_km_per_s * config.time_step_s + 1e-8
            assert event["battery_remaining_wh"] >= config.reserve_wh - 1e-9
            x, y = event["position_km"]
            assert 0 <= x <= config.base.city_width_km
            assert 0 <= y <= config.base.city_height_km
        if run.strategy_id == "D_lexicographic_rescue_priority":
            decisions = [event for event in run.event_log if event["event_type"] == "optimizer_decision"]
            assert decisions
            assert all("planning_target_km" in event for event in decisions)
            assert all(
                event["reason"] == "lexicographic_rescue_action_selected"
                or event["infeasible_reasons"]
                for event in decisions
            )
            successful = [event for event in decisions if event["reason"] == "lexicographic_rescue_action_selected"]
            assert successful
            assert all(
                event["planned_sortie_energy_wh"]
                <= event["planning_battery_wh"] - config.reserve_wh + 1e-6
                for event in successful
            )


def test_phase4_benchmark_serializes_seed_level_latency_and_confidence_intervals() -> None:
    from lowalt6g.experiment import run_dynamic_benchmark

    config = load_dynamic_config(DYNAMIC_CONFIG)
    short_base = replace(config.base, duration_s=60)
    short_config = replace(
        config,
        base=short_base,
        events=tuple(event for event in config.events if event.time_s <= short_base.duration_s),
        seeds=(3000,),
    )
    result = run_dynamic_benchmark(
        short_config,
        minimum_seed_count=1,
        include_d=True,
    )
    assert result["schema_version"] == "2.1"
    assert result["strategy_order"][-1] == "D_lexicographic_rescue_priority"
    d_summary = result["aggregate"]["D_lexicographic_rescue_priority"]
    assert d_summary["metrics"]["rescue_user_service_success_rate"]["mean_ci95_t"] is None
    assert d_summary["metrics"]["network_recovery_success"]["ci95_wilson"] is not None
    for strategy_id in result["strategy_order"]:
        run = result["seed_experiments"][0]["strategies"][strategy_id]
        assert len(run["latency_samples_ms"]) == run["metrics"]["latency_sample_count"]


def test_phase4_chart_accepts_scalar_recovery_rates(tmp_path: Path) -> None:
    from lowalt6g.charts import write_phase4_comparison_chart

    strategy_order = ["A", "B", "C", "D"]
    summary = {"mean": 0.5, "mean_ci95_t": [0.4, 0.6]}
    binary_summary = {"mean": 1.0, "mean_ci95_t": [1.0, 1.0], "ci95_wilson": [0.839, 1.0]}
    aggregate = {
        strategy_id: {
            "metrics": {
                "user_connection_success_rate": summary,
                "rescue_user_service_success_rate": summary,
                "network_recovery_success": binary_summary,
                "sustained_rescue_recovery_success": binary_summary,
                "drone_energy_consumed_wh": summary,
                "algorithm_decision_total_ms": summary,
            },
            "network_recovery": {"success_rate": 1.0, "recovered_only_time_s": summary},
            "sustained_network_recovery_30s": {"success_rate": 1.0},
            "latency_conditioned_on_success": {"per_seed_average_ms": summary},
        }
        for strategy_id in strategy_order
    }
    result = {
        "aggregate": aggregate,
        "strategy_order": strategy_order,
        "reproducibility": {"seed_count": 1},
        "seed_experiments": [
            {"strategies": {strategy_id: {"latency_samples_ms": [10.0, 20.0]} for strategy_id in strategy_order}}
        ],
    }

    paths = write_phase4_comparison_chart(result, tmp_path)

    assert len(paths) == 4
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)


def test_wilson_interval_for_binary_recovery_rate() -> None:
    from lowalt6g.experiment import _wilson_interval

    assert _wilson_interval([1.0] * 20) == [0.838875, 1.0]
    assert _wilson_interval([0.0] * 20) == [0.0, 0.161125]
