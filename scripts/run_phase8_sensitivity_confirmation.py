"""Run a frozen, independent confirmation of the remaining Phase 8 factor levels."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lowalt6g import phase8_experiments as p8  # noqa: E402
from lowalt6g.dynamic_simulation import run_seed_experiment  # noqa: E402
from lowalt6g.dynamic_world import build_world_trace  # noqa: E402
from run_phase8_replication import vectorized_paired_test  # noqa: E402


SENSITIVITY_SEEDS = {
    "severe_persistent_faults": tuple(range(90800, 90820)),
    "dynamic_failures": tuple(range(90900, 90920)),
    "high_mobility_rescue": tuple(range(91000, 91020)),
    "high_load_backhaul_limit": tuple(range(91100, 91120)),
}

# These are the remaining low/high levels from the already frozen sensitivity
# plan. Horizon, replanning-event, selected candidate-cap, switch-suppression,
# and objective-priority checks are in the separately preserved 20-seed cohort.
SENSITIVITY_VARIANT_IDS = (
    "C_interval_10",
    "C_interval_40",
    "D_interval_90",
    "D_interval_120",
    "C_target_grid_0p125",
    "C_target_grid_0p5",
    "D_grid_0p125",
    "D_grid_0p5",
    "D_candidate_cap_128",
    "D_switch_penalty_0",
    "D_switch_penalty_10",
    "C_energy_weight_4",
    "C_rescue_weight_5",
    "C_rescue_weight_20",
    "C_beam_width_3",
    "C_beam_width_12",
    "C_reserve_75",
    "C_reserve_100",
    "D_reserve_75",
    "D_reserve_100",
)
SENSITIVITY_VARIANTS = tuple(p8.VARIANT_BY_ID[key] for key in SENSITIVITY_VARIANT_IDS)
PROTOCOL_PATH = ROOT / "configs/phase8/sensitivity_validation_protocol.json"
OUTPUT_RAW = ROOT / "results/phase8_sensitivity_validation_raw.json"
OUTPUT_SUMMARY = ROOT / "results/phase8_sensitivity_validation_summary.json"
OUTPUT_AUDIT = ROOT / "results/phase8_sensitivity_validation_audit.json"
CODE_PATHS = (
    "src/lowalt6g/phase8_experiments.py",
    "src/lowalt6g/phase8_d_optimizer.py",
    "src/lowalt6g/dynamic_simulation.py",
    "src/lowalt6g/dynamic_world.py",
    "scripts/run_phase8_replication.py",
    "scripts/run_phase8_sensitivity_confirmation.py",
)
CONFIG_PATHS = (
    "configs/phase8/experiment_plan.json",
    "configs/phase8/ablation_plan.json",
    "configs/phase8/sensitivity_plan.json",
    "configs/phase8/validation_protocol.json",
    "configs/phase8/replication_protocol.json",
    "results/phase5_frozen_manifest.json",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_sensitivity_seeds() -> None:
    selected = [seed for values in SENSITIVITY_SEEDS.values() for seed in values]
    if len(selected) != 80 or len(set(selected)) != 80:
        raise ValueError("parameter confirmation requires 80 unique seeds")
    prior = set(p8.HISTORICAL_SEEDS)
    for partition in (p8.DEVELOPMENT_SEEDS, p8.VALIDATION_SEEDS):
        prior.update(seed for values in partition.values() for seed in values)
    for seed in range(90400, 90420):
        prior.add(seed)
    for seed in range(90500, 90520):
        prior.add(seed)
    for seed in range(90600, 90620):
        prior.add(seed)
    for seed in range(90700, 90720):
        prior.add(seed)
    for config in p8._load_scenarios().values():
        prior.update(config.development_seeds)
        prior.update(config.validation_seeds)
    if prior.intersection(selected):
        raise ValueError("sensitivity confirmation seeds overlap an existing cohort")


def freeze_protocol() -> Path:
    p8.ensure_plan_file()
    validate_sensitivity_seeds()
    if PROTOCOL_PATH.exists():
        raise FileExistsError(f"refusing to replace frozen protocol: {PROTOCOL_PATH}")
    dev_raw = ROOT / "results/phase8_development_raw.json"
    dev_summary = ROOT / "results/phase8_development_summary.json"
    if not dev_raw.is_file() or not dev_summary.is_file():
        raise FileNotFoundError("complete development data are required before freezing sensitivity confirmation")
    if json.loads(dev_raw.read_text(encoding="utf-8")).get("status") != "complete":
        raise ValueError("Phase 8 development raw data are incomplete")
    protocol = {
        "schema_version": "1.0",
        "status": "frozen_before_parameter_confirmation",
        "study_design": (
            "Remaining low/high parameter levels from the pre-existing sensitivity plan; selected from the factor matrix, "
            "not from held-out outcomes. One factor changes per variant."
        ),
        "development_artifacts_sha256": {
            "results/phase8_development_raw.json": sha256_file(dev_raw),
            "results/phase8_development_summary.json": sha256_file(dev_summary),
        },
        "experiment_plan_sha256": sha256_file(ROOT / "configs/phase8/experiment_plan.json"),
        "sensitivity_plan_sha256": sha256_file(ROOT / "configs/phase8/sensitivity_plan.json"),
        "phase5_manifest_sha256": sha256_file(ROOT / "results/phase5_frozen_manifest.json"),
        "phase5_source_sha256": p8.verify_phase5_freeze(),
        "code_sha256": {path: sha256_file(ROOT / path) for path in CODE_PATHS},
        "configuration_sha256": {path: sha256_file(ROOT / path) for path in CONFIG_PATHS},
        "seed_map": SENSITIVITY_SEEDS,
        "seeds_per_scenario": 20,
        "variant_ids": list(SENSITIVITY_VARIANT_IDS),
        "baseline_strategies": list(p8.BASELINE_ORDER),
        "policy_runs_expected": 80 * (len(p8.BASELINE_ORDER) + len(SENSITIVITY_VARIANTS)),
        "analysis": {
            "pairing": "same scenario seed and same DynamicWorldTrace for all five baseline strategies and all one-factor variants",
            "primary_outcomes": [
                "rescue_user_service_success_rate",
                "network_recovery_or_censoring_time_s",
                "network_recovery_success",
                "sustained_rescue_recovery_success",
            ],
            "secondary_outcomes": [
                "drone_energy_consumed_wh",
                "drone_energy_wh_per_rescue_user_hour",
                "conditional_latency_with_sample_count",
                "algorithm_decision_total_ms",
                "algorithm_decision_mean_ms",
                "target_switch_count",
            ],
            "tests": "paired exact sign-flip randomization for continuous per-seed outcomes; exact McNemar/binomial test for binary outcomes",
            "intervals_effects": "two-sided 95% Student-t intervals for paired differences; Cohen dz and Hedges gz",
            "multiplicity": "Holm separately across complete predeclared efficacy and resource/cost families",
            "failure_handling": "unrecovered runs remain censored at 600 s; sustained-recovery failures remain in denominators",
            "latency": "conditional on each strategy's own successful user-time samples; report per-policy sample count, no paired test",
        },
        "safety_constraints": [
            "runtime speed, energy, backhaul, access, capacity, and city-boundary checks remain active",
            "positive battery reserve and return-energy protection remain enforced by planner and simulator",
            "no variant can bypass runtime feasibility checks",
        ],
        "model_scope": "abstract_6g_research_simulation_not_real_network_test",
        "git_head": p8._git_head(),
    }
    PROTOCOL_PATH.write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return PROTOCOL_PATH


def verify_protocol() -> dict[str, object]:
    validate_sensitivity_seeds()
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    for path, expected in protocol["code_sha256"].items():
        if sha256_file(ROOT / path) != expected:
            raise ValueError(f"code changed after sensitivity protocol freeze: {path}")
    for path, expected in protocol["configuration_sha256"].items():
        if sha256_file(ROOT / path) != expected:
            raise ValueError(f"configuration changed after sensitivity protocol freeze: {path}")
    for path, expected in protocol["development_artifacts_sha256"].items():
        if sha256_file(ROOT / path) != expected:
            raise ValueError(f"development artifact changed after protocol freeze: {path}")
    if protocol["phase5_source_sha256"] != p8.verify_phase5_freeze():
        raise ValueError("Phase 5 frozen sources changed")
    return protocol


def _atomic_json(path: Path, payload: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    temp.replace(path)


def _audit_raw(raw: dict[str, object]) -> dict[str, object]:
    issues: list[str] = []
    records = raw["records"]
    expected_pairs = {(scene, seed) for scene, seeds in SENSITIVITY_SEEDS.items() for seed in seeds}
    actual_pairs = {(row["scenario_id"], int(row["seed"])) for row in records}
    if actual_pairs != expected_pairs or len(records) != len(expected_pairs):
        issues.append("seed_partition_mismatch")
    run_count = 0
    reserve_violations = 0
    latency_count_mismatches = 0
    missing_trace_hashes = 0
    untimed_environment_events = 0
    for row in records:
        missing_trace_hashes += int(not row.get("world_trace_sha256"))
        untimed_environment_events += sum("time_s" not in event for event in row["environment_events"])
        for run in list(row["baseline_strategy_runs"].values()) + list(row["variant_runs"].values()):
            run_count += 1
            metrics = run["metrics"]
            latency_count_mismatches += int(len(run.get("latency_samples_ms", [])) != metrics.get("latency_sample_count"))
        for variant_id, reserve in row["variant_reserve_wh"].items():
            minimum = float(row["variant_runs"][variant_id]["metrics"]["drone_battery_minimum_wh"])
            reserve_violations += int(minimum < float(reserve) - 1e-6)
    expected_count = 80 * (len(p8.BASELINE_ORDER) + len(SENSITIVITY_VARIANTS))
    checks = {
        "seed_partition_mismatch": len(actual_pairs) != len(expected_pairs) or len(records) != len(expected_pairs),
        "policy_run_count_mismatch": run_count != expected_count,
        "battery_reserve_violations": reserve_violations != 0,
        "latency_sample_count_mismatches": latency_count_mismatches != 0,
        "missing_world_trace_hashes": missing_trace_hashes != 0,
        "untimed_environment_events": untimed_environment_events != 0,
    }
    issues.extend(key for key, failed in checks.items() if failed and key not in issues)
    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "seed_count": len(records),
        "policy_run_count": run_count,
        "expected_policy_run_count": expected_count,
        "battery_reserve_violations": reserve_violations,
        "latency_sample_count_mismatches": latency_count_mismatches,
        "missing_world_trace_hashes": missing_trace_hashes,
        "untimed_environment_events": untimed_environment_events,
        "phase5_frozen_manifest_sha256": sha256_file(ROOT / "results/phase5_frozen_manifest.json"),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "raw_canonical_sha256": hashlib.sha256(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def run(progress=None) -> dict[str, object]:
    protocol = verify_protocol()
    protocol_hash = sha256_file(PROTOCOL_PATH)
    code_hashes = {path: sha256_file(ROOT / path) for path in CODE_PATHS}
    config_hashes = {path: sha256_file(ROOT / path) for path in CONFIG_PATHS}
    if OUTPUT_RAW.exists():
        raw = json.loads(OUTPUT_RAW.read_text(encoding="utf-8"))
        expected = (protocol_hash, code_hashes, config_hashes)
        actual = (raw.get("protocol_sha256"), raw.get("phase8_code_sha256"), raw.get("phase8_config_sha256"))
        if actual != expected:
            raise ValueError("existing parameter validation checkpoint does not match the frozen protocol")
        if (
            raw.get("status") == "complete"
            and OUTPUT_SUMMARY.is_file()
            and OUTPUT_AUDIT.is_file()
            and json.loads(OUTPUT_AUDIT.read_text(encoding="utf-8")).get("status") == "PASS"
        ):
            return {"status": "complete", "resumed": True, "raw": str(OUTPUT_RAW), "summary": str(OUTPUT_SUMMARY)}
    else:
        raw = {
            "schema_version": "1.0",
            "phase": "validation",
            "experiment_role": "independent_confirmatory_parameter_sensitivity",
            "analysis_status": "confirmatory",
            "status": "running",
            "protocol_sha256": protocol_hash,
            "protocol_path": str(PROTOCOL_PATH.relative_to(ROOT)),
            "experiment_plan_sha256": protocol["experiment_plan_sha256"],
            "plan_sha256": protocol["experiment_plan_sha256"],
            "phase5_frozen_manifest_sha256": protocol["phase5_manifest_sha256"],
            "phase5_source_sha256": protocol["phase5_source_sha256"],
            "phase8_code_sha256": code_hashes,
            "phase8_config_sha256": config_hashes,
            "seed_assignments": SENSITIVITY_SEEDS,
            "variant_ids": list(SENSITIVITY_VARIANT_IDS),
            "model_scope": "abstract_6g_research_simulation_not_real_network_test",
            "records": [],
        }
        _atomic_json(OUTPUT_RAW, raw)

    done = {(row["scenario_id"], int(row["seed"])) for row in raw["records"]}
    scenarios = p8._load_scenarios()
    total = sum(map(len, SENSITIVITY_SEEDS.values()))
    completed = len(done)
    for scene in p8.SCENARIO_ORDER:
        config = scenarios[scene]
        for seed in SENSITIVITY_SEEDS[scene]:
            if (scene, seed) in done:
                continue
            seeded_config = p8.replace(config, seeds=(seed,))
            trace = build_world_trace(seeded_config, seed)
            baseline = run_seed_experiment(seeded_config, seed, trace, include_d=True, include_bprime=True)
            record = p8._new_seed_record(scene, seed, seeded_config, baseline, trace, SENSITIVITY_VARIANTS)
            raw["records"].append(record)
            completed += 1
            _atomic_json(OUTPUT_RAW, raw)
            if progress:
                progress(completed, total, scene, seed)

    raw["status"] = "complete"
    raw["completed_seed_count"] = completed
    raw["actual_policy_run_count"] = sum(len(row["baseline_strategy_runs"]) + len(row["variant_runs"]) for row in raw["records"])
    _atomic_json(OUTPUT_RAW, raw)
    previous_test = p8._paired_test
    try:
        p8._paired_test = vectorized_paired_test
        summary = p8.summarize_raw(raw)
    finally:
        p8._paired_test = previous_test
    summary["cohort_note"] = "independent 20-seed-per-scenario parameter confirmation; not pooled with prior Phase 8 cohorts"
    summary["exact_sign_flip_backend"] = "NumPy vectorized exhaustive enumeration of all 2^20 sign assignments"
    _atomic_json(OUTPUT_SUMMARY, summary)
    audit = _audit_raw(raw)
    _atomic_json(OUTPUT_AUDIT, audit)
    if audit["status"] != "PASS":
        raise RuntimeError(f"parameter validation audit failed: {audit['issues']}")
    return {
        "status": "complete",
        "seed_count": completed,
        "policy_run_count": raw["actual_policy_run_count"],
        "raw": str(OUTPUT_RAW),
        "summary": str(OUTPUT_SUMMARY),
        "audit": str(OUTPUT_AUDIT),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze-protocol", action="store_true")
    mode.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.freeze_protocol:
        print(f"Frozen parameter validation protocol: {freeze_protocol()}")
        return 0
    started = time.perf_counter()

    def progress(done: int, total: int, scene: str, seed: int) -> None:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        print(f"[{now}] parameter confirmation: {done}/{total} seeds; {scene} seed={seed}", flush=True)

    result = run(progress)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Elapsed wall time: {time.perf_counter() - started:.3f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
