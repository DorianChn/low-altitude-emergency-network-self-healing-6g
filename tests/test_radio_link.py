from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path

import pytest

from lowalt6g.config import load_config
from lowalt6g.engine import evaluate_network
from lowalt6g.models import Position
from lowalt6g.multi_uav import FleetUserOutcome, UAVState, evaluate_fleet
from lowalt6g import dynamic_simulation, multi_uav
from lowalt6g.phase14_experiments import paired_test, summarize_comparison, run_comparison
from lowalt6g.phase14_radio import evaluate_fleet_link_budget, evaluate_network_link_budget
from lowalt6g.phase14_radio import radio_model_context
from lowalt6g.radio_link import (
    LegacyDistanceModel,
    LinkBudgetModelConfig,
    LinkBudgetProfile,
    LinkBudgetV1,
    free_space_path_loss_db,
    load_link_budget_config,
)
from lowalt6g.scenario import build_network


ROOT = Path(__file__).resolve().parents[1]
LINK_CONFIG = load_link_budget_config(ROOT / "configs/phase14/link_budget_v1.toml")


def _profile(**changes: float) -> LinkBudgetProfile:
    values = {
        "carrier_frequency_mhz": 1000.0,
        "tx_power_dbm": 30.0,
        "tx_antenna_gain_dbi": 0.0,
        "rx_antenna_gain_dbi": 0.0,
        "other_losses_db": 0.0,
        "reference_distance_m": 1.0,
        "path_loss_exponent": 2.0,
        "rx_sensitivity_dbm": -100.0,
        "fade_margin_db": 0.0,
        "shadowing_sigma_db": 0.0,
        "obstruction_loss_db": 0.0,
    }
    values.update(changes)
    return LinkBudgetProfile(**values)


def _simple_budget(profile: LinkBudgetProfile) -> LinkBudgetV1:
    return LinkBudgetV1(
        LinkBudgetModelConfig(
            version="link_budget_v1",
            base_access=profile,
            uav_access=profile,
            backhaul=profile,
        ),
        seed=43,
    )


def test_free_space_path_loss_matches_reference_value_and_units() -> None:
    assert free_space_path_loss_db(1000.0, 1.0) == pytest.approx(32.4478, abs=0.01)
    assert free_space_path_loss_db(1000.0, 1000.0) - free_space_path_loss_db(1000.0, 1.0) == pytest.approx(60.0)


def test_log_distance_path_loss_increases_with_distance_and_zero_is_bounded() -> None:
    model = _simple_budget(_profile())
    at_reference = model.path_loss_db("base_access", 0.0, "bs", "ue")
    at_one_meter = model.path_loss_db("base_access", 0.001, "bs", "ue")
    at_two_meters = model.path_loss_db("base_access", 0.002, "bs", "ue")
    assert at_reference == pytest.approx(at_one_meter)
    assert at_two_meters > at_one_meter


@pytest.mark.parametrize(
    "frequency_mhz,distance_m",
    [(0.0, 1.0), (-1.0, 1.0), (1000.0, 0.0), (1000.0, -2.0), (math.inf, 1.0)],
)
def test_free_space_formula_rejects_invalid_units_or_values(frequency_mhz: float, distance_m: float) -> None:
    with pytest.raises(ValueError):
        free_space_path_loss_db(frequency_mhz, distance_m)


@pytest.mark.parametrize(
    "change,value",
    [
        ("carrier_frequency_mhz", 0.0),
        ("reference_distance_m", 0.0),
        ("path_loss_exponent", 0.0),
        ("other_losses_db", -0.1),
        ("rx_sensitivity_dbm", -250.0),
        ("fade_margin_db", -1.0),
        ("shadowing_sigma_db", -1.0),
        ("obstruction_loss_db", -1.0),
    ],
)
def test_profile_validation_rejects_invalid_values(change: str, value: float) -> None:
    with pytest.raises(ValueError):
        _profile(**{change: value}).validate()


def test_received_power_and_sensitivity_boundary_are_explicit() -> None:
    profile = _profile(
        carrier_frequency_mhz=1000.0,
        tx_power_dbm=32.4477832219,
        rx_sensitivity_dbm=-100.0,
        fade_margin_db=0.0,
    )
    assessment = _simple_budget(profile).assess(
        "base_access", 0.001, 2.0, "bs", "ue"
    )
    assert assessment.path_loss_db == pytest.approx(32.4478, abs=1e-3)
    assert assessment.received_power_dbm == pytest.approx(0.0, abs=1e-3)
    assert assessment.margin_db == pytest.approx(100.0, abs=1e-3)
    assert assessment.feasible

    edge_profile = replace(profile, tx_power_dbm=profile.tx_power_dbm - 100.0)
    edge = _simple_budget(edge_profile).assess("base_access", 0.001, 2.0, "bs", "ue")
    assert edge.margin_db == pytest.approx(0.0, abs=1e-3)
    assert edge.feasible
    below = _simple_budget(replace(edge_profile, tx_power_dbm=edge_profile.tx_power_dbm - 0.01))
    assert not below.assess("base_access", 0.001, 2.0, "bs", "ue").feasible


