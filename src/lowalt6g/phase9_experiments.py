"""Reproducible development, confirmation, and energy sensitivity experiments."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import Callable

from .dynamic_config import DynamicExperimentConfig, load_dynamic_config
from .dynamic_simulation import (
    DynamicRun,
    _MPCController,
    _NoRecoveryController,
    _RescuePriorityController,
    _SafeStaticGridController,
    _StaticGridController,
    _run_one,
    run_seed_experiment,
)
from .dynamic_world import build_world_trace
from .experiment import _percentile, _stats, _wilson_interval
from .phase8_experiments import _holm_adjust
from .phase9_strategy_e import EventDrivenController


ROOT = Path(__file__).resolve().parents[2]
SCENARIO_CONFIGS = {
    "dynamic_failures": "configs/phase9/dynamic_failures_validation.toml",
    "severe_persistent_faults": "configs/phase9/severe_persistent_faults_validation.toml",
    "high_mobility_rescue": "configs/phase9/high_mobility_rescue_validation.toml",
    "high_load_backhaul_limit": "configs/phase9/high_load_backhaul_limit_validation.toml",
}
DEVELOPMENT_CONFIG = "configs/phase9/dynamic_failures_development.toml"
PROTOCOL_PATH = "configs/phase9/validation_protocol_corrected.json"
ENERGY_PLAN_PATH = "configs/phase9/energy_sensitivity_plan_corrected.json"
CORRECTED_EXPERIMENT_PLAN_PATH = "configs/phase9/experiment_plan_corrected.json"
SOURCE_PATHS = (
    "src/lowalt6g/dynamic_simulation.py",
    "src/lowalt6g/dynamic_world.py",
    "src/lowalt6g/dynamic_config.py",
    "src/lowalt6g/config.py",
    "src/lowalt6g/energy_budget.py",
    "src/lowalt6g/experiment.py",
    "src/lowalt6g/optimizer.py",
    "src/lowalt6g/phase8_experiments.py",
    "src/lowalt6g/phase8_d_optimizer.py",
    "src/lowalt6g/phase9_strategy_e.py",
    "src/lowalt6g/phase9_experiments.py",
    "scripts/run_phase9_experiments.py",
)
CONFIG_PATHS = (
    "configs/phase9/experiment_plan.json",
    CORRECTED_EXPERIMENT_PLAN_PATH,
    DEVELOPMENT_CONFIG,
    *SCENARIO_CONFIGS.values(),
    "configs/phase9/energy_sensitivity_plan.json",
    ENERGY_PLAN_PATH,
)
PROTECTED_PATHS = (
    "results/phase5_frozen_manifest.json",
    "results/phase5_integrity_audit.json",
    "results/phase5_validation_summary.json",
    "results/phase5_validation_dynamic_failures.json",
    "results/phase5_validation_severe_persistent_faults.json",
    "results/phase5_validation_high_mobility_rescue.json",
    "results/phase5_validation_high_load_backhaul_limit.json",
    "results/phase8_development_raw.json",
    "results/phase8_development_summary.json",
    "results/phase8_validation_raw.json",
    "results/phase8_validation_summary.json",
    "results/phase8_sensitivity_validation_raw.json",
    "results/phase8_sensitivity_validation_summary.json",
    "results/phase8_replication_raw.json",
    "results/phase8_replication_summary.json",
)
BASELINE_STRATEGIES = (
    "A_no_recovery",
    "B_phase1_static_grid",
    "Bprime_static_grid_shared_safety",
    "C_rolling_horizon_mpc",
    "D_lexicographic_rescue_priority",
)
STRATEGY_ORDER = (*BASELINE_STRATEGIES, "E_event_driven_rescue_recovery")
DEVELOPMENT_COOLDOWNS_S = (0, 20, 40)
ENERGY_VARIANTS = (
    ("base", "movement_wh_per_km", 1.0),
    ("movement_low_0p75", "movement_wh_per_km", 0.75),
    ("movement_high_1p25", "movement_wh_per_km", 1.25),
    ("hover_low_0p75", "hover_power_w", 0.75),
    ("hover_high_1p25", "hover_power_w", 1.25),
    ("relay_low_0p75", "relay_power_w", 0.75),
    ("relay_high_1p25", "relay_power_w", 1.25),
)
ENERGY_SENSITIVITY_SEEDS = tuple(range(93500, 93510))
EFFICIACY_METRICS = (
    "rescue_user_service_success_rate",
    "user_connection_success_rate",
    "network_recovery_or_censoring_time_s",
    "network_recovery_success",
    "sustained_rescue_recovery_success",
    "drone_extra_rescue_user_seconds",
)
COST_METRICS = (
    "drone_energy_consumed_wh",
    "drone_energy_wh_per_rescue_user_hour",
    "algorithm_decision_total_ms",
    "target_switch_count",
)
PAIR_METRICS = (*EFFICIACY_METRICS, *COST_METRICS)
BINARY_METRICS = {"network_recovery_success", "sustained_rescue_recovery_success"}


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _combined_source_hash() -> str:
    digest = hashlib.sha256()
    for relative in SOURCE_PATHS:
        digest.update(relative.encode("utf-8"))
        digest.update(Path(ROOT / relative).read_bytes())
    return digest.hexdigest()


def _config_hashes() -> dict[str, str]:
    return {relative: sha256_file(ROOT / relative) for relative in CONFIG_PATHS}


def _protected_hashes() -> dict[str, str]:
    return {relative: sha256_file(ROOT / relative) for relative in PROTECTED_PATHS}


def _git_head() -> str | None:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _paired_summary(differences: list[float], *, binary: bool, inferential: bool) -> dict[str, object]:
    n = len(differences)
    if not differences:
        return {
            "n": 0,
            "mean_difference": None,
            "sample_sd_difference": None,
            "median_difference": None,
            "ci95_t": None,
            "cohen_dz": None,
            "hedges_gz": None,
            "p_exact_two_sided": None,
        }
    mean = statistics.fmean(differences)
    sample_sd = statistics.stdev(differences) if n > 1 else 0.0
    dz = mean / sample_sd if sample_sd > 0 else (float("inf") if mean > 0 else float("-inf") if mean < 0 else 0.0)
    correction = 1.0 - 3.0 / max(4.0 * (n - 1) - 1.0, 1.0)
    stats = _stats(differences, include_ci=True)
    p_value: float | None = None
    test_name = "descriptive_no_confirmatory_test"
    if inferential and binary:
        positive = sum(value > 0 for value in differences)
        negative = sum(value < 0 for value in differences)
        discordant = positive + negative
        tail = min(positive, negative)
        p_value = (
            min(1.0, 2.0 * sum(math.comb(discordant, index) for index in range(tail + 1)) / (2**discordant))
            if discordant
            else 1.0
        )
        test_name = "exact_mcnemar_binomial"
    elif inferential:
        import numpy as np

        observed = abs(sum(differences))
        signed_sums = 0
        total = 1 << n
        bit_positions = np.arange(n, dtype=np.uint32)
        vector = np.asarray(differences, dtype=np.float64)
        chunk_size = 131072
        for offset in range(0, total, chunk_size):
            masks = np.arange(offset, min(offset + chunk_size, total), dtype=np.uint32)
            flips = ((masks[:, None] >> bit_positions[None, :]) & 1).astype(np.int8)
            signs = 1 - 2 * flips
            signed = signs @ vector
            signed_sums += int(np.count_nonzero(np.abs(signed) >= observed - 1e-12))
        p_value = signed_sums / total
        test_name = "exact_sign_flip_randomization_vectorized"
    return {
        "n": n,
        "mean_difference": round(mean, 8),
        "sample_sd_difference": round(sample_sd, 8) if n > 1 else None,
        "median_difference": round(statistics.median(differences), 8),
        "ci95_t": stats.get("mean_ci95_t"),
        "cohen_dz": round(dz, 8) if math.isfinite(dz) else None,
        "hedges_gz": round(dz * correction, 8) if math.isfinite(dz) else None,
        "p_exact_two_sided": round(p_value, 8) if p_value is not None else None,
        "test": test_name,
    }


def _initial_checkpoint(
    path: Path,
    *,
    stage: str,
    role: str,
    protocol_sha256: str | None,
    seed_assignments: dict[str, list[int]],
) -> dict[str, object]:
    identity = {
        "phase": stage,
        "experiment_role": role,
        "phase9_source_sha256": _combined_source_hash(),
        "phase9_config_sha256": _config_hashes(),
        "protected_historical_sha256": _protected_hashes(),
        "protocol_sha256": protocol_sha256,
    }
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        for key, value in identity.items():
            if state.get(key) != value:
                raise ValueError(f"checkpoint {path} has different {key}; refusing to mix experiments")
        if state.get("seed_assignments") != seed_assignments:
            raise ValueError(f"checkpoint {path} has different seed assignments")
        return state
    return {
        "schema_version": "1.0",
        **identity,
        "project_git_head": _git_head(),
        "model_scope": "abstract_6g_research_simulation_not_real_network_test",
        "runtime_environment": {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "seed_assignments": seed_assignments,
        "status": "running",
        "records": [],
    }


def _strategy_dicts(experiment, *, latency_samples: bool = True) -> dict[str, object]:
    return {
        strategy_id: run.to_dict(include_latency_samples=latency_samples)
        for strategy_id, run in experiment.strategies.items()
    }


def run_development(
    *,
    progress: Callable[[str, int, int, int], None] | None = None,
) -> dict[str, object]:
    config = load_dynamic_config(ROOT / DEVELOPMENT_CONFIG)
    seed_assignments = {"dynamic_failures": list(config.seeds)}
    path = ROOT / "results/phase9_development_raw.json"
    state = _initial_checkpoint(
        path,
        stage="development",
        role="exploratory_development_not_confirmatory",
        protocol_sha256=None,
        seed_assignments=seed_assignments,
    )
    records = state["records"]
    done = {int(row["seed"]) for row in records}
    total = len(config.seeds)
    for index, seed in enumerate(config.seeds, start=1):
        if seed in done:
            continue
        trace = build_world_trace(config, seed)
        baseline = run_seed_experiment(
            config,
            seed,
            trace,
            include_d=True,
            include_bprime=True,
        )
        e_variants: dict[str, object] = {}
        for cooldown_s in DEVELOPMENT_COOLDOWNS_S:
            controller = EventDrivenController(config, cooldown_s=cooldown_s)
            run = _run_one(config, seed, trace, controller)
            e_variants[f"E_cooldown_{cooldown_s}s"] = run.to_dict(include_latency_samples=True)
        records.append(
            {
                "scenario_id": "dynamic_failures",
                "seed": seed,
                "world_trace_sha256": trace.trace_sha256,
                "environment_events": list(trace.environment_event_log),
                "baseline_strategy_runs": _strategy_dicts(baseline),
                "event_driven_cooldown_variants": e_variants,
            }
        )
        _atomic_write(path, state)
        if progress:
            progress("development", index, total, seed)
    state["status"] = "complete"
    state["completed_seed_count"] = len(records)
    state["actual_policy_run_count"] = sum(
        len(row["baseline_strategy_runs"]) + len(row["event_driven_cooldown_variants"])
        for row in records
    )
    state["cooldown_candidates_s"] = list(DEVELOPMENT_COOLDOWNS_S)
    _atomic_write(path, state)
    summary = summarize_development(state)
    summary_path = ROOT / "results/phase9_development_summary.json"
    _atomic_write(summary_path, summary)
    return {"raw": str(path), "summary": str(summary_path), "seed_count": len(records), "policy_run_count": state["actual_policy_run_count"]}


def summarize_development(raw: dict[str, object]) -> dict[str, object]:
    records = raw["records"]
    summaries: dict[str, object] = {}
    for cooldown_s in DEVELOPMENT_COOLDOWNS_S:
        key = f"E_cooldown_{cooldown_s}s"
        runs = [row["event_driven_cooldown_variants"][key] for row in records]
        metric_summary = {}
        for metric in (
            "rescue_user_service_success_rate",
            "network_recovery_success",
            "sustained_rescue_recovery_success",
            "network_recovery_or_censoring_time_s",
            "algorithm_decision_total_ms",
            "algorithm_decision_count",
            "event_triggered_decision_count",
            "event_suppressed_count",
            "drone_energy_consumed_wh",
        ):
            values = [float(run["metrics"][metric]) for run in runs if run["metrics"].get(metric) is not None]
            metric_summary[metric] = _stats(values, include_ci=True)
        summaries[key] = {"metrics": metric_summary}
    scores = {
        key: (
            summary["metrics"]["rescue_user_service_success_rate"]["mean"],
            summary["metrics"]["sustained_rescue_recovery_success"]["mean"],
            summary["metrics"]["network_recovery_success"]["mean"],
            -summary["metrics"]["network_recovery_or_censoring_time_s"]["mean"],
            -summary["metrics"]["algorithm_decision_total_ms"]["mean"],
            -summary["metrics"]["algorithm_decision_count"]["mean"],
            -abs(int(key.removeprefix("E_cooldown_").removesuffix("s")) - 20),
        )
        for key, summary in summaries.items()
    }
    chosen = max(scores, key=scores.get)
    return {
        "schema_version": "1.0",
        "phase": "development",
        "experiment_role": raw["experiment_role"],
        "status": raw["status"],
        "seed_count": len(records),
        "seed_ids": [int(row["seed"]) for row in records],
        "variant_summaries": summaries,
        "selection_rule": (
            "Lexicographic maximum of mean rescue-service rate, sustained-30-second success, full-recovery success, "
            "negative recovery-or-censoring time, negative decision compute and negative decision count; ties prefer 20 s."
        ),
        "development_selected_cooldown_s": int(chosen.removeprefix("E_cooldown_").removesuffix("s")),
        "selection_scores": {key: list(value) for key, value in scores.items()},
        "confirmatory_inference": False,
    }


def freeze_validation_protocol() -> Path:
    raw_path = ROOT / "results/phase9_development_raw.json"
    summary_path = ROOT / "results/phase9_development_summary.json"
    if not raw_path.is_file() or not summary_path.is_file():
        raise ValueError("complete the 20-seed development stage before freezing validation")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if raw.get("status") != "complete" or len(raw.get("records", [])) != 20:
        raise ValueError("the development partition must contain all 20 seeds before freezing")
    source_hash = _combined_source_hash()
    if raw.get("phase9_source_sha256") != source_hash:
        raise ValueError("Phase 9 source changed after development; rerun development before freezing")
    config_hashes = _config_hashes()
    if raw.get("phase9_config_sha256") != config_hashes:
        raise ValueError("Phase 9 configuration changed after development")
    if raw.get("protected_historical_sha256") != _protected_hashes():
        raise ValueError("a protected Phase 5/8 historical result changed after development")
    protocol_path = ROOT / PROTOCOL_PATH
    if protocol_path.exists():
        raise FileExistsError(f"refusing to replace frozen validation protocol {protocol_path}")
    chosen_cooldown = int(summary["development_selected_cooldown_s"])
    seed_assignment = {
        "dynamic_failures": list(range(93100, 93120)),
        "severe_persistent_faults": list(range(93200, 93220)),
        "high_mobility_rescue": list(range(93300, 93320)),
        "high_load_backhaul_limit": list(range(93400, 93420)),
    }
    flat_seeds = [seed for values in seed_assignment.values() for seed in values]
    development_seeds = set(raw["seed_assignments"]["dynamic_failures"])
    if len(flat_seeds) != len(set(flat_seeds)) or development_seeds.intersection(flat_seeds):
        raise ValueError("Phase 9 development and confirmation seeds overlap")
    protocol = {
        "schema_version": "1.0",
        "status": "frozen_before_confirmation",
        "protocol_rule": "Corrected Strategy E route-hold behavior, event filters, timeout policy, cooldown and comparison plan are frozen before corrected confirmation runs.",
        "implementation_revision": "E2_hold_terminal_target_and_detect_mobility_v2",
        "phase9_source_sha256": source_hash,
        "phase9_source_files_sha256": {item: sha256_file(ROOT / item) for item in SOURCE_PATHS},
        "phase9_config_sha256": config_hashes,
        "protected_historical_sha256": _protected_hashes(),
        "development_raw_sha256": sha256_file(raw_path),
        "development_summary_sha256": sha256_file(summary_path),
        "development_seed_ids": sorted(development_seeds),
        "confirmation_seed_assignments": seed_assignment,
        "energy_sensitivity_seed_ids": list(ENERGY_SENSITIVITY_SEEDS),
        "cooldown_selected_from_development_s": chosen_cooldown,
        "frozen_strategy_e_parameters": {
            "cooldown_s": chosen_cooldown,
            "rescue_loss_threshold_users": 1,
            "battery_reserve_margin_alert_wh": 25.0,
            "candidate_limit": 64,
            "decision_output_timeout_ms": 500.0,
            "no_periodic_replanning": True,
            "critical_event_cooldown_bypass": True,
        },
            "event_observation": "current stations, backhaul state/capacity, current service counts, quantized rescue-user positions, traffic demand, congestion diagnosis, battery and return-energy margin only; no future trace/schedule is passed to the controller",
        "strategy_order": list(STRATEGY_ORDER),
        "primary_confirmatory_contrasts": [
            "E_event_driven_rescue_recovery_minus_B_phase1_static_grid",
            "E_event_driven_rescue_recovery_minus_Bprime_static_grid_shared_safety",
        ],
        "statistical_plan": {
            "pairing": "same seed and identical pre-generated DynamicWorldTrace for every strategy",
            "continuous": "paired per-seed differences; two-sided exact sign-flip randomization; mean, median, sample SD, 95% t CI, Cohen dz and Hedges gz",
            "binary": "paired exact McNemar binomial test and Wilson CIs for each strategy rate",
            "multiplicity": "Holm correction separately for efficacy and resource/cost families across all four scenes and both E contrasts",
            "recovery_time": "first tick with every rescue user connected; unrecovered stays a failure and uses horizon only for recovery-or-censoring paired analysis; recovered-only time reports count/total",
            "sustained_recovery": "all rescue users connected for at least 30 continuous simulation seconds",
            "latency": "conditional on each policy's own connected user-time set; report sample count, mean and nearest-rank P95, no paired inference",
            "decision_compute": "wall perf_counter duration of the full observe call, separate from simulated time; simulator does not advance by planner wall time",
            "sample_size": "20 independent seed IDs per scenario; intervals describe this abstract simulator, not field uncertainty",
        },
    }
    _atomic_write(protocol_path, protocol)
    return protocol_path


def _verify_protocol() -> dict[str, object]:
    path = ROOT / PROTOCOL_PATH
    if not path.is_file():
        raise ValueError("freeze the Phase 9 validation protocol after development and before confirmation")
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen_before_confirmation":
        raise ValueError("Phase 9 protocol is not frozen")
    if protocol["phase9_source_sha256"] != _combined_source_hash():
        raise ValueError("Phase 9 source changed after validation protocol freeze")
    if protocol["phase9_config_sha256"] != _config_hashes():
        raise ValueError("Phase 9 configuration changed after validation protocol freeze")
    if protocol["protected_historical_sha256"] != _protected_hashes():
        raise ValueError("a protected Phase 5/8 historical result changed after protocol freeze")
    return protocol


def run_confirmation(
    *,
    progress: Callable[[str, int, int, int], None] | None = None,
) -> dict[str, object]:
    protocol = _verify_protocol()
    seeds = protocol["confirmation_seed_assignments"]
    path = ROOT / "results/phase9_corrected_confirmation_raw.json"
    state = _initial_checkpoint(
        path,
        stage="confirmation",
        role="confirmatory_held_out_not_used_for_tuning",
        protocol_sha256=sha256_file(ROOT / PROTOCOL_PATH),
        seed_assignments=seeds,
    )
    done = {(row["scenario_id"], int(row["seed"])) for row in state["records"]}
    total = sum(len(values) for values in seeds.values())
    completed = len(done)
    cooldown_s = int(protocol["cooldown_selected_from_development_s"])
    for scenario_id, config_path in SCENARIO_CONFIGS.items():
        config = load_dynamic_config(ROOT / config_path)
        for seed in seeds[scenario_id]:
            if (scenario_id, seed) in done:
                continue
            trace = build_world_trace(config, seed)
            experiment = run_seed_experiment(
                config,
                seed,
                trace,
                include_d=True,
                include_bprime=True,
                include_e=True,
                e_cooldown_s=cooldown_s,
            )
            state["records"].append(
                {
                    "scenario_id": scenario_id,
                    "seed": seed,
                    "world_trace_sha256": trace.trace_sha256,
                    "environment_events": list(trace.environment_event_log),
                    "strategy_runs": _strategy_dicts(experiment),
                }
            )
            completed += 1
            _atomic_write(path, state)
            if progress:
                progress("confirmation", completed, total, seed)
    state["status"] = "complete"
    state["completed_seed_count"] = len(state["records"])
    state["actual_policy_run_count"] = sum(len(row["strategy_runs"]) for row in state["records"])
    _atomic_write(path, state)
    summary = summarize_confirmation(state)
    summary_path = ROOT / "results/phase9_corrected_confirmation_summary.json"
    _atomic_write(summary_path, summary)
    _write_event_timeline(state)
    write_phase9_charts(state, summary)
    return {"raw": str(path), "summary": str(summary_path), "seed_count": len(state["records"]), "policy_run_count": state["actual_policy_run_count"]}


def _metric_values(rows: list[dict[str, object]], policy: str, metric: str) -> list[float]:
    values = []
    for row in rows:
        value = row["strategy_runs"][policy]["metrics"].get(metric)
        if value is not None:
            values.append(float(value))
    return values


def summarize_confirmation(raw: dict[str, object]) -> dict[str, object]:
    scene_ids = list(SCENARIO_CONFIGS)
    scenes: dict[str, object] = {}
    inferential: list[dict[str, object]] = []
    for scene_id in scene_ids:
        rows = [row for row in raw["records"] if row["scenario_id"] == scene_id]
        if not rows:
            continue
        strategy_summaries: dict[str, object] = {}
        for strategy in STRATEGY_ORDER:
            runs = [row["strategy_runs"][strategy] for row in rows]
            metric_names = (
                "rescue_user_service_success_rate",
                "user_connection_success_rate",
                "network_recovery_or_censoring_time_s",
                "network_recovery_success",
                "sustained_rescue_recovery_success",
                "drone_energy_consumed_wh",
                "drone_extra_rescue_user_seconds",
                "drone_energy_wh_per_rescue_user_hour",
                "algorithm_decision_total_ms",
                "controller_observe_total_ms",
                "algorithm_decision_count",
                "target_switch_count",
                "event_triggered_decision_count",
                "event_suppressed_count",
                "decision_timeout_count",
                "invalid_action_filtered_count",
            )
            metric_stats = {}
            for metric in metric_names:
                values = [float(run["metrics"][metric]) for run in runs if run["metrics"].get(metric) is not None]
                metric_stats[metric] = _stats(values, include_ci=True)
            first_recovery = [
                float(run["metrics"]["network_recovery_time_s"])
                for run in runs
                if run["metrics"].get("network_recovery_time_s") is not None
            ]
            sustained_recovery = [
                float(run["metrics"]["sustained_rescue_recovery_time_s"])
                for run in runs
                if run["metrics"].get("sustained_rescue_recovery_time_s") is not None
            ]
            recovery_flags = [float(run["metrics"]["network_recovery_success"]) for run in runs]
            sustained_flags = [float(run["metrics"]["sustained_rescue_recovery_success"]) for run in runs]
            latency_samples = [float(value) for run in runs for value in run.get("latency_samples_ms", [])]
            strategy_summaries[strategy] = {
                "seed_count": len(runs),
                "metrics": metric_stats,
                "first_full_recovery": {
                    "successes": len(first_recovery),
                    "total": len(runs),
                    "unrecovered": len(runs) - len(first_recovery),
                    "success_rate_ci95_wilson": _wilson_interval(recovery_flags),
                    "successful_run_time_s": _stats(first_recovery, include_ci=True),
                    "censored_time_mean_s": metric_stats["network_recovery_or_censoring_time_s"]["mean"],
                },
                "sustained_30s_recovery": {
                    "successes": len(sustained_recovery),
                    "total": len(runs),
                    "failures": len(runs) - len(sustained_recovery),
                    "success_rate_ci95_wilson": _wilson_interval(sustained_flags),
                    "successful_run_start_time_s": _stats(sustained_recovery, include_ci=True),
                },
                "conditional_latency": {
                    "successful_user_time_sample_count": len(latency_samples),
                    "mean_ms": round(statistics.fmean(latency_samples), 8) if latency_samples else None,
                    "p95_ms_nearest_rank": _percentile(latency_samples, 0.95),
                    "policy_specific_success_set": True,
                },
            }
        contrasts = []
        for comparator in ("B_phase1_static_grid", "Bprime_static_grid_shared_safety"):
            for metric in PAIR_METRICS:
                differences = []
                for row in rows:
                    left = row["strategy_runs"]["E_event_driven_rescue_recovery"]["metrics"].get(metric)
                    right = row["strategy_runs"][comparator]["metrics"].get(metric)
                    if left is None or right is None:
                        continue
                    differences.append(float(left) - float(right))
                item = _paired_summary(
                    differences,
                    binary=metric in BINARY_METRICS,
                    inferential=True,
                )
                family = "efficacy" if metric in EFFICIACY_METRICS else "resource_cost"
                item.update(
                    {
                        "scenario_id": scene_id,
                        "comparison": f"E_minus_{comparator}",
                        "metric": metric,
                        "family": family,
                        "direction": "negative_is_better"
                        if metric
                        in {
                            "network_recovery_or_censoring_time_s",
                            "drone_energy_consumed_wh",
                            "drone_energy_wh_per_rescue_user_hour",
                            "algorithm_decision_total_ms",
                            "target_switch_count",
                        }
                        else "positive_is_better",
                    }
                )
                contrasts.append(item)
                inferential.append(item)
        scenes[scene_id] = {
            "seed_count": len(rows),
            "seed_ids": [int(row["seed"]) for row in rows],
            "strategy_summaries": strategy_summaries,
            "paired_contrasts": contrasts,
            "event_timing": _event_timing(rows),
        }
    for family in ("efficacy", "resource_cost"):
        _holm_adjust([item for item in inferential if item["family"] == family])
    for scene in scenes.values():
        for item in scene["paired_contrasts"]:
            match = next(
                row
                for row in inferential
                if row["scenario_id"] == item["scenario_id"]
                and row["comparison"] == item["comparison"]
                and row["metric"] == item["metric"]
            )
            item.update({key: value for key, value in match.items() if key.startswith("p_holm") or key == "holm_family_size"})
    return {
        "schema_version": "1.0",
        "phase": "confirmation",
        "experiment_role": raw["experiment_role"],
        "status": raw["status"],
        "phase9_source_sha256": raw["phase9_source_sha256"],
        "phase9_config_sha256": raw["phase9_config_sha256"],
        "protocol_sha256": raw["protocol_sha256"],
        "scenario_count": len(scenes),
        "seed_count_total": len(raw["records"]),
        "policy_run_count": raw.get("actual_policy_run_count"),
        "statistical_method": {
            "continuous": "paired within-seed differences, exact two-sided sign-flip randomization, 95% t confidence interval, Cohen dz and Hedges gz",
            "binary": "paired exact McNemar binomial test and Wilson 95% interval",
            "multiple_testing": "Holm step-down within efficacy and resource/cost families across scenes and E-vs-B/Bprime comparisons",
            "latency": "conditional sample set per strategy; no paired inference",
            "failed_recovery": "retained as failure; recovery-or-censoring uses configured duration for the paired continuous analysis",
        },
        "paired_tests": inferential,
        "scenarios": scenes,
    }


def _event_timing(rows: list[dict[str, object]]) -> dict[str, object]:
    event_rows: list[dict[str, object]] = []
    for row in rows:
        run = row["strategy_runs"]["E_event_driven_rescue_recovery"]
        events = run.get("event_log", [])
        environment = [event for event in events if event.get("event_type") == "phase9_environment_event_applied"]
        decisions = [event for event in events if event.get("event_type") == "phase9_decision_timeline"]
        action_starts = [event for event in events if event.get("event_type") == "phase9_action_execution_started"]
        suppressions = [event for event in events if event.get("event_type") == "phase9_replan_suppressed"]
        for applied in environment:
            t = int(applied["time_s"])
            matches = [event for event in decisions if int(event["time_s"]) == t]
            suppressed = [event for event in suppressions if int(event["time_s"]) == t]
            trigger = matches[0] if matches else None
            action = next(
                (event for event in action_starts if event.get("decision_time_s") == t),
                None,
            )
            event_rows.append(
                {
                    "seed": row["seed"],
                    "environment_event_type": applied.get("environment_event_type"),
                    "target_id": applied.get("target_id"),
                    "event_occurrence_time_s": t,
                    "controller_observation_time_s": t,
                    "event_detection_delay_s": 0,
                    "replanning_trigger_time_s": trigger.get("replanning_trigger_time_s") if trigger else None,
                    "decision_completed_sim_time_s": trigger.get("decision_completed_sim_time_s") if trigger else None,
                    "fault_to_decision_sim_delay_s": (
                        trigger.get("decision_completed_sim_time_s") - t if trigger else None
                    ),
                    "action_motion_start_time_s": action.get("time_s") if action else None,
                    "fault_to_action_start_delay_s": action.get("time_s") - t if action else None,
                    "algorithm_compute_wall_ms": trigger.get("algorithm_compute_wall_ms") if trigger else None,
                    "suppression_reason": suppressed[0].get("suppression_reason") if suppressed else None,
                }
            )
    detection_delays = [float(row["event_detection_delay_s"]) for row in event_rows]
    command_delays = [float(row["fault_to_decision_sim_delay_s"]) for row in event_rows if row["fault_to_decision_sim_delay_s"] is not None]
    action_delays = [float(row["fault_to_action_start_delay_s"]) for row in event_rows if row["fault_to_action_start_delay_s"] is not None]
    compute = [float(row["algorithm_compute_wall_ms"]) for row in event_rows if row["algorithm_compute_wall_ms"] is not None]
    return {
        "environment_event_count": len(event_rows),
        "event_rows": event_rows,
        "detection_delay_s": _stats(detection_delays, include_ci=True),
        "fault_to_decision_sim_delay_s": _stats(command_delays, include_ci=True),
        "fault_to_action_start_sim_delay_s": _stats(action_delays, include_ci=True),
        "event_decision_compute_wall_ms": _stats(compute, include_ci=True),
        "events_without_new_plan": sum(row["fault_to_decision_sim_delay_s"] is None for row in event_rows),
        "timing_scope": "Fault occurrence and controller observation use the same 10-second discrete simulator tick. Planner wall time is measured separately; it does not advance simulation time. A new command is first executed at the next tick.",
    }


def _write_event_timeline(raw: dict[str, object]) -> Path:
    rows = []
    for row in raw["records"]:
        e_run = row["strategy_runs"]["E_event_driven_rescue_recovery"]
        rows.append(
            {
                "scenario_id": row["scenario_id"],
                "seed": row["seed"],
                "world_trace_sha256": row["world_trace_sha256"],
                "events": [
                    event
                    for event in e_run.get("event_log", [])
                    if str(event.get("event_type", "")).startswith("phase9_")
                ],
                "metrics": {
                    key: e_run["metrics"].get(key)
                    for key in (
                        "network_recovery_time_s",
                        "network_recovery_success",
                        "sustained_rescue_recovery_time_s",
                        "sustained_rescue_recovery_success",
                        "algorithm_decision_total_ms",
                    )
                },
            }
        )
    path = ROOT / "results/phase9_corrected_event_timeline.json"
    _atomic_write(
        path,
        {
            "schema_version": "1.0",
            "experiment_role": "confirmatory_held_out_not_used_for_tuning",
            "source_raw": "results/phase9_corrected_confirmation_raw.json",
            "records": rows,
        },
    )
    return path


def run_energy_sensitivity(
    *,
    progress: Callable[[str, int, int, int], None] | None = None,
) -> dict[str, object]:
    protocol = _verify_protocol()
    config = load_dynamic_config(ROOT / SCENARIO_CONFIGS["dynamic_failures"])
    energy_plan = json.loads((ROOT / ENERGY_PLAN_PATH).read_text(encoding="utf-8"))
    seed_assignments = {"dynamic_failures_energy_sensitivity": list(ENERGY_SENSITIVITY_SEEDS)}
    path = ROOT / "results/phase9_corrected_energy_sensitivity_raw.json"
    state = _initial_checkpoint(
        path,
        stage="energy_sensitivity",
        role="independent_parameter_sensitivity_not_physical_calibration",
        protocol_sha256=sha256_file(ROOT / PROTOCOL_PATH),
        seed_assignments=seed_assignments,
    )
    current_energy_plan_hash = sha256_file(ROOT / ENERGY_PLAN_PATH)
    if state["records"] and state.get("energy_sensitivity_plan_sha256") != current_energy_plan_hash:
        raise ValueError("energy sensitivity plan changed after the checkpoint started")
    state["energy_sensitivity_plan_sha256"] = current_energy_plan_hash
    done = {int(row["seed"]) for row in state["records"]}
    for index, seed in enumerate(ENERGY_SENSITIVITY_SEEDS, start=1):
        if seed in done:
            continue
        trace = build_world_trace(config, seed)
        variants: dict[str, object] = {}
        for variant_id, parameter, factor in ENERGY_VARIANTS:
            energy_config = config
            if variant_id != "base":
                energy_config = replace(config, **{parameter: getattr(config, parameter) * factor})
            experiment = run_seed_experiment(
                energy_config,
                seed,
                trace,
                include_d=True,
                include_bprime=True,
                include_e=True,
                e_cooldown_s=int(protocol["cooldown_selected_from_development_s"]),
            )
            variants[variant_id] = {
                "energy_parameters": {
                    "movement_wh_per_km": energy_config.movement_wh_per_km,
                    "hover_power_w": energy_config.hover_power_w,
                    "relay_power_w": energy_config.relay_power_w,
                    "battery_capacity_wh": energy_config.battery_capacity_wh,
                    "initial_battery_wh": energy_config.initial_battery_wh,
                    "reserve_wh": energy_config.reserve_wh,
                },
                "strategies": _strategy_dicts(experiment),
            }
        state["records"].append(
            {
                "scenario_id": "dynamic_failures",
                "seed": seed,
                "world_trace_sha256": trace.trace_sha256,
                "energy_variants": variants,
            }
        )
        _atomic_write(path, state)
        if progress:
            progress("energy-sensitivity", index, len(ENERGY_SENSITIVITY_SEEDS), seed)
    state["status"] = "complete"
    state["completed_seed_count"] = len(state["records"])
    state["actual_policy_run_count"] = sum(
        len(row["energy_variants"]) * len(STRATEGY_ORDER) for row in state["records"]
    )
    _atomic_write(path, state)
    summary = summarize_energy_sensitivity(state)
    summary_path = ROOT / "results/phase9_corrected_energy_sensitivity_summary.json"
    _atomic_write(summary_path, summary)
    write_energy_sensitivity_chart(summary)
    return {"raw": str(path), "summary": str(summary_path), "seed_count": len(state["records"]), "policy_run_count": state["actual_policy_run_count"]}


def summarize_energy_sensitivity(raw: dict[str, object]) -> dict[str, object]:
    scenes: dict[str, object] = {}
    for variant_id, parameter, factor in ENERGY_VARIANTS:
        policy_summary = {}
        for strategy in STRATEGY_ORDER:
            runs = [row["energy_variants"][variant_id]["strategies"][strategy] for row in raw["records"]]
            names = (
                "rescue_user_service_success_rate",
                "network_recovery_success",
                "sustained_rescue_recovery_success",
                "network_recovery_or_censoring_time_s",
                "drone_energy_consumed_wh",
                "drone_energy_wh_per_rescue_user_hour",
                "algorithm_decision_total_ms",
                "drone_battery_minimum_wh",
                "target_switch_count",
            )
            policy_summary[strategy] = {
                metric: _stats(
                    [float(run["metrics"][metric]) for run in runs if run["metrics"].get(metric) is not None],
                    include_ci=True,
                )
                for metric in names
            }
        scenes[variant_id] = {
            "perturbed_parameter": parameter,
            "factor": factor,
            "policy_summaries": policy_summary,
            "paired_difference_vs_base": {},
        }
        if variant_id != "base":
            for strategy in STRATEGY_ORDER:
                for metric in (
                    "rescue_user_service_success_rate",
                    "network_recovery_success",
                    "sustained_rescue_recovery_success",
                    "drone_energy_consumed_wh",
                    "algorithm_decision_total_ms",
                    "drone_battery_minimum_wh",
                ):
                    differences = []
                    for row in raw["records"]:
                        value = row["energy_variants"][variant_id]["strategies"][strategy]["metrics"].get(metric)
                        base = row["energy_variants"]["base"]["strategies"][strategy]["metrics"].get(metric)
                        if value is not None and base is not None:
                            differences.append(float(value) - float(base))
                    scenes[variant_id]["paired_difference_vs_base"].setdefault(strategy, {})[metric] = _paired_summary(
                        differences,
                        binary=metric in BINARY_METRICS,
                        inferential=False,
                    )
    return {
        "schema_version": "1.0",
        "experiment_role": raw["experiment_role"],
        "status": raw["status"],
        "seed_ids": [int(row["seed"]) for row in raw["records"]],
        "seed_count": len(raw["records"]),
        "policy_run_count": raw.get("actual_policy_run_count"),
        "scope": "one-factor-at-a-time dynamic-failure sensitivity; not hardware calibration and not a second policy-tuning set",
        "scenarios": scenes,
    }


def write_phase9_charts(raw: dict[str, object], summary: dict[str, object]) -> list[str]:
    import matplotlib.pyplot as plt

    output = ROOT / "plots/phase9_corrected"
    output.mkdir(parents=True, exist_ok=True)
    labels = ["A", "B", "B′", "C", "D", "E"]
    ids = list(STRATEGY_ORDER)
    scene_ids = list(SCENARIO_CONFIGS)
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharey=True, constrained_layout=True)
    for axis, scene_id in zip(axes.flat, scene_ids, strict=True):
        strategies = summary["scenarios"][scene_id]["strategy_summaries"]
        means = [strategies[key]["metrics"]["rescue_user_service_success_rate"]["mean"] for key in ids]
        intervals = [strategies[key]["metrics"]["rescue_user_service_success_rate"]["mean_ci95_t"] for key in ids]
        yerr = [
            [max(0, means[i] - intervals[i][0]) if intervals[i] else 0 for i in range(len(ids))],
            [max(0, intervals[i][1] - means[i]) if intervals[i] else 0 for i in range(len(ids))],
        ]
        axis.bar(labels, means, color=["#646b73", "#9a9fa5", "#c9a166", "#8192a1", "#787f8f", "#a2382d"], alpha=0.9)
        axis.errorbar(labels, means, yerr=yerr, fmt="none", ecolor="#1b1b1b", capsize=3)
        axis.set_title(scene_id.replace("_", " "))
        axis.set_ylim(0, 1.03)
        axis.grid(axis="y", alpha=0.2)
        axis.set_ylabel("Rescue user service success rate")
    fig.suptitle("Phase 9 held-out confirmation: rescue service\nmean and 95% t interval across 20 paired seeds")
    service_png = output / "phase9_rescue_service_by_scene.png"
    fig.savefig(service_png, dpi=170)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    x = list(range(len(scene_ids)))
    width = 0.14
    for index, (strategy, label) in enumerate(zip(ids, labels, strict=True)):
        vals = [
            summary["scenarios"][scene]["strategy_summaries"][strategy]["metrics"]["algorithm_decision_total_ms"]["mean"]
            for scene in scene_ids
        ]
        axis.bar([point + (index - 2.5) * width for point in x], vals, width, label=label)
    axis.set_xticks(x, [scene.replace("_", " ") for scene in scene_ids])
    axis.set_ylabel("Decision compute per run (ms, wall clock)")
    axis.grid(axis="y", alpha=0.2)
    axis.legend(ncols=6, frameon=False)
    axis.set_title("Planning compute is separate from simulated recovery time")
    compute_png = output / "phase9_compute_by_scene.png"
    fig.savefig(compute_png, dpi=170)
    plt.close(fig)
    return [str(service_png), str(compute_png)]


def write_energy_sensitivity_chart(summary: dict[str, object]) -> str:
    import matplotlib.pyplot as plt

    output = ROOT / "plots/phase9_corrected"
    output.mkdir(parents=True, exist_ok=True)
    variant_ids = [row[0] for row in ENERGY_VARIANTS]
    labels = ["Base", "Move −25%", "Move +25%", "Hover −25%", "Hover +25%", "Relay −25%", "Relay +25%"]
    policies = ["B_phase1_static_grid", "Bprime_static_grid_shared_safety", "C_rolling_horizon_mpc", "D_lexicographic_rescue_priority", "E_event_driven_rescue_recovery"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5), constrained_layout=True)
    for policy, label in zip(policies, ("B", "B′", "C", "D", "E"), strict=True):
        means = [
            summary["scenarios"][variant]["policy_summaries"][policy]["rescue_user_service_success_rate"]["mean"]
            for variant in variant_ids
        ]
        axes[0].plot(labels, means, marker="o", label=label)
        energy = [
            summary["scenarios"][variant]["policy_summaries"][policy]["drone_energy_consumed_wh"]["mean"]
            for variant in variant_ids
        ]
        axes[1].plot(labels, energy, marker="o", label=label)
    axes[0].set_ylabel("Rescue user service rate")
    axes[0].set_ylim(0, 1.03)
    axes[1].set_ylabel("Drone energy consumed (Wh)")
    for axis in axes:
        axis.tick_params(axis="x", rotation=28)
        axis.grid(alpha=0.2)
    axes[0].legend(frameon=False)
    fig.suptitle("Energy-model parameter sensitivity on 10 separate dynamic-failure seeds")
    path = output / "phase9_energy_sensitivity.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return str(path)
