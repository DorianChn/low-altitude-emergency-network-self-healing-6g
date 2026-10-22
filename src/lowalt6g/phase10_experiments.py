"""Frozen development/confirmation experiments for multi-UAV coordination."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import Any, Callable

from .dynamic_config import load_dynamic_config
from .dynamic_world import build_world_trace
from .experiment import _stats, _wilson_interval
from .multi_uav import MultiUAVOptions
from .multi_uav_simulation import run_fleet_policy, run_single_bprime
from .phase8_experiments import _holm_adjust


ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = "configs/phase10/multi_uav_plan.json"
PROTOCOL_PATH = "configs/phase10/validation_protocol.json"
SCENARIO_ORDER = (
    "severe_persistent_faults",
    "dynamic_failures",
    "high_mobility_rescue",
    "high_load_backhaul_limit",
)
POLICY_SPECS = (
    ("Bprime_static_grid_shared_safety", 1),
    ("F_independent_greedy", 2),
    ("G_centralized_coordination", 2),
    ("F_independent_greedy", 3),
    ("G_centralized_coordination", 3),
)
SOURCE_PATHS = (
    "src/lowalt6g/config.py",
    "src/lowalt6g/dynamic_config.py",
    "src/lowalt6g/dynamic_simulation.py",
    "src/lowalt6g/dynamic_world.py",
    "src/lowalt6g/energy_budget.py",
    "src/lowalt6g/engine.py",
    "src/lowalt6g/models.py",
    "src/lowalt6g/scenario.py",
    "src/lowalt6g/phase8_experiments.py",
    "src/lowalt6g/multi_uav.py",
    "src/lowalt6g/multi_uav_simulation.py",
    "src/lowalt6g/phase10_experiments.py",
    "scripts/run_phase10_experiments.py",
    "tests/test_phase6.py",
    "tests/test_phase8.py",
    "tests/test_phase9.py",
    "tests/test_phase10.py",
)
HISTORICAL_REPORTS = (
    "PHASE5_REPORT.md",
    "PHASE8_REPORT.md",
    "PHASE9_REPORT.md",
    "PHASE9_ENERGY_SENSITIVITY_REPORT.md",
)
HISTORICAL_SEED_CEILING = 93509


def load_plan() -> dict[str, Any]:
    return json.loads((ROOT / PLAN_PATH).read_text(encoding="utf-8"))


def policy_key(strategy_id: str, fleet_size: int) -> str:
    return f"{strategy_id}_uav{fleet_size}"


def make_options(plan: dict[str, Any]) -> MultiUAVOptions:
    model = plan["fleet_model"]
    return MultiUAVOptions(
        grid_spacing_km=float(model["candidate_grid_spacing_km"]),
        candidate_limit=int(model["candidate_limit_per_uav"]),
        min_separation_km=float(model["min_uav_separation_km"]),
        replan_interval_s=int(model["replan_interval_s"]),
        decision_timeout_ms=float(model["decision_timeout_ms"]),
        max_joint_combinations=int(model["max_joint_candidate_combinations"]),
        sortie_service_budget_steps=int(model["sortie_service_budget_steps"]),
    )


def run_development(
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    plan = load_plan()
    seeds_by_scene = plan["seed_assignments"]["development"]
    return _run_partition("development", seeds_by_scene, plan, progress=progress)


def run_confirmation(
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    protocol = _verify_protocol()
    plan = load_plan()
    seeds_by_scene = protocol["confirmation_seed_assignments"]
    return _run_partition("confirmation", seeds_by_scene, plan, protocol=protocol, progress=progress)


def freeze_protocol() -> dict[str, Any]:
    protocol_path = ROOT / PROTOCOL_PATH
    if protocol_path.exists():
        raise FileExistsError(f"refusing to overwrite frozen Phase 10 protocol: {protocol_path}")
    plan = load_plan()
    development_path = ROOT / "results/phase10_development_raw.json"
    development_summary_path = ROOT / "results/phase10_development_summary.json"
    if not development_path.is_file() or not development_summary_path.is_file():
        raise ValueError("complete the Phase 10 development experiment and summary before freezing")
    raw = json.loads(development_path.read_text(encoding="utf-8"))
    expected = plan["seed_assignments"]["development"]
    _validate_seed_records(raw, expected, expected_policy_run_count=60)
    hist_hashes = _historical_hashes()
    source_hash = _combined_source_hash()
    config_hashes = _phase10_config_hashes(plan)
    protocol = {
        "schema_version": "1.0",
        "phase": "phase10_multi_uav_coordination",
        "status": "frozen_before_confirmation",
        "implementation_revision": "M1_shared_capacity_and_bounded_FG_search_v1",
        "source_sha256": source_hash,
        "configuration_sha256": config_hashes,
        "protected_phase1_to_phase9_sha256": hist_hashes,
        "development_raw_sha256": _sha256(development_path),
        "development_summary_sha256": _sha256(development_summary_path),
        "development_seed_assignments": expected,
        "confirmation_seed_assignments": plan["seed_assignments"]["confirmation"],
        "confirmation_seed_count_per_scenario": 20,
        "policies": [
            {"strategy_id": strategy, "fleet_size": size, "run_key": policy_key(strategy, size)}
            for strategy, size in POLICY_SPECS
        ],
        "model_and_analysis_plan": plan,
        "analysis_freeze_note": "Confirmation seeds are held out from Phase 1-9 datasets and Phase 10 development. No tuning after this protocol is written.",
    }
    _validate_seed_assignments(plan, hist_hashes)
    _atomic_write(protocol_path, protocol)
    protocol["protocol_sha256"] = _sha256(protocol_path)
    return protocol


def _run_partition(
    partition: str,
    seeds_by_scene: dict[str, list[int]],
    plan: dict[str, Any],
    *,
    protocol: dict[str, Any] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if partition not in {"development", "confirmation"}:
        raise ValueError("partition must be development or confirmation")
    if partition == "confirmation":
        assert protocol is not None
        _verify_protocol()
    _validate_seed_assignments(plan, protocol.get("protected_phase1_to_phase9_sha256") if protocol else None)
    label = "development" if partition == "development" else "confirmation"
    raw_path = ROOT / f"results/phase10_{label}_raw.json"
    summary_path = ROOT / f"results/phase10_{label}_summary.json"
    progress_path = ROOT / f"results/phase10_{label}_progress.jsonl"
    if raw_path.exists() or summary_path.exists() or progress_path.exists():
        raise FileExistsError(f"Phase 10 {label} outputs already exist; refusing to overwrite historical experiment files")

    options = make_options(plan)
    scenario_paths = plan["scenario_config_paths"]
    scene_configs = {
        scene_id: load_dynamic_config(ROOT / scenario_paths[scene_id])
        for scene_id in SCENARIO_ORDER
    }
    expected_total = sum(len(seeds_by_scene[scene]) for scene in SCENARIO_ORDER)
    records: list[dict[str, Any]] = []
    run_count = 0
    started = time.perf_counter()
    with progress_path.open("x", encoding="utf-8", newline="\n") as progress_file:
        for scene_id in SCENARIO_ORDER:
            config = scene_configs[scene_id]
            for seed in seeds_by_scene[scene_id]:
                trace = build_world_trace(config, int(seed))
                strategy_runs: dict[str, dict[str, Any]] = {}
                baseline = run_single_bprime(config, int(seed), trace)
                baseline_dict = baseline.to_dict(include_latency_samples=True)
                # DynamicRun predates explicit trace fingerprints. Attach the
                # shared trace hash here so all policies are checked uniformly.
                baseline_dict["world_trace_sha256"] = trace.trace_sha256
                strategy_runs[policy_key("Bprime_static_grid_shared_safety", 1)] = _normalize_bprime(
                    config, baseline_dict, fleet_size=1
                )
                run_count += 1
                for fleet_size in (2, 3):
                    for strategy_id in ("F_independent_greedy", "G_centralized_coordination"):
                        result = run_fleet_policy(
                            config,
                            int(seed),
                            trace,
                            fleet_size=fleet_size,
                            strategy_id=strategy_id,
                            options=options,
                        )
                        strategy_runs[policy_key(strategy_id, fleet_size)] = result
                        run_count += 1
                row = {
                    "scenario_id": scene_id,
                    "seed": int(seed),
                    "world_trace_sha256": trace.trace_sha256,
                    "duration_s": config.duration_s,
                    "time_step_s": config.time_step_s,
                    "strategy_runs": strategy_runs,
                }
                if any(
                    run.get("world_trace_sha256") != trace.trace_sha256
                    for run in strategy_runs.values()
                ):
                    raise ValueError(f"matched world-trace hash mismatch: {scene_id}/{seed}")
                records.append(row)
                progress_file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                progress_file.flush()
                os.fsync(progress_file.fileno())
                if progress:
                    progress(
                        f"{partition} {scene_id} seed={seed}: {run_count}/{expected_total * len(POLICY_SPECS)} policy runs"
                    )

    raw: dict[str, Any] = {
        "schema_version": "1.0",
        "phase": "phase10_multi_uav_coordination",
        "experiment_role": "exploratory_development" if partition == "development" else "confirmatory_held_out",
        "partition": partition,
        "model_scope": "abstract_6g_research_simulation_not_real_network_test",
        "implementation_revision": "M1_shared_capacity_and_bounded_FG_search_v1",
        "project_git_head": _git_head(),
        "working_tree_status": "dirty_preexisting_phase1_to_phase9_workspace_plus_phase10_changes",
        "phase10_source_sha256": _combined_source_hash(),
        "phase10_config_sha256": _phase10_config_hashes(plan),
        "protocol_sha256": _sha256(ROOT / PROTOCOL_PATH) if protocol else None,
        "protected_phase1_to_phase9_sha256": _historical_hashes(),
        "runtime_environment": {
            "python": sys.version,
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "seed_assignments": seeds_by_scene,
        "scenario_count": len(SCENARIO_ORDER),
        "seed_count_total": len(records),
        "policy_run_count": run_count,
        "policy_order": [policy_key(strategy, size) for strategy, size in POLICY_SPECS],
        "records": records,
        "elapsed_wall_s": round(time.perf_counter() - started, 6),
        "status": "complete",
    }
    _validate_raw_safety(raw)
    _validate_seed_records(raw, seeds_by_scene, expected_policy_run_count=run_count)
    _atomic_write(raw_path, raw)
    summary = summarize_raw(raw)
    _atomic_write(summary_path, summary)
    return raw


def _normalize_bprime(config, run: dict[str, Any], *, fleet_size: int) -> dict[str, Any]:
    metrics = dict(run["metrics"])
    total_samples = int(metrics["user_count"]) * int(metrics["evaluation_ticks"])
    rescue_samples = int(metrics["rescue_user_count"]) * int(metrics["evaluation_ticks"])
    normal_users = int(metrics["user_count"]) - int(metrics["rescue_user_count"])
    normal_samples = normal_users * int(metrics["evaluation_ticks"])
    total_connected = round(float(metrics["user_connection_success_rate"]) * total_samples)
    rescue_connected = round(float(metrics["rescue_user_service_success_rate"]) * rescue_samples)
    normal_rate = (total_connected - rescue_connected) / normal_samples if normal_samples else 0.0
    events = run.get("event_log", [])
    target_decisions = [event for event in events if event.get("event_type") == "optimizer_decision"]
    movement = sum(
        float(event.get("moved_km", 0.0))
        for event in events
        if event.get("event_type") == "drone_state_update"
    )
    total_energy = float(metrics.get("drone_energy_consumed_wh", 0.0))
    service_seconds = float(metrics.get("drone_rescue_user_seconds", 0.0))
    metrics.update(
        {
            "normal_user_connection_success_rate": normal_rate,
            "first_full_recovery_success": int(metrics.get("network_recovery_success", 0)),
            "first_full_recovery_time_s": metrics.get("network_recovery_time_s"),
            "first_full_recovery_or_censor_time_s": metrics.get(
                "network_recovery_or_censoring_time_s", config.duration_s
            ),
            "sustained_30s_recovery_success": int(metrics.get("sustained_rescue_recovery_success", 0)),
            "sustained_30s_recovery_time_s": metrics.get("sustained_rescue_recovery_time_s"),
            "uav_energy_total_wh": total_energy,
            "uav_energy_by_id_wh": {config.base.drone.id: total_energy},
            "uav_rescue_user_seconds": service_seconds,
            "energy_wh_per_uav_rescue_user_hour": (
                total_energy / (service_seconds / 3600.0) if service_seconds > 0 else None
            ),
            "average_latency_ms": metrics.get("average_latency_ms"),
            "p95_latency_ms": metrics.get("p95_latency_ms"),
            "latency_sample_count": metrics.get("latency_sample_count", len(run.get("latency_samples_ms", []))),
            "task_assignment_count": sum(bool(event.get("deploy")) for event in target_decisions),
            "target_switch_count": metrics.get("target_switch_count", 0),
            "duplicate_relay_opportunity_user_ticks": None,
            "capacity_blocked_user_ticks": None,
            "movement_distance_total_km": movement,
            "coordination_decision_count": metrics.get("algorithm_decision_count", len(target_decisions)),
            "coordination_compute_total_ms": metrics.get("algorithm_decision_total_ms", 0.0),
            "coordination_compute_mean_ms": metrics.get("algorithm_decision_mean_ms", 0.0),
            "coordination_compute_p95_ms": metrics.get("algorithm_decision_p95_ms"),
            "candidate_evaluation_count": None,
            "collision_rejection_count": None,
            "decision_timeout_count": 0,
            "infeasible_decision_count": metrics.get("infeasible_decision_count", 0),
            "safety_action_count": sum(
                event.get("event_type") in {"drone_energy_reserve_shutdown", "drone_move_blocked"}
                for event in events
            ),
            "speed_violation_count": 0,
            "boundary_violation_count": 0,
            "separation_violation_count": 0,
            "resource_capacity_violation_count": 0,
            "duplicate_user_service_count": 0,
            "uav_battery_remaining_wh_by_id": {config.base.drone.id: metrics.get("drone_battery_remaining_wh")},
            "uav_battery_minimum_wh_by_id": {config.base.drone.id: metrics.get("drone_battery_minimum_wh")},
            "uav_fleet_size": fleet_size,
            "recovery_success_count": int(metrics.get("network_recovery_success", 0)),
            "recovery_total_count": 1,
            "sustained_success_count": int(metrics.get("sustained_rescue_recovery_success", 0)),
            "sustained_total_count": 1,
        }
    )
    return {
        "strategy_id": "Bprime_static_grid_shared_safety",
        "fleet_size": fleet_size,
        "world_trace_sha256": run.get("world_trace_sha256"),
        "metrics": metrics,
        "latency_samples_ms": run.get("latency_samples_ms", []),
        "event_log": events,
        "uavs": [],
        "state_timeline": [],
    }


def summarize_raw(raw: dict[str, Any]) -> dict[str, Any]:
    by_scene: dict[str, list[dict[str, Any]]] = {scene: [] for scene in SCENARIO_ORDER}
    for row in raw["records"]:
        by_scene[row["scenario_id"]].append(row)
    policy_ids = [policy_key(strategy, size) for strategy, size in POLICY_SPECS]
    metrics = (
        "rescue_user_service_success_rate",
        "normal_user_connection_success_rate",
        "user_connection_success_rate",
        "first_full_recovery_success",
        "first_full_recovery_time_s",
        "first_full_recovery_or_censor_time_s",
        "sustained_30s_recovery_success",
        "sustained_30s_recovery_time_s",
        "uav_energy_total_wh",
        "energy_wh_per_uav_rescue_user_hour",
        "average_latency_ms",
        "p95_latency_ms",
        "latency_sample_count",
        "task_assignment_count",
        "target_switch_count",
        "duplicate_relay_opportunity_user_ticks",
        "capacity_blocked_user_ticks",
        "movement_distance_total_km",
        "coordination_compute_total_ms",
        "coordination_compute_mean_ms",
        "coordination_compute_p95_ms",
        "candidate_evaluation_count",
        "collision_rejection_count",
        "decision_timeout_count",
        "infeasible_decision_count",
        "safety_action_count",
        "speed_violation_count",
        "boundary_violation_count",
        "separation_violation_count",
        "resource_capacity_violation_count",
        "duplicate_user_service_count",
    )
    scene_summaries: dict[str, Any] = {}
    primary_tests: list[dict[str, Any]] = []
    recovery_tests: list[dict[str, Any]] = []
    sustained_tests: list[dict[str, Any]] = []
    contrast_pairs = (
        ("F2_vs_Bprime", "F_independent_greedy_uav2", "Bprime_static_grid_shared_safety_uav1"),
        ("G2_vs_Bprime", "G_centralized_coordination_uav2", "Bprime_static_grid_shared_safety_uav1"),
        ("F3_vs_Bprime", "F_independent_greedy_uav3", "Bprime_static_grid_shared_safety_uav1"),
        ("G3_vs_Bprime", "G_centralized_coordination_uav3", "Bprime_static_grid_shared_safety_uav1"),
        ("G2_vs_F2", "G_centralized_coordination_uav2", "F_independent_greedy_uav2"),
        ("G3_vs_F3", "G_centralized_coordination_uav3", "F_independent_greedy_uav3"),
        ("G3_vs_G2", "G_centralized_coordination_uav3", "G_centralized_coordination_uav2"),
        ("F3_vs_F2", "F_independent_greedy_uav3", "F_independent_greedy_uav2"),
    )

    for scene_id in SCENARIO_ORDER:
        rows = by_scene[scene_id]
        policy_summary: dict[str, Any] = {}
        for policy_id in policy_ids:
            runs = [row["strategy_runs"][policy_id] for row in rows]
            policy_metrics: dict[str, Any] = {}
            for metric in metrics:
                values = [
                    float(value)
                    for run in runs
                    if (value := run["metrics"].get(metric)) is not None
                ]
                policy_metrics[metric] = _stats(values, include_ci=True)
            recovered = [
                float(run["metrics"]["first_full_recovery_time_s"])
                for run in runs
                if run["metrics"].get("first_full_recovery_time_s") is not None
            ]
            sustained = [
                float(run["metrics"]["sustained_30s_recovery_time_s"])
                for run in runs
                if run["metrics"].get("sustained_30s_recovery_time_s") is not None
            ]
            first_flags = [
                float(run["metrics"]["first_full_recovery_success"]) for run in runs
            ]
            sustained_flags = [
                float(run["metrics"]["sustained_30s_recovery_success"]) for run in runs
            ]
            policy_metrics["first_full_recovery_success"] = {
                **_stats(first_flags, include_ci=True),
                "success_count": int(sum(first_flags)),
                "total_count": len(first_flags),
            }
            policy_metrics["first_full_recovery_time_s_successful_runs"] = {
                **_stats(recovered, include_ci=True),
                "success_count": len(recovered),
                "total_count": len(runs),
                "unrecovered_count": len(runs) - len(recovered),
            }
            policy_metrics["sustained_30s_recovery_success"] = {
                **_stats(sustained_flags, include_ci=True),
                "success_count": int(sum(sustained_flags)),
                "total_count": len(sustained_flags),
            }
            policy_metrics["sustained_30s_recovery_time_s_successful_runs"] = {
                **_stats(sustained, include_ci=True),
                "success_count": len(sustained),
                "total_count": len(runs),
                "unrecovered_count": len(runs) - len(sustained),
            }
            policy_metrics["conditional_latency_summary"] = {
                "mean_of_seed_means_ms": policy_metrics["average_latency_ms"],
                "mean_of_seed_p95_ms": policy_metrics["p95_latency_ms"],
                "pooled_connected_user_time_samples": int(
                    sum(int(run["metrics"].get("latency_sample_count", 0)) for run in runs)
                ),
                "comparison_note": "each policy conditions on its own connected user-time samples; do not interpret as a paired same-user latency effect",
            }
            policy_summary[policy_id] = policy_metrics

        scene_pairs: dict[str, Any] = {}
        for pair_name, left_id, right_id in contrast_pairs:
            left_runs = {row["seed"]: row["strategy_runs"][left_id] for row in rows}
            right_runs = {row["seed"]: row["strategy_runs"][right_id] for row in rows}
            shared_seeds = sorted(set(left_runs) & set(right_runs))
            pair_metrics: dict[str, Any] = {}
            for metric in metrics:
                differences = []
                for seed in shared_seeds:
                    left = left_runs[seed]["metrics"].get(metric)
                    right = right_runs[seed]["metrics"].get(metric)
                    if left is not None and right is not None:
                        differences.append(float(left) - float(right))
                if metric in {"average_latency_ms", "p95_latency_ms"}:
                    pair_metrics[metric] = {
                        "paired_n": 0,
                        "status": "not_paired_due_to_policy_specific_connected_user_time_samples",
                    }
                else:
                    pair_metrics[metric] = _paired_effect(differences)
                    if metric == "rescue_user_service_success_rate":
                        test = _paired_sign_flip(differences)
                        pair_metrics[metric].update(test)
                        primary_tests.append({
                            "scene_id": scene_id,
                            "contrast": pair_name,
                            "metric": metric,
                            **test,
                        })
                    elif metric == "first_full_recovery_success":
                        test = _mcnemar_from_differences(differences)
                        pair_metrics[metric].update(test)
                        recovery_tests.append({
                            "scene_id": scene_id,
                            "contrast": pair_name,
                            "metric": metric,
                            **test,
                        })
                    elif metric == "sustained_30s_recovery_success":
                        test = _mcnemar_from_differences(differences)
                        pair_metrics[metric].update(test)
                        sustained_tests.append({
                            "scene_id": scene_id,
                            "contrast": pair_name,
                            "metric": metric,
                            **test,
                        })
            scene_pairs[pair_name] = {
                "left_strategy": left_id,
                "right_strategy": right_id,
                "paired_seed_count": len(shared_seeds),
                "metrics": pair_metrics,
            }
        scene_summaries[scene_id] = {
            "seed_count": len(rows),
            "seed_ids": [row["seed"] for row in rows],
            "policies": policy_summary,
            "paired_comparisons": scene_pairs,
        }

    _holm_adjust(primary_tests)
    _holm_adjust(recovery_tests)
    _holm_adjust(sustained_tests)
    _apply_adjusted_tests(scene_summaries, primary_tests, "rescue_user_service_success_rate")
    _apply_adjusted_tests(scene_summaries, recovery_tests, "first_full_recovery_success")
    _apply_adjusted_tests(scene_summaries, sustained_tests, "sustained_30s_recovery_success")
    return {
        "schema_version": "1.0",
        "phase": "phase10_multi_uav_coordination",
        "partition": raw["partition"],
        "experiment_role": raw["experiment_role"],
        "status": raw["status"],
        "source_sha256": raw["phase10_source_sha256"],
        "configuration_sha256": raw["phase10_config_sha256"],
        "protocol_sha256": raw.get("protocol_sha256"),
        "scene_count": len(scene_summaries),
        "seed_count_total": raw["seed_count_total"],
        "policy_run_count": raw["policy_run_count"],
        "policies": policy_ids,
        "statistical_method": {
            "continuous": "same-seed paired differences; Student-t 95% CI; Cohen dz and Hedges gz",
            "primary_rescue_service_test": "two-sided exact sign-flip randomization test across the predeclared 8 contrasts x 4 scenes; Holm corrected as one family",
            "binary_recovery_test": "exact paired McNemar binomial test; Holm corrected separately for first and sustained recovery families",
            "recovery_time": "successful-run time reports n/total; all-run paired endpoint uses scenario horizon as censor time for unrecovered runs",
            "latency": "conditional per policy on connected user-time samples, sample count reported; no paired latency test across different served-user sets",
            "resource_metrics": "paired intervals/effect sizes are reported; no confirmatory superiority claim is made from resource-only endpoints",
        },
        "holm_families": {
            "rescue_service": primary_tests,
            "first_full_recovery": recovery_tests,
            "sustained_30s_recovery": sustained_tests,
        },
        "scenarios": scene_summaries,
        "safety_summary": _safety_summary(raw),
    }


def _paired_effect(differences: list[float]) -> dict[str, Any]:
    stats = _stats(differences, include_ci=True)
    sd = statistics.stdev(differences) if len(differences) > 1 else 0.0
    mean = statistics.fmean(differences) if differences else None
    dz = mean / sd if mean is not None and sd > 0 else (0.0 if mean == 0 else None)
    correction = 1.0 - 3.0 / max(4.0 * (len(differences) - 1) - 1.0, 1.0)
    return {
        "paired_n": len(differences),
        "mean_difference": round(mean, 8) if mean is not None else None,
        "sample_sd_difference": round(sd, 8) if len(differences) > 1 else None,
        "median_difference": round(statistics.median(differences), 8) if differences else None,
        "ci95_t": stats.get("mean_ci95_t"),
        "cohen_dz": round(dz, 8) if dz is not None else None,
        "hedges_gz": round(dz * correction, 8) if dz is not None else None,
    }


def _paired_sign_flip(differences: list[float]) -> dict[str, Any]:
    """Exact two-sided sign-flip test using Gray-code incremental sums."""

    n = len(differences)
    if not n or n > 20:
        return {"p_exact_two_sided": None, "test": "not_computed_outside_n_1_to_20"}
    observed = abs(sum(differences))
    total = 1 << n
    current = sum(differences)
    previous_gray = 0
    extreme = 1
    for index in range(1, total):
        gray = index ^ (index >> 1)
        changed = gray ^ previous_gray
        bit = changed.bit_length() - 1
        current += -2.0 * differences[bit] if gray & changed else 2.0 * differences[bit]
        if abs(current) >= observed - 1e-12:
            extreme += 1
        previous_gray = gray
    return {
        "p_exact_two_sided": round(extreme / total, 10),
        "test": "exact_sign_flip_randomization_gray_code",
    }


def _mcnemar_from_differences(differences: list[float]) -> dict[str, Any]:
    positive = sum(value > 0 for value in differences)
    negative = sum(value < 0 for value in differences)
    discordant = positive + negative
    tail = min(positive, negative)
    p_value = (
        min(1.0, 2.0 * sum(math.comb(discordant, i) for i in range(tail + 1)) / (2**discordant))
        if discordant
        else 1.0
    )
    return {
        "n_discordant_pairs": discordant,
        "left_only_successes": positive,
        "right_only_successes": negative,
        "p_exact_two_sided": round(p_value, 10),
        "test": "exact_mcnemar_binomial",
    }


def _apply_adjusted_tests(
    summaries: dict[str, Any], tests: list[dict[str, Any]], metric: str
) -> None:
    lookup = {
        (item["scene_id"], item["contrast"]): item for item in tests
    }
    for scene_id, scene in summaries.items():
        for contrast, result in scene["paired_comparisons"].items():
            adjusted = lookup.get((scene_id, contrast))
            if adjusted is not None:
                result["metrics"][metric].update(
                    {
                        "p_holm_adjusted": adjusted.get("p_holm_adjusted"),
                        "holm_family_size": adjusted.get("holm_family_size"),
                    }
                )


def _validate_raw_safety(raw: dict[str, Any]) -> None:
    issues: list[str] = []
    for row in raw["records"]:
        for key, run in row["strategy_runs"].items():
            metrics = run["metrics"]
            for field in (
                "speed_violation_count",
                "boundary_violation_count",
                "separation_violation_count",
                "resource_capacity_violation_count",
                "duplicate_user_service_count",
            ):
                value = metrics.get(field)
                if value is not None and value != 0:
                    issues.append(f"{row['scenario_id']}/{row['seed']}/{key}:{field}={value}")
            for uav_id, minimum in (metrics.get("uav_battery_minimum_wh_by_id") or {}).items():
                if minimum is not None:
                    reserve = next(
                        (
                            float(unit["reserve_wh"])
                            for unit in run.get("uavs", [])
                            if unit["uav_id"] == uav_id
                        ),
                        None,
                    )
                    if reserve is not None and float(minimum) < reserve - 1e-7:
                        issues.append(f"{row['scenario_id']}/{row['seed']}/{key}:{uav_id}_below_reserve")
    if issues:
        raise ValueError("Phase 10 runtime safety audit failed: " + "; ".join(issues[:10]))


def _safety_summary(raw: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "speed_violation_count",
        "boundary_violation_count",
        "separation_violation_count",
        "resource_capacity_violation_count",
        "duplicate_user_service_count",
        "decision_timeout_count",
        "safety_action_count",
        "infeasible_decision_count",
        "collision_rejection_count",
    )
    totals = {field: 0 for field in fields}
    per_uav_min: dict[str, float] = {}
    run_count = 0
    for row in raw["records"]:
        for run in row["strategy_runs"].values():
            run_count += 1
            metrics = run["metrics"]
            for field in fields:
                value = metrics.get(field)
                if value is not None:
                    totals[field] += int(value)
            for uav_id, minimum in (metrics.get("uav_battery_minimum_wh_by_id") or {}).items():
                if minimum is not None:
                    per_uav_min[uav_id] = min(per_uav_min.get(uav_id, float(minimum)), float(minimum))
    return {
        "policy_run_count": run_count,
        "totals": totals,
        "minimum_observed_battery_wh_by_id": per_uav_min,
        "battery_reserve_violations": 0,
    }


def _validate_seed_records(
    value: dict[str, Any],
    expected_by_scene: dict[str, list[int]],
    *,
    expected_policy_run_count: int | None,
) -> None:
    if "records" not in value:
        return
    records = value["records"]
    actual: dict[str, list[int]] = {scene: [] for scene in SCENARIO_ORDER}
    policy_runs = 0
    for row in records:
        scene = row["scenario_id"]
        if scene not in actual:
            raise ValueError(f"unexpected Phase 10 scene {scene}")
        actual[scene].append(int(row["seed"]))
        policy_runs += len(row["strategy_runs"])
        required_keys = {policy_key(strategy, size) for strategy, size in POLICY_SPECS}
        if set(row["strategy_runs"]) != required_keys:
            raise ValueError(f"policy set mismatch for {scene}/{row['seed']}")
    expected = {scene: [int(seed) for seed in seeds] for scene, seeds in expected_by_scene.items()}
    for scene in SCENARIO_ORDER:
        if sorted(actual[scene]) != sorted(expected[scene]):
            raise ValueError(f"seed assignment mismatch for {scene}: expected {expected[scene]}, got {actual[scene]}")
    if expected_policy_run_count is not None and policy_runs != expected_policy_run_count:
        raise ValueError(f"expected {expected_policy_run_count} policy runs, got {policy_runs}")


def _validate_seed_assignments(
    plan: dict[str, Any],
    protected_hashes: dict[str, str] | None = None,
) -> None:
    assignments = plan["seed_assignments"]
    dev = assignments["development"]
    confirm = assignments["confirmation"]
    all_ids: list[int] = []
    for partition, by_scene, minimum_count in (("development", dev, 1), ("confirmation", confirm, 20)):
        for scene in SCENARIO_ORDER:
            seeds = [int(seed) for seed in by_scene[scene]]
            if len(seeds) < minimum_count or len(seeds) != len(set(seeds)):
                raise ValueError(f"invalid {partition} seed list for {scene}")
            all_ids.extend(seeds)
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Phase 10 development and confirmation seeds overlap")
    historical_config_seeds = _collect_config_seed_ids()
    overlap = sorted(set(all_ids) & historical_config_seeds)
    if overlap:
        raise ValueError(f"Phase 10 seeds overlap prior phase configuration seeds: {overlap}")
    if min(all_ids) <= HISTORICAL_SEED_CEILING:
        raise ValueError(
            f"new seeds must be above the Phase 1-9 observed seed ceiling {HISTORICAL_SEED_CEILING}"
        )
    if protected_hashes is not None and protected_hashes != _historical_hashes():
        raise ValueError("Phase 1-9 protected files changed after protocol freeze")


def _collect_config_seed_ids() -> set[int]:
    found: set[int] = set()
    for path in (ROOT / "configs").rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        _collect_seed_values(payload, found)
    for path in (ROOT / "configs").rglob("*.toml"):
        try:
            import tomllib

            payload = tomllib.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        _collect_seed_values(payload, found)
    return found


def _collect_seed_values(value: Any, found: set[int], parent_key: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_seed_values(item, found, str(key).lower())
    elif isinstance(value, list):
        if "seed" in parent_key:
            found.update(int(item) for item in value if isinstance(item, int) and not isinstance(item, bool))
        for item in value:
            _collect_seed_values(item, found, parent_key)
    elif "seed" in parent_key and isinstance(value, int) and not isinstance(value, bool):
        found.add(value)


def _verify_protocol() -> dict[str, Any]:
    protocol_path = ROOT / PROTOCOL_PATH
    if not protocol_path.is_file():
        raise ValueError("freeze the Phase 10 protocol after development and before confirmation")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen_before_confirmation":
        raise ValueError("Phase 10 confirmation protocol is not frozen")
    plan = load_plan()
    if protocol["source_sha256"] != _combined_source_hash():
        raise ValueError("Phase 10 source changed after the confirmation protocol freeze")
    if protocol["configuration_sha256"] != _phase10_config_hashes(plan):
        raise ValueError("Phase 10 configuration changed after the confirmation protocol freeze")
    if protocol["protected_phase1_to_phase9_sha256"] != _historical_hashes():
        raise ValueError("a Phase 1-9 protected file changed after Phase 10 protocol freeze")
    development_path = ROOT / "results/phase10_development_raw.json"
    development_summary_path = ROOT / "results/phase10_development_summary.json"
    if _sha256(development_path) != protocol["development_raw_sha256"]:
        raise ValueError("Phase 10 development raw data changed after protocol freeze")
    if _sha256(development_summary_path) != protocol["development_summary_sha256"]:
        raise ValueError("Phase 10 development summary changed after protocol freeze")
    _validate_seed_assignments(plan, protocol["protected_phase1_to_phase9_sha256"])
    return protocol


def _phase10_config_hashes(plan: dict[str, Any]) -> dict[str, str]:
    paths = {PLAN_PATH}
    for relative in plan["scenario_config_paths"].values():
        paths.add(relative)
        config = load_dynamic_config(ROOT / relative)
        paths.add(str(config.scenario_path.relative_to(ROOT)).replace("\\", "/"))
    return {path: _sha256(ROOT / path) for path in sorted(paths)}


def _combined_source_hash() -> str:
    digest = hashlib.sha256()
    for relative in SOURCE_PATHS:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Phase 10 source path is missing: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _historical_paths() -> list[Path]:
    paths: set[Path] = set()
    for rel in HISTORICAL_REPORTS:
        path = ROOT / rel
        if path.is_file():
            paths.add(path)
    for dirname in ("configs/phase5", "configs/phase8", "configs/phase9"):
        folder = ROOT / dirname
        if folder.exists():
            paths.update(path for path in folder.rglob("*") if path.is_file())
    results = ROOT / "results"
    for path in results.rglob("*"):
        if not path.is_file():
            continue
        path_parts = [part.lower() for part in path.relative_to(results).parts]
        if path_parts[0].startswith(("phase5", "phase8", "phase9")):
            paths.add(path)
    return sorted(paths)


def _historical_hashes() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): _sha256(path)
        for path in _historical_paths()
    }


def _git_head() -> str | None:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(payload, target, ensure_ascii=False, indent=2)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())
    temporary.replace(path)


def _paired_name(scene: str, contrast: str) -> str:
    return f"{scene}/{contrast}"

