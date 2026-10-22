"""Frozen-protocol multi-hazard experiment runner for Phase 5."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Callable

from .dynamic_config import load_dynamic_config
from .experiment import PHASE5_STRATEGY_ORDER, run_dynamic_benchmark


SCENARIO_FILES = (
    "severe_persistent_faults.toml",
    "dynamic_failures.toml",
    "high_mobility_rescue.toml",
    "high_load_backhaul_limit.toml",
)
SOURCE_FILES = (
    "config.py",
    "dynamic_config.py",
    "dynamic_world.py",
    "dynamic_simulation.py",
    "energy_budget.py",
    "engine.py",
    "optimizer.py",
    "experiment.py",
    "charts.py",
    "phase5.py",
    "cli.py",
    "api.py",
)
HISTORICAL_SEEDS = set(range(2026, 2046)) | set(range(3000, 3005)) | set(range(4000, 4020))


def run_phase5_suite(
    config_dir: str | Path,
    results_dir: str | Path,
    plots_dir: str | Path,
    *,
    phase: str = "both",
    progress: Callable[[str, int, int, int], None] | None = None,
) -> dict[str, object]:
    """Run development, freeze the exact protocol, then validate held-out seeds.

    A validation-only run refuses to proceed when any source or scenario file
    differs from the manifest produced after development.
    """
    if phase not in {"development", "validation", "both"}:
        raise ValueError("phase must be development, validation, or both")
    config_root = Path(config_dir).resolve()
    output_root = Path(results_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    configs = {
        Path(filename).stem: (config_root / filename).resolve()
        for filename in SCENARIO_FILES
    }
    loaded = {name: load_dynamic_config(path) for name, path in configs.items()}
    _validate_seed_partitions(loaded)

    manifest_path = output_root / "phase5_frozen_manifest.json"
    if phase in {"development", "both"}:
        for scene_id, config in loaded.items():
            result = _run_partition(
                scene_id,
                config,
                config.development_seeds,
                "development_parameter_check_not_validation",
                progress,
            )
            _write_json(output_root / f"phase5_development_{scene_id}.json", result)
        manifest = _build_manifest(config_root, configs, loaded)
        _write_json(manifest_path, manifest)
    if phase == "development":
        return {
            "phase": "development",
            "development_files": [
                str(output_root / f"phase5_development_{scene_id}.json")
                for scene_id in loaded
            ],
            "frozen_manifest": str(manifest_path),
            "frozen_manifest_sha256": _file_sha256(manifest_path),
            "held_out_validation_started": False,
        }

    current_manifest = _build_manifest(config_root, configs, loaded)
    if phase == "validation":
        if not manifest_path.is_file():
            raise ValueError("Phase 5 validation requires a development freeze manifest")
        frozen_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if frozen_manifest != current_manifest:
            raise ValueError(
                "Phase 5 source/configuration differs from the development freeze; "
                "rerun development and freeze before held-out validation"
            )

    manifest_sha256 = _file_sha256(manifest_path)
    validation_results: dict[str, dict[str, object]] = {}
    for scene_id, config in loaded.items():
        result = _run_partition(
            scene_id,
            config,
            config.validation_seeds,
            "held_out_validation_frozen_algorithm",
            progress,
        )
        result["frozen_manifest_sha256"] = manifest_sha256
        validation_path = output_root / f"phase5_validation_{scene_id}.json"
        _write_json(validation_path, result)
        validation_results[scene_id] = result

    from .charts import write_phase5_comparison_charts

    chart_paths = write_phase5_comparison_charts(validation_results, plots_dir)
    summary = {
        "schema_version": "1.0",
        "phase": "validation",
        "model_scope": "abstract_6g_research_simulation_not_real_network_test",
        "frozen_manifest_sha256": manifest_sha256,
        "strategy_order": list(PHASE5_STRATEGY_ORDER),
        "scenarios": {
            scene_id: {
                "validation_seed_count": len(config.validation_seeds),
                "validation_seeds": list(config.validation_seeds),
                "effective_config_sha256": result["reproducibility"]["effective_config_sha256"],
                "aggregate": result["aggregate"],
                "paired_differences": result["paired_differences"],
                "raw_seed_results": f"phase5_validation_{scene_id}.json",
            }
            for scene_id, result in validation_results.items()
            for config in (loaded[scene_id],)
        },
        "artifacts": {"charts": [str(path) for path in chart_paths]},
        "statistical_scope": (
            "95% intervals quantify variation over configured simulation seeds only; "
            "they are not confidence intervals for field networks."
        ),
    }
    summary_path = output_root / "phase5_validation_summary.json"
    _write_json(summary_path, summary)
    return {
        "phase": "validation",
        "validation_summary": str(summary_path),
        "validation_files": [
            str(output_root / f"phase5_validation_{scene_id}.json")
            for scene_id in validation_results
        ],
        "charts": [str(path) for path in chart_paths],
        "frozen_manifest_sha256": manifest_sha256,
        "scenarios": summary["scenarios"],
    }


def _run_partition(
    scene_id: str,
    config,
    seeds: tuple[int, ...],
    role: str,
    progress: Callable[[str, int, int, int], None] | None,
) -> dict[str, object]:
    minimum = 5 if role.startswith("development") else 20
    if len(seeds) < minimum:
        raise ValueError(f"{scene_id} requires at least {minimum} seeds for {role}")
    selected = replace(config, seeds=seeds)
    result = run_dynamic_benchmark(
        selected,
        minimum_seed_count=minimum,
        include_d=True,
        include_bprime=True,
        progress=(
            (lambda index, total, seed: progress(scene_id, index, total, seed))
            if progress is not None
            else None
        ),
    )
    result["scenario_id"] = scene_id
    result["experiment_role"] = role
    result["seed_partition"] = {
        "development_seeds": list(config.development_seeds),
        "validation_seeds": list(config.validation_seeds),
        "overlap": [],
    }
    result["raw_result_policy"] = (
        "One record per seed and strategy, with shared world trace hash, timestamped environment events, "
        "controller/drone/recovery event log, per-seed latency samples, and computed metrics."
    )
    return result


def _validate_seed_partitions(configs: dict[str, object]) -> None:
    all_development: set[int] = set()
    all_validation: set[int] = set()
    for scene_id, config in configs.items():
        development = set(config.development_seeds)
        validation = set(config.validation_seeds)
        if len(development) < 5 or len(validation) < 20:
            raise ValueError(f"{scene_id} must define at least 5 development and 20 validation seeds")
        if development & validation:
            raise ValueError(f"{scene_id} development and validation seeds overlap")
        if (development | validation) & HISTORICAL_SEEDS:
            raise ValueError(f"{scene_id} reuses Phase 2 or Phase 4 historical seeds")
        all_development |= development
        all_validation |= validation
    if all_development & all_validation:
        raise ValueError("development and held-out validation seed IDs must be disjoint across scenes")


def _build_manifest(config_root: Path, configs: dict[str, Path], loaded: dict[str, object]) -> dict[str, object]:
    package_root = Path(__file__).resolve().parent
    source_hashes = {
        filename: _file_sha256(package_root / filename)
        for filename in SOURCE_FILES
    }
    scenario_hashes: dict[str, dict[str, str]] = {}
    for scene_id, config_path in configs.items():
        config = loaded[scene_id]
        scenario_hashes[scene_id] = {
            "dynamic_config": _file_sha256(config_path),
            "base_scenario": _file_sha256(config.scenario_path),
        }
    return {
        "schema_version": "1.0",
        "protocol_revision": "phase5-v2-corrected-dynamic-initial-service",
        "freeze_point": "after development runs and before held-out validation",
        "strategy_order": list(PHASE5_STRATEGY_ORDER),
        "strategies": {
            "A_no_recovery": "No UAV deployment; ground-station recovery only when explicitly scheduled.",
            "B_phase1_static_grid": "Historical one-time static grid planner retained unchanged.",
            "Bprime_static_grid_shared_safety": "Same static grid target as B with shared sortie-energy feasibility and reserve envelope.",
            "C_rolling_horizon_mpc": "Existing deterministic finite-horizon beam search with shared conservative return-energy check.",
            "D_lexicographic_rescue_priority": "Existing deterministic lexicographic rescue-priority candidate search with shared sortie-energy envelope.",
        },
        "protocol": {
            "matched_world_traces": True,
            "development_minimum_per_scenario": 5,
            "validation_minimum_per_scenario": 20,
            "recovery_success": "all configured rescue users connected at one observation; sustained recovery separately requires 30 continuous seconds",
            "unrecovered_time_reporting": "retain null success-only time, report failures/counts, and report recovery-or-censoring time at the simulation horizon",
            "uav_service_attribution": "same-tick no-drone counterfactual plus actual selected drone_relay user-seconds",
            "energy_unit": "Wh; hover/relay W multiplied by seconds / 3600; movement Wh/km multiplied by km",
            "decision_timing": "perf_counter wall-clock around controller.observe; simulation recovery time is a separate metric",
        },
        "scenario_file_hashes": scenario_hashes,
        "source_file_sha256": source_hashes,
        "seeds": {
            scene_id: {
                "development": list(loaded[scene_id].development_seeds),
                "validation": list(loaded[scene_id].validation_seeds),
            }
            for scene_id in configs
        },
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
