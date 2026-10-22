"""Run Phase 14 development, sensitivity, or frozen confirmation experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase14_experiments import (  # noqa: E402
    CONFIRMATION_SEEDS,
    DEVELOPMENT_SEEDS,
    LINK_CONFIG_PATH,
    PHASE10_PLAN_PATH,
    SCENARIOS,
    _source_sha256,
    _stable_sha256,
    run_comparison,
    run_sensitivity,
    sha256_file,
    summarize_comparison,
)


PROTOCOL_PATH = ROOT / "configs/phase14/confirmation_protocol.json"


def _write_json(path: Path, value: Any, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def freeze_protocol() -> dict[str, Any]:
    """Write the confirmation plan once, after code/config/development are fixed."""
    if PROTOCOL_PATH.exists():
        raise FileExistsError(f"confirmation protocol already exists: {PROTOCOL_PATH}")
    all_dev = {seed for values in DEVELOPMENT_SEEDS.values() for seed in values}
    all_confirm = {seed for values in CONFIRMATION_SEEDS.values() for seed in values}
    if all_dev & all_confirm:
        raise RuntimeError("development and confirmation seed sets overlap")
    plan = {
        "schema_version": "1.0",
        "phase": "phase14_radio_link_model",
        "status": "frozen_before_confirmation",
        "frozen_source_bundle_sha256": _source_sha256(),
        "frozen_link_budget_config_sha256": sha256_file(ROOT / LINK_CONFIG_PATH),
        "frozen_phase10_plan_sha256": sha256_file(ROOT / PHASE10_PLAN_PATH),
        "scenario_config_sha256": {
            key: sha256_file(ROOT / path) for key, path in SCENARIOS.items()
        },
        "development_seeds": {key: list(value) for key, value in DEVELOPMENT_SEEDS.items()},
        "confirmation_seeds": {key: list(value) for key, value in CONFIRMATION_SEEDS.items()},
        "seed_partitions_disjoint": True,
        "strategies": [
            "Bprime_static_grid_shared_safety",
            "F_independent_greedy (3 UAV)",
            "G_centralized_coordination (3 UAV)",
        ],
        "models": ["legacy_distance", "link_budget_v1"],
        "primary_endpoint": "rescue_user_service_success_rate",
        "primary_comparison": "within each scenario and policy, paired seed difference link_budget_v1 minus legacy_distance",
        "primary_multiplicity": "Holm correction across 12 scenario-policy comparisons",
        "confirmation_seed_count": sum(len(items) for items in CONFIRMATION_SEEDS.values()),
        "confirmation_runs": sum(len(items) for items in CONFIRMATION_SEEDS.values()) * 3 * 2,
        "sensitivity_analysis": "one-factor-at-a-time development screen only; no confirmation tuning",
        "model_claim_boundary": "abstract research link budget; no real equipment calibration, full channel model, SINR, or interference",
    }
    _write_json(PROTOCOL_PATH, plan, overwrite=False)
    return plan


def check_frozen_protocol() -> dict[str, Any]:
    plan = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    checks = {
        "status_frozen": plan.get("status") == "frozen_before_confirmation",
        "source_bundle_matches": plan.get("frozen_source_bundle_sha256") == _source_sha256(),
        "link_config_matches": plan.get("frozen_link_budget_config_sha256") == sha256_file(ROOT / LINK_CONFIG_PATH),
        "phase10_plan_matches": plan.get("frozen_phase10_plan_sha256") == sha256_file(ROOT / PHASE10_PLAN_PATH),
        "scenario_configs_match": plan.get("scenario_config_sha256") == {
            key: sha256_file(ROOT / path) for key, path in SCENARIOS.items()
        },
        "seed_assignments_match": plan.get("confirmation_seeds") == {
            key: list(value) for key, value in CONFIRMATION_SEEDS.items()
        },
    }
    if not all(checks.values()):
        failed = ", ".join(key for key, passed in checks.items() if not passed)
        raise RuntimeError(f"confirmation freeze check failed: {failed}")
    return {"passed": True, "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partition", choices=("development", "confirmation"), default="development")
    parser.add_argument("--scenario", choices=tuple(SCENARIOS))
    parser.add_argument("--seed-limit", type=int)
    parser.add_argument("--sensitivity", action="store_true")
    parser.add_argument("--freeze-confirmation", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.freeze_confirmation:
        if args.sensitivity or args.scenario or args.seed_limit is not None:
            parser.error("--freeze-confirmation cannot be combined with run filters")
        plan = freeze_protocol()
        print(json.dumps({"status": plan["status"], "protocol": str(PROTOCOL_PATH), "source_hash": plan["frozen_source_bundle_sha256"]}, indent=2))
        return 0

    if args.partition == "confirmation":
        print(json.dumps(check_frozen_protocol(), indent=2))
        if args.sensitivity or args.scenario or args.seed_limit is not None:
            parser.error("confirmation runs use the complete frozen seed set")

    if args.sensitivity:
        if args.partition != "development":
            parser.error("sensitivity analysis is development-only")
        raw = run_sensitivity(seed_limit=args.seed_limit)
        raw_name = "phase14_model_sensitivity_raw.json"
        summary_name = "phase14_model_sensitivity_summary.json"
        summary = raw["summary"]
    else:
        raw = run_comparison(
            args.partition,
            scenario_filter=args.scenario,
            seed_limit=args.seed_limit,
        )
        raw_name = f"phase14_{args.partition}_raw.json"
        summary_name = f"phase14_{args.partition}_summary.json"
        summary = summarize_comparison(raw)

    raw_path = ROOT / "results" / raw_name
    summary_path = ROOT / "results" / summary_name
    _write_json(raw_path, raw, overwrite=args.overwrite)
    _write_json(summary_path, summary, overwrite=args.overwrite)
    print(json.dumps({
        "raw": str(raw_path),
        "summary": str(summary_path),
        "raw_sha256": sha256_file(raw_path),
        "summary_sha256": sha256_file(summary_path),
        "record_count": len(raw.get("records", [])),
        "partition": raw.get("partition"),
        "scenario_count": len(raw.get("seed_assignments", {})),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
