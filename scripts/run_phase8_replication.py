"""Run an independent 20-seed-per-scene Phase 8 replication cohort.

This cohort is deliberately separate from the already completed 10-seed
Phase 8 validation batch. It reuses the frozen algorithms and contrast set,
but has new seed IDs, its own immutable protocol, checkpoint and outputs.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lowalt6g import phase8_experiments as p8  # noqa: E402
from lowalt6g.dynamic_simulation import run_seed_experiment  # noqa: E402
from lowalt6g.dynamic_world import build_world_trace  # noqa: E402
from lowalt6g.experiment import _stats  # noqa: E402


REPLICATION_SEEDS = {
    "severe_persistent_faults": tuple(range(90400, 90420)),
    "dynamic_failures": tuple(range(90500, 90520)),
    "high_mobility_rescue": tuple(range(90600, 90620)),
    "high_load_backhaul_limit": tuple(range(90700, 90720)),
}
OUTPUT_RAW = ROOT / "results/phase8_replication_raw.json"
OUTPUT_SUMMARY = ROOT / "results/phase8_replication_summary.json"
PROTOCOL_PATH = ROOT / "configs/phase8/replication_protocol.json"
REPLICATION_CODE_PATHS = (*p8.PHASE8_CODE_PATHS, "scripts/run_phase8_replication.py")
REPLICATION_CONFIG_PATHS = (
    *p8.PHASE8_CONFIG_PATHS,
    "configs/phase8/validation_protocol.json",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_replication_seeds() -> None:
    selected = [seed for values in REPLICATION_SEEDS.values() for seed in values]
    if len(selected) != 80 or len(set(selected)) != 80:
        raise ValueError("replication cohort must contain 80 unique seeds")
    earlier = {
        *p8.HISTORICAL_SEEDS,
        *(seed for values in p8.DEVELOPMENT_SEEDS.values() for seed in values),
        *(seed for values in p8.VALIDATION_SEEDS.values() for seed in values),
    }
    if set(selected) & earlier:
        raise ValueError("replication seeds overlap historical or Phase 8 seed partitions")


def freeze_protocol() -> Path:
    p8.ensure_plan_file()
    _validate_replication_seeds()
    if PROTOCOL_PATH.exists():
        raise FileExistsError(f"refusing to replace frozen replication protocol: {PROTOCOL_PATH}")
    initial_raw = ROOT / "results/phase8_validation_raw.json"
    initial_summary = ROOT / "results/phase8_validation_summary.json"
    if not initial_raw.is_file() or not initial_summary.is_file():
        raise FileNotFoundError("the first Phase 8 validation batch must be complete before replication freeze")
    if json.loads(initial_raw.read_text(encoding="utf-8")).get("status") != "complete":
        raise ValueError("the first Phase 8 validation batch is incomplete")
    protocol = {
        "schema_version": "1.0",
        "status": "frozen_before_replication_run",
        "study_design_note": (
            "A separate 20-seed-per-scene independent replication cohort was added after the initial 10-seed batch. "
            "The original batch is retained separately; no outcomes from it were used to change algorithms or variant IDs."
        ),
        "sample_size_rationale": (
            "At n=10, the minimum two-sided exact sign-flip p is 2/2^10=0.001953; with 520 predeclared efficacy hypotheses, "
            "no p-value can survive Holm at 0.05. This independent cohort uses 20 new seeds per scenario."
        ),
        "experiment_plan_sha256": sha256_file(ROOT / "configs/phase8/experiment_plan.json"),
        "initial_validation_protocol_sha256": sha256_file(ROOT / "configs/phase8/validation_protocol.json"),
        "initial_validation_raw_sha256": sha256_file(initial_raw),
        "initial_validation_summary_sha256": sha256_file(initial_summary),
        "phase5_manifest_sha256": sha256_file(ROOT / "results/phase5_frozen_manifest.json"),
        "phase5_source_sha256": p8.verify_phase5_freeze(),
        "code_sha256": {path: sha256_file(ROOT / path) for path in REPLICATION_CODE_PATHS},
        "configuration_sha256": {path: sha256_file(ROOT / path) for path in REPLICATION_CONFIG_PATHS},
        "seed_map": REPLICATION_SEEDS,
        "seeds_per_scenario": 20,
        "variant_ids": list(p8.VALIDATION_VARIANTS[i].variant_id for i in range(len(p8.VALIDATION_VARIANTS))),
        "baseline_strategies": list(p8.BASELINE_ORDER),
        "policy_runs_expected": 80 * (len(p8.BASELINE_ORDER) + len(p8.VALIDATION_VARIANTS)),
        "analysis": {
            "pairing": "same seed and same generated DynamicWorldTrace for A/B/Bprime/C/D and each Phase 8 variant",
            "continuous_tests": "exact two-sided sign-flip test over all 2^20 assignments; NumPy vectorized enumeration is numerically equivalent to the frozen Phase 8 method",
            "binary_tests": "exact McNemar/binomial tail over discordant paired seed outcomes",
            "multiplicity": "Holm step-down separately across the same frozen efficacy and resource/cost families",
            "latency": "conditional on each policy's own successful user-time samples; counts and pooled mean/P95 only, no paired latency test",
            "failures": "unrecovered and non-sustained runs remain in denominators; censoring time uses the configured 600 s horizon",
        },
        "model_scope": "abstract_6g_research_simulation_not_real_network_test",
        "git_head": p8._git_head(),
    }
    PROTOCOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROTOCOL_PATH.write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return PROTOCOL_PATH


def _verify_protocol() -> dict[str, object]:
    p8.ensure_plan_file()
    _validate_replication_seeds()
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    if protocol["experiment_plan_sha256"] != sha256_file(ROOT / "configs/phase8/experiment_plan.json"):
        raise ValueError("replication experiment plan changed after protocol freeze")
    if protocol["initial_validation_raw_sha256"] != sha256_file(ROOT / "results/phase8_validation_raw.json"):
        raise ValueError("initial validation raw data changed after replication protocol freeze")
    if protocol["phase5_source_sha256"] != p8.verify_phase5_freeze():
        raise ValueError("Phase 5 frozen sources changed")
    for path, expected in protocol["code_sha256"].items():
        if sha256_file(ROOT / path) != expected:
            raise ValueError(f"replication code changed after freeze: {path}")
    for path, expected in protocol["configuration_sha256"].items():
        if sha256_file(ROOT / path) != expected:
            raise ValueError(f"replication configuration changed after freeze: {path}")
    return protocol


def exact_sign_flip_p(differences: list[float]) -> float:
    if not differences:
        return 1.0
    totals = np.array([0.0], dtype=np.float64)
    for value in differences:
        totals = np.concatenate((totals + value, totals - value))
    observed = abs(sum(differences))
    extreme = np.count_nonzero(np.abs(totals) >= observed - 1e-12)
    return float(extreme / totals.size)


def vectorized_paired_test(
    differences: list[float], *, binary: bool, inferential: bool
) -> dict[str, object]:
    """Drop-in equivalent of Phase 8's paired test, with vectorized exact enumeration."""
    n = len(differences)
    if n == 0:
        return {"n": 0, "mean_difference": None, "ci95_t": None, "cohen_dz": None, "hedges_gz": None, "p_exact_two_sided": None}
    mean = statistics.fmean(differences)
    stats = _stats(differences, include_ci=True)
    sd = statistics.stdev(differences) if n > 1 else 0.0
    dz = mean / sd if sd > 0 else (math.copysign(math.inf, mean) if mean else 0.0)
    correction = 1.0 - 3.0 / max(4.0 * (n - 1) - 1.0, 1.0)
    if binary:
        positive = sum(value > 0 for value in differences)
        negative = sum(value < 0 for value in differences)
        discordant = positive + negative
        tail = min(positive, negative)
        p = min(1.0, 2.0 * sum(math.comb(discordant, index) for index in range(tail + 1)) / (2**discordant)) if discordant else 1.0
        test_name = "exact_mcnemar_binomial"
    else:
        if n > 20:
            raise ValueError("exact sign-flip implementation is capped at 20 paired seeds")
        p = exact_sign_flip_p(differences)
        test_name = "exact_sign_flip_randomization"
    return {
        "n": n,
        "mean_difference": round(mean, 8),
        "sample_sd_difference": round(sd, 8) if n > 1 else None,
        "median_difference": round(statistics.median(differences), 8),
        "ci95_t": stats.get("mean_ci95_t"),
        "cohen_dz": round(dz, 8) if math.isfinite(dz) else None,
        "hedges_gz": round(dz * correction, 8) if math.isfinite(dz) else None,
        "p_exact_two_sided": round(p, 8) if inferential else None,
        "test": test_name if inferential else "descriptive_no_confirmatory_test",
    }


