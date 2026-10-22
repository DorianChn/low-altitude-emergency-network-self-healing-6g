"""Print compact audit tables from the Phase 5 held-out JSON artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SCENES = (
    "severe_persistent_faults",
    "dynamic_failures",
    "high_mobility_rescue",
    "high_load_backhaul_limit",
)
STRATEGIES = (
    "A_no_recovery",
    "B_phase1_static_grid",
    "Bprime_static_grid_shared_safety",
    "C_rolling_horizon_mpc",
    "D_lexicographic_rescue_priority",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--phase", choices=("development", "validation"), default="validation")
    args = parser.parse_args()
    print(
        "scene,strategy,rescue_rate,rescue_ci95,sustained_runs,recovered_runs,"
        "restricted_time_s,mean_latency_ms,mean_p95_ms,latency_samples,energy_wh,"
        "uav_rescue_h,uav_extra_h,wh_per_uav_rescue_h,decision_ms,replans,target_switches"
    )
    for scene in SCENES:
        path = args.results / f"phase5_{args.phase}_{scene}.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        sample_count = result["reproducibility"]["seed_count"]
        for strategy in STRATEGIES:
            group = result["aggregate"][strategy]
            metrics = group["metrics"]
            latency = group["latency_conditioned_on_success"]
            rescue = metrics["rescue_user_service_success_rate"]
            sustained = group["sustained_network_recovery_30s"]
            recovery = group["network_recovery"]
            fields = (
                scene,
                strategy,
                _fmt(rescue["mean"]),
                _fmt(rescue.get("mean_ci95_t")),
                f"{sustained['recovered_runs']}/{sample_count}",
                f"{recovery['recovered_runs']}/{sample_count}",
                _fmt(recovery["recovery_or_censoring_time_s"]["mean"]),
                _fmt(latency["per_seed_average_ms"]["mean"]),
                _fmt(latency["per_seed_p95_ms"]["mean"]),
                str(latency["pooled_successful_user_time_samples"]),
                _fmt(metrics["drone_energy_consumed_wh"]["mean"]),
                _fmt(metrics["drone_rescue_user_seconds"]["mean"] / 3600),
                _fmt(metrics["drone_extra_rescue_user_seconds"]["mean"] / 3600),
                _fmt(metrics["drone_energy_wh_per_rescue_user_hour"]["mean"]),
                _fmt(metrics["algorithm_decision_total_ms"]["mean"]),
                _fmt(metrics["replan_count"]["mean"]),
                _fmt(metrics["target_switch_count"]["mean"]),
            )
            print(",".join(fields))
        for pair in (
            "Bprime_minus_B",
            "C_rolling_horizon_mpc_minus_B_phase1_static_grid",
            "D_minus_B_phase1_static_grid",
            "D_minus_Bprime_static_grid_shared_safety",
        ):
            stats = result["paired_differences"].get(pair, {}).get(
                "rescue_user_service_success_rate", {}
            )
            if stats:
                print(
                    f"{scene},PAIRED:{pair},{_fmt(stats['mean'])},"
                    f"{_fmt(stats.get('mean_ci95_t'))},,,,,,,,,,,,"
                )
    return 0


def _fmt(value: object) -> str:
    if value is None:
        return "NA"
    if isinstance(value, list):
        return f"[{','.join(_fmt(item) for item in value)}]"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
