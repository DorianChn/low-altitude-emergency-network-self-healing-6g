"""Recheck Phase 14-16 and earlier protected inputs without modifying them."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "results" / "phase17" / "protected_start_manifest.json"


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def build_audit(root: Path = ROOT) -> dict[str, Any]:
    baseline_path = root / "results" / "phase17" / "protected_start_manifest.json"
    baseline = _read_json(baseline_path)
    errors: list[str] = []
    checked: list[dict[str, Any]] = []
    for item in baseline.get("files", []):
        path = root / item["path"]
        actual = _sha256(path)
        matches = actual == item["sha256"] and path.is_file() and path.stat().st_size == item["size_bytes"]
        checked.append({
            "path": item["path"],
            "expected_sha256": item["sha256"],
            "actual_sha256": actual,
            "expected_size_bytes": item["size_bytes"],
            "actual_size_bytes": path.stat().st_size if path.is_file() else None,
            "matches": matches,
        })
        if not matches:
            errors.append(f"protected file changed or missing: {item['path']}")

    phase14_audit_path = root / "results" / "phase14_integrity_audit.json"
    phase14_audit = _read_json(phase14_audit_path)
    phase15_baseline = _read_json(root / "configs" / "phase15" / "protected_artifacts_baseline.json")
    phase14_hash_matches = _sha256(phase14_audit_path) == phase15_baseline.get("phase14_integrity_audit_sha256")
    if phase14_audit.get("status") != "PASS" or not phase14_hash_matches:
        errors.append("Phase 14 stored audit/hash is not the protected PASS baseline")

    phase15_audit = _read_json(root / "results" / "phase15_integrity_audit.json")
    if phase15_audit.get("status") != "PASS":
        errors.append("Phase 15 stored integrity audit is not PASS")
    dataset_manifest = _read_json(root / "configs" / "phase15" / "public_dataset_manifest.json")
    raw_dir = root / "data" / "phase15" / "raw" / dataset_manifest["dataset_id"]
    raw_sources = []
    for source in dataset_manifest.get("files", []):
        path = raw_dir / source["filename"]
        digest = _sha256(path)
        size = path.stat().st_size if path.is_file() else None
        matches = digest == source["sha256"] and size == source["size_bytes"]
        raw_sources.append({"filename": source["filename"], "sha256": digest, "size_bytes": size, "matches": matches})
        if not matches:
            errors.append(f"Phase 15 source data changed: {source['filename']}")

    phase16_audit = _read_json(root / "results" / "phase16_integrity_audit.json")
    phase16_state = _read_json(root / "results" / "phase16_calibration_state.json")
    phase16_readiness = _read_json(root / "results" / "phase16_measurement_readiness.json")
    if phase16_audit.get("status") != "PASS":
        errors.append("Phase 16 stored historical integrity audit is not PASS")
    if phase16_state.get("status") != "NOT_CALIBRATED":
        errors.append("Phase 16 calibration state does not preserve the uncalibrated boundary")
    if phase16_readiness.get("status") != "NOT_READY_FOR_FIELD_MEASUREMENT":
        errors.append("Phase 16 measurement readiness state changed unexpectedly")

    dirty = subprocess.run(["git", "status", "--porcelain=v1"], cwd=root, capture_output=True, text=True, check=False).stdout.splitlines()
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True, check=False).stdout.strip()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False).stdout.strip()
    worktrees = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=root, capture_output=True, text=True, check=False).stdout
    return {
        "schema_version": "1.0",
        "phase": "phase17_protected_integrity_audit",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "git": {
            "branch": branch,
            "head_commit": head,
            "dirty_entry_count": len(dirty),
            "dirty_entries_preserved": True,
            "worktree_count": sum(line.startswith("worktree ") for line in worktrees.splitlines()),
            "staged_changes": subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root, check=False).returncode != 0,
            "remote_push_performed": False,
        },
        "baseline": {
            "path": baseline_path.relative_to(root).as_posix(),
            "captured_before_phase17_source_changes": baseline.get("created_before_phase17_changes") is True,
            "captured_dirty_entry_count": baseline.get("dirty_entry_count_at_capture"),
            "protected_file_count": len(checked),
            "all_hashes_match": all(item["matches"] for item in checked),
            "sha256": _sha256(baseline_path),
        },
        "phase14": {"stored_status": phase14_audit.get("status"), "stored_audit_hash_matches_phase15_baseline": phase14_hash_matches},
        "phase15": {"stored_status": phase15_audit.get("status"), "source_file_count": len(raw_sources), "all_source_hashes_match": all(item["matches"] for item in raw_sources), "raw_sources": raw_sources},
        "phase16": {
            "stored_status": phase16_audit.get("status"),
            "calibration_state": phase16_state.get("status"),
            "measurement_readiness": phase16_readiness.get("status"),
        },
        "protected_files": checked,
        "errors": errors,
    }


def main() -> int:
    result = build_audit()
    out = ROOT / "results" / "phase17_integrity_audit.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "protected_file_count": result["baseline"]["protected_file_count"], "phase15_source_count": result["phase15"]["source_file_count"], "errors": result["errors"]}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
