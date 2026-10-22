"""Paired Phase 14 radio-model experiments and uncertainty summaries."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
from typing import Any, Iterable

from .dynamic_config import DynamicExperimentConfig, load_dynamic_config
from .dynamic_simulation import DynamicRun, _SafeStaticGridController, _run_one
from .dynamic_world import DynamicWorldTrace, build_world_trace
from .multi_uav import MultiUAVOptions
from .multi_uav_simulation import run_fleet_policy
from .phase14_radio import radio_model_context
from .radio_link import (
    LegacyDistanceModel,
    LinkBudgetModelConfig,
    LinkBudgetProfile,
    LinkBudgetV1,
    load_link_budget_config,
)


ROOT = Path(__file__).resolve().parents[2]
LINK_CONFIG_PATH = "configs/phase14/link_budget_v1.toml"
PHASE10_PLAN_PATH = "configs/phase10/multi_uav_plan.json"
SCENARIOS = {
    "severe_persistent_faults": "configs/phase5/severe_persistent_faults.toml",
    "dynamic_failures": "configs/phase5/dynamic_failures.toml",
    "high_mobility_rescue": "configs/phase5/high_mobility_rescue.toml",
    "high_load_backhaul_limit": "configs/phase5/high_load_backhaul_limit.toml",
}
DEVELOPMENT_SEEDS = {
    "severe_persistent_faults": (96000, 96001, 96002),
    "dynamic_failures": (96010, 96011, 96012),
    "high_mobility_rescue": (96020, 96021, 96022),
    "high_load_backhaul_limit": (96030, 96031, 96032),
}
CONFIRMATION_SEEDS = {
    "severe_persistent_faults": tuple(range(96100, 96120)),
    "dynamic_failures": tuple(range(96200, 96220)),
    "high_mobility_rescue": tuple(range(96300, 96320)),
    "high_load_backhaul_limit": tuple(range(96400, 96420)),
}
POLICIES = (
    ("Bprime_static_grid_shared_safety", 1),
    ("F_independent_greedy", 3),
    ("G_centralized_coordination", 3),
)
MODELS = ("legacy_distance", "link_budget_v1")
PRIMARY_METRIC = "rescue_user_service_success_rate"
DECISION_SCOPE = {
    "Bprime_static_grid_shared_safety": "controller.observe wall time per time tick; includes diagnosis and controller planning",
    "F_independent_greedy": "wall time around complete plan_fleet call, measured by Phase 14 wrapper",
    "G_centralized_coordination": "wall time around complete plan_fleet call, measured by Phase 14 wrapper",
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _multi_uav_options() -> MultiUAVOptions:
    plan = json.loads((ROOT / PHASE10_PLAN_PATH).read_text(encoding="utf-8"))
    raw = plan["fleet_model"]
    return MultiUAVOptions(
        grid_spacing_km=float(raw["candidate_grid_spacing_km"]),
        candidate_limit=int(raw["candidate_limit_per_uav"]),
        min_separation_km=float(raw["min_uav_separation_km"]),
        replan_interval_s=int(raw["replan_interval_s"]),
        decision_timeout_ms=float(raw["decision_timeout_ms"]),
        max_joint_combinations=int(raw["max_joint_candidate_combinations"]),
        sortie_service_budget_steps=int(raw["sortie_service_budget_steps"]),
    )


def model_for(model_id: str, seed: int, budget_config: LinkBudgetModelConfig):
    if model_id == "legacy_distance":
        return LegacyDistanceModel()
    if model_id == "link_budget_v1":
        return LinkBudgetV1(budget_config, seed=seed)
    raise ValueError(f"unknown Phase 14 model: {model_id}")


def _source_sha256() -> str:
    paths = (
        "src/lowalt6g/radio_link.py",
        "src/lowalt6g/phase14_radio.py",
        "src/lowalt6g/phase14_experiments.py",
        "scripts/run_phase14_experiments.py",
    )
    entries = {path: sha256_file(ROOT / path) for path in paths if (ROOT / path).is_file()}
    return _stable_sha256(entries)


def _run_policy(
    config: DynamicExperimentConfig,
    trace: DynamicWorldTrace,
    policy_id: str,
    fleet_size: int,
    model_id: str,
    budget_config: LinkBudgetModelConfig,
    seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[float], list[float]]:
    model = model_for(model_id, seed, budget_config)
    options = _multi_uav_options()
    with radio_model_context(model) as telemetry:
        if policy_id == "Bprime_static_grid_shared_safety":
            result = _run_one(
                config,
                seed,
                trace,
                _SafeStaticGridController(config),
                capture_snapshots=True,
            )
            raw_metrics = dict(result.metrics)
            geometry = _single_geometry(result)
            events = list(result.event_log)
            latency_samples = list(result.latency_samples_ms)
            normal_connected = normal_total = 0
            for snapshot in result.state_snapshots:
                for user in snapshot["users"]:
                    if user["group"] == "normal":
                        normal_total += 1
                        normal_connected += int(user["connected"])
            if normal_total:
                raw_metrics["normal_user_connection_success_rate"] = normal_connected / normal_total
            decision_compute_samples = [
                float(event["decision_time_ms"])
                for event in events
                if event.get("event_type") == "optimizer_decision" and event.get("decision_time_ms") is not None
            ]
            decision_compute_ms = float(raw_metrics.get("algorithm_decision_total_ms", 0.0))
            decision_count = int(raw_metrics.get("algorithm_decision_count", len(decision_compute_samples)))
        else:
            result = run_fleet_policy(
                config,
                seed,
                trace,
                fleet_size=fleet_size,
                strategy_id=policy_id,
                options=options,
            )
            raw_metrics = dict(result["metrics"])
            geometry = _fleet_geometry(result)
            events = list(result["event_log"])
            latency_samples = [float(value) for value in result.get("latency_samples_ms", [])]
            decision_compute_samples = list(telemetry["plan_compute_ms"])
            decision_count = len(decision_compute_samples)
            decision_compute_ms = sum(decision_compute_samples)

    normalized = _normalize_metrics(raw_metrics)
    normalized["decision_compute_total_ms"] = decision_compute_ms
    normalized["decision_compute_call_count"] = decision_count
    normalized["decision_compute_mean_ms"] = (
        decision_compute_ms / decision_count if decision_count else 0.0
    )
    normalized["decision_compute_timing_scope"] = DECISION_SCOPE[policy_id]
    run = {
        "strategy_id": policy_id,
        "fleet_size": fleet_size,
        "metrics": normalized,
        "latency_samples_ms": latency_samples,
        "decision_compute_samples_ms": decision_compute_samples,
        "decision_event_count": sum(
            1 for event in events
            if event.get("event_type") in {"optimizer_decision", "fleet_decision"}
        ),
        "event_log": events,
        "geometry_timeline": geometry,
    }
    return run, geometry, latency_samples, decision_compute_samples


def _normalize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    first_time = metrics.get("network_recovery_time_s", metrics.get("first_full_recovery_time_s"))
    recovery_success = metrics.get("network_recovery_success", metrics.get("first_full_recovery_success"))
    if recovery_success is None:
        recovery_success = int(first_time is not None)
    sustained_time = metrics.get("sustained_rescue_recovery_time_s", metrics.get("sustained_30s_recovery_time_s"))
    sustained_success = metrics.get(
        "sustained_rescue_recovery_success", metrics.get("sustained_30s_recovery_success")
    )
    if sustained_success is None:
        sustained_success = int(sustained_time is not None)
    energy = metrics.get("drone_energy_consumed_wh", metrics.get("uav_energy_total_wh"))
    energy_per_service = metrics.get(
        "drone_energy_wh_per_rescue_user_hour", metrics.get("energy_wh_per_uav_rescue_user_hour")
    )
    compute = metrics.get("decision_compute_total_ms")
    if compute is None:
        compute = metrics.get("algorithm_decision_total_ms", metrics.get("coordination_compute_total_ms", 0.0))
    return {
        "rescue_user_service_success_rate": metrics.get("rescue_user_service_success_rate"),
        "normal_user_connection_success_rate": metrics.get("normal_user_connection_success_rate"),
        "user_connection_success_rate": metrics.get("user_connection_success_rate"),
        "first_full_recovery_success": int(recovery_success),
        "first_full_recovery_time_s": first_time,
        "first_full_recovery_or_censor_time_s": metrics.get(
            "network_recovery_or_censoring_time_s", metrics.get("first_full_recovery_or_censor_time_s")
        ),
        "sustained_30s_recovery_success": int(sustained_success),
        "sustained_30s_recovery_time_s": sustained_time,
        "uav_energy_total_wh": energy,
        "energy_wh_per_uav_rescue_user_hour": energy_per_service,
        "conditional_average_latency_ms": metrics.get("average_latency_ms"),
        "conditional_p95_latency_ms": metrics.get("p95_latency_ms"),
        "latency_sample_count": int(metrics.get("latency_sample_count", 0)),
        "decision_compute_total_ms": float(compute or 0.0),
        "decision_compute_mean_ms": metrics.get(
            "algorithm_decision_mean_ms", metrics.get("coordination_compute_mean_ms")
        ),
        "decision_count": int(metrics.get("algorithm_decision_count", metrics.get("coordination_decision_count", 0))),
        "target_switch_count": metrics.get("target_switch_count"),
        "uav_battery_minimum_wh": metrics.get("drone_battery_minimum_wh"),
        "uav_battery_remaining_wh": metrics.get("drone_battery_remaining_wh"),
        "raw_metric_source_keys": sorted(metrics),
    }


def _single_geometry(run: DynamicRun) -> list[dict[str, Any]]:
    frames = []
    for snapshot in run.state_snapshots:
        drone = snapshot["drone"]
        frames.append(
            {
                "time_s": snapshot["time_s"],
                "healthy_station_ids": sorted(
                    station["id"] for station in snapshot["stations"] if station["healthy"]
                ),
                "backhaul_available": bool(drone["backhaul_available"]),
                "uavs": [
                    {
                        "uav_id": drone["id"],
                        "position_km": [drone["x_km"], drone["y_km"]],
                        "active": bool(drone["active"]),
                    }
                ],
            }
        )
    return frames


def _fleet_geometry(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "time_s": frame["time_s"],
            "healthy_station_ids": frame["healthy_station_ids"],
            "backhaul_available": frame["backhaul_available"],
            "uavs": [
                {
                    "uav_id": uav["uav_id"],
                    "position_km": uav["position_km"],
                    "active": bool(uav["active"]),
                }
                for uav in frame["uavs"]
            ],
        }
        for frame in result["state_timeline"]
    ]


def _geometry_link_probe(
    config: DynamicExperimentConfig,
    trace: DynamicWorldTrace,
    frames: list[dict[str, Any]],
    seed: int,
    budget_config: LinkBudgetModelConfig,
) -> dict[str, Any]:
    legacy = LegacyDistanceModel()
    budget = LinkBudgetV1(budget_config, seed)
    checked = 0
    feasible_old = 0
    feasible_new = 0
    disagreements = 0
    rejected_old_feasible = 0

    def sample(profile: str, distance: float, limit: float, source: str, target: str) -> None:
        nonlocal checked, feasible_old, feasible_new, disagreements, rejected_old_feasible
        old = legacy.assess(profile, distance, limit, source, target, tolerance_km=1e-9).feasible
        new = budget.assess(profile, distance, limit, source, target, tolerance_km=1e-9).feasible
        checked += 1
        feasible_old += int(old)
        feasible_new += int(new)
        disagreements += int(old != new)
        rejected_old_feasible += int(old and not new)

    station_by_id = {station.id: station for station in config.base.stations}
    for tick, frame in enumerate(frames):
        user_positions = trace.user_positions_by_tick[tick]
        healthy = [station_by_id[item] for item in frame["healthy_station_ids"] if item in station_by_id]
        for station in healthy:
            for user_id, (ux, uy) in user_positions.items():
                sample(
                    "base_access", math.hypot(station.x_km - ux, station.y_km - uy),
                    station.coverage_radius_km, station.id, user_id,
                )
        for uav in frame["uavs"]:
            if not uav["active"]:
                continue
            ux, uy = map(float, uav["position_km"])
            uav_id = str(uav["uav_id"])
            for user_id, (user_x, user_y) in user_positions.items():
                sample(
                    "uav_access", math.hypot(ux - user_x, uy - user_y),
                    config.base.drone.access_radius_km, uav_id, user_id,
                )
            for station in healthy:
                sample(
                    "backhaul", math.hypot(ux - station.x_km, uy - station.y_km),
                    config.base.drone.backhaul_radius_km, station.id, uav_id,
                )
    return {
        "geometry_source": "same_seed_legacy_strategy_trajectory",
        "scope": "potential radio segment feasibility only; excludes capacity, global backhaul availability and user allocation",
        "checked_link_segments": checked,
        "legacy_feasible_count": feasible_old,
        "link_budget_feasible_count": feasible_new,
        "legacy_feasibility_rate": feasible_old / checked if checked else None,
        "link_budget_feasibility_rate": feasible_new / checked if checked else None,
        "model_disagreement_count": disagreements,
        "model_disagreement_rate": disagreements / checked if checked else None,
        "budget_rejected_legacy_feasible_count": rejected_old_feasible,
        "budget_rejection_rate_among_legacy_feasible": (
            rejected_old_feasible / feasible_old if feasible_old else None
        ),
    }


def run_comparison(
    partition: str,
    *,
    scenario_filter: str | None = None,
    seed_limit: int | None = None,
) -> dict[str, Any]:
    if partition not in {"development", "confirmation"}:
        raise ValueError("partition must be development or confirmation")
    seed_map = DEVELOPMENT_SEEDS if partition == "development" else CONFIRMATION_SEEDS
    scenarios = [scenario_filter] if scenario_filter else list(SCENARIOS)
    if any(scenario not in SCENARIOS for scenario in scenarios):
        raise ValueError(f"unknown scenario: {scenario_filter}")
    budget_config = load_link_budget_config(ROOT / LINK_CONFIG_PATH)
    plan_hash = sha256_file(ROOT / PHASE10_PLAN_PATH)
    source_hash = _source_sha256()
    records = []
    probes = []
    expected_trace_hashes: dict[tuple[str, int], str] = {}

    for scenario_id in scenarios:
        config_path = ROOT / SCENARIOS[scenario_id]
        config = load_dynamic_config(config_path)
        seeds = seed_map[scenario_id]
        if seed_limit is not None:
            seeds = seeds[:seed_limit]
        for seed in seeds:
            trace = build_world_trace(config, seed)
            expected_trace_hashes[(scenario_id, seed)] = trace.trace_sha256
            runs_by_policy_model: dict[tuple[str, str], dict[str, Any]] = {}
            for policy_id, fleet_size in POLICIES:
                for model_id in MODELS:
                    run, geometry, _latencies, _compute_samples = _run_policy(
                        config, trace, policy_id, fleet_size, model_id,
                        budget_config, seed,
                    )
                    runs_by_policy_model[(policy_id, model_id)] = run
                    model_payload = (
                        {"model_id": "legacy_distance", "parameters": "distance-threshold model from existing scenario"}
                        if model_id == "legacy_distance"
                        else {"model_id": "link_budget_v1", "parameters": budget_config.to_dict()}
                    )
                    config_hash = _stable_sha256(
                        {
                            "scenario_file_sha256": sha256_file(config_path),
                            "base_scenario_sha256": sha256_file(config.scenario_path),
                            "model": model_payload,
                            "model_seed": seed,
                            "policy_id": policy_id,
                            "fleet_size": fleet_size,
                            "phase10_plan_sha256": plan_hash,
                        }
                    )
                    records.append(
                        {
                            "scenario_id": scenario_id,
                            "seed": seed,
                            "policy_id": policy_id,
                            "fleet_size": fleet_size,
                            "model_id": model_id,
                            "world_trace_sha256": trace.trace_sha256,
                            "scenario_config_sha256": sha256_file(config_path),
                            "base_scenario_sha256": sha256_file(config.scenario_path),
                            "link_budget_config_sha256": sha256_file(ROOT / LINK_CONFIG_PATH),
                            "phase10_plan_sha256": plan_hash,
                            "configuration_sha256": config_hash,
                            "source_bundle_sha256": source_hash,
                            "metrics": run["metrics"],
                            "latency_samples_ms": run["latency_samples_ms"],
                            "decision_event_count": run["decision_event_count"],
                            "event_log": run["event_log"],
                            "geometry_timeline": run["geometry_timeline"],
                        }
                    )
            for policy_id, _fleet_size in POLICIES:
                legacy_run = runs_by_policy_model[(policy_id, "legacy_distance")]
                probes.append(
                    {
                        "scenario_id": scenario_id,
                        "seed": seed,
                        "policy_id": policy_id,
                        "world_trace_sha256": trace.trace_sha256,
                        "link_feasibility_probe": _geometry_link_probe(
                            config,
                            trace,
                            legacy_run["geometry_timeline"],
                            seed,
                            budget_config,
                        ),
                    }
                )

    if len(set(expected_trace_hashes.values())) != len(expected_trace_hashes):
        # Hashes may legitimately coincide only for empty/static traces; this
        # experiment has nonempty seeded user traces, so duplicates indicate a bug.
        raise RuntimeError("unexpected duplicate world trace hashes across scenario/seed pairs")

    seed_assignments = {
        scenario: list(seed_map[scenario])[:seed_limit] if seed_limit is not None else list(seed_map[scenario])
        for scenario in scenarios
    }
    return {
        "schema_version": "1.0",
        "phase": "phase14_radio_link_model",
        "partition": partition,
        "model_scope": "abstract_link_budget_research_model_not_calibrated_real_6g_or_device_measurement",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "source_bundle_sha256": source_hash,
        "link_budget_config_path": LINK_CONFIG_PATH,
        "link_budget_config_sha256": sha256_file(ROOT / LINK_CONFIG_PATH),
        "phase10_fleet_plan_sha256": plan_hash,
        "scenario_config_sha256": {
            scenario: {
                "dynamic": sha256_file(ROOT / SCENARIOS[scenario]),
                "base": sha256_file(load_dynamic_config(ROOT / SCENARIOS[scenario]).scenario_path),
            }
            for scenario in scenarios
        },
        "seed_assignments": seed_assignments,
        "policy_runs_per_seed": len(POLICIES) * len(MODELS),
        "seed_trajectory_pairing": "all models and policies reuse one pre-generated DynamicWorldTrace per scenario and seed",
        "shadowing_randomness": "stateless deterministic Gaussian keyed by run seed, profile, source ID, target ID; fixed over time and identical across strategies at matching endpoints",
        "decision_compute_timing": DECISION_SCOPE,
        "strategies": [{"policy_id": policy, "fleet_size": size} for policy, size in POLICIES],
        "records": records,
        "link_feasibility_probes": probes,
        "trace_hashes": [
            {"scenario_id": scenario, "seed": seed, "world_trace_sha256": digest}
            for (scenario, seed), digest in sorted(expected_trace_hashes.items())
        ],
    }


def summarize_comparison(raw: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], dict[str, dict[int, dict[str, Any]]]] = {}
    for record in raw["records"]:
        key = (record["scenario_id"], record["policy_id"], record["model_id"])
        grouped.setdefault(key, {})[record["seed"]] = record
    groups: dict[str, Any] = {}
    primary_tests = []
    for scenario_id in sorted({record["scenario_id"] for record in raw["records"]}):
        groups[scenario_id] = {}
        for policy_id, _size in POLICIES:
            old = grouped.get((scenario_id, policy_id, "legacy_distance"), {})
            new = grouped.get((scenario_id, policy_id, "link_budget_v1"), {})
            common = sorted(set(old) & set(new))
            if not common:
                continue
            old_records = [old[seed] for seed in common]
            new_records = [new[seed] for seed in common]
            old_service = [float(item["metrics"][PRIMARY_METRIC]) for item in old_records]
            new_service = [float(item["metrics"][PRIMARY_METRIC]) for item in new_records]
            primary = paired_test(old_service, new_service)
            primary_tests.append({
                "scenario_id": scenario_id,
                "policy_id": policy_id,
                "p_value": primary["p_value_two_sided"],
                "summary": primary,
            })
            groups[scenario_id][policy_id] = {
                "paired_seed_count": len(common),
                "legacy_distance": _summarize_runs(old_records),
                "link_budget_v1": _summarize_runs(new_records),
                "paired_link_budget_minus_legacy": {
                    "rescue_user_service_success_rate": primary,
                    "first_full_recovery_success": paired_test(
                        [float(item["metrics"]["first_full_recovery_success"]) for item in old_records],
                        [float(item["metrics"]["first_full_recovery_success"]) for item in new_records],
                    ),
                    "sustained_30s_recovery_success": paired_test(
                        [float(item["metrics"]["sustained_30s_recovery_success"]) for item in old_records],
                        [float(item["metrics"]["sustained_30s_recovery_success"]) for item in new_records],
                    ),
                    "uav_energy_total_wh": paired_test(
                        [float(item["metrics"]["uav_energy_total_wh"] or 0.0) for item in old_records],
                        [float(item["metrics"]["uav_energy_total_wh"] or 0.0) for item in new_records],
                    ),
                    "energy_wh_per_uav_rescue_user_hour": paired_optional_test(
                        [item["metrics"]["energy_wh_per_uav_rescue_user_hour"] for item in old_records],
                        [item["metrics"]["energy_wh_per_uav_rescue_user_hour"] for item in new_records],
                    ),
                    "decision_compute_total_ms": paired_test(
                        [float(item["metrics"]["decision_compute_total_ms"] or 0.0) for item in old_records],
                        [float(item["metrics"]["decision_compute_total_ms"] or 0.0) for item in new_records],
                    ),
                },
                "conditional_latency_comparison": _latency_comparison(old_records, new_records),
                "recovery_time_comparison": _recovery_comparison(old_records, new_records),
                "world_trace_hashes_match": all(
                    old[seed]["world_trace_sha256"] == new[seed]["world_trace_sha256"] for seed in common
                ),
            }
    valid_primary = [
        (index, float(item["p_value"]))
        for index, item in enumerate(primary_tests)
        if item["p_value"] is not None
    ]
    adjusted_valid = holm_adjust([value for _index, value in valid_primary])
    adjusted_by_index = {
        index: adjusted for (index, _value), adjusted in zip(valid_primary, adjusted_valid)
    }
    primary_adjusted = []
    for index, item in enumerate(primary_tests):
        primary_adjusted.append({
            "scenario_id": item["scenario_id"],
            "policy_id": item["policy_id"],
            "p_value_two_sided": item["p_value"],
            "p_value_holm": adjusted_by_index.get(index),
            "paired_difference": item["summary"]["mean_difference_new_minus_legacy"],
            "ci95": item["summary"]["ci95_mean_difference"],
            "inference_available": item["p_value"] is not None,
        })
    return {
        "schema_version": "1.0",
        "phase": raw["phase"],
        "partition": raw["partition"],
        "source_bundle_sha256": raw["source_bundle_sha256"],
        "link_budget_config_sha256": raw["link_budget_config_sha256"],
        "scenario_count": len(groups),
        "seed_count_per_scenario": {scenario: next(iter(policies.values()))["paired_seed_count"] for scenario, policies in groups.items() if policies},
        "policy_run_count": len(raw["records"]),
        "primary_endpoint": PRIMARY_METRIC,
        "primary_comparisons_holm": primary_adjusted,
        "scenarios": groups,
        "link_feasibility_probe_summary": summarize_link_probes(raw.get("link_feasibility_probes", [])),
        "statistical_methods": {
            "paired_effect": "paired mean difference (link_budget_v1 minus legacy_distance)",
            "confidence_interval": "two-sided 95% Student t interval over paired seed differences",
            "effect_size": "paired Cohen dz = mean paired difference / sample standard deviation of differences",
            "primary_multiplicity": "Holm step-down adjustment over rescue-service comparisons across all scenario-policy pairs",
            "latency": "pooled conditional samples; no paired causal interpretation because connected user-time sets can differ",
            "recovery_time": "successful-only duration and all-run horizon-censored duration reported separately; failures remain in success denominator",
        },
    }


def _summarize_runs(records: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [item["metrics"] for item in records]
    rescue = [float(item["rescue_user_service_success_rate"]) for item in metrics]
    normal = [float(item["normal_user_connection_success_rate"]) for item in metrics]
    all_users = [float(item["user_connection_success_rate"]) for item in metrics]
    recovery = [int(item["first_full_recovery_success"]) for item in metrics]
    sustained = [int(item["sustained_30s_recovery_success"]) for item in metrics]
    successes = [float(item["first_full_recovery_time_s"]) for item in metrics if item["first_full_recovery_time_s"] is not None]
    censored = [float(item["first_full_recovery_or_censor_time_s"]) for item in metrics]
    energies = [float(item["uav_energy_total_wh"] or 0.0) for item in metrics]
    energy_efficiencies = [item["energy_wh_per_uav_rescue_user_hour"] for item in metrics]
    energy_efficiencies_valid = [float(value) for value in energy_efficiencies if value is not None]
    compute = [float(item["decision_compute_total_ms"] or 0.0) for item in metrics]
    latency_values = [value for record in records for value in record["latency_samples_ms"]]
    return {
        "run_count": len(records),
        "rescue_user_service_success_rate": describe(rescue),
        "normal_user_connection_success_rate": describe(normal),
        "user_connection_success_rate": describe(all_users),
        "first_full_recovery": {
            "success_count": sum(recovery),
            "total_runs": len(recovery),
            "unrecovered_count": len(recovery) - sum(recovery),
            "success_rate_wilson95": wilson_interval(sum(recovery), len(recovery)),
            "successful_run_time_s": describe(successes),
            "all_run_horizon_censored_time_s": describe(censored),
        },
        "sustained_30s_recovery": {
            "success_count": sum(sustained),
            "total_runs": len(sustained),
            "failure_count": len(sustained) - sum(sustained),
            "success_rate_wilson95": wilson_interval(sum(sustained), len(sustained)),
        },
        "uav_energy_total_wh": describe(energies),
        "energy_wh_per_uav_rescue_user_hour": describe(energy_efficiencies_valid),
        "decision_compute_total_ms": describe(compute),
        "conditional_latency": {
            "pooled_successful_user_time_sample_count": len(latency_values),
            "pooled_mean_ms": statistics.fmean(latency_values) if latency_values else None,
            "pooled_p95_ms": nearest_rank(latency_values, 0.95),
            "mean_per_run_conditional_mean_ms": describe(
                [float(item["conditional_average_latency_ms"]) for item in metrics if item["conditional_average_latency_ms"] is not None]
            ),
            "mean_per_run_conditional_p95_ms": describe(
                [float(item["conditional_p95_latency_ms"]) for item in metrics if item["conditional_p95_latency_ms"] is not None]
            ),
            "sample_counts_by_run": [int(item["latency_sample_count"]) for item in metrics],
            "interpretation": "conditional on each run's successful user-time samples; sets can differ by model",
        },
        "target_switch_count": describe(
            [float(item["target_switch_count"]) for item in metrics if item["target_switch_count"] is not None]
        ),
    }


def _latency_comparison(old_records: list[dict[str, Any]], new_records: list[dict[str, Any]]) -> dict[str, Any]:
    old_values = [float(value) for record in old_records for value in record["latency_samples_ms"]]
    new_values = [float(value) for record in new_records for value in record["latency_samples_ms"]]
    return {
        "legacy_successful_user_time_samples": len(old_values),
        "link_budget_successful_user_time_samples": len(new_values),
        "legacy_pooled_conditional_mean_ms": statistics.fmean(old_values) if old_values else None,
        "link_budget_pooled_conditional_mean_ms": statistics.fmean(new_values) if new_values else None,
        "legacy_pooled_conditional_p95_ms": nearest_rank(old_values, 0.95),
        "link_budget_pooled_conditional_p95_ms": nearest_rank(new_values, 0.95),
        "paired_inference": False,
        "reason": "the successful user-time sample sets can differ between models",
    }


def _recovery_comparison(old_records: list[dict[str, Any]], new_records: list[dict[str, Any]]) -> dict[str, Any]:
    def view(records):
        metrics = [record["metrics"] for record in records]
        success_times = [float(item["first_full_recovery_time_s"]) for item in metrics if item["first_full_recovery_time_s"] is not None]
        censored_times = [float(item["first_full_recovery_or_censor_time_s"]) for item in metrics]
        success_count = sum(int(item["first_full_recovery_success"]) for item in metrics)
        return {
            "success_count": success_count,
            "total_runs": len(metrics),
            "unrecovered_count": len(metrics) - success_count,
            "successful_only_time_s": describe(success_times),
            "all_run_horizon_censored_time_s": describe(censored_times),
        }
    return {"legacy_distance": view(old_records), "link_budget_v1": view(new_records)}


def summarize_link_probes(probes: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for probe in probes:
        groups.setdefault(probe["scenario_id"], []).append(probe["link_feasibility_probe"])
    out = {}
    for scenario, items in groups.items():
        checked = sum(int(item["checked_link_segments"]) for item in items)
        old = sum(int(item["legacy_feasible_count"]) for item in items)
        new = sum(int(item["link_budget_feasible_count"]) for item in items)
        disagreements = sum(int(item["model_disagreement_count"]) for item in items)
        rejected = sum(int(item["budget_rejected_legacy_feasible_count"]) for item in items)
        out[scenario] = {
            "trajectory_count": len(items),
            "checked_link_segments": checked,
            "legacy_feasible_count": old,
            "link_budget_feasible_count": new,
            "legacy_feasibility_rate": old / checked if checked else None,
            "link_budget_feasibility_rate": new / checked if checked else None,
            "model_disagreement_rate": disagreements / checked if checked else None,
            "budget_rejected_legacy_feasible_count": rejected,
            "budget_rejection_rate_among_legacy_feasible": rejected / old if old else None,
        }
    return out


def sensitivity_variants(base: LinkBudgetModelConfig) -> dict[str, dict[str, Any]]:
    variants: dict[str, dict[str, Any]] = {"baseline": {"parameter": "baseline", "level": "base", "config": base}}

    def put(name: str, parameter: str, level: str, transform) -> None:
        variants[name] = {"parameter": parameter, "level": level, "config": _map_profiles(base, transform)}

    put("pathloss_exponent_low", "path_loss_exponent", "base - 0.2", lambda profile: replace(profile, path_loss_exponent=max(1.1, profile.path_loss_exponent - 0.2)))
    put("pathloss_exponent_high", "path_loss_exponent", "base + 0.2", lambda profile: replace(profile, path_loss_exponent=profile.path_loss_exponent + 0.2))
    put("tx_power_low", "tx_power_dbm", "base - 3 dB", lambda profile: replace(profile, tx_power_dbm=profile.tx_power_dbm - 3.0))
    put("tx_power_high", "tx_power_dbm", "base + 3 dB", lambda profile: replace(profile, tx_power_dbm=profile.tx_power_dbm + 3.0))
    put("rx_sensitivity_low", "rx_sensitivity_dbm", "base - 3 dB (less sensitive)", lambda profile: replace(profile, rx_sensitivity_dbm=profile.rx_sensitivity_dbm - 3.0))
    put("rx_sensitivity_high", "rx_sensitivity_dbm", "base + 3 dB (more sensitive)", lambda profile: replace(profile, rx_sensitivity_dbm=profile.rx_sensitivity_dbm + 3.0))
    put("fade_margin_low", "fade_margin_db", "base - 2 dB", lambda profile: replace(profile, fade_margin_db=max(0.0, profile.fade_margin_db - 2.0)))
    put("fade_margin_high", "fade_margin_db", "base + 2 dB", lambda profile: replace(profile, fade_margin_db=profile.fade_margin_db + 2.0))
    put("shadowing_low", "shadowing_sigma_db", "0 dB", lambda profile: replace(profile, shadowing_sigma_db=0.0))
    put("shadowing_high", "shadowing_sigma_db", "8 dB", lambda profile: replace(profile, shadowing_sigma_db=8.0))
    put("obstruction_low", "obstruction_loss_db", "0 dB", lambda profile: replace(profile, obstruction_loss_db=0.0))
    put("obstruction_high", "obstruction_loss_db", "12 dB", lambda profile: replace(profile, obstruction_loss_db=12.0))
    return variants


def _map_profiles(config: LinkBudgetModelConfig, transform) -> LinkBudgetModelConfig:
    return replace(
        config,
        base_access=transform(config.base_access),
        uav_access=transform(config.uav_access),
        backhaul=transform(config.backhaul),
    )


def run_sensitivity(*, seed_limit: int | None = None) -> dict[str, Any]:
    budget_config = load_link_budget_config(ROOT / LINK_CONFIG_PATH)
    variants = sensitivity_variants(budget_config)
    records = []
    for scenario_id, config_path_relative in SCENARIOS.items():
        config_path = ROOT / config_path_relative
        config = load_dynamic_config(config_path)
        seeds = DEVELOPMENT_SEEDS[scenario_id]
        if seed_limit is not None:
            seeds = seeds[:seed_limit]
        for seed in seeds:
            trace = build_world_trace(config, seed)
            for variant_id, variant in variants.items():
                if variant_id == "baseline":
                    policies = (("Bprime_static_grid_shared_safety", 1), ("G_centralized_coordination", 3))
                else:
                    policies = (("Bprime_static_grid_shared_safety", 1), ("G_centralized_coordination", 3))
                variant_config: LinkBudgetModelConfig = variant["config"]
                for policy_id, fleet_size in policies:
                    run, _geometry, _latencies, _compute_samples = _run_policy(
                        config, trace, policy_id, fleet_size, "link_budget_v1",
                        variant_config, seed,
                    )
                    records.append(
                        {
                            "scenario_id": scenario_id,
                            "seed": seed,
                            "world_trace_sha256": trace.trace_sha256,
                            "policy_id": policy_id,
                            "fleet_size": fleet_size,
                            "variant_id": variant_id,
                            "parameter": variant["parameter"],
                            "level": variant["level"],
                            "profile_values": {
                                "base_access": asdict(variant_config.base_access),
                                "uav_access": asdict(variant_config.uav_access),
                                "backhaul": asdict(variant_config.backhaul),
                            },
                            "metrics": run["metrics"],
                            "latency_samples_ms": run["latency_samples_ms"],
                            "source_bundle_sha256": _source_sha256(),
                            "scenario_config_sha256": sha256_file(config_path),
                            "base_scenario_sha256": sha256_file(config.scenario_path),
                            "link_budget_config_sha256": sha256_file(ROOT / LINK_CONFIG_PATH),
                        }
                    )
    baseline_map = {
        (item["scenario_id"], item["seed"], item["policy_id"]): item
        for item in records if item["variant_id"] == "baseline"
    }
    for item in records:
        base = baseline_map[(item["scenario_id"], item["seed"], item["policy_id"])]
        item["paired_baseline_differences"] = {
            key: (
                float(item["metrics"][key]) - float(base["metrics"][key])
                if item["metrics"].get(key) is not None and base["metrics"].get(key) is not None
                else None
            )
            for key in (
                "rescue_user_service_success_rate",
                "first_full_recovery_success",
                "sustained_30s_recovery_success",
                "uav_energy_total_wh",
                "energy_wh_per_uav_rescue_user_hour",
                "decision_compute_total_ms",
            )
        }
    summary = _summarize_sensitivity(records)
    return {
        "schema_version": "1.0",
        "phase": "phase14_radio_link_model_sensitivity",
        "partition": "exploratory_development_only",
        "source_bundle_sha256": _source_sha256(),
        "link_budget_config_sha256": sha256_file(ROOT / LINK_CONFIG_PATH),
        "seed_assignments": {scenario: list(DEVELOPMENT_SEEDS[scenario])[:seed_limit] if seed_limit is not None else list(DEVELOPMENT_SEEDS[scenario]) for scenario in SCENARIOS},
        "factorial_design": "one-factor-at-a-time; 1 baseline + 12 perturbed variants; only Bprime and G3; no safety or capacity checks disabled",
        "sample_limitations": "three development seeds per scenario; screening only, not confirmation; all repeated runs are paired to the same trace and seed",
        "variant_definitions": {
            key: {"parameter": value["parameter"], "level": value["level"], "profile_values": {
                "base_access": asdict(value["config"].base_access),
                "uav_access": asdict(value["config"].uav_access),
                "backhaul": asdict(value["config"].backhaul),
            }}
            for key, value in variants.items()
        },
        "records": records,
        "summary": summary,
    }


def _summarize_sensitivity(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (record["scenario_id"], record["policy_id"], record["variant_id"])
        grouped.setdefault(key, []).append(record)
    out = {}
    for (scenario, policy, variant), items in sorted(grouped.items()):
        out.setdefault(scenario, {}).setdefault(policy, {})[variant] = {
            "parameter": items[0]["parameter"],
            "level": items[0]["level"],
            "seed_count": len(items),
            "rescue_user_service_success_rate": describe([
                float(item["metrics"]["rescue_user_service_success_rate"]) for item in items
            ]),
            "first_full_recovery_success_count": sum(
                int(item["metrics"]["first_full_recovery_success"]) for item in items
            ),
            "sustained_30s_recovery_success_count": sum(
                int(item["metrics"]["sustained_30s_recovery_success"]) for item in items
            ),
            "uav_energy_total_wh": describe([
                float(item["metrics"]["uav_energy_total_wh"] or 0.0) for item in items
            ]),
            "decision_compute_total_ms": describe([
                float(item["metrics"]["decision_compute_total_ms"] or 0.0) for item in items
            ]),
            "paired_service_delta_from_baseline": describe([
                float(item["paired_baseline_differences"]["rescue_user_service_success_rate"])
                for item in items if item["paired_baseline_differences"]["rescue_user_service_success_rate"] is not None
            ]),
            "interpretation": "exploratory; no independent validation inference",
        }
    return out


def describe(values: Iterable[float]) -> dict[str, Any]:
    sample = [float(value) for value in values if math.isfinite(float(value))]
    n = len(sample)
    if not n:
        return {"n": 0, "mean": None, "sample_sd": None, "ci95": None}
    mean = statistics.fmean(sample)
    sd = statistics.stdev(sample) if n > 1 else None
    margin = t_critical_975(n - 1) * sd / math.sqrt(n) if sd is not None else None
    return {
        "n": n,
        "mean": mean,
        "sample_sd": sd,
        "ci95": [mean - margin, mean + margin] if margin is not None else None,
        "min": min(sample),
        "max": max(sample),
    }


def paired_test(old: list[float], new: list[float]) -> dict[str, Any]:
    if len(old) != len(new) or not old:
        raise ValueError("paired samples must have the same positive length")
    differences = [float(after) - float(before) for before, after in zip(old, new)]
    info = describe(differences)
    mean = info["mean"]
    sd = info["sample_sd"]
    if sd is None:
        statistic = None
        p_value = None
        dz = None
    elif sd == 0:
        statistic = 0.0 if mean == 0 else None
        p_value = 1.0 if mean == 0 else 0.0
        dz = 0.0 if mean == 0 else None
    else:
        statistic = mean / (sd / math.sqrt(len(differences)))
        p_value = student_t_two_sided_p(statistic, len(differences) - 1)
        dz = mean / sd
    return {
        "n_pairs": len(differences),
        "mean_difference_new_minus_legacy": mean,
        "sample_sd_of_difference": sd,
        "ci95_mean_difference": info["ci95"],
        "paired_cohen_dz": dz,
        "t_statistic": statistic,
        "p_value_two_sided": p_value,
        "zero_variance_of_paired_differences": sd == 0 if sd is not None else None,
    }


def paired_optional_test(old: list[Any], new: list[Any]) -> dict[str, Any]:
    if len(old) != len(new):
        raise ValueError("optional paired samples must have the same length")
    pairs = [
        (float(before), float(after))
        for before, after in zip(old, new)
        if before is not None and after is not None
    ]
    if not pairs:
        return {"n_pairs": 0, "excluded_pairs": len(old), "reason": "metric unavailable in at least one paired run"}
    result = paired_test([pair[0] for pair in pairs], [pair[1] for pair in pairs])
    result["excluded_pairs"] = len(old) - len(pairs)
    return result


def holm_adjust(p_values: list[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 0.0
    for rank, index in enumerate(order):
        value = min(1.0, (count - rank) * p_values[index])
        running = max(running, value)
        adjusted[index] = running
    return adjusted


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total <= 0:
        return None
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def nearest_rank(values: Iterable[float], percentile: float) -> float | None:
    sample = sorted(float(value) for value in values)
    if not sample:
        return None
    rank = max(1, math.ceil(percentile * len(sample)))
    return sample[rank - 1]


def t_critical_975(df: int) -> float:
    if df <= 0:
        raise ValueError("degrees of freedom must be positive")
    low, high = 0.0, 100.0
    for _ in range(90):
        middle = (low + high) / 2.0
        if student_t_cdf(middle, df) < 0.975:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def student_t_two_sided_p(statistic: float, df: int) -> float:
    if math.isinf(statistic):
        return 0.0
    return max(0.0, min(1.0, 2.0 * (1.0 - student_t_cdf(abs(statistic), df))))


def student_t_cdf(value: float, df: int) -> float:
    if df <= 0:
        raise ValueError("degrees of freedom must be positive")
    if value == 0:
        return 0.5
    x = df / (df + value * value)
    tail = 0.5 * regularized_beta(x, df / 2.0, 0.5)
    return 1.0 - tail if value > 0 else tail


def regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * beta_continued_fraction(a, b, x) / a
    return 1.0 - front * beta_continued_fraction(b, a, 1.0 - x) / b


def beta_continued_fraction(a: float, b: float, x: float) -> float:
    max_iterations = 200
    epsilon = 3e-14
    tiny = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < epsilon:
            return h
    raise ArithmeticError("incomplete beta continued fraction did not converge")
