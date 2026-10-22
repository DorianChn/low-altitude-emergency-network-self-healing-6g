from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from lowalt6g.dynamic_config import DynamicEventSpec, load_dynamic_config
from lowalt6g.dynamic_simulation import _apply_event, run_seed_experiment
from lowalt6g.engine import evaluate_network
from lowalt6g.optimizer import ControlDecision, diagnose_network
from lowalt6g.phase9_strategy_e import EventDrivenController
from lowalt6g.scenario import build_network


ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_dynamic_config(ROOT / "configs/phase9/dynamic_failures_development.toml")


def _state(seed: int = 92000):
    network = build_network(replace(CONFIG.base, seed=seed))
    network.drone.battery_wh = CONFIG.initial_battery_wh
    network.drone_backhaul_capacity_mbps = CONFIG.initial_backhaul_capacity_mbps
    snapshot = evaluate_network(network)
    diagnosis = diagnose_network(network, snapshot, CONFIG.congestion_threshold)
    return network, snapshot, diagnosis


def test_e_detects_station_failure_in_the_same_simulation_tick_and_deduplicates_repeat() -> None:
    network, snapshot, diagnosis = _state()
    controller = EventDrivenController(CONFIG, cooldown_s=20)
    assert controller.config.events == ()
    controller.observe(0, network, snapshot, diagnosis, CONFIG.initial_battery_wh)

    _apply_event(network, DynamicEventSpec(120, "station_failure", "bs-west"), 1.0)
    failed_snapshot = evaluate_network(network)
    failed_diagnosis = diagnose_network(network, failed_snapshot, CONFIG.congestion_threshold)
    decision = controller.observe(120, network, failed_snapshot, failed_diagnosis, CONFIG.initial_battery_wh)
    assert decision.decision_made
    record = controller.drain_timeline_events()[-1]
    assert record["event_detection_delay_s"] == 0
    assert "station_health_change" in record["event_changes"]
    assert record["replanning_trigger_time_s"] == 120

    repeated = controller.observe(120, network, failed_snapshot, failed_diagnosis, CONFIG.initial_battery_wh)
    assert not repeated.decision_made
    assert controller.event_triggered_decision_count == 2  # initial decision plus one fault response
    assert controller.event_deduplicated_count == 1
    assert controller.drain_timeline_events()[0]["suppression_reason"] == "duplicate_observation_same_simulation_tick"


def test_e_reports_no_healthy_path_and_replans_when_backhaul_recovers() -> None:
    network, snapshot, diagnosis = _state()
    controller = EventDrivenController(CONFIG)
    controller.observe(0, network, snapshot, diagnosis, CONFIG.initial_battery_wh)

    _apply_event(network, DynamicEventSpec(10, "backhaul_failure", network.drone_spec.id), 1.0)
    snapshot = evaluate_network(network)
    diagnosis = diagnose_network(network, snapshot, CONFIG.congestion_threshold)
    decision = controller.observe(10, network, snapshot, diagnosis, CONFIG.initial_battery_wh)
    assert not decision.deploy
    assert decision.reason == "drone_backhaul_temporarily_unavailable"

    repeated = controller.observe(20, network, snapshot, diagnosis, CONFIG.initial_battery_wh)
    assert not repeated.decision_made
    assert controller.event_triggered_decision_count == 2

    _apply_event(network, DynamicEventSpec(30, "backhaul_recovery", network.drone_spec.id), 1.0)
    snapshot = evaluate_network(network)
    diagnosis = diagnose_network(network, snapshot, CONFIG.congestion_threshold)
    recovered = controller.observe(30, network, snapshot, diagnosis, CONFIG.initial_battery_wh)
    assert recovered.decision_made
    assert recovered.reason != "drone_backhaul_temporarily_unavailable"


def test_e_never_deploys_without_a_healthy_ground_backhaul_or_with_battery_at_reserve() -> None:
    network, snapshot, diagnosis = _state()
    network.stations = tuple(replace(station, healthy=False) for station in network.stations)
    snapshot = evaluate_network(network)
    diagnosis = diagnose_network(network, snapshot, CONFIG.congestion_threshold)
    no_station = EventDrivenController(CONFIG).observe(0, network, snapshot, diagnosis, CONFIG.initial_battery_wh)
    assert not no_station.deploy
    assert no_station.reason == "no_healthy_base_station"

    network, snapshot, diagnosis = _state()
    low_battery = EventDrivenController(CONFIG).observe(0, network, snapshot, diagnosis, CONFIG.reserve_wh)
    assert not low_battery.deploy
    assert low_battery.reason == "battery_at_or_below_reserve"


def test_e_battery_alert_triggers_only_when_return_reserve_margin_crosses_threshold() -> None:
    network, snapshot, diagnosis = _state()
    controller = EventDrivenController(CONFIG, battery_reserve_margin_alert_wh=25.0)
    return_energy = controller._observable_state(
        network, snapshot, diagnosis, CONFIG.initial_battery_wh
    )["battery_margin_wh"]
    return_energy = CONFIG.initial_battery_wh - CONFIG.reserve_wh - return_energy

    safe_state = controller._observable_state(
        network, snapshot, diagnosis, CONFIG.reserve_wh + return_energy + 40.0
    )
    critical_state = controller._observable_state(
        network, snapshot, diagnosis, CONFIG.reserve_wh + return_energy + 20.0
    )
    categories, critical = controller._changed_categories(safe_state, safe_state)
    assert categories == []
    assert not critical

    categories, critical = controller._changed_categories(safe_state, critical_state)
    assert categories == ["battery_return_reserve_margin_critical"]
    assert not critical  # battery margin is a soft event subject to cooldown


