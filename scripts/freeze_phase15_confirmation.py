"""Freeze Phase 15 v2 code and data split before final holdout scoring."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lowalt6g.phase15_integrity import sha256_file, source_bundle  # noqa: E402


OUT = ROOT / "configs/phase15/confirmation_freeze_v2.json"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"refusing to replace the existing confirmation freeze: {OUT.relative_to(ROOT)}")
    protocol_path = ROOT / "configs/phase15/calibration_protocol_v2.json"
    manifest_path = ROOT / "configs/phase15/public_dataset_manifest.json"
    audit_path = ROOT / "results/phase15_dataset_audit.json"
    clean_path = ROOT / "results/phase15_measurements_public_clean.csv"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("status") != "PASS" or audit.get("group_partition_audit", {}).get("status") != "PASS":
        raise SystemExit("dataset audit or group partition is not PASS; confirmation freeze blocked")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("protocol_status") != "frozen_before_holdout_metrics_review":
        raise SystemExit("protocol is not marked frozen; confirmation freeze blocked")
    bundle_sha, source_files = source_bundle(ROOT)
    result = {
        "schema_version": "1.0",
        "phase": "phase15_link_calibration_pipeline",
        "status": "frozen_before_holdout_scoring",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "branch": git("branch", "--show-current"),
        "base_commit": git("rev-parse", "HEAD"),
        "source_bundle_sha256": bundle_sha,
        "source_files": source_files,
        "protocol_id": protocol["protocol_id"],
        "protocol_path": "configs/phase15/calibration_protocol_v2.json",
        "protocol_sha256": sha256_file(protocol_path),
        "dataset_manifest_path": "configs/phase15/public_dataset_manifest.json",
        "dataset_manifest_sha256": sha256_file(manifest_path),
        "phase14_baseline_config_path": "configs/phase14/link_budget_v1.toml",
        "phase14_baseline_config_sha256": sha256_file(ROOT / "configs/phase14/link_budget_v1.toml"),
        "dataset_audit_path": "results/phase15_dataset_audit.json",
        "dataset_audit_sha256": sha256_file(audit_path),
        "cleaned_dataset_path": "results/phase15_measurements_public_clean.csv",
        "cleaned_dataset_sha256": sha256_file(clean_path),
        "cleaned_dataset_row_count": audit["row_audit"]["valid_row_count"],
        "fit_groups": protocol["fit_groups"],
        "holdout_groups": protocol["holdout_groups"],
        "holdout_groups_viewed_for_fit_or_parameter_selection": False,
        "holdout_use": "one final descriptive environment holdout; no retuning after scoring",
        "prior_pre_holdout_attempt_log": "results/phase15_preholdout_run_attempts.json",
        "prior_failed_attempt_changed_parameterization": True,
        "seed": {
            "fit_cluster_bootstrap": protocol["bootstrap"]["seed"],
            "holdout_cluster_bootstrap": protocol["holdout_bootstrap"]["seed"],
        },
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "source_bundle_sha256": bundle_sha, "cleaned_dataset_row_count": result["cleaned_dataset_row_count"], "fit_groups": len(result["fit_groups"]), "holdout_groups": len(result["holdout_groups"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
