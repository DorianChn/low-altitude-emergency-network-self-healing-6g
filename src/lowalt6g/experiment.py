"""Matched multi-seed experiments and statistically explicit summaries."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
import platform
import statistics
import sys
from typing import Callable

from . import __version__
from .dynamic_config import DynamicExperimentConfig
from .dynamic_simulation import DynamicRun, SeedExperiment, run_seed_experiment


STRATEGY_ORDER = (
    "A_no_recovery",
    "B_phase1_static_grid",
    "C_rolling_horizon_mpc",
)
PHASE4_STRATEGY_ORDER = STRATEGY_ORDER + ("D_lexicographic_rescue_priority",)
PHASE5_STRATEGY_ORDER = (
    "A_no_recovery",
    "B_phase1_static_grid",
    "Bprime_static_grid_shared_safety",
    "C_rolling_horizon_mpc",
    "D_lexicographic_rescue_priority",
)


def run_dynamic_benchmark(
    config: DynamicExperimentConfig,
    *,
    progress: Callable[[int, int, int], None] | None = None,
    on_seed: Callable[[SeedExperiment], None] | None = None,
    minimum_seed_count: int = 20,
    include_d: bool = False,
    include_bprime: bool = False,
) -> dict[str, object]:
    """Run the configured fixed-seed benchmark and aggregate without imputation."""
    config.validate()
    if len(config.seeds) < minimum_seed_count:
        raise ValueError(
            f"the comparison benchmark requires at least {minimum_seed_count} fixed seeds; "
            f"configured {len(config.seeds)}"
        )
    experiments: list[SeedExperiment] = []
    if include_bprime and include_d:
        strategy_order = PHASE5_STRATEGY_ORDER
    elif include_d:
        strategy_order = PHASE4_STRATEGY_ORDER
    else:
        strategy_order = STRATEGY_ORDER
    for index, seed in enumerate(config.seeds, start=1):
        experiment = run_seed_experiment(
            config,
            seed,
            include_d=include_d,
            include_bprime=include_bprime,
        )
        experiments.append(experiment)
        if on_seed is not None:
            on_seed(experiment)
        if progress is not None:
            progress(index, len(config.seeds), seed)

    aggregate = _aggregate(experiments, strategy_order, include_ci=include_d)
    paired = _paired_differences(experiments, strategy_order, include_ci=include_d)
    effective = _effective_config(config, strategy_order)
    config_bytes = json.dumps(effective, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": "2.2" if include_bprime and include_d else "2.1" if include_d else "2.0",
        "project_version": __version__,
        "model_scope": "abstract_dynamic_6g_research_simulation_not_real_network_test",
        "reproducibility": {
            "seeds": list(config.seeds),
            "seed_count": len(config.seeds),
            "effective_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
            "paired_world_traces": True,
        },
        "runtime_environment": {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "configuration": effective,
        "strategy_order": list(strategy_order),
        "aggregate": aggregate,
        "paired_differences": paired,
        "statistical_notes": {
            "rates": "Per-seed user-time rates use the same number of opportunities for all policies; summaries are equal-weight means across seeds.",
            "recovery": "Unrecovered runs remain null. Recovery-time mean and median include only recovered runs and are reported with recovered/unrecovered counts; no timeout value is imputed.",
            "sustained_recovery": "A sustained recovery requires all rescue users connected for 30 seconds continuously (four observations at 10-second sampling); the reported time is the first observation in that run.",
            "latency": "Latency is conditional on successful user-time connections. Each policy has its own successful-user sample set; latency is summarized separately and is not treated as a paired comparison.",
            "p95": "Per-seed P95 uses nearest-rank. The aggregate pooled P95 is calculated over all successful user-time latency samples across seeds.",
            "decision_time": "Decision compute time uses one wall-clock perf_counter boundary around controller.observe; only calls that emit a new decision are accumulated. Total run time and mean/p95 per decision are reported separately from simulated recovery time.",
            "confidence_intervals": "Continuous per-seed metrics use two-sided 95% Student-t confidence intervals; binary recovery proportions use two-sided 95% Wilson intervals; paired policy comparisons use within-seed differences. These intervals describe uncertainty under this configured simulation, not field-network uncertainty.",
            "raw_latency_samples": "Phase 4 seed records include each successful user-time latency sample so pooled conditional summaries can be independently recomputed.",
            "recovery_censoring": "network_recovery_or_censoring_time_s is T when recovered and the simulation horizon when not recovered; recovery success and recovered-only times remain separately reported.",
            "uav_attribution": "Ground-only rescue service is recomputed each tick with the same topology, demand, and positions but drone_active=false. UAV-relayed service counts rescue outcomes whose selected path_kind is drone_relay. Extra UAV service is max(0, actual connected rescue count minus ground-only connected rescue count) per interval.",
            "uav_energy_per_service": "Wh per rescue-user-hour divides total UAV energy by actual rescue user-seconds routed over drone_relay. It is null when no such service was delivered.",
            "shared_safety_policy": "B is retained as the historical grid planner. Bprime uses the same grid destination with a common conservative sortie budget including movement, hover, relay, service horizon, return, and reserve. C, D, and the runtime actuator use the same Wh rates and return-hover reserve helper.",
        },
        "seed_experiments": [experiment.to_dict(include_latency_samples=include_d) for experiment in experiments],
    }


def _effective_config(
    config: DynamicExperimentConfig,
    strategy_order: tuple[str, ...] = STRATEGY_ORDER,
) -> dict[str, object]:
    return {
        "strategy_order": list(strategy_order),
        "base_scenario_file": config.scenario_path.name,
        "base_scenario": config.base.to_dict(),
        "seeds": list(config.seeds),
        "events": [asdict(event) for event in config.events],
        "mobility_axis_max_km_per_tick": config.mobility_axis_max_km_per_tick,
        "rescue_mobility_axis_max_km_per_tick": config.rescue_mobility_axis_max_km_per_tick,
        "initial_backhaul_capacity_mbps": config.initial_backhaul_capacity_mbps,
        "development_seeds": list(config.development_seeds),
        "validation_seeds": list(config.validation_seeds),
        "energy": {
            "battery_capacity_wh": config.battery_capacity_wh,
            "initial_battery_wh": config.initial_battery_wh,
            "reserve_wh": config.reserve_wh,
            "movement_wh_per_km": config.movement_wh_per_km,
            "hover_power_w": config.hover_power_w,
            "relay_power_w": config.relay_power_w,
        },
        "optimizer": {
            "algorithm": (
                "phase5_comparison_with_lexicographic_rescue_priority_mpc"
                if len(strategy_order) == 5
                else "lexicographic_rescue_priority_mpc"
                if len(strategy_order) == 4
                else "rolling_horizon_beam_search"
            ),
            "decision_interval_s": config.decision_interval_s,
            "prediction_horizon_steps": config.prediction_horizon_steps,
            "beam_width": config.beam_width,
            "position_signature_quantum_km": config.position_signature_quantum_km,
            "congestion_threshold": config.congestion_threshold,
            "objective_weights": {
                "rescue_service": config.rescue_service_weight,
                "all_user_connection": config.connection_weight,
                "full_rescue_recovery_bonus": config.recovery_bonus,
                "latency_penalty": config.latency_penalty_weight,
                "energy_penalty": config.energy_penalty_weight,
                "rescue_progress_per_control_step": config.rescue_progress_weight,
            },
            "phase4_rescue_priority_profile": (
                {
                    "objective": "lexicographic_rescue_user_ticks_full_recovery_time_target_rescue_count_ordinary_service_latency_energy_movement_switches",
                    "periodic_replan_interval_s": max(60, config.decision_interval_s),
                    "event_signature": "station_backhaul_rescue_normal_service_counts_congestion_group_offered_load_and_0.5_km_rescue_centroid",
                    "target_commitment": "retarget-only-on-projected-rescue-user-tick_or_terminal-rescue-service-improvement",
                    "initial_warm_start": "phase1_static_grid_best_position_then_dynamic_lexicographic_replanning",
                    "candidate_grid_step_km": config.base.policy_search_grid_km,
                    "geometric_grid_candidates_max": 64,
                    "rescue_pair_intersection_candidates_max": 12,
                    "terminal_value": "target_rescue_count_and_earliest_feasible_full_rescue_point_on_route",
                    "return_energy_includes_hover_and_relay_power": True,
                    "forecast": "frozen-current-topology-and-user-positions-over-configured-horizon",
                }
                if len(strategy_order) == 4
                else None
            ),
        },
    }


def _aggregate(
    experiments: list[SeedExperiment],
    strategy_order: tuple[str, ...] = STRATEGY_ORDER,
    *,
    include_ci: bool = False,
) -> dict[str, object]:
    output: dict[str, object] = {}
    for strategy_id in strategy_order:
        runs = [experiment.strategies[strategy_id] for experiment in experiments]
        per_run = [run.metrics for run in runs]
        metric_names = (
            "network_coverage_rate",
            "user_connection_success_rate",
            "rescue_user_service_success_rate",
            "ground_only_rescue_service_success_rate",
            "final_coverage_rate",
            "final_connection_success_rate",
            "drone_energy_consumed_wh",
            "drone_rescue_user_seconds",
            "drone_extra_rescue_user_seconds",
            "ground_rescue_user_seconds",
            "drone_energy_wh_per_rescue_user_hour",
            "algorithm_decision_total_ms",
            "controller_observe_total_ms",
            "algorithm_decision_mean_ms",
            "algorithm_decision_p95_ms",
            "algorithm_decision_count",
            "target_switch_count",
            "replan_count",
            "infeasible_decision_count",
            "network_recovery_success",
            "sustained_rescue_recovery_success",
        )
        statistics_by_metric: dict[str, dict[str, float | int | None]] = {}
        for metric in metric_names:
            values = [float(result[metric]) for result in per_run if result.get(metric) is not None]
            statistics_by_metric[metric] = _stats(values, include_ci=include_ci)

        recovered = [
            float(result["network_recovery_time_s"])
            for result in per_run
            if result["network_recovery_time_s"] is not None
        ]
        recovery_or_censoring = [
            float(result["network_recovery_or_censoring_time_s"])
            for result in per_run
        ]
        all_latencies = [value for run in runs for value in run.latency_samples_ms]
        sustained_recovered = [
            float(result["sustained_rescue_recovery_time_s"])
            for result in per_run
            if result.get("sustained_rescue_recovery_time_s") is not None
        ]
        per_seed_mean_latencies = [
            float(result["average_latency_ms"])
            for result in per_run
            if result["average_latency_ms"] is not None
        ]
        per_seed_p95_latencies = [
            float(result["p95_latency_ms"])
            for result in per_run
            if result["p95_latency_ms"] is not None
        ]
        output[strategy_id] = {
            "seed_count": len(per_run),
            "metrics": statistics_by_metric,
            "network_recovery": {
                "recovered_runs": len(recovered),
                "unrecovered_runs": len(per_run) - len(recovered),
                "success_rate": round(len(recovered) / len(per_run), 6) if per_run else None,
                "recovered_only_time_s": _stats(recovered, include_ci=include_ci),
                "recovery_or_censoring_time_s": _stats(recovery_or_censoring, include_ci=include_ci),
            },
            "sustained_network_recovery_30s": {
                "recovered_runs": len(sustained_recovered),
                "unrecovered_runs": len(per_run) - len(sustained_recovered),
                "success_rate": round(len(sustained_recovered) / len(per_run), 6) if per_run else None,
                "recovered_only_time_s": _stats(sustained_recovered, include_ci=include_ci),
            },
            "latency_conditioned_on_success": {
                "per_seed_average_ms": _stats(per_seed_mean_latencies, include_ci=include_ci),
                "per_seed_p95_ms": _stats(per_seed_p95_latencies, include_ci=include_ci),
                "pooled_average_ms": round(statistics.fmean(all_latencies), 6) if all_latencies else None,
                "pooled_p95_ms": _percentile(all_latencies, 0.95),
                "pooled_successful_user_time_samples": len(all_latencies),
            },
        }
    return output


def _paired_differences(
    experiments: list[SeedExperiment],
    strategy_order: tuple[str, ...] = STRATEGY_ORDER,
    *,
    include_ci: bool = False,
) -> dict[str, object]:
    pairs = {
        f"{left}_minus_{right}": (left, right)
        for left, right in (
            ("C_rolling_horizon_mpc", "A_no_recovery"),
            ("C_rolling_horizon_mpc", "B_phase1_static_grid"),
        )
    }
    if "Bprime_static_grid_shared_safety" in strategy_order:
        pairs["Bprime_minus_B"] = (
            "Bprime_static_grid_shared_safety",
            "B_phase1_static_grid",
        )
        pairs["C_minus_Bprime"] = (
            "C_rolling_horizon_mpc",
            "Bprime_static_grid_shared_safety",
        )
    if "D_lexicographic_rescue_priority" in strategy_order:
        pairs.update(
            {
                f"D_minus_{right}": ("D_lexicographic_rescue_priority", right)
                for right in (
                    "A_no_recovery",
                    "B_phase1_static_grid",
                    *(('Bprime_static_grid_shared_safety',) if "Bprime_static_grid_shared_safety" in strategy_order else ()),
                    "C_rolling_horizon_mpc",
                )
            }
        )
    metrics = (
        "network_coverage_rate",
        "user_connection_success_rate",
        "rescue_user_service_success_rate",
        "ground_only_rescue_service_success_rate",
        "network_recovery_or_censoring_time_s",
        "drone_energy_consumed_wh",
        "drone_rescue_user_seconds",
        "drone_extra_rescue_user_seconds",
        "algorithm_decision_total_ms",
        "controller_observe_total_ms",
        "algorithm_decision_mean_ms",
        "network_recovery_success",
        "sustained_rescue_recovery_success",
    )
    result: dict[str, object] = {}
    for pair_name, (left_id, right_id) in pairs.items():
        differences: dict[str, object] = {}
        for metric in metrics:
            values = [
                float(experiment.strategies[left_id].metrics[metric])
                - float(experiment.strategies[right_id].metrics[metric])
                for experiment in experiments
            ]
            differences[metric] = _stats(values, include_ci=include_ci)
        recovery_diffs = [
            float(left) - float(right)
            for experiment in experiments
            if (left := experiment.strategies[left_id].metrics["network_recovery_time_s"]) is not None
            and (right := experiment.strategies[right_id].metrics["network_recovery_time_s"]) is not None
        ]
        differences["network_recovery_time_s_both_recovered"] = {
            "paired_recovered_seeds": len(recovery_diffs),
            "difference_stats": _stats(recovery_diffs, include_ci=include_ci),
        }
        sustained_recovery_diffs = [
            float(left) - float(right)
            for experiment in experiments
            if (left := experiment.strategies[left_id].metrics.get("sustained_rescue_recovery_time_s")) is not None
            and (right := experiment.strategies[right_id].metrics.get("sustained_rescue_recovery_time_s")) is not None
        ]
        differences["sustained_recovery_time_s_both_recovered"] = {
            "paired_recovered_seeds": len(sustained_recovery_diffs),
            "difference_stats": _stats(sustained_recovery_diffs, include_ci=include_ci),
        }
        result[pair_name] = differences
    result["latency_comparison"] = (
        "No paired latency difference is computed because policies may serve different users/time samples; see each policy's conditional summaries."
    )
    return result


_T_CRITICAL_975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
    7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
    13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
    19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
    25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def _stats(values: list[float], *, include_ci: bool = False) -> dict[str, object]:
    if not values:
        output: dict[str, object] = {"n": 0, "mean": None, "sample_sd": None, "median": None, "min": None, "max": None}
        if include_ci:
            output["mean_ci95_t"] = None
            output["ci95_wilson"] = None
        return output
    mean = statistics.fmean(values)
    sample_sd = statistics.stdev(values) if len(values) > 1 else 0.0
    output = {
        "n": len(values),
        "mean": round(mean, 6),
        "sample_sd": round(sample_sd, 6),
        "median": round(statistics.median(values), 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }
    if include_ci:
        if len(values) < 2:
            output["mean_ci95_t"] = None
        else:
            degrees_of_freedom = len(values) - 1
            critical = _T_CRITICAL_975.get(degrees_of_freedom, 1.96)
            margin = critical * sample_sd / math.sqrt(len(values))
            output["mean_ci95_t"] = [round(mean - margin, 6), round(mean + margin, 6)]
        output["ci95_wilson"] = _wilson_interval(values) if all(value in (0.0, 1.0) for value in values) else None
    return output


def _wilson_interval(values: list[float]) -> list[float] | None:
    """Return the two-sided 95% Wilson interval for binary run outcomes."""
    if not values or not all(value in (0.0, 1.0) for value in values):
        return None
    count = len(values)
    successes = sum(values)
    z = 1.959963984540054
    z_squared = z * z
    proportion = successes / count
    denominator = 1.0 + z_squared / count
    center = (proportion + z_squared / (2.0 * count)) / denominator
    radius = z * math.sqrt(
        proportion * (1.0 - proportion) / count + z_squared / (4.0 * count * count)
    ) / denominator
    return [round(max(0.0, center - radius), 6), round(min(1.0, center + radius), 6)]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 6)
