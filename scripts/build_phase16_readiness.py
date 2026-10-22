"""Build Phase 16's read-only inventory and acceptance evidence from saved files."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tomllib
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase15_integrity import source_bundle  # noqa: E402
from lowalt6g.phase16_measurement import (  # noqa: E402
    initial_uncertainty_budget,
    calibration_state_record,
)


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_hash(relative: str, expected: str) -> dict[str, Any]:
    path = ROOT / relative
    actual = digest(path)
    return {"path": relative, "expected_sha256": expected, "actual_sha256": actual, "matches": actual == expected}


def audit_frozen_history() -> dict[str, Any]:
    baseline = read_json(ROOT / "configs/phase15/protected_artifacts_baseline.json")
    errors: list[str] = []
    protected = [check_hash(item["path"], item["sha256"]) for item in baseline["files"]]
    errors.extend(f"protected hash mismatch: {item['path']}" for item in protected if not item["matches"])

    phase14_audit_path = ROOT / "results/phase14_integrity_audit.json"
    phase14_audit = read_json(phase14_audit_path)
    phase14_hash_match = digest(phase14_audit_path) == baseline.get("phase14_integrity_audit_sha256")
    if not phase14_hash_match or phase14_audit.get("status") != "PASS":
        errors.append("Phase 14 stored integrity audit hash/status mismatch")

    manifest = read_json(ROOT / "configs/phase15/public_dataset_manifest.json")
    raw_directory = ROOT / "data/phase15/raw" / manifest["dataset_id"]
    raw_files = []
    for item in manifest.get("files", []):
        path = raw_directory / item["filename"]
        actual = digest(path)
        size_ok = path.is_file() and path.stat().st_size == item["size_bytes"]
        match = actual == item["sha256"] and size_ok
        raw_files.append({"filename": item["filename"], "expected_sha256": item["sha256"], "actual_sha256": actual, "size_matches": size_ok, "matches": match})
        if not match:
            errors.append(f"Phase 15 raw dataset source mismatch: {item['filename']}")

    freeze = read_json(ROOT / "configs/phase15/confirmation_freeze_v2.json")
    current_bundle, source_items = source_bundle(ROOT)
    bundle_match = current_bundle == freeze.get("source_bundle_sha256")
    if not bundle_match:
        errors.append("Phase 15 frozen source bundle mismatch")
    frozen_inputs = []
    for path_key, hash_key in (
        ("protocol_path", "protocol_sha256"),
        ("dataset_manifest_path", "dataset_manifest_sha256"),
        ("dataset_audit_path", "dataset_audit_sha256"),
        ("cleaned_dataset_path", "cleaned_dataset_sha256"),
        ("phase14_baseline_config_path", "phase14_baseline_config_sha256"),
    ):
        item = check_hash(freeze[path_key], freeze[hash_key])
        frozen_inputs.append(item)
        if not item["matches"]:
            errors.append(f"Phase 15 frozen input mismatch: {item['path']}")

    phase15_audit = read_json(ROOT / "results/phase15_integrity_audit.json")
    phase15_dataset_audit = read_json(ROOT / "results/phase15_dataset_audit.json")
    phase15_summary = read_json(ROOT / "results/phase15_calibration_summary.json")
    holdout = read_json(ROOT / "results/phase15_holdout_validation.json")
    clean_sha = digest(ROOT / "results/phase15_measurements_public_clean.csv")
    if phase15_audit.get("status") != "PASS":
        errors.append("Stored Phase 15 integrity audit is not PASS")
    if phase15_dataset_audit.get("status") != "PASS" or clean_sha != freeze.get("cleaned_dataset_sha256"):
        errors.append("Phase 15 public data audit or cleaned CSV hash mismatch")
    if phase15_summary.get("project_device_calibration_status") != "NOT_CALIBRATED":
        errors.append("Phase 15 target-device status is not conservatively NOT_CALIBRATED")
    if holdout.get("acceptance", {}).get("decision") != "NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING":
        errors.append("Phase 15 holdout uncertainty decision mismatch")
    tracked_raw = subprocess.run(
        ["git", "ls-files", "--", "data/phase15/raw"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.splitlines()
    if tracked_raw:
        errors.append("Phase 15 raw source data is unexpectedly tracked by Git")
    try:
        status_lines = subprocess.run(["git", "status", "--porcelain=v1"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.splitlines()
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        status_lines, branch, head = [], None, None
    return {
        "schema_version": "1.0",
        "phase": "phase16_read_only_history_integrity_audit",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "git": {
            "branch": branch,
            "head_commit": head,
            "preexisting_dirty_entry_count_at_phase16_start": 213,
            "current_dirty_entry_count": len(status_lines),
            "worktree_count": len(subprocess.run(["git", "worktree", "list"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.splitlines()),
            "historical_changes_preserved": True,
            "remote_push_performed": False,
        },
        "phase14": {
            "stored_audit_status": phase14_audit.get("status"),
            "stored_audit_hash_matches_phase15_baseline": phase14_hash_match,
            "link_budget_config_sha256": digest(ROOT / "configs/phase14/link_budget_v1.toml"),
            "protected_historical_file_count": len(protected),
        },
        "phase15": {
            "stored_audit_status": phase15_audit.get("status"),
            "protected_historical_file_count": len(protected),
            "historical_phase5_8_9_10_11_file_count": baseline.get("historical_phase5_8_9_10_11_count"),
            "raw_dataset_source_file_count": len(raw_files),
            "raw_dataset_sources_match": all(item["matches"] for item in raw_files),
            "source_bundle_sha256": current_bundle,
            "source_bundle_matches_freeze": bundle_match,
            "freeze_inputs": frozen_inputs,
            "dataset_audit_status": phase15_dataset_audit.get("status"),
            "cleaned_csv_sha256": clean_sha,
            "cleaned_record_count": phase15_summary.get("dataset", {}).get("cleaned_measurement_count"),
            "target_device_status": phase15_summary.get("project_device_calibration_status"),
            "holdout_acceptance": holdout.get("acceptance", {}).get("decision"),
            "formal_network_simulation_applied": phase15_summary.get("formal_network_simulation", {}).get("executed"),
            "raw_source_tracked_by_git": bool(tracked_raw),
        },
        "protected_hashes": protected,
        "raw_dataset_files": raw_files,
        "phase15_frozen_source_files": source_items,
        "errors": errors,
    }


def _windows_device_scan() -> dict[str, Any]:
    if os.name != "nt":
        return {"status": "NOT_AVAILABLE_ON_THIS_PLATFORM", "matched_devices": [], "serial_port_count": None}
    scan = (
        "$d=@(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
        "Where-Object {$_.FriendlyName -match 'SDR|USRP|HackRF|LimeSDR|RTL-SDR|spectrum|radio test|RF test|GNSS receiver|GPS receiver|oscilloscope|signal generator|analyzer'} | "
        "Select-Object Class,FriendlyName,Status); ConvertTo-Json -InputObject $d -Compress"
    )
    try:
        response = subprocess.run(["powershell.exe", "-NoProfile", "-Command", scan], capture_output=True, text=True, timeout=20, check=False)
        if response.returncode != 0:
            raise RuntimeError(response.stderr.strip() or f"exit={response.returncode}")
        parsed = json.loads(response.stdout) if response.stdout.strip() else []
        devices = parsed if isinstance(parsed, list) else ([parsed] if parsed else [])
        serial = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "@(Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue).Count"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        return {
            "status": "COMPLETED",
            "method": "present Windows PnP device names filtered for known RF/GNSS instrumentation; serial-port count only",
            "matched_devices": devices,
            "serial_port_count": int(serial.stdout.strip()) if serial.stdout.strip().isdigit() else None,
            "serial_numbers_recorded": False,
            "limitation": "A name-filtered device scan cannot prove that no unrecognized, unenumerated, borrowed, or off-machine equipment exists.",
        }
    except Exception as error:  # inventory failure is represented, not silently replaced
        return {"status": "SCAN_FAILED", "matched_devices": [], "serial_port_count": None, "error": str(error)}


def main() -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    with (ROOT / "configs/phase14/link_budget_v1.toml").open("rb") as stream:
        link_budget_config = tomllib.load(stream)
    phase15 = read_json(ROOT / "results/phase15_calibration_summary.json")
    holdout = read_json(ROOT / "results/phase15_holdout_validation.json")
    measurement_plan = read_json(ROOT / "configs/phase16/urban_measurement_plan.json")
    import_candidates = sorted((ROOT / "results/phase16/imports").rglob("*.audit.json"))
    imported = [(path, read_json(path)) for path in import_candidates]
    preferred = [item for item in imported if item[1].get("required_device_metadata_fields")]
    selected_import = preferred[-1] if preferred else (imported[-1] if imported else None)
    import_audit = selected_import[1] if selected_import else None
    budget = initial_uncertainty_budget()
    budget_path = ROOT / "results/phase16_uncertainty_budget.json"
    budget["created_at_utc"] = timestamp
    budget["source_evidence"] = {
        "phase14_link_budget_config_sha256": digest(ROOT / "configs/phase14/link_budget_v1.toml"),
        "phase15_calibration_summary_sha256": digest(ROOT / "results/phase15_calibration_summary.json"),
        "phase15_holdout_validation_sha256": digest(ROOT / "results/phase15_holdout_validation.json"),
        "project_device_measurement_count": 0,
        "public_dataset_measurement_count": phase15.get("dataset", {}).get("cleaned_measurement_count"),
        "public_dataset_measurement_uncertainty_available": False,
    }
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    budget_path.write_text(json.dumps(budget, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    integrity = audit_frozen_history()
    (ROOT / "results/phase16_integrity_audit.json").write_text(json.dumps(integrity, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    inventory = {
        "schema_version": "1.0",
        "phase": "phase16_measurement_environment_inventory",
        "created_at_utc": timestamp,
        "project_root": str(ROOT),
        "git_branch": subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip(),
        "host_platform": platform.platform(),
        "equipment_scan": _windows_device_scan(),
        "project_device_measurements": {
            "status": "NO_PROJECT_DEVICE_MEASUREMENTS",
            "file_count": 0,
            "evidence_scope": "scoped project data/results/configs/docs inventory plus Phase 15 calibration artifacts",
        },
        "project_device_manuals_and_calibration_certificates": {
            "status": "NOT_FOUND_IN_SCOPED_PROJECT_INVENTORY",
            "scope": "project workspace only; does not inspect unrelated user directories",
        },
        "available_measurement_data": {
            "source_type": "public_measurement",
            "dataset_id": "mendeley_8p6r8ft4fz_v2",
            "doi": "10.17632/8p6r8ft4fz.2",
            "source_url": "https://data.mendeley.com/datasets/8p6r8ft4fz/2",
            "source_file_count": 14,
            "record_count": phase15.get("dataset", {}).get("cleaned_measurement_count"),
            "carrier_frequency_hz": 3600000000,
            "measurement_scope": "CIR measured; path_loss_db is publisher-derived; not project-device received-power calibration",
            "measurement_uncertainty_per_record_available": False,
            "license": "CC-BY-4.0",
        },
        "link_budget_parameters": {
            "configuration_path": "configs/phase14/link_budget_v1.toml",
            "configuration_sha256": digest(ROOT / "configs/phase14/link_budget_v1.toml"),
            "status": "PROJECT_ASSUMPTIONS_NOT_DEVICE_CALIBRATED",
            "profiles": {
                "model": link_budget_config.get("model"),
                "base_access": link_budget_config.get("base_access"),
                "uav_access": link_budget_config.get("uav_access"),
                "backhaul": link_budget_config.get("backhaul"),
            },
        },
        "spectrum_and_flight_authorization": {
            "project_authorization_evidence_found": False,
            "3p5_ghz_emission_status": "NOT_AUTHORIZED_OR_VERIFIED_FOR_THIS_PROJECT",
            "uav_flight_status": "NOT_AUTHORIZED_OR_VERIFIED_FOR_THIS_PROJECT",
            "must_be_rechecked_for_actual_site_equipment_frequency_power_and_date": True,
            "software_does_not_transmit_or_control_aircraft": True,
        },
        "phase15_import_audit": None if import_audit is None else {
            "path": selected_import[0].relative_to(ROOT).as_posix(),
            "raw_sha256": import_audit.get("source_sha256"),
            "records_before": import_audit.get("record_count_before_cleaning"),
            "records_after": import_audit.get("record_count_after_cleaning"),
            "device_metadata_complete": import_audit.get("device_metadata_complete"),
        },
        "limitations": [
            "Windows device-name enumeration is only a bounded read-only check, not proof that no equipment exists.",
            "No field site, radio authorization, drone flight authorization, or target hardware was supplied to this project workspace.",
            "The public 3.6 GHz non-urban data are not re-labelled as 3.5 GHz urban device measurements.",
        ],
    }
    (ROOT / "results/phase16_environment_inventory.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    calibration_evidence = {
        "source_type": "public_measurement",
        "target_device_id": None,
        "target_device_record_count": 0,
        "public_measurement_record_count": phase15.get("dataset", {}).get("cleaned_measurement_count"),
        "measurement_uncertainty_complete": False,
    }
    state = calibration_state_record(
        calibration_evidence,
        input_hashes={
            "phase15_summary": digest(ROOT / "results/phase15_calibration_summary.json") or "",
            "phase15_holdout": digest(ROOT / "results/phase15_holdout_validation.json") or "",
            "phase16_uncertainty_budget": digest(budget_path) or "",
        },
        model_version="phase16_acceptance_state_v1",
        previous_status=None,
        timestamp_utc=timestamp,
    )
    state["public_dataset_candidate"] = {
        "pipeline_status": phase15.get("public_dataset_candidate_status"),
        "holdout_evaluation_status": holdout.get("status"),
        "measurement_acceptance": holdout.get("acceptance", {}).get("decision"),
        "device_calibration": "NOT_CALIBRATED",
    }
    (ROOT / "results/phase16_calibration_state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    readiness = {
        "schema_version": "1.0",
        "phase": "phase16_field_measurement_readiness",
        "created_at_utc": timestamp,
        "status": "NOT_READY_FOR_FIELD_MEASUREMENT",
        "calibration_status": state["status"],
        "public_data_only": True,
        "target_device_calibration_complete": False,
        "field_measurement_executed": False,
        "transmission_or_uav_operation_performed": False,
        "project_measurement_records": 0,
        "blocking_gates": [
            "No verified project transmitter/receiver, antenna, feedline, or instrument calibration certificates are recorded.",
            "No project-specific radio authorization for 3.5 GHz or actual emission configuration is recorded.",
            "No actual UAV, registration/airspace assessment, or flight authorization is recorded.",
            "No target-device measurement uncertainty values or preregistered numerical acceptance thresholds exist.",
        ],
        "completed_software_capabilities": [
            "Read-only CSV/JSON measurement import and raw-file SHA-256 audit.",
            "Unit/value checks, duplicate detection, metadata completeness reporting, and session-level leakage checks.",
            "Uncertainty propagation with correlation handling, explicit missing-input behavior, and reproducible Monte Carlo.",
            "Evidence-driven calibration acceptance state machine and offline import adapter.",
        ],
        "measurement_adapters": [
            {"id": "offline_file_import", "status": "IMPLEMENTED_AND_TESTED", "live_device": False},
            {"id": "radio_instrument_driver", "status": "UNAVAILABLE", "live_device": False},
            {"id": "future_instrument_adapter_contract", "status": "INTERFACE_ONLY", "live_device": False},
        ],
        "required_notice": "真实设备校准尚未完成；当前工具用于测量准备、数据审计和校准验收。",
        "measurement_import_audit_path": None if selected_import is None else selected_import[0].relative_to(ROOT).as_posix(),
        "measurement_plan": {
            "status": measurement_plan["status"],
            "target_frequency_hz": measurement_plan["target_frequency_hz"],
            "transmission_authorized": measurement_plan["transmission_authorized"],
            "uav_flight_authorized": measurement_plan["uav_flight_authorized"],
            "scenarios": measurement_plan["scenarios"],
            "design": measurement_plan["design"],
        },
        "equipment_readiness_checklist": [
            {"item": "Authorized, type-appropriate transmitter or shielded-lab source", "status": "MISSING"},
            {"item": "Calibrated receiver/test instrument with certificate", "status": "MISSING"},
            {"item": "Antenna patterns and calibrated feedline-loss records", "status": "MISSING"},
            {"item": "Positioning and time synchronization evidence", "status": "MISSING"},
            {"item": "Site/frequency authorization for any emission", "status": "NOT_VERIFIED"},
            {"item": "UAV and actual site flight/airspace approval if airborne", "status": "NOT_VERIFIED"},
            {"item": "Privacy-reviewed, session-grouped storage location", "status": "TEMPLATE_READY"},
        ],
        "integrity_audit_path": "results/phase16_integrity_audit.json",
        "uncertainty_budget_path": "results/phase16_uncertainty_budget.json",
        "environment_inventory_path": "results/phase16_environment_inventory.json",
        "state_history_path": "results/phase16_calibration_state.json",
    }
    (ROOT / "results/phase16_measurement_readiness.json").write_text(json.dumps(readiness, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "integrity_status": integrity["status"],
        "protected_files": len(integrity["protected_hashes"]),
        "phase15_raw_sources": len(integrity["raw_dataset_files"]),
        "phase15_source_bundle_match": integrity["phase15"]["source_bundle_matches_freeze"],
        "project_calibration_status": state["status"],
        "field_readiness": readiness["status"],
        "errors": integrity["errors"],
    }, ensure_ascii=False))
    return 0 if integrity["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

