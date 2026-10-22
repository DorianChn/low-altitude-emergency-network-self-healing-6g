from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from lowalt6g.dynamic_config import load_dynamic_config
from lowalt6g.dynamic_world import apply_world_state, build_world_trace
from lowalt6g.engine import evaluate_network
from lowalt6g.models import Position
from lowalt6g.optimizer import RescuePriorityOptimizer, diagnose_network
from lowalt6g.phase8_experiments import (
    ROOT,
    Variant,
    _Phase8COptimizer,
    _Phase8DOptimizer,
    _apply_variant,
    _run_variant,
    _validate_seed_assignments,
    summarize_raw,
)
from lowalt6g.phase8_d_optimizer import SOURCE_OPTIMIZER_SHA256
from lowalt6g.scenario import build_network


def _scenario_config(scene_id: str):
    filenames = {
        "severe_persistent_faults": "severe_persistent_faults.toml",
        "dynamic_failures": "dynamic_failures.toml",
        "high_mobility_rescue": "high_mobility_rescue.toml",
        "high_load_backhaul_limit": "high_load_backhaul_limit.toml",
    }
    return load_dynamic_config(ROOT / "configs/phase5" / filenames[scene_id])


def test_phase8_seed_partitions_are_reproducible_and_disjoint() -> None:
    _validate_seed_assignments()


def test_phase5_historical_source_fingerprints_and_d_copy_provenance_are_recorded() -> None:
    manifest_path = ROOT / "results/phase5_frozen_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == "386be3c58f822e326d7283451bcc00c1d2c710c60240c65f5231968c8aa5b6d5"
    historical_sources = manifest["source_file_sha256"]
    assert historical_sources["dynamic_simulation.py"] == "2aa1b62f8bbef7758aaaeba3c8f8a9771320e3ed7796c42d92f790959a2faf54"
    assert SOURCE_OPTIMIZER_SHA256 == historical_sources["optimizer.py"]


def test_phase8_default_d_decision_matches_formal_d_first_decision() -> None:
    config = _scenario_config("severe_persistent_faults")
    seed = 6500
    seeded_base = replace(config.base, seed=seed)
    network = build_network(seeded_base)
    base_users = {user.id: user for user in network.users}
    trace = build_world_trace(config, seed)
    apply_world_state(network, base_users, trace, 0, 1.0)
    snapshot = evaluate_network(network)
    diagnosis = diagnose_network(network, snapshot, config.congestion_threshold)

    formal = RescuePriorityOptimizer(config)
    phase8 = _Phase8DOptimizer(config, {})
    formal_decision = formal.observe(0, network, snapshot, diagnosis, config.initial_battery_wh)
    phase8_decision = phase8.observe(0, network, snapshot, diagnosis, config.initial_battery_wh)
    assert phase8_decision == formal_decision
    assert phase8.last_target == formal.last_target


def test_c_direct_heading_ablation_changes_candidate_set() -> None:
    config = _scenario_config("severe_persistent_faults")
    base, default_options = _apply_variant(config, Variant("C_default", "C", "event_triggered_replanning", True))
    direct = _Phase8COptimizer(base, default_options)
    no_direct = _Phase8COptimizer(base, {"direct_heading_candidates": False})
    current = Position(1.0, 1.0)
    target = Position(2.0, 1.3)
    assert len(direct._action_headings(current, (target,))) == 10
    assert len(no_direct._action_headings(current, (target,))) == 9


@pytest.mark.parametrize(
    ("scene_id", "seed", "variant"),
    [
        ("severe_persistent_faults", 6500, Variant("C_reserve_75", "C", "reserve_wh", 75.0)),
        ("severe_persistent_faults", 6500, Variant("D_reserve_75", "D", "reserve_wh", 75.0)),
    ],
)
def test_reserve_sensitivity_variants_keep_execution_reserve(scene_id: str, seed: int, variant: Variant) -> None:
    config = _scenario_config(scene_id)
    trace = build_world_trace(config, seed)
    run, _, _, variant_config, _ = _run_variant(config, seed, trace, variant)
    assert variant_config.reserve_wh == 75.0
    minimum_battery = run.metrics["drone_battery_minimum_wh"]
    assert minimum_battery is not None
    assert float(minimum_battery) >= variant_config.reserve_wh - 1e-6


