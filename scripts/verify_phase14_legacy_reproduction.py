"""Re-run one frozen Phase 10 B′ case through the Phase 14 legacy adapter."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.dynamic_config import load_dynamic_config  # noqa: E402
from lowalt6g.dynamic_world import build_world_trace  # noqa: E402
from lowalt6g.phase14_experiments import (  # noqa: E402
    LINK_CONFIG_PATH,
    ROOT as PROJECT_ROOT,
    SCENARIOS,
    _run_policy,
    load_link_budget_config,
    sha256_file,
)


HISTORICAL_RAW = ROOT / "results/phase10_confirmation_raw.json"
OUTPUT = ROOT / "results/phase14_legacy_reproduction.json"
SCENE = "severe_persistent_faults"
SEED = 94100
STRATEGY_KEY = "Bprime_static_grid_shared_safety_uav1"

# Wall-clock timings are intentionally excluded: they are runtime-dependent.
METRIC_MAP = {
    "rescue_user_service_success_rate": "rescue_user_service_success_rate",
    "normal_user_connection_success_rate": "normal_user_connection_success_rate",
    "user_connection_success_rate": "user_connection_success_rate",
    "first_full_recovery_success": "first_full_recovery_success",
    "first_full_recovery_time_s": "first_full_recovery_time_s",
    "sustained_30s_recovery_success": "sustained_30s_recovery_success",
    "sustained_30s_recovery_time_s": "sustained_30s_recovery_time_s",
    "drone_energy_consumed_wh": "uav_energy_total_wh",
    "drone_energy_wh_per_rescue_user_hour": "energy_wh_per_uav_rescue_user_hour",
    "average_latency_ms": "conditional_average_latency_ms",
    "p95_latency_ms": "conditional_p95_latency_ms",
    "latency_sample_count": "latency_sample_count",
}


def verify() -> dict:
    historical = json.loads(HISTORICAL_RAW.read_text(encoding="utf-8"))
    old_record = next(
        row for row in historical["records"]
        if row["scenario_id"] == SCENE and int(row["seed"]) == SEED
    )
    old_run = old_record["strategy_runs"][STRATEGY_KEY]
    old_metrics = old_run["metrics"]

    config_path = PROJECT_ROOT / SCENARIOS[SCENE]
    config = load_dynamic_config(config_path)
    trace = build_world_trace(config, SEED)
    budget_config = load_link_budget_config(PROJECT_ROOT / LINK_CONFIG_PATH)
    replay, _, _, _ = _run_policy(
        config,
        trace,
        "Bprime_static_grid_shared_safety",
        1,
        "legacy_distance",
        budget_config,
        SEED,
    )
    replay_metrics = replay["metrics"]
    comparisons = {
        old_key: {
            "historical": old_metrics.get(old_key),
            "replayed": replay_metrics.get(new_key),
            "matches": old_metrics.get(old_key) == replay_metrics.get(new_key),
        }
        for old_key, new_key in METRIC_MAP.items()
    }
    trace_matches = trace.trace_sha256 == old_record["world_trace_sha256"]
    metrics_match = all(item["matches"] for item in comparisons.values())
    return {
        "schema_version": "1.0",
        "status": "PASS" if trace_matches and metrics_match else "FAIL",
        "historical_source": "results/phase10_confirmation_raw.json",
        "historical_source_sha256": sha256_file(HISTORICAL_RAW),
        "scenario_id": SCENE,
        "seed": SEED,
        "strategy_id": "Bprime_static_grid_shared_safety",
        "model_id": "legacy_distance",
        "historical_trace_sha256": old_record["world_trace_sha256"],
        "replayed_trace_sha256": trace.trace_sha256,
        "trace_matches": trace_matches,
        "metrics_match": metrics_match,
        "compared_metric_count": len(comparisons),
        "wall_clock_compute_time_compared": False,
        "metric_comparisons": comparisons,
        "config_sha256": sha256_file(config_path),
    }


if __name__ == "__main__":
    result = verify()
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "trace_matches": result["trace_matches"], "metrics_match": result["metrics_match"], "output": str(OUTPUT)}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