def test_hard_distance_limit_and_fade_margin_are_both_enforced() -> None:
    model = _simple_budget(_profile(tx_power_dbm=100.0))
    assert model.assess("base_access", 1.0, 1.0, "bs", "ue").feasible
    assert model.assess("base_access", 1.0001, 1.0, "bs", "ue").failure_reason == "distance_limit_exceeded"

    weak = _simple_budget(_profile(tx_power_dbm=-130.0, rx_sensitivity_dbm=-100.0, fade_margin_db=20.0))
    result = weak.assess("base_access", 0.001, 2.0, "bs", "ue")
    assert not result.feasible
    assert result.failure_reason == "received_power_below_sensitivity_with_fade_margin"


def test_shadowing_is_repeatable_and_keyed_by_link_not_call_order() -> None:
    config = replace(LINK_CONFIG, base_access=replace(LINK_CONFIG.base_access, shadowing_sigma_db=6.0))
    first = LinkBudgetV1(config, seed=9123)
    second = LinkBudgetV1(config, seed=9123)
    a = first.path_loss_db("base_access", 0.9, "bs-1", "ue-2")
    first.path_loss_db("base_access", 0.9, "bs-9", "ue-8")
    b = first.path_loss_db("base_access", 0.9, "bs-1", "ue-2")
    c = second.path_loss_db("base_access", 0.9, "bs-1", "ue-2")
    assert a == b == c
    assert first.config.shadowing_model == "static_per_link_per_run"


def test_link_profiles_are_isolated() -> None:
    model = LinkBudgetV1(LINK_CONFIG, seed=17)
    base = model.path_loss_db("base_access", 1.0, "bs", "ue")
    access = model.path_loss_db("uav_access", 1.0, "uav", "ue")
    assert base != access
    with pytest.raises(ValueError, match="unknown radio link profile"):
        model.assess("unknown", 1.0, 2.0, "a", "b")


def test_link_budget_config_file_is_valid_and_has_all_profiles() -> None:
    config = load_link_budget_config(ROOT / "configs/phase14/link_budget_v1.toml")
    assert set(config.to_dict()) == {"version", "shadowing_model", "base_access", "uav_access", "backhaul"}
    assert config.version == "link_budget_v1"


def test_no_healthy_backhaul_station_cannot_create_drone_connection() -> None:
    config = load_config(ROOT / "configs/disaster_scenario.toml")
    network = build_network(config)
    network.stations = tuple(replace(station, healthy=False) for station in network.stations)
    network.drone.active = True
    snapshot = evaluate_network_link_budget(network, LinkBudgetV1(LINK_CONFIG, seed=config.seed))
    assert not any(outcome.connected for outcome in snapshot.outcomes)


def test_legacy_model_matches_default_single_uav_outcomes() -> None:
    config = load_config(ROOT / "configs/disaster_scenario.toml")
    implicit = build_network(config)
    explicit = build_network(config)
    explicit.drone.active = True
    implicit.drone.active = True
    expected = evaluate_network(implicit)
    actual = evaluate_network(explicit)
    assert actual.outcomes == expected.outcomes
    assert actual.links == expected.links
    assert actual.resource_utilization == expected.resource_utilization
    model = LegacyDistanceModel()
    sample = model.assess("base_access", 1.0, 1.0, "bs", "ue")
    assert sample.feasible and sample.path_loss_db is None


def test_multi_uav_legacy_capacity_is_shared_and_users_are_unique() -> None:
    config = load_config(ROOT / "configs/disaster_scenario.toml")
    network = build_network(config)
    station = next(item for item in network.stations if item.healthy)
    network.stations = tuple(
        replace(item, capacity_mbps=4.0) if item.id == station.id else replace(item, healthy=False)
        for item in network.stations
    )
    network.users = tuple(
        replace(item, x_km=station.x_km, y_km=station.y_km, demand_mbps=4.0)
        for item in network.users[:2]
    )
    units = [
        UAVState(
            id=f"uav-{index}",
            position=Position(station.x_km, station.y_km),
            target_position=None,
            battery_wh=300.0,
            reserve_wh=50.0,
            access_capacity_mbps=10.0,
            backhaul_capacity_mbps=10.0,
            active=True,
        )
        for index in range(2)
    ]
    snapshot = evaluate_fleet(network, units)
    assert len(snapshot.outcomes) == len(network.users)
    assert sum(outcome.connected for outcome in snapshot.outcomes) == 1
    assert snapshot.resource_used_mbps[f"station:{station.id}"] <= 4.0
    assert all(unit.battery_wh >= unit.reserve_wh for unit in units)