def test_d_ablation_cannot_disable_runtime_reserve_by_invalid_candidate_setting() -> None:
    config = _scenario_config("severe_persistent_faults")
    with pytest.raises(ValueError, match="candidate_limit must be positive"):
        _Phase8DOptimizer(config, {"candidate_limit": 0})


def test_summary_retains_unrecovered_runs_as_censored_failures() -> None:
    from lowalt6g.phase8_experiments import BASELINE_ORDER, METRICS

    def make_run(strategy_id: str, *, recovered: bool) -> dict[str, object]:
        metrics: dict[str, int | float | str | None] = {name: 0.0 for name in METRICS}
        metrics.update({
            "network_recovery_time_s": 300.0 if recovered else None,
            "network_recovery_or_censoring_time_s": 300.0 if recovered else 600.0,
            "network_recovery_success": int(recovered),
            "sustained_rescue_recovery_time_s": 330.0 if recovered else None,
            "sustained_rescue_recovery_success": int(recovered),
        })
        return {"strategy_id": strategy_id, "metrics": metrics, "event_log": [], "latency_samples_ms": []}

    baseline = {key: make_run(key, recovered=(key == "C_rolling_horizon_mpc")) for key in BASELINE_ORDER}
    variant = "C_horizon_1"
    row = {
        "scenario_id": "severe_persistent_faults",
        "seed": 90000,
        "baseline_strategy_runs": baseline,
        "variant_runs": {variant: make_run(variant, recovered=False)},
    }
    raw = {
        "phase": "development",
        "experiment_role": "exploratory_development_not_confirmatory",
        "status": "complete",
        "phase5_frozen_manifest_sha256": "test",
        "plan_sha256": "test",
        "records": [row],
        "variant_ids": [variant],
        "actual_policy_run_count": len(BASELINE_ORDER) + 1,
    }
    result = summarize_raw(raw)
    scene = result["scenarios"]["severe_persistent_faults"]
    variant_summary = scene["all_strategy_and_variant_summaries"][variant]
    assert variant_summary["recovery_time"]["successes"] == 0
    assert variant_summary["recovery_time"]["unrecovered"] == 1
    assert variant_summary["recovery_time"]["recovered_only_s"]["n"] == 0
    censor = variant_summary["metrics"]["network_recovery_or_censoring_time_s"]
    assert censor["mean"] == 600.0
    assert result["analysis_status"] == "exploratory_descriptive_only"


def test_replication_exact_test_matches_frozen_sign_flip_and_resolves_n20() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from lowalt6g.phase8_experiments import _paired_test
    from run_phase8_replication import exact_sign_flip_p, vectorized_paired_test

    differences = [0.3, -0.8, 1.1, 0.2, -0.4, 1.8, -0.9, 0.1, 0.7, -1.0]
    original = _paired_test(differences, binary=False, inferential=True)
    optimized = vectorized_paired_test(differences, binary=False, inferential=True)
    assert optimized["p_exact_two_sided"] == original["p_exact_two_sided"]
    assert exact_sign_flip_p([1.0] * 20) == 2 / (2**20)


def test_replication_seed_ids_are_disjoint_from_initial_validation() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from run_phase8_replication import REPLICATION_SEEDS, _validate_replication_seeds

    _validate_replication_seeds()
    phase8_validation = {seed for values in (range(90000, 90010), range(90100, 90110), range(90200, 90210), range(90300, 90310)) for seed in values}
    replication = {seed for values in REPLICATION_SEEDS.values() for seed in values}
    assert len(replication) == 80
    assert not phase8_validation & replication


def test_parameter_sensitivity_plot_uses_development_only_data(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from plot_phase8_parameter_sensitivity import create_sensitivity_charts

    paths = create_sensitivity_charts(ROOT / "results/phase8_development_summary.json", tmp_path)
    assert [path.suffix for path in paths] == [".png", ".svg"]
    assert all(path.is_file() and path.stat().st_size > 10_000 for path in paths)
    with pytest.raises(ValueError, match="development data"):
        create_sensitivity_charts(ROOT / "results/phase8_replication_summary.json", tmp_path)


def test_parameter_confirmation_uses_new_seed_partition_and_frozen_factor_set() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from run_phase8_sensitivity_confirmation import (
        SENSITIVITY_SEEDS,
        SENSITIVITY_VARIANT_IDS,
        validate_sensitivity_seeds,
    )

    validate_sensitivity_seeds()
    assert len(SENSITIVITY_VARIANT_IDS) == 20
    assert all(len(seeds) == 20 for seeds in SENSITIVITY_SEEDS.values())

