"""One-factor-at-a-time ablations and sensitivity runs for Phase 8.

Formal Phase 2/4/5 strategies and source files stay untouched. Each variant
uses the same exogenous trace as A/B/B'/C/D; runtime feasibility and energy
reserve checks are inherited from the production simulator.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
from typing import Any

from . import optimizer as core_optimizer
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
from .dynamic_world import DynamicWorldTrace, build_world_trace
from .experiment import _stats, _wilson_interval
from .models import Network, NetworkSnapshot, Position, User
from .optimizer import ControlDecision, NetworkDiagnosis, RollingHorizonOptimizer
from .phase8_d_optimizer import Phase8RescuePriorityOptimizer


ROOT = Path(__file__).resolve().parents[2]
SCENARIO_FILES = {
    "severe_persistent_faults": "severe_persistent_faults.toml",
    "dynamic_failures": "dynamic_failures.toml",
    "high_mobility_rescue": "high_mobility_rescue.toml",
    "high_load_backhaul_limit": "high_load_backhaul_limit.toml",
}
SCENARIO_ORDER = tuple(SCENARIO_FILES)
BASELINE_ORDER = (
    "A_no_recovery",
    "B_phase1_static_grid",
    "Bprime_static_grid_shared_safety",
    "C_rolling_horizon_mpc",
    "D_lexicographic_rescue_priority",
)
DEVELOPMENT_SEEDS = {
    "severe_persistent_faults": (6500, 6501, 6502),
    "dynamic_failures": (6510, 6511, 6512),
    "high_mobility_rescue": (6520, 6521, 6522),
    "high_load_backhaul_limit": (6530, 6531, 6532),
}
VALIDATION_SEEDS = {
    "severe_persistent_faults": tuple(range(90000, 90010)),
    "dynamic_failures": tuple(range(90100, 90110)),
    "high_mobility_rescue": tuple(range(90200, 90210)),
    "high_load_backhaul_limit": tuple(range(90300, 90310)),
}
CONFIRMATORY_VARIANTS = (
    "C_replan_event_off",
    "C_horizon_1",
    "C_horizon_6",
    "C_direct_heading_off",
    "C_energy_weight_0",
    "D_replan_event_off",
    "D_horizon_1",
    "D_horizon_6",
    "D_switch_suppression_off",
    "D_energy_tiebreak_off",
    "D_rescue_priority_off",
    "D_candidate_cap_16",
)
PHASE8_CODE_PATHS = (
    "src/lowalt6g/phase8_experiments.py",
    "src/lowalt6g/phase8_d_optimizer.py",
    "src/lowalt6g/phase8_charts.py",
    "scripts/run_phase8_experiments.py",
    "scripts/materialize_phase8_d_optimizer.py",
)
PHASE8_CONFIG_PATHS = (
    "configs/phase8/experiment_plan.json",
    "configs/phase8/ablation_plan.json",
    "configs/phase8/sensitivity_plan.json",
)


@dataclass(frozen=True)
class Variant:
    variant_id: str
    algorithm: str
    factor: str
    value: Any


def _variant_set() -> tuple[Variant, ...]:
    variants: list[Variant] = []
    for item in (
        Variant("C_replan_event_off", "C", "event_triggered_replanning", False),
        Variant("C_horizon_1", "C", "prediction_horizon_steps", 1),
        Variant("C_horizon_6", "C", "prediction_horizon_steps", 6),
        Variant("C_direct_heading_off", "C", "direct_target_heading_candidates", False),
        Variant("C_target_grid_0p125", "C", "relay_target_quantization_km", 0.125),
        Variant("C_target_grid_0p5", "C", "relay_target_quantization_km", 0.5),
        Variant("C_beam_width_3", "C", "beam_width", 3),
        Variant("C_beam_width_12", "C", "beam_width", 12),
        Variant("C_energy_weight_0", "C", "energy_penalty_weight", 0.0),
        Variant("C_energy_weight_4", "C", "energy_penalty_weight", 4.0),
        Variant("C_rescue_weight_5", "C", "rescue_service_weight", 5.0),
        Variant("C_rescue_weight_20", "C", "rescue_service_weight", 20.0),
        Variant("C_interval_10", "C", "decision_interval_s", 10),
        Variant("C_interval_40", "C", "decision_interval_s", 40),
        Variant("C_reserve_75", "C", "reserve_wh", 75.0),
        Variant("C_reserve_100", "C", "reserve_wh", 100.0),
        Variant("D_replan_event_off", "D", "event_triggered_replanning", False),
        Variant("D_horizon_1", "D", "prediction_horizon_steps", 1),
        Variant("D_horizon_6", "D", "prediction_horizon_steps", 6),
        Variant("D_grid_0p125", "D", "policy_search_grid_km", 0.125),
        Variant("D_grid_0p5", "D", "policy_search_grid_km", 0.5),
        Variant("D_candidate_cap_16", "D", "candidate_limit", 16),
        Variant("D_candidate_cap_128", "D", "candidate_limit", 128),
        Variant("D_switch_suppression_off", "D", "switch_suppression", False),
        Variant("D_switch_penalty_0", "D", "switch_penalty_weight", 0.0),
        Variant("D_switch_penalty_10", "D", "switch_penalty_weight", 10.0),
        Variant("D_energy_tiebreak_off", "D", "energy_tiebreak", False),
        Variant("D_rescue_priority_off", "D", "rescue_priority", False),
        Variant("D_interval_60", "D", "decision_interval_s", 60),
        Variant("D_interval_90", "D", "decision_interval_s", 90),
        Variant("D_interval_120", "D", "decision_interval_s", 120),
        Variant("D_reserve_75", "D", "reserve_wh", 75.0),
        Variant("D_reserve_100", "D", "reserve_wh", 100.0),
    ):
        variants.append(item)
    return tuple(variants)


VARIANTS = _variant_set()
VARIANT_BY_ID = {item.variant_id: item for item in VARIANTS}
VALIDATION_VARIANTS = tuple(VARIANT_BY_ID[item] for item in CONFIRMATORY_VARIANTS)
HISTORICAL_SEEDS = (
    set(range(2026, 2046))
    | set(range(3000, 3005))
    | set(range(4000, 4020))
    | set(range(6500, 6535))
    | set(range(7000, 7080))
)
METRICS = (
    "rescue_user_service_success_rate",
    "user_connection_success_rate",
    "network_recovery_or_censoring_time_s",
    "network_recovery_time_s",
    "network_recovery_success",
    "sustained_rescue_recovery_success",
    "sustained_rescue_recovery_time_s",
    "drone_energy_consumed_wh",
    "drone_energy_wh_per_rescue_user_hour",
    "drone_rescue_user_seconds",
    "average_latency_ms",
    "p95_latency_ms",
    "algorithm_decision_total_ms",
    "algorithm_decision_mean_ms",
    "target_switch_count",
)
BINARY_METRICS = {"network_recovery_success", "sustained_rescue_recovery_success"}
EFFICACY_METRICS = {
    "rescue_user_service_success_rate",
    "network_recovery_or_censoring_time_s",
    "network_recovery_success",
    "sustained_rescue_recovery_success",
}
RESOURCE_METRICS = {
    "drone_energy_consumed_wh",
    "drone_energy_wh_per_rescue_user_hour",
    "algorithm_decision_total_ms",
    "algorithm_decision_mean_ms",
    "target_switch_count",
    "user_connection_success_rate",
}


def experiment_plan() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "title": "Phase 8 one-factor ablation and parameter sensitivity",
        "control": "Each seed uses one generated world trace for A/B/Bprime/C/D and every variant.",
        "phase5_scenarios": SCENARIO_ORDER,
        "development_seed_role": "exploratory; first three seeds from each existing Phase 5 development partition",
        "development_seeds": DEVELOPMENT_SEEDS,
        "validation_seed_role": "confirmatory; new seed IDs not present in Phase 2/4/5 development or validation data",
        "validation_seeds": VALIDATION_SEEDS,
        "validation_variants_frozen_before_run": CONFIRMATORY_VARIANTS,
        "parameter_levels": {
            "C_replanning_interval_s": {"low": 10, "base": 20, "high": 40},
            "D_effective_replanning_interval_s": {"low": 60, "base": 60, "middle": 90, "high": 120, "note": "production D clamps this interval to at least 60 s"},
            "prediction_horizon_steps": {"low": 1, "base": 3, "high": 6, "time_step_s": 10},
            "C_relay_target_quantization_km": {"low": 0.125, "base": 0.25, "high": 0.5},
            "D_policy_grid_step_km": {"low": 0.125, "base": 0.25, "high": 0.5},
            "D_coarse_grid_shortlist_limit": {"low": 16, "base": 64, "high": 128, "note": "limits the pre-ranked grid shortlist only; exact relay and rescue-cluster points are retained"},
            "D_switch_penalty_weight": {"low": 0, "base": 1, "high": 10},
            "C_energy_penalty_weight": {"low": 0, "base": 2, "high": 4},
            "D_energy_tiebreak": {"low": "disabled", "base": "enabled", "high": "not_applicable_numeric_factor"},
            "rescue_priority": {"low": "disabled", "base": "enabled", "high": "not_applicable_numeric_factor"},
            "battery_reserve_wh": {"production_base": 50, "low": 50, "middle": 75, "high": 100},
        },
        "baseline_strategies": BASELINE_ORDER,
        "variants": [asdict(item) for item in VARIANTS],
        "safety_invariants": [
            "runtime speed and energy enforcement unchanged",
            "return-to-healthy-station reserve check remains active",
            "battery reserve remains positive and configurable at 50/75/100 Wh",
            "backhaul, access-radius, capacity, city-boundary and link checks unchanged",
            "no candidate result may bypass runtime simulator feasibility checks",
        ],
        "confirmatory_selection_rule": (
            "Mechanism contrasts fixed before development outcomes are inspected: event trigger, H=1/6, "
            "C direct headings and energy weight, D switch suppression/energy tie-break/rescue priority/candidate cap. "
            "No best-development variant is relabeled as an unbiased discovery."
        ),
        "statistical_plan": {
            "pairing": "within seed and identical exogenous world trace",
            "confidence_intervals": "two-sided 95% Student-t intervals over per-seed means/differences; Wilson interval for binary success rate",
            "effect_size": "paired Hedges g_z with paired Cohen d_z also retained",
            "p_values": "exact two-sided sign-flip randomization for continuous paired outcomes; exact McNemar/binomial tail for binary outcomes",
            "multiplicity": "Holm correction separately over efficacy and resource/cost families across all confirmatory comparisons and scenes",
            "latency": "conditional on each policy's successful user-time samples; per-seed means and pooled P95 with sample counts; no user-level paired test",
            "unrecovered": "remain failures; recovery-or-censoring time uses simulation horizon for paired comparison; recovered-only time reports n_success/n_total",
        },
    }


def ensure_plan_file() -> Path:
    path = ROOT / "configs/phase8/experiment_plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    full_plan = experiment_plan()
    documents = {
        "experiment_plan.json": full_plan,
        "ablation_plan.json": {
            "schema_version": "1.0",
            "role": "one-factor ablations; formal C/D implementations remain unchanged",
            "controlled_variables": ["scenario config", "seeded world trace", "simulation time step", "runtime safety layer", "radio and backhaul feasibility"],
            "development_variant_ids": [item.variant_id for item in VARIANTS],
            "confirmatory_variant_ids": list(CONFIRMATORY_VARIANTS),
            "mechanisms": {
                "event_replanning": "disable event-triggered updates while retaining first and periodic decisions",
                "prediction_horizon_steps": "compare H=1,3,6; time step is 10 s, so horizons are 10/30/60 s",
                "candidate_generation": "remove direct pursuit headings or quantize C relay candidates; vary D grid shortlist and mesh step",
                "target_switching": "turn D switch suppression off or vary its tie-break penalty; hard feasibility remains active",
                "energy": "vary C's energy objective weight and D's ranking-only energy tie-break; do not remove energy/return constraints",
                "rescue_priority": "reduce C rescue weight or remove D rescue lexicographic rank; runtime service and radio checks stay unchanged",
                "battery_reserve": "vary positive operational reserve while enforcing it in planner and execution",
            },
            "hypotheses": [
                "Event replanning can improve response to exogenous changes at additional computation cost.",
                "Longer horizons can improve foresight but increase candidate evaluation cost under a frozen-state forecast.",
                "Direct/quantized candidate generation can change the chance of reaching useful relay geometry.",
                "Switch suppression can reduce chattering but may delay response to a genuine rescue-service gain.",
                "Energy preference can lower Wh while reducing rescue service; safety limits are never ablated.",
                "Rescue priority can improve rescue service while reallocating capacity away from ordinary users.",
            ],
            "comparison_rules": full_plan["statistical_plan"],
        },
        "sensitivity_plan.json": {
            "schema_version": "1.0",
            "role": "staged one-factor parameter screening and held-out confirmation",
            "parameter_levels": full_plan["parameter_levels"],
            "development_seed_map": DEVELOPMENT_SEEDS,
            "validation_seed_map": VALIDATION_SEEDS,
            "validation_variant_ids_frozen_before_run": list(CONFIRMATORY_VARIANTS),
            "safety_constraints_always_on": full_plan["safety_invariants"],
            "candidate_selection": "No best variant is selected from the held-out set. The confirmatory contrasts are fixed in advance; development results are exploratory.",
            "range_basis": "Ranges are bounded by the existing 10 s simulator step, 600 s scenario horizon, 0.25 km base grid, 20 s C interval, D's 60 s minimum interval, and 50 Wh configured reserve. They are engineering sensitivity probes, not literature-claimed optima.",
        },
    }
    for filename, value in documents.items():
        document_path = path.parent / filename
        expected = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if document_path.exists():
            actual = document_path.read_text(encoding="utf-8")
            if actual != expected:
                raise ValueError(f"{document_path} differs from the Phase 8 executable protocol")
        else:
            document_path.write_text(expected, encoding="utf-8", newline="\n")
    return path


def _load_scenarios() -> dict[str, DynamicExperimentConfig]:
    return {
        scenario_id: load_dynamic_config(ROOT / "configs/phase5" / filename)
        for scenario_id, filename in SCENARIO_FILES.items()
    }


def verify_phase5_freeze() -> dict[str, str]:
    manifest_path = ROOT / "results/phase5_frozen_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_sources: dict[str, str] = manifest["source_file_sha256"]
    actual: dict[str, str] = {}
    for filename, expected in expected_sources.items():
        path = ROOT / "src/lowalt6g" / filename
        digest = sha256_file(path)
        if digest != expected:
            raise ValueError(f"Phase 5 frozen source mismatch: {filename}")
        actual[filename] = digest
    from .phase8_d_optimizer import SOURCE_OPTIMIZER_SHA256

    if SOURCE_OPTIMIZER_SHA256 != expected_sources.get("optimizer.py"):
        raise ValueError("Phase 8 experimental D copy is not derived from the frozen Phase 5 optimizer")
    configs = _load_scenarios()
    for scenario_id, filename in SCENARIO_FILES.items():
        config = configs[scenario_id]
        checks = {
            "dynamic_config": sha256_file(ROOT / "configs/phase5" / filename),
            "base_scenario": sha256_file(config.scenario_path),
        }
        expected_config_hashes = manifest["scenario_file_hashes"][scenario_id]
        for role, value in checks.items():
            if expected_config_hashes.get(role) != value:
                raise ValueError(f"Phase 5 frozen config mismatch: {scenario_id}/{role}")
    return actual


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_config_hash(config: DynamicExperimentConfig, strategy_id: str) -> str:
    from .experiment import _effective_config

    effective = _effective_config(config, (strategy_id,))
    payload = json.dumps(effective, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _apply_variant(config: DynamicExperimentConfig, variant: Variant) -> tuple[DynamicExperimentConfig, dict[str, object]]:
    optimizer_options: dict[str, object] = {}
    if variant.factor == "prediction_horizon_steps":
        config = replace(config, prediction_horizon_steps=int(variant.value))
    elif variant.factor == "decision_interval_s":
        config = replace(config, decision_interval_s=int(variant.value))
    elif variant.factor == "reserve_wh":
        config = replace(config, reserve_wh=float(variant.value))
    elif variant.factor == "energy_penalty_weight":
        config = replace(config, energy_penalty_weight=float(variant.value))
    elif variant.factor == "rescue_service_weight":
        config = replace(config, rescue_service_weight=float(variant.value))
    elif variant.factor == "beam_width":
        config = replace(config, beam_width=int(variant.value))
    elif variant.factor == "policy_search_grid_km":
        config = replace(config, base=replace(config.base, policy_search_grid_km=float(variant.value)))
    elif variant.factor == "relay_target_quantization_km":
        optimizer_options["target_quantum_km"] = float(variant.value)
    elif variant.factor == "event_triggered_replanning":
        optimizer_options["event_replanning"] = bool(variant.value)
    elif variant.factor == "direct_target_heading_candidates":
        optimizer_options["direct_heading_candidates"] = bool(variant.value)
    elif variant.factor == "candidate_limit":
        optimizer_options["candidate_limit"] = int(variant.value)
    elif variant.factor == "switch_suppression":
        optimizer_options["suppress_switch_without_rescue_gain"] = bool(variant.value)
    elif variant.factor == "switch_penalty_weight":
        optimizer_options["switch_penalty_weight"] = float(variant.value)
    elif variant.factor == "energy_tiebreak":
        optimizer_options["energy_tiebreak_enabled"] = bool(variant.value)
    elif variant.factor == "rescue_priority":
        optimizer_options["rescue_priority_enabled"] = bool(variant.value)
    else:
        raise ValueError(f"unsupported Phase 8 factor: {variant.factor}")
    config.validate()
    return config, optimizer_options


class _Phase8COptimizer(RollingHorizonOptimizer):
    def __init__(self, config: DynamicExperimentConfig, options: dict[str, object]) -> None:
        super().__init__(config)
        self.event_replanning = bool(options.get("event_replanning", True))
        self.direct_heading_candidates = bool(options.get("direct_heading_candidates", True))
        self.target_quantum_km = options.get("target_quantum_km")

    def _state_signature(self, network, snapshot, diagnosis):
        if not self.event_replanning:
            return ("periodic_only",)
        return super()._state_signature(network, snapshot, diagnosis)

    def _action_headings(self, current, targets):
        if not self.direct_heading_candidates:
            return core_optimizer._HEADINGS
        return RollingHorizonOptimizer._action_headings(current, targets)

    def _feasible_relay_positions(self, network, users, stations):
        points = super()._feasible_relay_positions(network, users, stations)
        quantum = self.target_quantum_km
        if quantum is None:
            return points
        snapped: dict[tuple[int, int], Position] = {}
        for point in points:
            x = round(point.x_km / float(quantum)) * float(quantum)
            y = round(point.y_km / float(quantum)) * float(quantum)
            if not (0 <= x <= network.config.city_width_km and 0 <= y <= network.config.city_height_km):
                continue
            if not any(
                math.hypot(x - station.x_km, y - station.y_km) <= network.drone_spec.backhaul_radius_km + 1e-9
                for station in stations
            ):
                continue
            if not any(math.hypot(x - user.x_km, y - user.y_km) <= network.drone_spec.access_radius_km + 1e-9 for user in users):
                continue
            candidate = Position(x, y)
            snapped[(round(x / 0.005), round(y / 0.005))] = candidate
        return tuple(snapped[key] for key in sorted(snapped))


class _Phase8DOptimizer(Phase8RescuePriorityOptimizer):
    def __init__(self, config: DynamicExperimentConfig, options: dict[str, object]) -> None:
        super().__init__(
            config,
            candidate_limit=int(options.get("candidate_limit", 64)),
            suppress_switch_without_rescue_gain=bool(options.get("suppress_switch_without_rescue_gain", True)),
            energy_tiebreak_enabled=bool(options.get("energy_tiebreak_enabled", True)),
            rescue_priority_enabled=bool(options.get("rescue_priority_enabled", True)),
            switch_penalty_weight=float(options.get("switch_penalty_weight", 1.0)),
        )
        self.event_replanning = bool(options.get("event_replanning", True))

    def _state_signature(self, network, snapshot, diagnosis):
        if not self.event_replanning:
            return ("periodic_only",)
        return super()._state_signature(network, snapshot, diagnosis)


class _Phase8Controller:
    def __init__(self, algorithm: str, optimizer) -> None:
        self.strategy_id = "C_rolling_horizon_mpc" if algorithm == "C" else "D_lexicographic_rescue_priority"
        self.strategy_name = "Phase 8 C ablation" if algorithm == "C" else "Phase 8 D ablation"
        self.optimizer = optimizer

    def observe(self, time_s, network, snapshot, diagnosis, battery_wh):
        return self.optimizer.observe(time_s, network, snapshot, diagnosis, battery_wh)


def _run_variant(
    base_config: DynamicExperimentConfig,
    seed: int,
    trace: DynamicWorldTrace,
    variant: Variant,
) -> tuple[DynamicRun, str, str, DynamicExperimentConfig, dict[str, object]]:
    variant_config = replace(base_config, seeds=(seed,))
    variant_config, options = _apply_variant(variant_config, variant)
    optimizer = _Phase8COptimizer(variant_config, options) if variant.algorithm == "C" else _Phase8DOptimizer(variant_config, options)
    run = _run_one(variant_config, seed, trace, _Phase8Controller(variant.algorithm, optimizer))
    config_hash = canonical_config_hash(variant_config, run.strategy_id)
    settings_payload = {
        "variant": asdict(variant),
        "config_sha256": config_hash,
        "optimizer_options": options,
    }
    settings_hash = hashlib.sha256(
        json.dumps(settings_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return run, config_hash, settings_hash, variant_config, options


def _validate_seed_assignments() -> None:
    selected = [seed for values in (*DEVELOPMENT_SEEDS.values(), *VALIDATION_SEEDS.values()) for seed in values]
    if len(selected) != len(set(selected)):
        raise ValueError("Phase 8 development and confirmation seed IDs overlap")
    all_validation = set().union(*(set(values) for values in VALIDATION_SEEDS.values()))
    all_development = set().union(*(set(values) for values in DEVELOPMENT_SEEDS.values()))
    if all_validation & all_development:
        raise ValueError("Phase 8 development and confirmation seeds overlap")
    phase5_development: set[int] = set()
    phase5_validation: set[int] = set()
    for config in _load_scenarios().values():
        phase5_development.update(config.development_seeds)
        phase5_validation.update(config.validation_seeds)
    prior_phase_seeds = set(range(2026, 2046)) | set(range(3000, 3005)) | set(range(4000, 4020))
    if all_development & (prior_phase_seeds | phase5_validation):
        raise ValueError("Phase 8 development seeds may reuse Phase 5 development data only")
    if all_development - phase5_development:
        raise ValueError("Phase 8 development seeds must be selected from Phase 5 development partitions")
    if all_validation & (prior_phase_seeds | phase5_development | phase5_validation):
        raise ValueError("Phase 8 validation seeds overlap prior phase data")


def _new_seed_record(
    scenario_id: str,
    seed: int,
    base_config: DynamicExperimentConfig,
    baseline,
    trace: DynamicWorldTrace,
    variants: tuple[Variant, ...],
) -> dict[str, object]:
    baseline_runs = {
        key: run.to_dict(include_latency_samples=True)
        for key, run in baseline.strategies.items()
    }
    variant_runs: dict[str, object] = {}
    variant_hashes: dict[str, str] = {}
    variant_setting_hashes: dict[str, str] = {}
    variant_options: dict[str, dict[str, object]] = {}
    batteries: dict[str, float] = {}
    for variant in variants:
        run, config_digest, settings_digest, variant_config, options = _run_variant(base_config, seed, trace, variant)
        variant_runs[variant.variant_id] = run.to_dict(include_latency_samples=True)
        variant_hashes[variant.variant_id] = config_digest
        variant_setting_hashes[variant.variant_id] = settings_digest
        variant_options[variant.variant_id] = options
        batteries[variant.variant_id] = variant_config.reserve_wh
        minimum_battery = run.metrics.get("drone_battery_minimum_wh")
        if minimum_battery is not None and float(minimum_battery) < variant_config.reserve_wh - 1e-6:
            raise AssertionError(f"battery reserve violated by {variant.variant_id} on {scenario_id}/{seed}")
    for key, run in baseline.strategies.items():
        minimum_battery = run.metrics.get("drone_battery_minimum_wh")
        if minimum_battery is not None and float(minimum_battery) < base_config.reserve_wh - 1e-6:
            raise AssertionError(f"battery reserve violated by baseline {key} on {scenario_id}/{seed}")
    if baseline.trace_sha256 != trace.trace_sha256:
        raise AssertionError("baseline trace hash mismatch")
    return {
        "scenario_id": scenario_id,
        "seed": seed,
        "world_trace_sha256": trace.trace_sha256,
        "environment_events": list(baseline.environment_events),
        "baseline_strategy_runs": baseline_runs,
        "variant_runs": variant_runs,
        "variant_effective_config_sha256": variant_hashes,
        "variant_decision_settings_sha256": variant_setting_hashes,
        "variant_optimizer_options": variant_options,
        "variant_reserve_wh": batteries,
    }


def _scene_config_hash(config: DynamicExperimentConfig) -> str:
    from .experiment import _effective_config

    payload = json.dumps(_effective_config(config, BASELINE_ORDER), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git_head() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _atomic_json_write(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def run_stage(phase: str, *, progress=None) -> dict[str, object]:
    if phase not in {"development", "validation"}:
        raise ValueError("phase must be development or validation")
    plan_path = ensure_plan_file()
    plan_hash = sha256_file(plan_path)
    freeze_sources = verify_phase5_freeze()
    _validate_seed_assignments()
    current_code_hashes = {item: sha256_file(ROOT / item) for item in PHASE8_CODE_PATHS}
    current_config_hashes = {item: sha256_file(ROOT / item) for item in PHASE8_CONFIG_PATHS}
    if phase == "validation":
        protocol_path = ROOT / "configs/phase8/validation_protocol.json"
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        if protocol["plan_sha256"] != plan_hash:
            raise ValueError("validation plan hash differs from frozen Phase 8 protocol")
        for relative_path, expected in protocol["code_sha256"].items():
            if sha256_file(ROOT / relative_path) != expected:
                raise ValueError(f"validation code changed after freeze: {relative_path}")
        if protocol["phase5_source_sha256"] != freeze_sources:
            raise ValueError("Phase 5 protected sources differ from the frozen Phase 8 protocol")
        variants = VALIDATION_VARIANTS
        seed_map = VALIDATION_SEEDS
        role = "confirmatory_held_out_not_used_for_tuning"
        output_path = ROOT / "results/phase8_validation_raw.json"
        freeze_hash = sha256_file(protocol_path)
    else:
        variants = VARIANTS
        seed_map = DEVELOPMENT_SEEDS
        role = "exploratory_development_not_confirmatory"
        output_path = ROOT / "results/phase8_development_raw.json"
        freeze_hash = None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        state = json.loads(output_path.read_text(encoding="utf-8"))
        if state.get("plan_sha256") != plan_hash or state.get("experiment_role") != role or state.get("protocol_sha256") != freeze_hash:
            raise ValueError(f"existing checkpoint {output_path} belongs to a different protocol")
        if state.get("phase8_code_sha256") != current_code_hashes or state.get("phase8_config_sha256") != current_config_hashes:
            raise ValueError(f"Phase 8 code or configuration differs from checkpoint {output_path}; refusing to mix runs")
        if state.get("status") == "complete":
            raw = state
            summary = summarize_raw(raw)
            summary_path = ROOT / ("results/phase8_development_summary.json" if phase == "development" else "results/phase8_validation_summary.json")
            if not summary_path.exists():
                _atomic_json_write(summary_path, summary)
            return {"raw": str(output_path), "summary": str(summary_path), "resumed": True, "status": "complete"}
    else:
        state = {
            "schema_version": "1.0",
            "phase": phase,
            "experiment_role": role,
            "status": "running",
            "plan_sha256": plan_hash,
            "protocol_sha256": freeze_hash,
            "project_git_head": _git_head(),
            "model_scope": "abstract_6g_research_simulation_not_real_network_test",
            "phase5_frozen_manifest_sha256": sha256_file(ROOT / "results/phase5_frozen_manifest.json"),
            "phase5_source_sha256": freeze_sources,
            "phase8_code_sha256": current_code_hashes,
            "phase8_config_sha256": current_config_hashes,
            "scenario_effective_config_sha256": {
                scenario_id: _scene_config_hash(config)
                for scenario_id, config in _load_scenarios().items()
            },
            "runtime_environment": {
                "python": sys.version.split()[0],
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
                "uv_lock_sha256": sha256_file(ROOT / "uv.lock"),
            },
            "seed_assignments": seed_map,
            "variant_ids": [item.variant_id for item in variants],
            "records": [],
        }
        _atomic_json_write(output_path, state)

    done = {(row["scenario_id"], int(row["seed"])) for row in state["records"]}
    configs = _load_scenarios()
    total = sum(len(seeds) for seeds in seed_map.values())
    completed = len(done)
    for scenario_id in SCENARIO_ORDER:
        config = configs[scenario_id]
        for seed in seed_map[scenario_id]:
            if (scenario_id, seed) in done:
                continue
            seeded_config = replace(config, seeds=(seed,))
            trace = build_world_trace(seeded_config, seed)
            baseline = run_seed_experiment(seeded_config, seed, trace, include_d=True, include_bprime=True)
            record = _new_seed_record(scenario_id, seed, seeded_config, baseline, trace, variants)
            state["records"].append(record)
            completed += 1
            _atomic_json_write(output_path, state)
            if progress:
                progress(phase, completed, total, scenario_id, seed)
    state["status"] = "complete"
    state["completed_seed_count"] = completed
    state["completed_policy_run_count"] = completed * (len(BASELINE_ORDER) + len(variants))
    state["actual_policy_run_count"] = sum(
        len(row["baseline_strategy_runs"]) + len(row["variant_runs"])
        for row in state["records"]
    )
    _atomic_json_write(output_path, state)
    summary = summarize_raw(state)
    summary_path = ROOT / ("results/phase8_development_summary.json" if phase == "development" else "results/phase8_validation_summary.json")
    _atomic_json_write(summary_path, summary)
    return {"raw": str(output_path), "summary": str(summary_path), "status": "complete", "seed_count": completed, "policy_run_count": state["actual_policy_run_count"]}


def freeze_validation_protocol() -> Path:
    plan_path = ensure_plan_file()
    plan_hash = sha256_file(plan_path)
    dev_path = ROOT / "results/phase8_development_raw.json"
    if not dev_path.is_file() or json.loads(dev_path.read_text(encoding="utf-8")).get("status") != "complete":
        raise ValueError("development screening must finish before validation protocol freeze")
    paths = (*PHASE8_CODE_PATHS, *PHASE8_CONFIG_PATHS)
    protocol = {
        "schema_version": "1.0",
        "status": "frozen_before_validation",
        "freeze_rule": "No confirmatory result was read before this file was written; no code/config changes are permitted after freeze.",
        "plan_sha256": plan_hash,
        "code_sha256": {item: sha256_file(ROOT / item) for item in paths},
        "phase5_source_sha256": verify_phase5_freeze(),
        "frozen_phase5_manifest_sha256": sha256_file(ROOT / "results/phase5_frozen_manifest.json"),
        "validation_seed_map": VALIDATION_SEEDS,
        "validation_variants": CONFIRMATORY_VARIANTS,
        "model_scope": "abstract_6g_research_simulation_not_real_network_test",
        "comparison_and_statistics": experiment_plan()["statistical_plan"],
        "created_from_development_artifact_sha256": sha256_file(dev_path),
        "git_head": _git_head(),
    }
    path = ROOT / "configs/phase8/validation_protocol.json"
    if path.exists():
        raise FileExistsError(f"refusing to replace frozen validation protocol: {path}")
    _atomic_json_write(path, protocol)
    return path


def _run_metric(run_dict: dict[str, object], metric: str):
    metrics = run_dict["metrics"]
    assert isinstance(metrics, dict)
    return metrics.get(metric)


def _paired_values(rows: list[dict[str, object]], left_key: str, right_key: str, metric: str) -> tuple[list[float], list[float]]:
    left: list[float] = []
    right: list[float] = []
    for row in rows:
        left_run = _get_run(row, left_key)
        right_run = _get_run(row, right_key)
        a = _run_metric(left_run, metric)
        b = _run_metric(right_run, metric)
        if a is None or b is None:
            continue
        left.append(float(a))
        right.append(float(b))
    return left, right


def _get_run(row: dict[str, object], key: str) -> dict[str, object]:
    if key in row["baseline_strategy_runs"]:
        return row["baseline_strategy_runs"][key]
    return row["variant_runs"][key]


def _paired_test(differences: list[float], *, binary: bool, inferential: bool) -> dict[str, object]:
    n = len(differences)
    if n == 0:
        return {"n": 0, "mean_difference": None, "ci95_t": None, "cohen_dz": None, "hedges_gz": None, "p_exact_two_sided": None}
    mean = statistics.fmean(differences)
    stats = _stats(differences, include_ci=True)
    sd = statistics.stdev(differences) if n > 1 else 0.0
    dz = mean / sd if sd > 0 else (math.copysign(math.inf, mean) if mean else 0.0)
    hedges_correction = 1.0 - 3.0 / max(4.0 * (n - 1) - 1.0, 1.0)
    if binary:
        positive = sum(value > 0 for value in differences)
        negative = sum(value < 0 for value in differences)
        discordant = positive + negative
        tail = min(positive, negative)
        p = min(1.0, 2.0 * sum(math.comb(discordant, index) for index in range(tail + 1)) / (2**discordant)) if discordant else 1.0
        test_name = "exact_mcnemar_binomial"
    elif n <= 20:
        observed = abs(sum(differences))
        extreme = 0
        total = 1 << n
        for mask in range(total):
            signed_total = 0.0
            for index, value in enumerate(differences):
                signed_total += -value if mask & (1 << index) else value
            if abs(signed_total) >= observed - 1e-12:
                extreme += 1
        p = extreme / total
        test_name = "exact_sign_flip_randomization"
    else:
        # This function is used only for the 10-seed confirmatory partition.
        raise ValueError("exact sign-flip implementation is capped at 20 paired seeds")
    return {
        "n": n,
        "mean_difference": round(mean, 8),
        "sample_sd_difference": round(sd, 8) if n > 1 else None,
        "median_difference": round(statistics.median(differences), 8),
        "ci95_t": stats.get("mean_ci95_t"),
        "cohen_dz": round(dz, 8) if math.isfinite(dz) else None,
        "hedges_gz": round(dz * hedges_correction, 8) if math.isfinite(dz) else None,
        "p_exact_two_sided": round(p, 8) if inferential else None,
        "test": test_name if inferential else "descriptive_no_confirmatory_test",
    }


def _holm_adjust(items: list[dict[str, object]]) -> None:
    valid = [(float(item["p_exact_two_sided"]), item) for item in items if item.get("p_exact_two_sided") is not None]
    valid.sort(key=lambda pair: pair[0])
    running = 0.0
    count = len(valid)
    for rank, (p, item) in enumerate(valid):
        adjusted = min(1.0, (count - rank) * p)
        running = max(running, adjusted)
        item["p_holm_adjusted"] = round(running, 8)
        item["holm_family_size"] = count


def summarize_raw(raw: dict[str, object]) -> dict[str, object]:
    by_scene: dict[str, list[dict[str, object]]] = {scene: [] for scene in SCENARIO_ORDER}
    for row in raw["records"]:
        by_scene[row["scenario_id"]].append(row)
    summary_scenes: dict[str, object] = {}
    inferential: list[dict[str, object]] = []
    for scene_id, rows in by_scene.items():
        if not rows:
            continue
        policy_ids = list(BASELINE_ORDER) + [variant.variant_id for variant in VARIANTS if variant.variant_id in raw["variant_ids"]]
        policy_summaries: dict[str, object] = {}
        for key in policy_ids:
            runs = [_get_run(row, key) for row in rows]
            per_policy: dict[str, object] = {}
            for metric in METRICS:
                values = [float(value) for run in runs if (value := _run_metric(run, metric)) is not None]
                per_policy[metric] = _stats(values, include_ci=True)
            recovered = [float(_run_metric(run, "network_recovery_time_s")) for run in runs if _run_metric(run, "network_recovery_time_s") is not None]
            sustained = [float(_run_metric(run, "sustained_rescue_recovery_time_s")) for run in runs if _run_metric(run, "sustained_rescue_recovery_time_s") is not None]
            recovery_flags = [float(_run_metric(run, "network_recovery_success")) for run in runs]
            sustained_flags = [float(_run_metric(run, "sustained_rescue_recovery_success")) for run in runs]
            latencies = [float(value) for run in runs for value in run.get("latency_samples_ms", [])]
            policy_summaries[key] = {
                "seed_count": len(runs),
                "metrics": per_policy,
                "recovery_time": {
                    "successes": len(recovered),
                    "total": len(runs),
                    "unrecovered": len(runs) - len(recovered),
                    "success_rate_ci95_wilson": _wilson_interval(recovery_flags),
                    "recovered_only_s": _stats(recovered, include_ci=True),
                },
                "sustained_30s": {
                    "successes": len(sustained),
                    "total": len(runs),
                    "failures": len(runs) - len(sustained),
                    "success_rate_ci95_wilson": _wilson_interval(sustained_flags),
                    "recovered_only_start_time_s": _stats(sustained, include_ci=True),
                },
                "latency_conditioned_on_success": {
                    "successful_user_time_sample_count": len(latencies),
                    "pooled_mean_ms": round(statistics.fmean(latencies), 8) if latencies else None,
                    "pooled_p95_ms": _percentile(latencies, 0.95),
                    "policy_specific_success_set": True,
                },
            }
        contrasts: list[tuple[str, str]] = []
        for variant in raw["variant_ids"]:
            algorithm = VARIANT_BY_ID[variant].algorithm
            parent = "C_rolling_horizon_mpc" if algorithm == "C" else "D_lexicographic_rescue_priority"
            contrasts.extend(((variant, parent), (variant, "B_phase1_static_grid")))
        contrasts.extend((
            ("C_rolling_horizon_mpc", "B_phase1_static_grid"),
            ("D_lexicographic_rescue_priority", "B_phase1_static_grid"),
        ))
        inferential_phase = raw.get("phase") == "validation"
        for left_id, comparator in contrasts:
            for metric in METRICS:
                if metric in {
                    "average_latency_ms",
                    "p95_latency_ms",
                    "network_recovery_time_s",
                    "sustained_rescue_recovery_time_s",
                }:
                    continue
                left, right = _paired_values(rows, left_id, comparator, metric)
                if not left:
                    continue
                item = _paired_test(
                    [a - b for a, b in zip(left, right, strict=True)],
                    binary=metric in BINARY_METRICS,
                    inferential=inferential_phase,
                )
                item.update({
                    "scenario_id": scene_id,
                    "variant": left_id,
                    "comparison": f"{left_id}_minus_{comparator}",
                    "metric": metric,
                    "family": "efficacy" if metric in EFFICACY_METRICS or metric == "user_connection_success_rate" else "resource_cost",
                    "direction": "negative_is_better" if metric in {"network_recovery_or_censoring_time_s", "drone_energy_consumed_wh", "drone_energy_wh_per_rescue_user_hour", "algorithm_decision_total_ms", "algorithm_decision_mean_ms", "target_switch_count"} else "positive_is_better",
                })
                inferential.append(item)
        summary_scenes[scene_id] = {
            "seed_count": len(rows),
            "seed_ids": [int(row["seed"]) for row in rows],
            "all_strategy_and_variant_summaries": policy_summaries,
            "paired_contrasts": [item for item in inferential if item["scenario_id"] == scene_id],
        }
    is_confirmatory = raw.get("phase") == "validation"
    if is_confirmatory:
        for family in ("efficacy", "resource_cost"):
            _holm_adjust([item for item in inferential if item["family"] == family])
    for scene_id, scene in summary_scenes.items():
        scene["paired_contrasts"] = [item for item in inferential if item["scenario_id"] == scene_id]
    return {
        "schema_version": "1.0",
        "phase": raw["phase"],
        "experiment_role": raw["experiment_role"],
        "analysis_status": "confirmatory" if is_confirmatory else "exploratory_descriptive_only",
        "status": raw["status"],
        "phase5_frozen_manifest_sha256": raw["phase5_frozen_manifest_sha256"],
        "plan_sha256": raw["plan_sha256"],
        "seed_count_total": len(raw["records"]),
        "policy_run_count": raw.get("actual_policy_run_count"),
        "paired_tests": inferential,
        "multiple_testing": {
            "method": "Holm step-down correction across the predeclared validation family; development p-values are omitted",
            "efficacy_family": "All confirmatory comparisons across scenes for rescue service, connection success, recovery/censoring time, recovery and 30 s sustained success.",
            "resource_cost_family": "All confirmatory comparisons across scenes for connection success, energy, energy/service, controller compute and target switches.",
            "latency_inference": "No paired p-values: successful user-time sample sets differ by policy; conditional sample counts and summaries are reported per policy.",
        },
        "scenarios": summary_scenes,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 8)

