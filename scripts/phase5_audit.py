"""Audit frozen Phase 5 results and index failure/recovery event evidence."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from lowalt6g.dynamic_config import load_dynamic_config


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = (
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
EXCLUDED_TIMING_METRICS = {
    "algorithm_decision_mean_ms",
    "algorithm_decision_p95_ms",
    "algorithm_decision_total_ms",
    "controller_observe_total_ms",
}
COMPARE_METRICS = (
    "network_coverage_rate",
    "user_connection_success_rate",
    "rescue_user_service_success_rate",
    "ground_only_rescue_service_success_rate",
    "network_recovery_time_s",
    "network_recovery_or_censoring_time_s",
    "sustained_rescue_recovery_time_s",
    "drone_energy_consumed_wh",
    "drone_rescue_user_seconds",
    "drone_extra_rescue_user_seconds",
    "drone_energy_wh_per_rescue_user_hour",
)


def _write(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _safe_reason_event(event: dict[str, Any]) -> dict[str, Any]:
    diagnosis = event.get("diagnosis") or {}
    return {
        "time_s": event.get("time_s"),
        "event_type": event.get("event_type"),
        "reason": event.get("reason"),
        "trigger": event.get("trigger"),
        "infeasible_reasons": event.get("infeasible_reasons", []),
        "failed_station_ids": diagnosis.get("failed_station_ids", []),
        "drone_backhaul_available": diagnosis.get("drone_backhaul_available"),
        "disconnected_rescue_user_count": len(
            diagnosis.get("disconnected_rescue_ids", [])
        ),
    }


def audit_phase5(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    results = root / "results"
    manifest_path = results / "phase5_frozen_manifest.json"
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    issues: list[str] = []
    scene_audits: dict[str, Any] = {}
    failure_cases: list[dict[str, Any]] = []

    for scene in SCENARIOS:
        source = results / f"phase5_validation_{scene}.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        config = load_dynamic_config(root / "configs" / "phase5" / f"{scene}.toml")
        runs = data.get("seed_experiments", [])
        seeds = [int(run["seed"]) for run in runs]
        if data.get("frozen_manifest_sha256") != manifest_sha:
            issues.append(f"{scene}: validation file does not match frozen manifest")
        if data.get("experiment_role") != "held_out_validation_frozen_algorithm":
            issues.append(f"{scene}: unexpected experiment role")
        if len(runs) != 20 or len(set(seeds)) != 20:
            issues.append(f"{scene}: expected 20 unique held-out seeds")
        if set(seeds) & set(config.development_seeds):
            issues.append(f"{scene}: development and validation seeds overlap")
        if data.get("strategy_order") != list(STRATEGIES):
            issues.append(f"{scene}: strategy set or order mismatch")

        event_counts: Counter[str] = Counter()
        minimum_battery = config.initial_battery_wh
        maximum_speed_ratio = 0.0
        minimum_plan_margin: float | None = None
        planned_actions = 0
        max_energy_log_error = 0.0
        paired_baseline_matches = True
        for run in runs:
            environment_events = run.get("environment_events", [])
            event_times = [event.get("time_s") for event in environment_events]
            event_counts.update(event.get("event_type", "unknown") for event in environment_events)
            if any(time is None for time in event_times) or event_times != sorted(event_times):
                issues.append(f"{scene}/{run['seed']}: missing or unordered environment timestamps")
            if not run.get("world_trace_sha256"):
                issues.append(f"{scene}/{run['seed']}: missing shared-world trace hash")
            if set(run.get("strategies", {})) != set(STRATEGIES):
                issues.append(f"{scene}/{run['seed']}: strategy set mismatch")

            for strategy, result in run.get("strategies", {}).items():
                metrics = result.get("metrics", {})
                energy_used = 0.0
                last_time = -1
                for event in result.get("event_log", []):
                    time_s = event.get("time_s")
                    if time_s is None:
                        issues.append(f"{scene}/{run['seed']}/{strategy}: untimestamped event log")
                        continue
                    if time_s < last_time:
                        issues.append(f"{scene}/{run['seed']}/{strategy}: unordered event log")
                    last_time = time_s
                    if event.get("event_type") == "drone_state_update":
                        moved_km = float(event.get("moved_km", 0.0))
                        step_limit = config.base.drone.speed_km_per_s * config.time_step_s
                        maximum_speed_ratio = max(maximum_speed_ratio, moved_km / step_limit)
                        battery = float(event.get("battery_remaining_wh", 0.0))
                        minimum_battery = min(minimum_battery, battery)
                        energy_used += float(event.get("energy_consumed_wh", 0.0))
                        if battery < config.reserve_wh - 1e-3:
                            issues.append(f"{scene}/{run['seed']}/{strategy}: battery below reserve")
                    planned_energy = event.get("planned_sortie_energy_wh")
                    planning_battery = event.get("planning_battery_wh")
                    if planned_energy is not None and planning_battery is not None:
                        planned_actions += 1
                        margin = float(planning_battery) - config.reserve_wh - float(planned_energy)
                        minimum_plan_margin = margin if minimum_plan_margin is None else min(minimum_plan_margin, margin)
                        if margin < -1e-3:
                            issues.append(f"{scene}/{run['seed']}/{strategy}: plan violates reserve")

                    if event.get("event_type") == "optimizer_decision" and event.get("deploy") is False:
                        # Include actual safe exits in the failure index below.
                        pass

                if float(metrics.get("drone_battery_minimum_wh", 0.0)) < config.reserve_wh - 1e-3:
                    issues.append(f"{scene}/{run['seed']}/{strategy}: reported minimum below reserve")
                max_energy_log_error = max(
                    max_energy_log_error,
                    abs(energy_used - float(metrics.get("drone_energy_consumed_wh", 0.0))),
                )
                if abs(energy_used - float(metrics.get("drone_energy_consumed_wh", 0.0))) > 0.03:
                    issues.append(f"{scene}/{run['seed']}/{strategy}: energy log does not reconcile")

            b_metrics = run["strategies"]["B_phase1_static_grid"]["metrics"]
            bp_metrics = run["strategies"]["Bprime_static_grid_shared_safety"]["metrics"]
            for metric in COMPARE_METRICS:
                if b_metrics.get(metric) != bp_metrics.get(metric):
                    paired_baseline_matches = False
                    break

            for strategy, result in run["strategies"].items():
                metrics = result["metrics"]
                recovery_failed = not bool(metrics.get("network_recovery_success"))
                sustained_failed = not bool(metrics.get("sustained_rescue_recovery_success"))
                if not recovery_failed and not sustained_failed:
                    continue
                logged_events = result.get("event_log", [])
                recovery_events = [
                    {
                        "time_s": event.get("time_s"),
                        "recovery_cause": event.get("recovery_cause"),
                        "rescue_users_connected": event.get("rescue_users_connected"),
                        "rescue_users_total": event.get("rescue_users_total"),
                        "ground_only_rescue_users_connected": event.get(
                            "ground_only_rescue_users_connected"
                        ),
                        "uav_relayed_rescue_users": event.get("uav_relayed_rescue_users"),
                    }
                    for event in logged_events
                    if event.get("event_type") == "network_recovery"
                ]
                safe_exits = [
                    _safe_reason_event(event)
                    for event in logged_events
                    if event.get("event_type") == "optimizer_decision"
                    and event.get("deploy") is False
                    and event.get("reason") not in {"baseline_no_deployment", "hold_previous_action"}
                ]
                safe_exits.extend(
                    {
                        "time_s": event.get("time_s"),
                        "event_type": event.get("event_type"),
                        "reason": event.get("reason"),
                    }
                    for event in logged_events
                    if event.get("event_type") == "drone_energy_reserve_shutdown"
                )
                hazard_events = [
                    event
                    for event in environment_events
                    if event.get("event_type")
                    in {
                        "station_failure",
                        "station_recovery",
                        "backhaul_failure",
                        "backhaul_recovery",
                        "backhaul_capacity_change",
                        "traffic_change",
                        "user_mobility_change",
                    }
                ]
                failure_cases.append(
                    {
                        "scenario_id": scene,
                        "seed": run["seed"],
                        "strategy_id": strategy,
                        "failed_criteria": [
                            name
                            for name, failed in (
                                ("all_rescue_users_connected_once", recovery_failed),
                                ("all_rescue_users_connected_continuously_30s", sustained_failed),
                            )
                            if failed
                        ],
                        "metrics": {
                            "rescue_user_service_success_rate": metrics.get(
                                "rescue_user_service_success_rate"
                            ),
                            "ground_only_rescue_service_success_rate": metrics.get(
                                "ground_only_rescue_service_success_rate"
                            ),
                            "network_recovery_time_s": metrics.get("network_recovery_time_s"),
                            "network_recovery_or_censoring_time_s": metrics.get(
                                "network_recovery_or_censoring_time_s"
                            ),
                            "network_recovery_cause": metrics.get("network_recovery_cause"),
                            "sustained_rescue_recovery_time_s": metrics.get(
                                "sustained_rescue_recovery_time_s"
                            ),
                            "drone_energy_consumed_wh": metrics.get("drone_energy_consumed_wh"),
                            "drone_battery_minimum_wh": metrics.get("drone_battery_minimum_wh"),
                        },
                        "hazard_event_timeline": hazard_events,
                        "recovery_events": recovery_events,
                        "safe_exit_decisions": safe_exits,
                        "raw_result_file": source.name,
                    }
                )

        if maximum_speed_ratio > 1.001:
            issues.append(f"{scene}: observed UAV movement exceeded configured speed")
        if not paired_baseline_matches:
            issues.append(f"{scene}: B and B-prime differ on service, energy, or recovery outcomes")
        if scene == "severe_persistent_faults" and any(
            event.event_type == "station_recovery" for event in config.events
        ):
            issues.append("severe_persistent_faults: contains a station recovery event")

        scene_audits[scene] = {
            "validation_runs": len(runs),
            "seed_range": [min(seeds), max(seeds)] if seeds else None,
            "validation_seeds": seeds,
            "development_seed_count": len(config.development_seeds),
            "development_validation_overlap": sorted(set(config.development_seeds) & set(seeds)),
            "environment_event_counts": dict(event_counts),
            "minimum_observed_battery_wh": round(minimum_battery, 6),
            "reserve_wh": config.reserve_wh,
            "maximum_movement_to_speed_limit_ratio": round(maximum_speed_ratio, 9),
            "planned_sortie_decision_count": planned_actions,
            "minimum_planned_reserve_margin_wh": (
                round(minimum_plan_margin, 6) if minimum_plan_margin is not None else None
            ),
            "maximum_event_energy_reconciliation_error_wh": round(max_energy_log_error, 9),
            "B_and_Bprime_outcome_metrics_identical": paired_baseline_matches,
            "failure_or_not_sustained_runs": sum(
                case["scenario_id"] == scene for case in failure_cases
            ),
        }

    audit = {
        "schema_version": "1.0",
        "status": "PASS" if not issues else "FAIL",
        "frozen_manifest_sha256": manifest_sha,
        "protocol_revision": manifest.get("protocol_revision"),
        "scenario_count": len(scene_audits),
        "held_out_seed_count": sum(item["validation_runs"] for item in scene_audits.values()),
        "strategy_run_count": sum(item["validation_runs"] for item in scene_audits.values())
        * len(STRATEGIES),
        "failure_or_not_sustained_case_count": len(failure_cases),
        "issues": issues,
        "scenarios": scene_audits,
    }
    failure_index = {
        "schema_version": "1.0",
        "frozen_manifest_sha256": manifest_sha,
        "criterion": "A run is indexed when first all-rescue recovery fails or 30-second sustained recovery fails.",
        "failure_or_not_sustained_case_count": len(failure_cases),
        "cases": failure_cases,
        "full_timestamped_logs_remain_in_raw_result_files": True,
    }
    return audit, failure_index


def main() -> None:
    audit, failure_index = audit_phase5()
    _write(ROOT / "results" / "phase5_integrity_audit.json", audit)
    _write(ROOT / "results" / "phase5_failure_cases.json", failure_index)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if audit["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
