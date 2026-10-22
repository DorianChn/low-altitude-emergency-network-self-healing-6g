"""Auditable development and held-out experiments for Phase 11 baselines."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import Any, Callable

from .dynamic_config import load_dynamic_config
from .dynamic_world import build_world_trace
from .experiment import _stats
from .multi_uav import MultiUAVOptions
from .multi_uav_simulation import run_fleet_policy, run_single_bprime
from .phase10_experiments import (
    _git_head,
    _historical_hashes,
    _mcnemar_from_differences,
    _normalize_bprime,
    _paired_effect,
    _paired_sign_flip,
    _sha256,
    _verify_protocol as _verify_phase10_protocol,
)
from .phase8_experiments import _holm_adjust
from .phase11_simulation import run_phase11_policy


ROOT = Path(__file__).resolve().parents[2]
PLAN_REL = "configs/phase11/benchmark_plan.json"
PROTOCOL_REL = "configs/phase11/confirmation_protocol.json"
SCENARIO_ORDER = (
    "severe_persistent_faults",
    "dynamic_failures",
    "high_mobility_rescue",
    "high_load_backhaul_limit",
)
PHASE10_ARTIFACT_MANIFEST = "results/phase10_artifact_manifest.json"
PHASE10_CONFIRMATION = "results/phase10_confirmation_raw.json"
SOURCE_PATHS = (
    "src/lowalt6g/config.py",
    "src/lowalt6g/dynamic_config.py",
    "src/lowalt6g/dynamic_simulation.py",
    "src/lowalt6g/dynamic_world.py",
    "src/lowalt6g/engine.py",
    "src/lowalt6g/models.py",
    "src/lowalt6g/scenario.py",
    "src/lowalt6g/multi_uav.py",
    "src/lowalt6g/multi_uav_simulation.py",
    "src/lowalt6g/phase11_algorithms.py",
    "src/lowalt6g/phase11_simulation.py",
    "src/lowalt6g/phase11_experiments.py",
    "scripts/run_phase11_experiments.py",
    "tests/test_phase11.py",
)
POLICY_METRICS = (
    "rescue_user_service_success_rate",
    "normal_user_connection_success_rate",
    "user_connection_success_rate",
    "first_full_recovery_or_censor_time_s",
    "uav_energy_total_wh",
    "uav_rescue_user_seconds",
    "energy_wh_per_uav_rescue_user_hour",
    "average_latency_ms",
    "p95_latency_ms",
    "coordination_compute_total_ms",
    "coordination_compute_mean_ms",
    "candidate_evaluation_count",
    "search_node_count",
    "target_switch_count",
    "task_assignment_count",
    "uav_activation_count",
    "uav_task_allocation_decision_count",
    "uav_relayed_user_ticks_total",
    "base_station_mean_utilization",
    "uav_mean_utilization",
    "movement_without_assignment_km",
    "infeasible_decision_count",
    "decision_timeout_count",
    "resource_capacity_violation_count",
    "safety_action_count",
)


def load_plan() -> dict[str, Any]:
    return json.loads((ROOT / PLAN_REL).read_text(encoding="utf-8"))


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


def verify_phase10_baseline() -> dict[str, Any]:
    """Verify frozen Phase 10 files and actual held-out row/run/trace counts."""

    protocol = _verify_phase10_protocol()
    manifest_path = ROOT / PHASE10_ARTIFACT_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing: list[str] = []
    mismatched: list[str] = []
    for relative, expected in manifest["artifacts_sha256"].items():
        path = ROOT / relative
        if not path.is_file():
            missing.append(relative)
        elif _sha256(path) != expected:
            mismatched.append(relative)
    raw = json.loads((ROOT / PHASE10_CONFIRMATION).read_text(encoding="utf-8"))
    trace_mismatches: list[str] = []
    run_count = 0
    for row in raw.get("records", []):
        for key, run in row.get("strategy_runs", {}).items():
            run_count += 1
            if run.get("world_trace_sha256") != row.get("world_trace_sha256"):
                trace_mismatches.append(f"{row.get('scenario_id')}/{row.get('seed')}/{key}")
    problems = []
    if missing:
        problems.append(f"missing Phase 10 manifest artifacts: {missing}")
    if mismatched:
        problems.append(f"Phase 10 manifest hash mismatches: {mismatched}")
    if len(raw.get("records", [])) != 80:
        problems.append(f"Phase 10 confirmation row count is {len(raw.get('records', []))}, expected 80")
    if run_count != 400 or int(raw.get("policy_run_count", -1)) != 400:
        problems.append(f"Phase 10 confirmation has {run_count} decoded runs, expected 400")
    if trace_mismatches:
        problems.append(f"Phase 10 policy trace mismatches: {trace_mismatches[:5]}")
    if problems:
        raise RuntimeError("Phase 10 baseline audit failed: " + "; ".join(problems))
    return {
        "protocol_status": protocol.get("status"),
        "phase10_artifact_count": len(manifest["artifacts_sha256"]),
        "phase10_artifact_hash_mismatches": 0,
        "phase10_confirmation_seed_rows": len(raw["records"]),
        "phase10_confirmation_policy_runs": run_count,
        "phase10_matched_trace_mismatches": 0,
        "phase10_protocol_sha256": _sha256(ROOT / "configs/phase10/validation_protocol.json"),
        "phase10_confirmation_sha256": _sha256(ROOT / PHASE10_CONFIRMATION),
        "phase10_manifest_sha256": _sha256(manifest_path),
    }


def validate_seed_plan(plan: dict[str, Any]) -> None:
    partitions = plan["seed_assignments"]
    dev_ids: list[int] = []
    confirmation_ids: list[int] = []
    all_ids: list[int] = []
    for partition, collector in (("development", dev_ids), ("confirmation", confirmation_ids)):
        for scene in SCENARIO_ORDER:
            values = [int(value) for value in partitions[partition][scene]]
            minimum_count = 3 if partition == "development" else 20
            if len(values) != minimum_count or len(set(values)) != len(values):
                raise ValueError(f"invalid {partition} seed list for {scene}")
            collector.extend(values)
            all_ids.extend(values)
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("Phase 11 development/confirmation seeds overlap each other")
    if set(dev_ids) & set(confirmation_ids):
        raise ValueError("Phase 11 development and confirmation partitions overlap")
    # Phase 10's audit capped Phase 1-9 at 93509 and used Phase 10 seeds up to
    # 94419. The new partitions must exceed that audited ceiling.
    if min(all_ids) <= 94419:
        raise ValueError("Phase 11 seeds must be above the audited Phase 10 seed ceiling 94419")


def freeze_confirmation_protocol() -> dict[str, Any]:
    plan = load_plan()
    validate_seed_plan(plan)
    baseline = verify_phase10_baseline()
    development_path = ROOT / "results/phase11_development_raw.json"
    if not development_path.is_file():
        raise FileNotFoundError("run the Phase 11 development partition before freezing confirmation")
    development = json.loads(development_path.read_text(encoding="utf-8"))
    expected_development = 12 * len(plan["policies"])
    if development.get("status") != "complete" or len(development.get("records", [])) != expected_development:
        raise ValueError("Phase 11 development data is incomplete; refusing confirmation freeze")
    protocol_path = ROOT / PROTOCOL_REL
    if protocol_path.exists():
        raise FileExistsError(f"Phase 11 protocol already exists: {protocol_path}")
    protocol = {
        "schema_version": "1.0",
        "phase": "phase11_baseline_benchmark",
        "status": "frozen_before_confirmation",
        "protocol_revision": "H_marginal_I_assignment_J_bounded_beam_v1",
        "source_sha256": _combined_source_hash(),
        "documentation_sha256": _sha256(ROOT / "PHASE11_ALGORITHM_DESIGN.md"),
        "configuration_sha256": _configuration_hashes(plan),
        "phase10_baseline_audit": baseline,
        "phase10_protected_phase1_to_phase9_sha256": _historical_hashes(),
        "development_raw_sha256": _sha256(development_path),
        "development_seed_assignments": plan["seed_assignments"]["development"],
        "confirmation_seed_assignments": plan["seed_assignments"]["confirmation"],
        "confirmation_seed_count_per_scenario": 20,
        "confirmation_scenario_count": 4,
        "confirmation_policy_run_count_expected": 80 * len(plan["policies"]),
        "confirmation_protocol_note": (
            "Algorithms, search caps, candidate definitions, analysis plan, and seed assignment "
            "are frozen after development and before the held-out confirmation partition."
        ),
        "project_git_head": _git_head(),
        "working_tree_note": "The inherited Phase 1-10 workspace contains pre-existing modifications; no mixed changes are staged or committed.",
    }
    _atomic_write(protocol_path, protocol)
    return protocol


def verify_confirmation_protocol() -> dict[str, Any]:
    plan = load_plan()
    validate_seed_plan(plan)
    path = ROOT / PROTOCOL_REL
    if not path.is_file():
        raise FileNotFoundError("confirmation protocol has not been frozen")
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen_before_confirmation":
        raise ValueError("Phase 11 confirmation protocol is not frozen")
    if protocol.get("source_sha256") != _combined_source_hash():
        raise ValueError("Phase 11 source changed after confirmation freeze")
    if protocol.get("documentation_sha256") != _sha256(ROOT / "PHASE11_ALGORITHM_DESIGN.md"):
        raise ValueError("Phase 11 algorithm design document changed after confirmation freeze")
    if protocol.get("configuration_sha256") != _configuration_hashes(plan):
        raise ValueError("Phase 11 configuration changed after confirmation freeze")
    if protocol.get("development_raw_sha256") != _sha256(ROOT / "results/phase11_development_raw.json"):
        raise ValueError("Phase 11 development data changed after confirmation freeze")
    current_baseline = verify_phase10_baseline()
    frozen_baseline = protocol["phase10_baseline_audit"]
    for key in (
        "phase10_protocol_sha256", "phase10_confirmation_sha256", "phase10_manifest_sha256"
    ):
        if current_baseline.get(key) != frozen_baseline.get(key):
            raise ValueError(f"Phase 10 protected artifact changed after freeze: {key}")
    return protocol


def run_partition(
    partition: str,
    *,
    resume: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if partition not in {"development", "confirmation"}:
        raise ValueError("partition must be development or confirmation")
    plan = load_plan()
    validate_seed_plan(plan)
    protocol = verify_confirmation_protocol() if partition == "confirmation" else None
    seeds_by_scene = (
        protocol["confirmation_seed_assignments"] if protocol
        else plan["seed_assignments"]["development"]
    )
    suffix = "development" if partition == "development" else "confirmation"
    raw_path = ROOT / f"results/phase11_{suffix}_raw.json"
    summary_path = ROOT / f"results/phase11_{suffix}_summary.json"
    progress_path = ROOT / f"results/phase11_{suffix}_progress.jsonl"
    if raw_path.exists() or summary_path.exists():
        raise FileExistsError(f"Phase 11 {suffix} outputs already exist; refusing to overwrite")
    if progress_path.exists() and not resume:
        raise FileExistsError(f"Phase 11 progress file exists; pass resume=True to continue: {progress_path}")
    if not progress_path.exists():
        with progress_path.open("x", encoding="utf-8", newline="\n"):
            pass

    options = make_options(plan)
    configs = {
        scene: load_dynamic_config(ROOT / plan["scenario_config_paths"][scene])
        for scene in SCENARIO_ORDER
    }
    completed = _read_progress(progress_path)
    _ensure_progress_line_boundary(progress_path)
    source_hash = _combined_source_hash()
    config_hashes = _configuration_hashes(plan)
    if completed:
        for key, old in completed.items():
            if old.get("phase11_source_sha256") != source_hash:
                raise ValueError(f"resume source hash mismatch for {key}; use a fresh, separately named run")
            if old.get("phase11_configuration_sha256") != config_hashes:
                raise ValueError(f"resume configuration hash mismatch for {key}")
    expected = {
        (scene, int(seed), item["key"])
        for scene in SCENARIO_ORDER
        for seed in seeds_by_scene[scene]
        for item in plan["policies"]
    }
    unexpected = set(completed) - expected
    if unexpected:
        raise ValueError(f"progress file includes runs outside this partition: {sorted(unexpected)[:4]}")
    rows: list[dict[str, Any]] = list(completed.values())
    started = time.perf_counter()
    policy_specs = plan["policies"]
    with progress_path.open("a", encoding="utf-8", newline="\n") as output:
        for scene in SCENARIO_ORDER:
            config = configs[scene]
            for seed_value in seeds_by_scene[scene]:
                seed = int(seed_value)
                trace = build_world_trace(config, seed)
                for policy in policy_specs:
                    key = (scene, seed, policy["key"])
                    if key in completed:
                        if completed[key]["world_trace_sha256"] != trace.trace_sha256:
                            raise ValueError(f"resume trace mismatch for {key}")
                        continue
                    run = _run_policy(
                        policy, config, seed, trace, options, plan["fleet_model"]
                    )
                    if run.get("world_trace_sha256") != trace.trace_sha256:
                        raise ValueError(f"matched trace hash mismatch for {scene}/{seed}/{policy['key']}")
                    record = {
                        "schema_version": "1.0",
                        "scenario_id": scene,
                        "seed": seed,
                        "strategy_key": policy["key"],
                        "strategy_id": policy["strategy_id"],
                        "fleet_size": int(policy["fleet_size"]),
                        "world_trace_sha256": trace.trace_sha256,
                        "phase11_source_sha256": source_hash,
                        "phase11_configuration_sha256": config_hashes,
                        "duration_s": config.duration_s,
                        "time_step_s": config.time_step_s,
                        "metrics": run["metrics"],
                        "run": run,
                    }
                    output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                    output.flush()
                    os.fsync(output.fileno())
                    completed[key] = record
                    rows.append(record)
                if progress:
                    done = len(completed)
                    progress(f"{suffix} {scene} seed={seed}: {done}/{len(expected)} policy runs")

    if len(completed) != len(expected):
        raise RuntimeError(
            f"Phase 11 {suffix} incomplete: {len(completed)}/{len(expected)} runs; progress preserved"
        )
    rows.sort(key=lambda row: (
        SCENARIO_ORDER.index(row["scenario_id"]), row["seed"],
        next(index for index, item in enumerate(policy_specs) if item["key"] == row["strategy_key"]),
    ))
    raw = {
        "schema_version": "1.0",
        "phase": "phase11_baseline_benchmark",
        "experiment_role": "exploratory_development" if partition == "development" else "confirmatory_held_out",
        "partition": partition,
        "status": "complete",
        "model_scope": "abstract_6g_research_simulation_not_real_network_test",
        "policy_order": [item["key"] for item in policy_specs],
        "seed_assignments": seeds_by_scene,
        "scenario_count": len(SCENARIO_ORDER),
        "seed_count_total": sum(len(seeds_by_scene[scene]) for scene in SCENARIO_ORDER),
        "policy_run_count": len(rows),
        "policy_run_count_expected": len(expected),
        "project_git_head": _git_head(),
        "working_tree_status": "preexisting_phase1_to_phase10_changes_preserved_plus_phase11_work",
        "phase11_source_sha256": source_hash,
        "phase11_configuration_sha256": config_hashes,
        "phase11_protocol_sha256": _sha256(ROOT / PROTOCOL_REL) if protocol else None,
        "phase10_baseline_audit": verify_phase10_baseline(),
        "protected_phase1_to_phase9_sha256": _historical_hashes(),
        "runtime_environment": {
            "python": sys.version,
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "elapsed_wall_s": round(time.perf_counter() - started, 6),
        "records": rows,
        "analysis_note": "Per-run user-time latencies are conditional observations, not independent seed samples.",
    }
    _atomic_write(raw_path, raw)
    summary = summarize_raw(raw, plan)
    _atomic_write(summary_path, summary)
    if partition == "confirmation":
        create_confirmation_plots(summary, plan)
    return raw


def _run_policy(policy, config, seed, trace, options, model) -> dict[str, Any]:
    strategy = policy["strategy_id"]
    fleet = int(policy["fleet_size"])
    if strategy == "Bprime_static_grid_shared_safety":
        baseline = run_single_bprime(config, seed, trace)
        values = baseline.to_dict(include_latency_samples=True)
        values["world_trace_sha256"] = trace.trace_sha256
        return _normalize_bprime(config, values, fleet_size=fleet)
    if strategy in {"F_independent_greedy", "G_centralized_coordination"}:
        result = run_fleet_policy(
            config, seed, trace, fleet_size=fleet, strategy_id=strategy, options=options
        )
        _augment_phase10_fleet_metrics(result, config.time_step_s)
        return result
    return run_phase11_policy(
        config,
        seed,
        trace,
        fleet_size=fleet,
        strategy_id=strategy,
        options=options,
        assignment_beam_width=int(model["assignment_beam_width"]),
        assignment_max_expansions=int(model["assignment_max_expansions_per_decision"]),
        joint_beam_width=int(model["joint_beam_width"]),
    )


def _read_progress(path: Path) -> dict[tuple[str, int, str], dict[str, Any]]:
    completed: dict[tuple[str, int, str], dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # A process may have been interrupted during its final line.
                # Preserve it in the audit file and ignore only that incomplete
                # record; the completed raw JSON is rebuilt from valid rows.
                continue
            key = (row["scenario_id"], int(row["seed"]), row["strategy_key"])
            completed[key] = row
    return completed


def _ensure_progress_line_boundary(path: Path) -> None:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        end = stream.tell()
        if end == 0:
            return
        stream.seek(-1, os.SEEK_END)
        ends_with_newline = stream.read(1) == b"\n"
    if not ends_with_newline:
        with path.open("ab") as stream:
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())


def _augment_phase10_fleet_metrics(run: dict[str, Any], time_step_s: int) -> None:
    """Derive Phase 11 audit metrics only from F/G's existing execution logs."""

    metrics = run["metrics"]
    timeline = run.get("state_timeline", [])
    by_time = {int(row["time_s"]): row for row in timeline}
    service_by_id: dict[str, int] = {}
    station_utilization: list[float] = []
    uav_utilization: list[float] = []
    activation_count = 0
    active_before: dict[str, bool] = {}
    relayed_user_ticks = 0
    for state in timeline:
        current_ids: set[str] = set()
        for item in state.get("uavs", []):
            unit_id = str(item["uav_id"])
            served = item.get("served_user_ids", [])
            count = len(served)
            relayed_user_ticks += count
            service_by_id[unit_id] = service_by_id.get(unit_id, 0) + count
            active = bool(item.get("active"))
            if active and not active_before.get(unit_id, False):
                activation_count += 1
            active_before[unit_id] = active
            if count:
                current_ids.add(unit_id)
        station = [
            float(value) for key, value in state.get("resource_utilization", {}).items()
            if key.startswith("station:")
        ]
        uav = [
            float(value) for key, value in state.get("resource_utilization", {}).items()
            if key.startswith("uav:")
        ]
        if station:
            station_utilization.append(statistics.fmean(station))
        if uav:
            uav_utilization.append(statistics.fmean(uav))
    movement_without_assignment = 0.0
    for event in run.get("event_log", []):
        if event.get("event_type") != "uav_action_execution":
            continue
        prior = by_time.get(int(event["time_s"]) - time_step_s)
        if prior is None:
            continue
        assigned = next(
            (
                item.get("served_user_ids", [])
                for item in prior.get("uavs", [])
                if item.get("uav_id") == event.get("uav_id")
            ),
            [],
        )
        if not assigned:
            movement_without_assignment += float(event.get("moved_km", 0.0))
    allocation_events = 0
    for event in run.get("event_log", []):
        if event.get("event_type") != "fleet_decision":
            continue
        state = by_time.get(int(event["time_s"]))
        if state is not None:
            allocation_events += sum(bool(item.get("served_user_ids")) for item in state.get("uavs", []))
    metrics.update(
        {
            "search_node_count": int(metrics.get("candidate_evaluation_count", 0))
            + int(metrics.get("collision_rejection_count", 0)),
            "uav_activation_count": activation_count,
            "uav_task_allocation_decision_count": allocation_events,
            "uav_relayed_user_ticks_total": relayed_user_ticks,
            "uav_relayed_user_ticks_by_id": service_by_id,
            "base_station_mean_utilization": statistics.fmean(station_utilization) if station_utilization else 0.0,
            "uav_mean_utilization": statistics.fmean(uav_utilization) if uav_utilization else 0.0,
            "movement_without_assignment_km": movement_without_assignment,
        }
    )


