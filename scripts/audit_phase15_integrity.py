"""Read-only audit of prior frozen deliverables and current Phase 15 provenance."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase15_integrity import sha256_file, source_bundle  # noqa: E402


BASELINE = ROOT / "configs/phase15/protected_artifacts_baseline.json"
OUT = ROOT / "results/phase15_integrity_audit.json"


def read_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def main() -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    errors: list[str] = []
    protected = []
    for item in baseline.get("files", []):
        path = ROOT / item["path"]
        actual = sha256_file(path) if path.is_file() else None
        matches = actual == item["sha256"]
        if not matches:
            errors.append(f"protected file mismatch or missing: {item['path']}")
        protected.append({"path": item["path"], "expected_sha256": item["sha256"], "actual_sha256": actual, "matches": matches})

    phase14_audit_path = ROOT / "results/phase14_integrity_audit.json"
    phase14_audit_hash = sha256_file(phase14_audit_path) if phase14_audit_path.is_file() else None
    if phase14_audit_hash != baseline.get("phase14_integrity_audit_sha256"):
        errors.append("Phase 14 integrity audit file changed or is missing")
    phase14_audit_status = read_json("results/phase14_integrity_audit.json").get("status") if phase14_audit_path.is_file() else None
    if phase14_audit_status != "PASS":
        errors.append("captured Phase 14 integrity audit status is not PASS")

    manifest = read_json("configs/phase15/public_dataset_manifest.json")
    raw_dir = ROOT / "data/phase15/raw" / manifest["dataset_id"]
    source_files = []
    for item in manifest.get("files", []):
        path = raw_dir / item["filename"]
        actual = sha256_file(path) if path.is_file() else None
        matches = actual == item["sha256"] and path.stat().st_size == item["size_bytes"] if path.is_file() else False
        if not matches:
            errors.append(f"public source file mismatch or missing: {item['filename']}")
        source_files.append({"filename": item["filename"], "expected_sha256": item["sha256"], "actual_sha256": actual, "matches": matches})

    freeze = read_json("configs/phase15/confirmation_freeze_v2.json")
    current_bundle, source_items = source_bundle(ROOT)
    frozen_source_match = current_bundle == freeze.get("source_bundle_sha256")
    if not frozen_source_match:
        errors.append("v2 frozen source bundle hash does not match current scoring source")
    protocol_path = ROOT / freeze["protocol_path"]
    manifest_path = ROOT / freeze["dataset_manifest_path"]
    audit_path = ROOT / freeze["dataset_audit_path"]
    clean_path = ROOT / freeze["cleaned_dataset_path"]
    phase14_config_path = ROOT / freeze["phase14_baseline_config_path"]
    frozen_inputs = {
        "protocol": (protocol_path, freeze["protocol_sha256"]),
        "dataset_manifest": (manifest_path, freeze["dataset_manifest_sha256"]),
        "dataset_audit": (audit_path, freeze["dataset_audit_sha256"]),
        "cleaned_dataset": (clean_path, freeze["cleaned_dataset_sha256"]),
        "phase14_config": (phase14_config_path, freeze["phase14_baseline_config_sha256"]),
    }
    input_matches = {}
    for name, (path, expected) in frozen_inputs.items():
        actual = sha256_file(path) if path.is_file() else None
        input_matches[name] = {"expected_sha256": expected, "actual_sha256": actual, "matches": actual == expected}
        if actual != expected:
            errors.append(f"frozen input mismatch or missing: {name}")

    audit = read_json("results/phase15_dataset_audit.json")
    if audit.get("status") != "PASS" or audit.get("row_audit", {}).get("rejected_row_count") != 0:
        errors.append("Phase 15 measurement data quality audit did not pass")
    summary = read_json("results/phase15_calibration_summary.json")
    holdout = read_json("results/phase15_holdout_validation.json")
    if summary.get("project_device_calibration_status") != "NOT_CALIBRATED":
        errors.append("project device calibration status is not conservatively marked NOT_CALIBRATED")
    if summary.get("formal_network_simulation", {}).get("executed") is not False:
        errors.append("public data candidate was marked as applied to a formal network simulation")
    if holdout.get("acceptance", {}).get("decision") != "NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING":
        errors.append("holdout acceptance does not reflect missing measurement uncertainty")

    tracked_raw = subprocess.check_output(
        ["git", "ls-files", "--", "data/phase15/raw"], cwd=ROOT, text=True
    ).splitlines()
    if tracked_raw:
        errors.append("public raw source files are unexpectedly tracked by Git")

    result = {
        "schema_version": "1.0",
        "phase": "phase15_integrity_audit",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "preexisting_protected_baseline": {
            "path": "configs/phase15/protected_artifacts_baseline.json",
            "protected_file_count": len(protected),
            "historical_phase5_8_9_10_11_count": baseline.get("historical_phase5_8_9_10_11_count"),
            "all_files_match": all(item["matches"] for item in protected),
            "files": protected,
        },
        "phase14_integrity_audit": {"expected_sha256": baseline.get("phase14_integrity_audit_sha256"), "actual_sha256": phase14_audit_hash, "status": phase14_audit_status},
        "public_dataset": {"dataset_id": manifest["dataset_id"], "source_file_count": len(source_files), "all_source_hashes_match": all(item["matches"] for item in source_files), "files": source_files},
        "v2_frozen_calibration": {
            "status": freeze.get("status"),
            "source_bundle_sha256": current_bundle,
            "source_bundle_matches_freeze": frozen_source_match,
            "source_files": source_items,
            "input_hashes": input_matches,
            "holdout_scored_after_freeze": bool(holdout.get("protocol_sha256") == freeze.get("protocol_sha256")),
            "holdout_acceptance": holdout.get("acceptance", {}).get("decision"),
            "target_device_status": summary.get("project_device_calibration_status"),
            "formal_network_simulation_executed": summary.get("formal_network_simulation", {}).get("executed"),
        },
        "raw_public_dataset_files_tracked_by_git": tracked_raw,
        "errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "protected_files": len(protected), "source_files": len(source_files), "source_bundle_match": frozen_source_match, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
