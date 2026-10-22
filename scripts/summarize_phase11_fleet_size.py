"""Supplementary paired 3-UAV versus 2-UAV analysis.

This was computed after the frozen primary analysis to answer the requested
fleet-size question. It is reported as exploratory, not as a pre-registered
primary hypothesis family.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from lowalt6g.phase10_experiments import (
    _mcnemar_from_differences,
    _paired_effect,
    _paired_sign_flip,
)
from lowalt6g.phase8_experiments import _holm_adjust


ROOT = Path(__file__).resolve().parents[1]
SCENES = (
    "severe_persistent_faults",
    "dynamic_failures",
    "high_mobility_rescue",
    "high_load_backhaul_limit",
)
STRATEGIES = (
    "F_independent_greedy",
    "G_centralized_coordination",
    "H_marginal_rescue_greedy",
    "I_constrained_user_assignment",
    "J_budgeted_joint_beam",
)


def main() -> None:
    raw_path = ROOT / "results/phase11_confirmation_raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    index = {
        (row["scenario_id"], int(row["seed"]), row["strategy_id"], int(row["fleet_size"])): row
        for row in raw["records"]
    }
    results: dict[str, dict] = {}
    families = {"rescue_service": [], "first_full": [], "sustained_30s": []}
    for scene in SCENES:
        results[scene] = {}
        for strategy in STRATEGIES:
            seed_ids = sorted(
                seed for (scenario, seed, policy, size) in index
                if scenario == scene and policy == strategy and size == 2
            )
            two = [index[(scene, seed, strategy, 2)] for seed in seed_ids]
            three = [index[(scene, seed, strategy, 3)] for seed in seed_ids]
            contrast = f"{strategy}_uav3__minus__uav2"
            rescue = [
                float(b["metrics"]["rescue_user_service_success_rate"])
                - float(a["metrics"]["rescue_user_service_success_rate"])
                for a, b in zip(two, three, strict=True)
            ]
            entry = {
                "paired_seed_count": len(seed_ids),
                "fleet3_minus_fleet2": {
                    "rescue_user_service_success_rate": {
                        **_paired_effect(rescue),
                        **_paired_sign_flip(rescue),
                    }
                },
            }
            families["rescue_service"].append(
                {
                    "scenario_id": scene,
                    "contrast": contrast,
                    "p_exact_two_sided": entry["fleet3_minus_fleet2"]["rescue_user_service_success_rate"]["p_exact_two_sided"],
                    "target": entry["fleet3_minus_fleet2"]["rescue_user_service_success_rate"],
                }
            )
            for metric, family in (
                ("first_full_recovery_success", "first_full"),
                ("sustained_30s_recovery_success", "sustained_30s"),
            ):
                differences = [
                    float(b["metrics"].get(metric, 0)) - float(a["metrics"].get(metric, 0))
                    for a, b in zip(two, three, strict=True)
                ]
                left_successes = sum(int(a["metrics"].get(metric, 0)) for a in two)
                right_successes = sum(int(b["metrics"].get(metric, 0)) for b in three)
                entry["fleet3_minus_fleet2"][metric] = {
                    **_paired_effect(differences),
                    "fleet2_successes": left_successes,
                    "fleet3_successes": right_successes,
                    "total_pairs": len(seed_ids),
                    "fleet2_failures": len(seed_ids) - left_successes,
                    "fleet3_failures": len(seed_ids) - right_successes,
                    **_mcnemar_from_differences(differences),
                }
                families[family].append(
                    {
                        "scenario_id": scene,
                        "contrast": contrast,
                        "p_exact_two_sided": entry["fleet3_minus_fleet2"][metric]["p_exact_two_sided"],
                        "target": entry["fleet3_minus_fleet2"][metric],
                    }
                )
            results[scene][strategy] = entry

    for family, tests in families.items():
        _holm_adjust(tests)
        for test in tests:
            test["target"]["p_holm_adjusted"] = test.get("p_holm_adjusted")
            test["target"]["holm_family_size"] = test.get("holm_family_size")
    output = {
        "schema_version": "1.0",
        "phase": "phase11_baseline_benchmark",
        "analysis_role": "supplementary_exploratory_fleet_size_contrasts",
        "source_raw_sha256": __import__("hashlib").sha256(raw_path.read_bytes()).hexdigest(),
        "method": "Paired differences between the same strategy at three versus two UAVs for each scene-seed; t 95% CI, Cohen dz/Hedges gz, exact sign-flip for rescue rate, exact McNemar for recovery; Holm correction within each 20-comparison endpoint family.",
        "note": "Supplementary fleet-size analyses answer a pre-existing project question but were not in the frozen Phase 11 primary contrast list; interpret as exploratory.",
        "holm_family_sizes": {key: len(items) for key, items in families.items()},
        "scenarios": results,
    }
    output_path = ROOT / "results/phase11_fleet_size_exploratory.json"
    payload = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")
        if existing != payload:
            raise SystemExit(
                "existing Phase 11 fleet-size result differs; refusing to overwrite it"
            )
    else:
        output_path.write_text(payload, encoding="utf-8", newline="\n")
    print(output_path)


if __name__ == "__main__":
    main()