def summarize_raw(raw: dict[str, Any], plan: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = plan or load_plan()
    records = raw["records"]
    by_scene_policy: dict[str, dict[str, list[dict[str, Any]]]] = {
        scene: {policy["key"]: [] for policy in plan["policies"]}
        for scene in SCENARIO_ORDER
    }
    for record in records:
        by_scene_policy[record["scenario_id"]][record["strategy_key"]].append(record)
    scene_summaries: dict[str, Any] = {}
    for scene in SCENARIO_ORDER:
        scene_summaries[scene] = {
            "seed_count": len({record["seed"] for record in records if record["scenario_id"] == scene}),
            "policies": {
                policy["key"]: _summarize_policy(by_scene_policy[scene][policy["key"]])
                for policy in plan["policies"]
            },
            "paired_comparisons": {},
        }
        scene_summaries[scene]["paired_comparisons"] = _paired_comparisons(
            by_scene_policy[scene], plan["policies"]
        )
    all_by_policy = {
        policy["key"]: [record for record in records if record["strategy_key"] == policy["key"]]
        for policy in plan["policies"]
    }
    pooled = {
        "seed_count": len({(record["scenario_id"], record["seed"]) for record in records}),
        "policies": {
            policy["key"]: _summarize_policy(all_by_policy[policy["key"]])
            for policy in plan["policies"]
        },
        "interpretation": "Pooled descriptive statistics only; the four scene-specific results remain primary.",
    }
    comparison_families: dict[str, list[dict[str, Any]]] = {
        "rescue_service_rate": [], "first_full_recovery": [], "sustained_30s_recovery": []
    }
    for scene, values in scene_summaries.items():
        for name, comparison in values["paired_comparisons"].items():
            context = {"scenario_id": scene, "contrast": name}
            for family, field in (
                ("rescue_service_rate", "rescue_user_service_success_rate"),
                ("first_full_recovery", "first_full_recovery_success"),
                ("sustained_30s_recovery", "sustained_30s_recovery_success"),
            ):
                p = comparison["metrics"][field].get("p_exact_two_sided")
                if p is not None:
                    comparison_families[family].append(
                        {**context, "p_exact_two_sided": p, "target": comparison["metrics"][field]}
                    )
    for tests in comparison_families.values():
        _holm_adjust(tests)
        for item in tests:
            item["target"]["p_holm_adjusted"] = item.get("p_holm_adjusted")
            item["target"]["holm_family_size"] = item.get("holm_family_size")
    return {
        "schema_version": "1.0",
        "phase": "phase11_baseline_benchmark",
        "partition": raw["partition"],
        "experiment_role": raw["experiment_role"],
        "status": raw["status"],
        "seed_count_total": raw["seed_count_total"],
        "policy_run_count": raw["policy_run_count"],
        "statistics": {
            "continuous": "per-run observations; mean, sample SD, median, Student-t 95% CI",
            "paired": "same scenario and seed differences; Student-t 95% CI, Cohen dz and Hedges gz",
            "rescue_service_test": "two-sided exact sign-flip; Holm adjusted across 120 predeclared scene/contrast tests",
            "binary_recovery_test": "exact McNemar; Holm adjusted separately for first-full and sustained recovery across 120 tests each",
            "recovery_time": "success count/total and conditional success-time distribution; all-run censored endpoint uses scenario duration for failures",
            "latency": "conditional per-policy successful user-time samples; per-run means/P95 summarized across seeds; sample counts exposed",
        },
        "scenarios": scene_summaries,
        "overall_pooled_descriptive": pooled,
        "comparison_family_sizes": {
            key: len(value) for key, value in comparison_families.items()
        },
        "model_scope": raw["model_scope"],
    }


def _summarize_policy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for metric in POLICY_METRICS:
        values = [
            float(record["metrics"][metric])
            for record in rows
            if record["metrics"].get(metric) is not None
        ]
        metrics[metric] = _stats(values, include_ci=True)
    first_successes = sum(int(record["metrics"].get("first_full_recovery_success", 0)) for record in rows)
    sustained_successes = sum(int(record["metrics"].get("sustained_30s_recovery_success", 0)) for record in rows)
    successful_first_times = [
        float(record["metrics"]["first_full_recovery_time_s"])
        for record in rows if record["metrics"].get("first_full_recovery_time_s") is not None
    ]
    successful_sustained_times = [
        float(record["metrics"]["sustained_30s_recovery_time_s"])
        for record in rows if record["metrics"].get("sustained_30s_recovery_time_s") is not None
    ]
    latency_sample_count = sum(int(record["metrics"].get("latency_sample_count", 0)) for record in rows)
    return {
        "run_count": len(rows),
        "metrics": metrics,
        "recovery": {
            "first_full_successes": first_successes,
            "first_full_total": len(rows),
            "first_full_unrecovered": len(rows) - first_successes,
            "sustained_30s_successes": sustained_successes,
            "sustained_30s_total": len(rows),
            "sustained_30s_unrecovered": len(rows) - sustained_successes,
            "first_full_time_given_success": _stats(successful_first_times, include_ci=True),
            "sustained_time_given_success": _stats(successful_sustained_times, include_ci=True),
            "all_run_first_full_or_censor": _stats(
                [float(record["metrics"]["first_full_recovery_or_censor_time_s"]) for record in rows],
                include_ci=True,
            ),
        },
        "latency_sample_count_total": latency_sample_count,
        "latency_sample_counts_by_seed": {
            str(record["seed"]): int(record["metrics"].get("latency_sample_count", 0))
            for record in rows
        },
    }


def _paired_comparisons(
    by_policy: dict[str, list[dict[str, Any]]], policies: list[dict[str, Any]]
) -> dict[str, Any]:
    by_key = {policy["key"]: policy for policy in policies}
    multi = [policy for policy in policies if policy["strategy_id"] != "Bprime_static_grid_shared_safety"]
    contrasts: list[tuple[str, str]] = []
    for fleet in (2, 3):
        group = [policy for policy in multi if int(policy["fleet_size"]) == fleet]
        contrasts.extend(
            (left["key"], right["key"])
            for left, right in itertools.combinations(group, 2)
        )
    baseline = next(
        policy["key"] for policy in policies
        if policy["strategy_id"] == "Bprime_static_grid_shared_safety"
    )
    contrasts.extend((policy["key"], baseline) for policy in multi)
    results: dict[str, Any] = {}
    index: dict[str, dict[int, dict[str, Any]]] = {
        key: {int(row["seed"]): row for row in rows}
        for key, rows in by_policy.items()
    }
    for left_key, right_key in contrasts:
        left = index[left_key]
        right = index[right_key]
        seeds = sorted(set(left) & set(right))
        name = f"{left_key}__minus__{right_key}"
        fields: dict[str, Any] = {}
        rescue_differences = [
            float(left[seed]["metrics"]["rescue_user_service_success_rate"])
            - float(right[seed]["metrics"]["rescue_user_service_success_rate"])
            for seed in seeds
        ]
        fields["rescue_user_service_success_rate"] = {
            **_paired_effect(rescue_differences),
            **_paired_sign_flip(rescue_differences),
        }
        for metric in ("first_full_recovery_success", "sustained_30s_recovery_success"):
            differences = [
                float(left[seed]["metrics"].get(metric, 0))
                - float(right[seed]["metrics"].get(metric, 0))
                for seed in seeds
            ]
            left_success = sum(int(left[seed]["metrics"].get(metric, 0)) for seed in seeds)
            right_success = sum(int(right[seed]["metrics"].get(metric, 0)) for seed in seeds)
            fields[metric] = {
                **_paired_effect(differences),
                "left_successes": left_success,
                "right_successes": right_success,
                "total_pairs": len(seeds),
                "left_failures": len(seeds) - left_success,
                "right_failures": len(seeds) - right_success,
                **_mcnemar_from_differences(differences),
            }
        results[name] = {
            "left_policy": left_key,
            "right_policy": right_key,
            "paired_seed_count": len(seeds),
            "metrics": fields,
        }
    return results


def create_confirmation_plots(summary: dict[str, Any], plan: dict[str, Any] | None = None) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plan = plan or load_plan()
    output_dir = ROOT / "plots/phase11"
    output_dir.mkdir(parents=True, exist_ok=True)
    policies = plan["policies"]
    labels = [
        "B′-1" if policy["strategy_id"] == "Bprime_static_grid_shared_safety"
        else f"{policy['strategy_id'][0]}{policy['fleet_size']}"
        for policy in policies
    ]
    scenes = summary["scenarios"]
    fig, axes = plt.subplots(2, 2, figsize=(18, 10), sharey=True)
    for axis, scene in zip(axes.flat, SCENARIO_ORDER, strict=True):
        means = [
            scenes[scene]["policies"][policy["key"]]["metrics"]["rescue_user_service_success_rate"]["mean"]
            for policy in policies
        ]
        cis = [
            scenes[scene]["policies"][policy["key"]]["metrics"]["rescue_user_service_success_rate"]["mean_ci95_t"]
            for policy in policies
        ]
        errors = [
            [mean - ci[0] if ci else 0.0 for mean, ci in zip(means, cis, strict=True)],
            [ci[1] - mean if ci else 0.0 for mean, ci in zip(means, cis, strict=True)],
        ]
        axis.bar(np.arange(len(policies)), means, yerr=errors, capsize=2, color=_policy_colors(policies))
        axis.set_title(scene.replace("_", " "))
        axis.set_xticks(np.arange(len(labels)), labels, rotation=45, ha="right")
        axis.set_ylim(0, 1.0)
        axis.grid(axis="y", alpha=0.2)
    axes[0, 0].set_ylabel("Rescue user-time service success rate")
    axes[1, 0].set_ylabel("Rescue user-time service success rate")
    fig.suptitle("Phase 11 confirmation: rescue service by disaster scene\nmean and 95% per-policy t intervals")
    fig.tight_layout()
    rescue_png = output_dir / "confirmation_rescue_service.png"
    rescue_svg = output_dir / "confirmation_rescue_service.svg"
    fig.savefig(rescue_png, dpi=170, bbox_inches="tight")
    fig.savefig(rescue_svg, bbox_inches="tight")
    plt.close(fig)

    colors = {
        "Bprime_static_grid_shared_safety": "#e45756",
        "F_independent_greedy": "#4c78a8",
        "G_centralized_coordination": "#f2cf5b",
        "H_marginal_rescue_greedy": "#72b7b2",
        "I_constrained_user_assignment": "#b279a2",
        "J_budgeted_joint_beam": "#ff9da6",
    }
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    for axis, scene in zip(axes.flat, SCENARIO_ORDER, strict=True):
        for policy in policies:
            metrics = scenes[scene]["policies"][policy["key"]]["metrics"]
            compute = metrics["coordination_compute_total_ms"]["mean"]
            rate = metrics["rescue_user_service_success_rate"]["mean"]
            fleet = int(policy["fleet_size"])
            marker = "o" if fleet <= 2 else "s"
            axis.scatter(
                compute, rate,
                color=colors[policy["strategy_id"]], marker=marker, s=72,
                edgecolors="#222222", linewidths=0.45,
            )
            short = "B′" if fleet == 1 else f"{policy['strategy_id'][0]}{fleet}"
            axis.annotate(short, (compute, rate), xytext=(4, 4), textcoords="offset points", fontsize=8)
        axis.set_title(scene.replace("_", " "))
        axis.set_xlabel("Mean decision computation per run (ms)")
        axis.set_ylabel("Rescue user-time service success rate")
        axis.grid(alpha=0.2)
        axis.set_ylim(0, 1.0)
    fig.suptitle("Phase 11 confirmation: computation cost and rescue-service performance")
    fig.tight_layout()
    efficiency_png = output_dir / "confirmation_compute_vs_service.png"
    efficiency_svg = output_dir / "confirmation_compute_vs_service.svg"
    fig.savefig(efficiency_png, dpi=170, bbox_inches="tight")
    fig.savefig(efficiency_svg, bbox_inches="tight")
    plt.close(fig)
    return [
        str(rescue_png.relative_to(ROOT)).replace("\\", "/"),
        str(rescue_svg.relative_to(ROOT)).replace("\\", "/"),
        str(efficiency_png.relative_to(ROOT)).replace("\\", "/"),
        str(efficiency_svg.relative_to(ROOT)).replace("\\", "/"),
    ]


def _policy_colors(policies: list[dict[str, Any]]) -> list[str]:
    color = {
        "Bprime_static_grid_shared_safety": "#e45756",
        "F_independent_greedy": "#4c78a8",
        "G_centralized_coordination": "#f2cf5b",
        "H_marginal_rescue_greedy": "#72b7b2",
        "I_constrained_user_assignment": "#b279a2",
        "J_budgeted_joint_beam": "#ff9da6",
    }
    return [color[policy["strategy_id"]] for policy in policies]


def _combined_source_hash() -> str:
    digest = hashlib.sha256()
    for relative in SOURCE_PATHS:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"missing Phase 11 source for freeze: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


def _configuration_hashes(plan: dict[str, Any]) -> dict[str, str]:
    paths = {PLAN_REL}
    paths.update(plan["scenario_config_paths"].values())
    return {relative: _sha256(ROOT / relative) for relative in sorted(paths)}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
