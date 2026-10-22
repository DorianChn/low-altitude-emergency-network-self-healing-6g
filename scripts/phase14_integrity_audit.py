"""Read-only audit of Phase 14 outputs and historical frozen result hashes."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase14_experiments import (  # noqa: E402
    CONFIRMATION_SEEDS,
    POLICIES,
    _source_sha256,
    sha256_file,
)


def read_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _add_expected(expected: dict[str, str], relative: str, value) -> None:
    if not isinstance(value, str) or len(value) != 64:
        return
    previous = expected.get(relative)
    if previous is not None and previous != value:
        raise ValueError(f"conflicting frozen hashes for {relative}: {previous} != {value}")
    expected[relative] = value


def frozen_hashes() -> dict[str, str]:
    expected: dict[str, str] = {}
    phase13 = read_json("results/phase13_visualization_audit.json")
    for item in phase13.get("data_sources", {}).values():
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            _add_expected(expected, item["path"], item.get("sha256"))

    phase9 = read_json("results/phase9_artifact_manifest.json")
    for path, value in phase9.get("protected_historical_sha256", {}).items():
        _add_expected(expected, path, value)
    for path, value in phase9.get("artifacts", {}).items():
        _add_expected(expected, path, value.get("sha256") if isinstance(value, dict) else value)

    phase10 = read_json("results/phase10_artifact_manifest.json")
    for path, value in phase10.get("artifacts_sha256", {}).items():
        _add_expected(expected, path, value)

    phase11 = read_json("results/phase11_artifact_manifest.json")
    for path, value in phase11.get("artifacts", {}).items():
        _add_expected(expected, path, value.get("sha256") if isinstance(value, dict) else value)
    return expected


def _numeric_leaves(value):
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _numeric_leaves(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _numeric_leaves(item)


def _historical_seed_values(value, *, in_seed_field: bool = False):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _historical_seed_values(
                item,
                in_seed_field=in_seed_field or "seed" in str(key).lower(),
            )
    elif in_seed_field:
        yield from _numeric_leaves(value)
    elif isinstance(value, list):
        for item in value:
            yield from _historical_seed_values(item, in_seed_field=False)


def audit_phase14() -> dict:
    errors: list[str] = []
    expected = frozen_hashes()
    historical_results = []
    for relative, expected_hash in sorted(expected.items()):
        path = ROOT / relative
        exists = path.is_file()
        actual_hash = digest(path) if exists else None
        matches = exists and actual_hash == expected_hash
        if not matches:
            errors.append(f"historical hash mismatch or missing: {relative}")
        historical_results.append({
            "path": relative,
            "expected_sha256": expected_hash,
            "actual_sha256": actual_hash,
            "matches": matches,
        })

    phase13 = read_json("results/phase13_visualization_audit.json")
    replay = phase13.get("phase6_replay_integrity", {})
    replay_results = []
    replay_manifest_path = ROOT / str(replay.get("manifest", "results/phase6_demo_manifest.json"))
    manifest_matches = replay_manifest_path.is_file() and digest(replay_manifest_path) == replay.get("manifest_sha256")
    if not manifest_matches:
        errors.append("Phase 6 replay manifest hash mismatch or missing")
    replay_results.append({
        "path": str(replay.get("manifest", "results/phase6_demo_manifest.json")),
        "matches": manifest_matches,
    })
    for scene, item in replay.get("scenarios", {}).items():
        relative = str(item.get("artifact", ""))
        path = ROOT / relative
        matches = path.is_file() and digest(path) == item.get("sha256")
        if not matches:
            errors.append(f"Phase 6 replay hash mismatch or missing: {relative}")
        replay_results.append({"scenario_id": scene, "path": relative, "matches": matches})

    raw = read_json("results/phase14_confirmation_raw.json")
    summary = read_json("results/phase14_confirmation_summary.json")
    protocol = read_json("configs/phase14/confirmation_protocol.json")
    sensitivity_raw = read_json("results/phase14_model_sensitivity_raw.json")
    sensitivity_summary = read_json("results/phase14_model_sensitivity_summary.json")
    legacy_reproduction = read_json("results/phase14_legacy_reproduction.json")
    expected_runs = sum(len(seeds) for seeds in CONFIRMATION_SEEDS.values()) * len(POLICIES) * 2
    records = raw.get("records", [])
    by_seed: dict[tuple[str, int], list[dict]] = {}
    for record in records:
        by_seed.setdefault((record["scenario_id"], int(record["seed"])), []).append(record)
    per_seed_complete = all(
        len(by_seed.get((scenario, seed), [])) == len(POLICIES) * 2
        and len({item["world_trace_sha256"] for item in by_seed[(scenario, seed)]}) == 1
        for scenario, seeds in CONFIRMATION_SEEDS.items()
        for seed in seeds
    )
    protocol_matches = (
        protocol.get("status") == "frozen_before_confirmation"
        and protocol.get("frozen_source_bundle_sha256") == raw.get("source_bundle_sha256") == _source_sha256()
    )
    confirm_complete = (
        raw.get("partition") == "confirmation"
        and len(records) == expected_runs
        and len(by_seed) == sum(len(items) for items in CONFIRMATION_SEEDS.values())
        and per_seed_complete
        and protocol_matches
        and summary.get("policy_run_count") == expected_runs
    )
    if not confirm_complete:
        errors.append("Phase 14 confirmation counts, paired traces, or frozen source hash do not match protocol")
    historical_seeds: set[int] = set()
    scanned_seed_files: list[str] = []
    for path in sorted((ROOT / "configs").rglob("*.json")):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("configs/phase14/"):
            continue
        try:
            historical_seeds.update(_historical_seed_values(json.loads(path.read_text(encoding="utf-8"))))
            scanned_seed_files.append(relative)
        except (OSError, json.JSONDecodeError):
            errors.append(f"historical seed-plan JSON cannot be read: {relative}")
    phase14_seed_values = {
        int(item["seed"]) for item in raw.get("trace_hashes", [])
    }
    overlapping_seeds = sorted(historical_seeds & phase14_seed_values)
    seed_partitions_disjoint = not overlapping_seeds
    if not seed_partitions_disjoint:
        errors.append(f"Phase 14 seeds overlap historical seed assignments: {overlapping_seeds}")
    dev_seed_count = sum(len(items) for items in sensitivity_raw.get("seed_assignments", {}).values())
    sensitivity_records = sensitivity_raw.get("records", [])
    sensitivity_keys = {
        (
            item.get("scenario_id"),
            int(item.get("seed", -1)),
            item.get("policy_id"),
            item.get("variant_id"),
        )
        for item in sensitivity_records
    }
    expected_sensitivity_keys = {
        (scenario, int(seed), policy, variant)
        for scenario, seeds in sensitivity_raw.get("seed_assignments", {}).items()
        for seed in seeds
        for policy in ("Bprime_static_grid_shared_safety", "G_centralized_coordination")
        for variant in sensitivity_raw.get("variant_definitions", {})
    }
    expected_sensitivity_scenes = set(CONFIRMATION_SEEDS)
    sensitivity_complete = (
        sensitivity_raw.get("partition") == "exploratory_development_only"
        and sensitivity_raw.get("phase") == "phase14_radio_link_model_sensitivity"
        and sensitivity_raw.get("source_bundle_sha256") == _source_sha256()
        and len(sensitivity_records) == 4 * 3 * 13 * 2
        and sensitivity_keys == expected_sensitivity_keys
        and dev_seed_count == 12
        and set(sensitivity_raw.get("seed_assignments", {})) == expected_sensitivity_scenes
        and set(sensitivity_summary) == expected_sensitivity_scenes
        and all(
            set(sensitivity_summary[scene]) == {"Bprime_static_grid_shared_safety", "G_centralized_coordination"}
            and all(len(sensitivity_summary[scene][policy]) == 13 for policy in sensitivity_summary[scene])
            for scene in sensitivity_summary
        )
    )
    if not sensitivity_complete:
        errors.append("Phase 14 sensitivity screening is incomplete or has an unexpected shape")

    legacy_source_matches = (
        legacy_reproduction.get("historical_source_sha256")
        == sha256_file(ROOT / "results/phase10_confirmation_raw.json")
    )
    legacy_reproduction_passed = (
        legacy_reproduction.get("status") == "PASS"
        and legacy_reproduction.get("trace_matches") is True
        and legacy_reproduction.get("metrics_match") is True
        and legacy_source_matches
    )
    if not legacy_reproduction_passed:
        errors.append("Phase 14 legacy baseline reproduction did not match the frozen Phase 10 source")

    phase12 = read_json("results/phase12_integrity_audit.json")
    phase13_status = phase13.get("historical_frozen_result_integrity", {}).get("status")
    if phase13_status != "PASS":
        errors.append("Phase 13 frozen-result audit was not PASS")
    result = {
        "schema_version": "1.0",
        "phase": "phase14_radio_link_model",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "historical_frozen_json": {
            "expected_count": len(expected),
            "verified_count": sum(item["matches"] for item in historical_results),
            "items": historical_results,
        },
        "phase6_replay_hashes": {
            "verified_count": sum(item["matches"] for item in replay_results),
            "items": replay_results,
        },
        "phase12_audit_status": phase12.get("phase5", {}).get("status", "not-recorded"),
        "phase13_frozen_result_status": phase13_status,
        "phase14_confirmation": {
            "record_count": len(records),
            "expected_record_count": expected_runs,
            "paired_seed_rows": len(by_seed),
            "expected_seed_rows": sum(len(items) for items in CONFIRMATION_SEEDS.values()),
            "per_seed_strategy_model_completeness": per_seed_complete,
            "protocol_source_hash_matches": protocol_matches,
            "historical_seed_config_count": len(scanned_seed_files),
            "historical_seed_maximum": max(historical_seeds) if historical_seeds else None,
            "phase14_seed_minimum": min(phase14_seed_values) if phase14_seed_values else None,
            "seed_partitions_disjoint_from_historical_configs": seed_partitions_disjoint,
            "overlapping_seeds": overlapping_seeds,
            "historical_seed_plan_files": scanned_seed_files,
            "result_sha256": sha256_file(ROOT / "results/phase14_confirmation_raw.json"),
        },
        "phase14_sensitivity": {
            "record_count": len(sensitivity_raw.get("records", [])),
            "expected_record_count": 4 * 3 * 13 * 2,
            "status_complete": sensitivity_complete,
            "raw_sha256": sha256_file(ROOT / "results/phase14_model_sensitivity_raw.json"),
        },
        "phase14_legacy_reproduction": {
            "status": "PASS" if legacy_reproduction_passed else "FAIL",
            "scenario_id": legacy_reproduction.get("scenario_id"),
            "seed": legacy_reproduction.get("seed"),
            "trace_matches": legacy_reproduction.get("trace_matches"),
            "metric_match_count": sum(
                bool(item.get("matches"))
                for item in legacy_reproduction.get("metric_comparisons", {}).values()
            ),
            "metric_comparison_count": legacy_reproduction.get("compared_metric_count"),
            "historical_source_matches": legacy_source_matches,
            "artifact_sha256": sha256_file(ROOT / "results/phase14_legacy_reproduction.json"),
        },
        "errors": errors,
    }
    path = ROOT / "results/phase14_integrity_audit.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    audit = audit_phase14()
    print(json.dumps({"status": audit["status"], "errors": audit["errors"], "verified_frozen": audit["historical_frozen_json"]["verified_count"]}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if audit["status"] == "PASS" else 1)
