"""Fit the public-data candidate and evaluate once on its frozen environment holdout."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase15_calibration import evaluate_holdout_baselines, fit_fixed_slope_offset_model  # noqa: E402
from lowalt6g.phase15_data import read_measurements, sha256_file  # noqa: E402
from lowalt6g.phase15_integrity import source_bundle  # noqa: E402
from lowalt6g.radio_link import free_space_path_loss_db, load_link_budget_config  # noqa: E402


FREEZE_PATH = ROOT / "configs/phase15/confirmation_freeze_v2.json"
PROTOCOL_PATH = ROOT / "configs/phase15/calibration_protocol_v2.json"
MANIFEST_PATH = ROOT / "configs/phase15/public_dataset_manifest.json"
CLEAN_PATH = ROOT / "results/phase15_measurements_public_clean.csv"
AUDIT_PATH = ROOT / "results/phase15_dataset_audit.json"
PHASE14_CONFIG_PATH = ROOT / "configs/phase14/link_budget_v1.toml"
SUMMARY_PATH = ROOT / "results/phase15_calibration_summary.json"
HOLDOUT_PATH = ROOT / "results/phase15_holdout_validation.json"


def _verify_freeze() -> tuple[dict, dict, dict, dict]:
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    current_bundle_sha, _ = source_bundle(ROOT)
    checks = {
        "source_bundle": current_bundle_sha == freeze.get("source_bundle_sha256"),
        "protocol": sha256_file(PROTOCOL_PATH) == freeze.get("protocol_sha256"),
        "manifest": sha256_file(MANIFEST_PATH) == freeze.get("dataset_manifest_sha256"),
        "dataset_audit": sha256_file(AUDIT_PATH) == freeze.get("dataset_audit_sha256"),
        "clean_data": sha256_file(CLEAN_PATH) == freeze.get("cleaned_dataset_sha256"),
        "phase14_config": sha256_file(PHASE14_CONFIG_PATH) == freeze.get("phase14_baseline_config_sha256"),
    }
    if freeze.get("status") != "frozen_before_holdout_scoring" or not all(checks.values()):
        raise ValueError(f"confirmation freeze/hash check failed: {checks}")
    if audit.get("status") != "PASS" or audit.get("group_partition_audit", {}).get("status") != "PASS":
        raise ValueError("measurement audit or group partition is not PASS")
    if tuple(freeze["fit_groups"]) != tuple(protocol["fit_groups"]) or tuple(freeze["holdout_groups"]) != tuple(protocol["holdout_groups"]):
        raise ValueError("frozen split differs from the experiment protocol")
    if freeze.get("protocol_id") != protocol.get("protocol_id"):
        raise ValueError("frozen protocol id differs from v2 experiment protocol")
    return freeze, protocol, manifest, audit


def main() -> int:
    if SUMMARY_PATH.exists() or HOLDOUT_PATH.exists():
        raise SystemExit("Phase 15 result files already exist; refusing to overwrite results")
    freeze, protocol, manifest, audit = _verify_freeze()
    rows = read_measurements(CLEAN_PATH)
    fit_groups = protocol["fit_groups"]
    holdout_groups = protocol["holdout_groups"]
    fixed = protocol["fixed_parameters"]
    fit = fit_fixed_slope_offset_model(
        rows,
        fit_groups,
        carrier_frequency_mhz=float(fixed["carrier_frequency_hz"]) / 1_000_000.0,
        fixed_exponent=float(fixed["path_loss_exponent"]),
        reference_distance_m=1.0,
        bootstrap_replicates=int(protocol["bootstrap"]["replicates"]),
        bootstrap_seed=int(protocol["bootstrap"]["seed"]),
    )

    phase14_config = load_link_budget_config(PHASE14_CONFIG_PATH)
    baseline_profile = phase14_config.uav_access
    baseline = {
        "model_id": "phase14_link_budget_v1_uav_access_mean_path_loss",
        "carrier_frequency_hz": baseline_profile.carrier_frequency_mhz * 1_000_000.0,
        "reference_distance_m": baseline_profile.reference_distance_m,
        "pl0_db_at_reference_distance": free_space_path_loss_db(
            baseline_profile.carrier_frequency_mhz,
            baseline_profile.reference_distance_m,
        ),
        "path_loss_exponent": baseline_profile.path_loss_exponent,
        "prediction_scope": "deterministic mean PL; zero-mean shadow term and no obstruction term for point prediction",
        "source_config": "configs/phase14/link_budget_v1.toml",
        "source_config_sha256": sha256_file(PHASE14_CONFIG_PATH),
    }
    frequency_matched_baseline = {
        "model_id": "phase15_free_space_3p6ghz_n2p3_no_offset",
        "carrier_frequency_hz": float(fixed["carrier_frequency_hz"]),
        "reference_distance_m": float(fixed["reference_distance_m"]),
        "pl0_db_at_reference_distance": free_space_path_loss_db(
            float(fixed["carrier_frequency_hz"]) / 1_000_000.0,
            float(fixed["reference_distance_m"]),
        ),
        "path_loss_exponent": float(fixed["path_loss_exponent"]),
        "prediction_scope": "unfitted frequency-matched deterministic mean PL; zero dataset offset",
        "source": "frozen Phase 15 protocol v2",
    }
    holdout = evaluate_holdout_baselines(
        rows,
        holdout_groups,
        candidate=fit,
        baselines={
            "phase14_exact": baseline,
            "frequency_matched_unfitted": frequency_matched_baseline,
        },
        bootstrap_replicates=int(protocol["holdout_bootstrap"]["replicates"]),
        bootstrap_seed=int(protocol["holdout_bootstrap"]["seed"]),
    )
    acceptance = holdout["acceptance"]
    phase14_comparison = holdout["comparisons"]["phase14_exact"]
    if acceptance["measurement_uncertainty_documented"]:
        interval = phase14_comparison["paired_mae_difference_ci95_cluster_bootstrap_db"]
        if interval is not None and interval[1] < 0:
            acceptance["decision"] = "CANDIDATE_IMPROVEMENT_SUPPORTED_SUBJECT_TO_GROUP_COUNT"
        else:
            acceptance["decision"] = "IMPROVEMENT_NOT_ESTABLISHED"

    holdout.update({
        "schema_version": "1.0",
        "phase": "phase15_public_a2g_holdout_validation",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "partition": "final_environment_holdout_descriptive_evaluation",
        "dataset_id": manifest["dataset_id"],
        "dataset_doi": manifest["doi"],
        "dataset_license": manifest["license"],
        "dataset_sha256": freeze["cleaned_dataset_sha256"],
        "protocol_sha256": freeze["protocol_sha256"],
        "source_bundle_sha256": freeze["source_bundle_sha256"],
        "fit_groups": fit_groups,
        "seed": int(protocol["holdout_bootstrap"]["seed"]),
        "measurement_uncertainty_db_missing_count": audit["missing_measurement_metadata_counts"]["measurement_uncertainty_db"],
        "results": "actual public measurement observations; not synthetic test samples",
    })
    summary = {
        "schema_version": "1.0",
        "phase": "phase15_link_calibration_pipeline",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "pipeline_status": "HOLDOUT_VALIDATED",
        "public_dataset_candidate_status": "HOLDOUT_VALIDATED",
        "project_device_calibration_status": "NOT_CALIBRATED",
        "holdout_acceptance_decision": acceptance["decision"],
        "calibration_status_definition": "HOLDOUT_VALIDATED means a candidate fit and a separately grouped dataset holdout evaluation were actually completed; it does not mean the model passed an accuracy threshold or is calibrated to project hardware.",
        "dataset": {
            "dataset_id": manifest["dataset_id"],
            "title": manifest["title"],
            "doi": manifest["doi"],
            "source_url": manifest["source_url"],
            "license": manifest["license"],
            "source_type": "public_measurement",
            "cleaned_measurement_count": len(rows),
            "cleaned_measurement_sha256": freeze["cleaned_dataset_sha256"],
            "source_file_count": audit["source_file_integrity"]["verified_file_count"],
            "frequency_hz": manifest["measurement_scope"]["carrier_frequency_hz"],
            "measurement_environment": manifest["measurement_scope"]["scenarios"],
            "scope_boundary": manifest["measurement_scope"]["target_applicability"],
        },
        "candidate_fit": fit,
        "baselines": {
            "phase14_exact": baseline,
            "frequency_matched_unfitted": frequency_matched_baseline,
        },
        "holdout_validation_path": "results/phase15_holdout_validation.json",
        "protocol_path": "configs/phase15/calibration_protocol_v2.json",
        "protocol_sha256": freeze["protocol_sha256"],
        "source_bundle_sha256": freeze["source_bundle_sha256"],
        "target_device_calibration_limit": "No local radio instrument or project-device measurement was found. Public measurements do not supply project-equivalent Tx power, antenna gains, receiver sensitivity, per-sample uncertainty, urban obstruction, or SINR/BLER labels.",
        "formal_network_simulation": {
            "executed": False,
            "reason": "measurement domain is non-urban 3.6 GHz and does not identify a project-equivalent absolute link budget; candidate parameters are not inserted into Phase 14 or formal project simulations",
        },
    }
    HOLDOUT_PATH.write_text(json.dumps(holdout, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "pipeline_status": summary["pipeline_status"],
        "device_calibration_status": summary["project_device_calibration_status"],
        "training_samples": fit["training_sample_count"],
        "holdout_samples": holdout["sample_count"],
        "candidate_holdout_mae_db": holdout["candidate_metrics"]["mae_db"],
        "phase14_holdout_mae_db": holdout["comparisons"]["phase14_exact"]["baseline_metrics"]["mae_db"],
        "acceptance": acceptance["decision"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Phase 15 calibration run failed: {error}", file=sys.stderr)
        raise SystemExit(2)