def test_e_cooldown_keeps_committed_terminal_target_instead_of_one_step_waypoint() -> None:
    from lowalt6g.models import Position

    network, snapshot, diagnosis = _state()
    controller = EventDrivenController(CONFIG)
    first = controller.observe(0, network, snapshot, diagnosis, CONFIG.initial_battery_wh)
    terminal_target = controller.optimizer.last_target
    assert first.destination == terminal_target
    assert terminal_target is not None

    # An MPC decision exposes a one-tick waypoint. The E controller must turn
    # that into a persistent terminal destination when no new event is planned.
    controller.last_decision = replace(first, destination=Position(
        network.drone.x_km + 0.01,
        network.drone.y_km + 0.01,
    ))
    held = controller._hold(diagnosis, "no_material_observable_change", network)
    assert not held.decision_made
    assert held.destination == terminal_target


def test_e_detects_rescue_mobility_cells_and_traffic_demand_changes() -> None:
    from lowalt6g.engine import evaluate_network
    from lowalt6g.optimizer import diagnose_network

    network, snapshot, diagnosis = _state()
    controller = EventDrivenController(CONFIG)
    previous = controller._observable_state(network, snapshot, diagnosis, CONFIG.initial_battery_wh)

    rescue = next(user for user in network.users if user.group == "rescue")
    cell_km = network.config.policy_search_grid_km
    moved_x = rescue.x_km + cell_km
    if moved_x > network.config.city_width_km:
        moved_x = rescue.x_km - cell_km
    network.users = tuple(
        replace(user, x_km=moved_x) if user.id == rescue.id else user
        for user in network.users
    )
    moved_snapshot = evaluate_network(network)
    moved_diagnosis = diagnose_network(network, moved_snapshot, CONFIG.congestion_threshold)
    moved = controller._observable_state(network, moved_snapshot, moved_diagnosis, CONFIG.initial_battery_wh)
    categories, _ = controller._changed_categories(previous, moved)
    assert "rescue_position_cell_change" in categories

    higher_load = replace(rescue, demand_mbps=rescue.demand_mbps * 1.5)
    network.users = tuple(higher_load if user.id == rescue.id else user for user in network.users)
    load_snapshot = evaluate_network(network)
    load_diagnosis = diagnose_network(network, load_snapshot, CONFIG.congestion_threshold)
    load_changed = controller._observable_state(network, load_snapshot, load_diagnosis, CONFIG.initial_battery_wh)
    categories, _ = controller._changed_categories(moved, load_changed)
    assert "traffic_demand_change" in categories


def test_e_discards_a_result_that_exceeds_its_decision_output_deadline() -> None:
    network, snapshot, diagnosis = _state()
    controller = EventDrivenController(CONFIG, decision_timeout_ms=1e-12)
    decision = controller.observe(0, network, snapshot, diagnosis, CONFIG.initial_battery_wh)
    assert not decision.deploy
    assert decision.reason == "decision_timeout_safe_no_deploy"
    assert controller.timeout_count == 1
    record = controller.drain_timeline_events()[-1]
    assert record["decision_timed_out"] is True
    assert record["infeasible_reasons"] == ["decision_timeout_safe_no_deploy"]


def test_all_strategies_keep_shared_runtime_speed_and_reserve_guards_with_e_enabled() -> None:
    experiment = run_seed_experiment(
        CONFIG,
        CONFIG.seeds[0],
        include_d=True,
        include_bprime=True,
        include_e=True,
    )
    assert tuple(experiment.strategies) == (
        "A_no_recovery",
        "B_phase1_static_grid",
        "Bprime_static_grid_shared_safety",
        "C_rolling_horizon_mpc",
        "D_lexicographic_rescue_priority",
        "E_event_driven_rescue_recovery",
    )
    max_distance = CONFIG.base.drone.speed_km_per_s * CONFIG.time_step_s
    for run in experiment.strategies.values():
        assert run.metrics["drone_battery_minimum_wh"] >= CONFIG.reserve_wh - 1e-8
        moves = [event["moved_km"] for event in run.event_log if event.get("event_type") == "drone_state_update"]
        assert all(distance <= max_distance + 1e-8 for distance in moves)

    e_run = experiment.strategies["E_event_driven_rescue_recovery"]
    assert e_run.metrics["event_triggered_decision_count"] < 20
    fault_response = next(
        event
        for event in e_run.event_log
        if event.get("event_type") == "phase9_decision_timeline"
        and "station_health_change" in event.get("event_changes", [])
        and event.get("time_s") == 120
    )
    assert fault_response["event_detection_delay_s"] == 0
    action = next(
        event
        for event in e_run.event_log
        if event.get("event_type") == "phase9_action_execution_started"
        and event.get("decision_time_s") == 120
    )
    assert action["time_s"] == 120 + CONFIG.time_step_s


def test_runtime_energy_counts_hover_once_when_holding_position() -> None:
    from lowalt6g.dynamic_simulation import _advance_drone

    network, snapshot, _ = _state()
    network.drone.active = True
    network.drone.battery_wh = CONFIG.initial_battery_wh
    decision = ControlDecision(
        deploy=True,
        heading_x=0.0,
        heading_y=0.0,
        destination=network.drone.position,
        reason="test_hover",
        trigger="test",
        decision_made=True,
        objective_score=None,
        infeasible_reasons=(),
        diagnosis=diagnose_network(network, snapshot, CONFIG.congestion_threshold),
    )
    movement = _advance_drone(network, decision, snapshot, CONFIG, CONFIG.time_step_s)
    expected_hover_wh = CONFIG.hover_power_w * CONFIG.time_step_s / 3600.0
    assert abs(movement["energy_consumed_wh"] - expected_hover_wh) < 1e-10
