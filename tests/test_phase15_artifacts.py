from __future__ import annotations

import json
from pathlib import Path

from lowalt6g.phase15_integrity import sha256_file, source_bundle


ROOT = Path(__file__).resolve().parents[1]


def read_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_candidate_remains_out_of_project_configuration_without_device_calibration():
    summary = read_json("results/phase15_calibration_summary.json")
    freeze = read_json("configs/phase15/confirmation_freeze_v2.json")
    config = ROOT / "configs/phase14/link_budget_v1.toml"
    assert summary["project_device_calibration_status"] == "NOT_CALIBRATED"
    assert summary["formal_network_simulation"]["executed"] is False
    assert sha256_file(config) == freeze["phase14_baseline_config_sha256"]


def test_frozen_candidate_and_holdout_results_have_matching_input_hashes():
    freeze = read_json("configs/phase15/confirmation_freeze_v2.json")
    protocol = ROOT / freeze["protocol_path"]
    clean = ROOT / freeze["cleaned_dataset_path"]
    audit = ROOT / freeze["dataset_audit_path"]
    summary = read_json("results/phase15_calibration_summary.json")
    holdout = read_json("results/phase15_holdout_validation.json")
    current_bundle, _ = source_bundle(ROOT)
    assert sha256_file(protocol) == freeze["protocol_sha256"]
    assert sha256_file(clean) == freeze["cleaned_dataset_sha256"]
    assert sha256_file(audit) == freeze["dataset_audit_sha256"]
    assert current_bundle == freeze["source_bundle_sha256"] == summary["source_bundle_sha256"]
    assert holdout["protocol_sha256"] == freeze["protocol_sha256"]
    assert holdout["acceptance"]["decision"] == "NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING"


def test_failed_v1_attempt_is_logged_before_any_holdout_metrics():
    log = read_json("results/phase15_preholdout_run_attempts.json")
    attempt = log["attempts"][0]
    assert attempt["status"] == "FAILED_BEFORE_HOLDOUT_SCORING"
    assert attempt["holdout_predictions_or_metrics_computed"] is False
    assert attempt["holdout_metrics_viewed"] is False


def test_saved_evidence_plot_outputs_exist_and_have_png_signature():
    plot = ROOT / "plots/phase15/phase15_fit_and_holdout.png"
    assert plot.is_file() and plot.stat().st_size > 10_000
    assert plot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