def test_new_model_records_link_budget_metadata_and_enforces_per_uav_capacity() -> None:
    config = load_config(ROOT / "configs/disaster_scenario.toml")
    network = build_network(config)
    station = next(item for item in network.stations if item.healthy)
    network.stations = tuple(
        replace(item, capacity_mbps=50.0) if item.id == station.id else replace(item, healthy=False)
        for item in network.stations
    )
    network.users = tuple(
        replace(item, x_km=station.x_km + 0.1, y_km=station.y_km, demand_mbps=3.0)
        for item in network.users[:3]
    )
    model = LinkBudgetV1(LINK_CONFIG, seed=config.seed)
    units = [
        UAVState(
            id=f"uav-{index}",
            position=Position(station.x_km + 0.1, station.y_km),
            target_position=None,
            battery_wh=300.0,
            reserve_wh=50.0,
            access_capacity_mbps=3.0,
            backhaul_capacity_mbps=50.0,
            active=True,
        )
        for index in range(2)
    ]
    snapshot = evaluate_fleet_link_budget(network, units, model)
    assert len({outcome.user_id for outcome in snapshot.outcomes}) == len(network.users)
    assert all(
        value <= snapshot.resource_capacity_mbps[key] + 1e-9
        for key, value in snapshot.resource_used_mbps.items()
    )
    assert snapshot.resource_capacity_mbps[f"uav:uav-0"] == 3.0
    assert snapshot.resource_capacity_mbps[f"uav:uav-1"] == 3.0


def test_new_link_budget_direct_path_can_reject_legacy_reachable_pair() -> None:
    config = load_config(ROOT / "configs/disaster_scenario.toml")
    network = build_network(config)
    station = next(item for item in network.stations if item.healthy)
    target = replace(network.users[0], x_km=station.x_km + 2.0, y_km=station.y_km)
    network.users = (target,)
    legacy = evaluate_network(network)
    weak_model = LinkBudgetV1(
        LinkBudgetModelConfig(
            version="link_budget_v1",
            base_access=_profile(tx_power_dbm=-120.0),
            uav_access=LINK_CONFIG.uav_access,
            backhaul=LINK_CONFIG.backhaul,
        ),
        seed=1,
    )
    budget = evaluate_network_link_budget(network, weak_model)
    assert legacy.outcomes[0].connected
    assert not budget.outcomes[0].connected


def test_phase14_radio_context_routes_and_restores_single_evaluator() -> None:
    config = load_config(ROOT / "configs/disaster_scenario.toml")
    network = build_network(config)
    station = next(item for item in network.stations if item.healthy)
    user = replace(network.users[0], x_km=station.x_km + 2.0, y_km=station.y_km)
    network.users = (user,)
    original = dynamic_simulation.evaluate_network
    model = LinkBudgetV1(
        LinkBudgetModelConfig(
            version="link_budget_v1",
            base_access=_profile(tx_power_dbm=-120.0),
            uav_access=LINK_CONFIG.uav_access,
            backhaul=LINK_CONFIG.backhaul,
        ),
        seed=7,
    )
    with radio_model_context(model):
        assert dynamic_simulation.evaluate_network(network).outcomes[0].connected is False
    assert dynamic_simulation.evaluate_network is original
    assert dynamic_simulation.evaluate_network(network).outcomes[0].connected is True


def test_phase14_radio_context_routes_fleet_evaluator_and_restores_it() -> None:
    config = load_config(ROOT / "configs/disaster_scenario.toml")
    network = build_network(config)
    station = next(item for item in network.stations if item.healthy)
    network.users = (replace(network.users[0], x_km=station.x_km + 2.0, y_km=station.y_km),)
    unit = UAVState(
        id="uav-0", position=Position(station.x_km, station.y_km),
        target_position=None, battery_wh=300.0, reserve_wh=50.0,
        access_capacity_mbps=20.0, backhaul_capacity_mbps=20.0, active=True,
    )
    original = multi_uav.evaluate_fleet
    model = LinkBudgetV1(
        LinkBudgetModelConfig(
            version="link_budget_v1",
            base_access=_profile(tx_power_dbm=-120.0),
            uav_access=_profile(tx_power_dbm=-120.0),
            backhaul=_profile(tx_power_dbm=-120.0),
        ),
        seed=19,
    )
    with radio_model_context(model):
        assert multi_uav.evaluate_fleet(network, [unit]).outcomes[0].connected is False
    assert multi_uav.evaluate_fleet is original
    assert multi_uav.evaluate_fleet(network, [unit]).outcomes[0].connected is True


def test_paired_statistics_do_not_infer_from_one_seed() -> None:
    one = paired_test([0.4], [0.3])
    assert one["n_pairs"] == 1
    assert one["ci95_mean_difference"] is None
    assert one["p_value_two_sided"] is None
    assert one["paired_cohen_dz"] is None


def test_single_seed_summary_leaves_holm_inference_unavailable() -> None:
    raw = run_comparison("development", scenario_filter="severe_persistent_faults", seed_limit=1)
    summary = summarize_comparison(raw)
    items = summary["primary_comparisons_holm"]
    assert len(items) == 3
    assert all(item["p_value_holm"] is None for item in items)
    assert all(item["inference_available"] is False for item in items)