def _atomic_json(path: Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    temp.replace(path)


def run_replication(progress=None) -> dict[str, object]:
    protocol = _verify_protocol()
    protocol_sha = sha256_file(PROTOCOL_PATH)
    code_hashes = {path: sha256_file(ROOT / path) for path in REPLICATION_CODE_PATHS}
    config_hashes = {path: sha256_file(ROOT / path) for path in REPLICATION_CONFIG_PATHS}
    role = "independent_confirmatory_replication_no_tuning"
    if OUTPUT_RAW.exists():
        state = json.loads(OUTPUT_RAW.read_text(encoding="utf-8"))
        if (
            state.get("protocol_sha256") != protocol_sha
            or state.get("phase8_code_sha256") != code_hashes
            or state.get("phase8_config_sha256") != config_hashes
            or state.get("experiment_role") != role
        ):
            raise ValueError("existing replication checkpoint does not match the frozen protocol")
        if state.get("status") == "complete":
            return {"raw": str(OUTPUT_RAW), "summary": str(OUTPUT_SUMMARY), "status": "complete", "resumed": True}
    else:
        state = {
            "schema_version": "1.0",
            "phase": "validation",
            "experiment_role": role,
            "status": "running",
            "protocol_sha256": protocol_sha,
            "protocol_path": str(PROTOCOL_PATH.relative_to(ROOT)),
            "experiment_plan_sha256": protocol["experiment_plan_sha256"],
            "initial_validation_raw_sha256": protocol["initial_validation_raw_sha256"],
            "phase5_frozen_manifest_sha256": protocol["phase5_manifest_sha256"],
            "phase5_source_sha256": protocol["phase5_source_sha256"],
            "phase8_code_sha256": code_hashes,
            "phase8_config_sha256": config_hashes,
            "seed_assignments": REPLICATION_SEEDS,
            "variant_ids": [variant.variant_id for variant in p8.VALIDATION_VARIANTS],
            "model_scope": "abstract_6g_research_simulation_not_real_network_test",
            "records": [],
        }
        _atomic_json(OUTPUT_RAW, state)

    done = {(row["scenario_id"], int(row["seed"])) for row in state["records"]}
    configs = p8._load_scenarios()
    total = sum(len(seeds) for seeds in REPLICATION_SEEDS.values())
    completed = len(done)
    for scene in p8.SCENARIO_ORDER:
        config = configs[scene]
        for seed in REPLICATION_SEEDS[scene]:
            if (scene, seed) in done:
                continue
            seeded_config = p8.replace(config, seeds=(seed,))
            trace = build_world_trace(seeded_config, seed)
            baseline = run_seed_experiment(seeded_config, seed, trace, include_d=True, include_bprime=True)
            record = p8._new_seed_record(scene, seed, seeded_config, baseline, trace, p8.VALIDATION_VARIANTS)
            state["records"].append(record)
            completed += 1
            _atomic_json(OUTPUT_RAW, state)
            if progress:
                progress(completed, total, scene, seed)
    state["status"] = "complete"
    state["completed_seed_count"] = completed
    state["actual_policy_run_count"] = sum(
        len(row["baseline_strategy_runs"]) + len(row["variant_runs"]) for row in state["records"]
    )
    _atomic_json(OUTPUT_RAW, state)

    original_paired_test = p8._paired_test
    try:
        p8._paired_test = vectorized_paired_test
        summary = p8.summarize_raw(state)
    finally:
        p8._paired_test = original_paired_test
    summary["cohort_note"] = "independent 20-seed-per-scenario replication; not pooled with initial 10-seed Phase 8 batch"
    summary["exact_sign_flip_backend"] = "NumPy vectorized exhaustive enumeration of all 2^20 sign assignments"
    _atomic_json(OUTPUT_SUMMARY, summary)
    return {
        "raw": str(OUTPUT_RAW),
        "summary": str(OUTPUT_SUMMARY),
        "status": "complete",
        "seed_count": completed,
        "policy_run_count": state["actual_policy_run_count"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze-protocol", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--charts-only", action="store_true")
    args = parser.parse_args()
    if args.freeze_protocol:
        print(f"Frozen independent replication protocol: {freeze_protocol()}")
        return 0
    if args.charts_only:
        _verify_protocol()
        from lowalt6g.phase8_charts import write_phase8_charts

        paths = write_phase8_charts(OUTPUT_RAW, ROOT / "plots/phase8_replication")
        print(json.dumps({"charts": [str(path) for path in paths]}, ensure_ascii=False, indent=2))
        return 0
    started = time.perf_counter()

    def progress(completed: int, total: int, scene: str, seed: int) -> None:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        print(f"[{now}] replication: {completed}/{total} seeds; {scene} seed={seed}", flush=True)

    result = run_replication(progress=progress)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    from lowalt6g.phase8_charts import write_phase8_charts

    paths = write_phase8_charts(OUTPUT_RAW, ROOT / "plots/phase8_replication")
    print(json.dumps({"charts": [str(path) for path in paths]}, ensure_ascii=False, indent=2))
    print(f"Elapsed wall time: {time.perf_counter() - started:.3f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
