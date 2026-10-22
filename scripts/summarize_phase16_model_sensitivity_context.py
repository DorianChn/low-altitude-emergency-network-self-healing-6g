"""Create a labeled Phase 16 re-analysis of existing Phase 14 model-stress results.

This script does not run simulations and never treats the stress levels as
measurement uncertainty distributions.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/phase14_model_sensitivity_summary.json"
OUTPUT = ROOT / "results/phase16_exploratory_model_sensitivity_context.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    source_hash = sha256(SOURCE)
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    scenarios: dict[str, object] = {}
    for scenario_id, policies in source.items():
        scenarios[scenario_id] = {}
        for policy_id, variants in policies.items():
            baseline = variants["baseline"]
            base_rate = baseline["rescue_user_service_success_rate"]["mean"]
            base_first = baseline.get("first_full_recovery_success_count")
            base_sustained = baseline.get("sustained_30s_recovery_success_count")
            rows = []
            for variant_id, result in variants.items():
                if variant_id == "baseline":
                    continue
                service = result["rescue_user_service_success_rate"]["mean"]
                rows.append({
                    "variant_id": variant_id,
                    "parameter": result.get("parameter"),
                    "level": result.get("level"),
                    "seed_count": result.get("seed_count"),
                    "rescue_service_mean": service,
                    "paired_delta_from_variant_baseline": service - base_rate,
                    "first_full_recovery_success_count": result.get("first_full_recovery_success_count"),
                    "sustained_30s_recovery_success_count": result.get("sustained_30s_recovery_success_count"),
                })
            delta_values = [item["paired_delta_from_variant_baseline"] for item in rows]
            scenarios[scenario_id][policy_id] = {
                "seed_count": baseline.get("seed_count"),
                "baseline_rescue_service_mean": base_rate,
                "baseline_first_full_recovery_success_count": base_first,
                "baseline_sustained_30s_recovery_success_count": base_sustained,
                "stress_variant_count": len(rows),
                "stress_delta_min": min(delta_values) if delta_values else None,
                "stress_delta_max": max(delta_values) if delta_values else None,
                "variants": rows,
            }
    output = {
        "schema_version": "1.0",
        "phase": "phase16_exploratory_parameter_stress_context",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "REANALYSIS_ONLY_NO_NEW_SIMULATIONS",
        "source_path": "results/phase14_model_sensitivity_summary.json",
        "source_sha256": source_hash,
        "source_experiment_role": "Phase 14 exploratory development sensitivity; 3 seeds per scenario; not independent confirmation",
        "phase16_project_device_uncertainty_propagation": "NOT_EXECUTED_NO_TARGET_DEVICE_UNCERTAINTY_DISTRIBUTIONS",
        "interpretation_boundary": "These are deterministic model stress levels inherited from Phase 14 (including ±2 dB fade margin, ±0.2 path-loss exponent, ±3 dB transmit power or sensitivity, and zero/12 dB obstruction). They are not empirically estimated device uncertainty bounds, probability distributions, measurement confidence intervals, or calibration evidence.",
        "scenarios": scenarios,
    }
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": output["status"],
        "scenario_count": len(scenarios),
        "policy_scenario_comparisons": sum(len(policies) for policies in scenarios.values()),
        "source_sha256": source_hash,
        "output": OUTPUT.relative_to(ROOT).as_posix(),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
