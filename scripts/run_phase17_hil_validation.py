"""Generate Phase 17 software-only HIL readiness and safety evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from audit_phase17_integrity import build_audit  # noqa: E402
from lowalt6g.phase17_hil import (  # noqa: E402
    OfflineReplayAdapter,
    SoftwareTestExecutor,
    adapter_status_catalog,
    build_replay_validation,
    canonical_sha256,
    environment_inventory,
    map_replay_snapshot,
    run_fault_injection_suite,
    run_software_closed_loop,
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _equipment_scan() -> dict[str, Any]:
    if os.name != "nt":
        return {
            "status": "NOT_AVAILABLE_ON_THIS_PLATFORM",
            "method": "read-only Windows PnP name scan unavailable on this platform",
            "matched_devices": [],
            "serial_port_count": None,
            "serial_numbers_recorded": False,
        }
    script = (
        "$d=@(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
        "Where-Object {$_.FriendlyName -match 'SDR|USRP|HackRF|LimeSDR|RTL-SDR|spectrum|radio test|RF test|GNSS receiver|GPS receiver|oscilloscope|signal generator|analyzer'} | "
        "Select-Object Class,FriendlyName,Status); ConvertTo-Json -InputObject $d -Compress"
    )
    try:
        response = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if response.returncode != 0:
            raise RuntimeError(response.stderr.strip() or f"PnP scan exited {response.returncode}")
        parsed = json.loads(response.stdout) if response.stdout.strip() else []
        devices = parsed if isinstance(parsed, list) else ([parsed] if isinstance(parsed, dict) else [])
        serial = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "@(Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue).Count"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if serial.returncode != 0:
            port_count = None
        else:
            port_count = int(serial.stdout.strip()) if serial.stdout.strip().isdigit() else None
        return {
            "status": "COMPLETED",
            "method": "read-only present Windows PnP names filtered for known measurement devices; serial count only",
            "matched_devices": devices,
            "serial_port_count": port_count,
            "serial_numbers_recorded": False,
            "limitation": "This bounded name scan does not detect unrecognized, unenumerated, borrowed, or off-machine hardware.",
        }
    except Exception as error:  # A scan failure is an explicit unavailable state.
        return {
            "status": "SCAN_FAILED",
            "method": "read-only Windows PnP name scan",
            "matched_devices": [],
            "serial_port_count": None,
            "serial_numbers_recorded": False,
            "error": str(error),
            "limitation": "No inference about equipment availability is made when enumeration fails.",
        }


def run() -> dict[str, Any]:
    result_dir = ROOT / "results"
    phase17_dir = result_dir / "phase17"
    phase17_dir.mkdir(parents=True, exist_ok=True)
    config = _read_json(ROOT / "configs" / "phase17" / "software_closed_loop.json")
    seed = int(config["seed"])
    config_hash = canonical_sha256(config)

    loop_arguments = {
        "seed": seed,
        "backhaul_available": bool(config["backhaul_available"]),
        "initial_battery_wh": float(config["initial_battery_wh"]),
        "reserve_wh": float(config["return_reserve_wh"]),
        "relay_activation_energy_wh": float(config["relay_activation_energy_wh"]),
        "rescue_users": int(config["rescue_users"]),
        "steps": int(config["steps"]),
        "time_step_s": float(config["time_step_s"]),
        "telemetry_max_age_s": float(config["telemetry_max_age_s"]),
        "manual_stop": bool(config["manual_stop"]),
        "telemetry_missing_steps": frozenset(int(item) for item in config["telemetry_missing_steps"]),
        "backhaul_schedule": {int(key): bool(value) for key, value in config["backhaul_schedule"].items()} or None,
    }
    loop = run_software_closed_loop(**loop_arguments)
    repeat = run_software_closed_loop(**loop_arguments)
    deterministic_match = loop["deterministic_output_sha256"] == repeat["deterministic_output_sha256"]
    command_audit = {
        "schema_version": "1.0",
        "source_classification": "SYNTHETIC_TEST_ONLY",
        "live_device": False,
        "real_hardware_output_enabled": False,
        "experiment_id": f"phase17-software-{seed}",
        "commands": loop["command_audit"],
        "required_fields_present": all(
            {"command", "safety", "receipt"}.issubset(item)
            and {"command_id", "target_device_id", "request_time", "source", "simulation_step"}.issubset(item["command"])
            for item in loop["command_audit"]
        ),
        "command_success_requires_matching_feedback": True,
        "timeout_is_not_success": True,
    }
    _write_json(result_dir / "phase17_closed_loop_run.json", loop)
    _write_json(result_dir / "phase17_command_audit.json", command_audit)

    replay_path = result_dir / "phase6_demo_dynamic_failures.json"
    replay_source = _read_json(replay_path)
    strategy_id = "D_lexicographic_rescue_priority"
    run_record = replay_source["strategies"][strategy_id]
    frames = run_record.get("state_snapshots", [])
    replay = build_replay_validation(
        replay_path,
        scenario_id="dynamic_failures",
        strategy_id=strategy_id,
    )
    mapped_hashes = [
        canonical_sha256(map_replay_snapshot(frame, source_path=replay_path.name, source_sha256=replay["source_sha256"]))
        for frame in frames
    ]
    mapped_frames = [
        map_replay_snapshot(frame, source_path=replay_path.name, source_sha256=replay["source_sha256"])
        for frame in frames
    ]
    replay["mapped_frame_count"] = len(mapped_hashes)
    replay["frame_mapping_hashes_sha256"] = canonical_sha256(mapped_hashes)
    replay["mapped_frames"] = mapped_frames
    replay["input_sha256"] = _digest(replay_path)
    replay["input_frame_count"] = len(frames)
    _write_json(result_dir / "phase17_replay_validation.json", replay)

    fault_results = run_fault_injection_suite(seed=seed)
    fault_plan = {
        "schema_version": "1.0",
        "plan_id": "phase17_software_fault_suite_v1",
        "seed": seed,
        "source_classification": "SYNTHETIC_TEST_ONLY",
        "hardware_output_enabled": False,
        "case_count": len(fault_results),
        "time_semantics": "synchronous contract/gate tests use case order only; only observed_simulation_events carry simulation timestamps",
        "cases": [
            {
                "test_case_index": item["test_case_index"],
                "fault_type": item["fault_type"],
                "injection_parameters": item["injection_parameters"],
                "expected_result": item["expected_result"],
            }
            for item in fault_results
        ],
    }
    _write_json(ROOT / "configs" / "phase17" / "fault_injection_plan.json", fault_plan)
    # Exercise a dynamic backhaul outage and restoration through the same deterministic plant.
    backhaul_recovery = run_software_closed_loop(seed=seed, backhaul_schedule={1: False, 2: True})
    tick1 = backhaul_recovery["timeline"][1]
    tick2 = backhaul_recovery["timeline"][2]
    recovery_valid = (
        tick1["event"] is not None
        and tick1["observed_state"]["rescue_connected"] == 0
        and tick2["event"] is not None
        and tick2["observed_state"]["rescue_connected"] == tick2["observed_state"]["rescue_total"]
        and backhaul_recovery["summary"]["first_rescue_recovery_step"] == 2
    )
    fault_payload = {
        "schema_version": "1.0",
        "test_mode": "SOFTWARE_CLOSED_LOOP",
        "source_classification": "SYNTHETIC_TEST_ONLY",
        "live_device": False,
        "seed": seed,
        "injection_count": len(fault_results),
        "passed_count": sum(item["passed"] for item in fault_results),
        "failed_count": sum(not item["passed"] for item in fault_results),
        "faults": fault_results,
        "backhaul_recovery_trace": {
            "passed": recovery_valid,
            "recovery_step": backhaul_recovery["summary"]["first_rescue_recovery_step"],
            "outage_observation": tick1,
            "restored_observation": tick2,
            "command_audit": backhaul_recovery["command_audit"],
        },
    }
    _write_json(result_dir / "phase17_fault_injection_results.json", fault_payload)

    executor = SoftwareTestExecutor()
    executor.connect()
    software_health = executor.health_check()
    executor.close()
    adapter_catalog = adapter_status_catalog()
    adapter_catalog["last_health_check"] = {
        "adapter_id": "phase17_software_test_executor",
        "result": software_health,
        "recorded_at": "deterministic_test_run_not_wall_clock_health_stream",
    }
    adapter_catalog["physical_adapter_count"] = 0
    adapter_catalog["physical_adapter_count_basis"] = "verified device drivers only; replay and software executor excluded"
    _write_json(result_dir / "phase17_adapter_status.json", adapter_catalog)

    inventory = environment_inventory(root=ROOT, equipment_scan=_equipment_scan())
    _write_json(result_dir / "phase17_environment_inventory.json", inventory)

    fault_pass = fault_payload["failed_count"] == 0
    mapped_all = len(frames) == len(mapped_hashes) == replay.get("walked_discrete_frames")
    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "phase": "phase17_hil_validation_framework",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment_role": "software_closed_loop_and_offline_replay_validation_not_real_hil",
        "model_scope": "abstract_6g_research_simulation_not_real_network_test",
        "current_mode": "SOFTWARE_CLOSED_LOOP",
        "current_mode_source": "saved validation artifact; not live telemetry",
        "software_closed_loop_status": "PASS" if loop["summary"]["feedback_matches"] == loop["summary"]["commands_requested"] else "FAIL",
        "offline_replay_status": "PASS" if replay["frame_count"] == replay["walked_discrete_frames"] == replay["mapped_frame_count"] else "FAIL",
        "real_hardware_in_loop_status": "NOT_RUN_NO_VERIFIED_HARDWARE_OR_DRIVER",
        "live_device_status": "UNAVAILABLE_AND_BLOCKED",
        "hardware_output_enabled": False,
        "live_device": False,
        "seed": seed,
        "source_revision": {
            "git_branch": subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip(),
            "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip(),
            "working_tree_dirty": bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()),
        },
        "implementation_file_sha256": {
            relative: _digest(ROOT / relative)
            for relative in ["src/lowalt6g/phase17_hil.py", "scripts/run_phase17_hil_validation.py", "src/lowalt6g/api.py"]
        },
        "effective_config_sha256": config_hash,
        "software_closed_loop": {
            "source_classification": "SYNTHETIC_TEST_ONLY",
            "configuration": config,
            "configuration_sha256": config_hash,
            "output_sha256": loop["deterministic_output_sha256"],
            "repeat_output_sha256": repeat["deterministic_output_sha256"],
            "same_seed_deterministic_match": deterministic_match,
            "summary": loop["summary"],
            "decision_compute_time_claimed": False,
        },
        "offline_replay": {
            "source_path": "results/phase6_demo_dynamic_failures.json",
            "source_sha256": replay["source_sha256"],
            "scenario_id": replay["scenario_id"],
            "source_seed": replay_source.get("seed"),
            "strategy_id": strategy_id,
            "frame_count": len(frames),
            "mapped_frame_count": len(mapped_hashes),
            "frame_mapping_hashes_sha256": replay["frame_mapping_hashes_sha256"],
            "walked_discrete_frames": replay["walked_discrete_frames"],
            "interpolation_count": replay["interpolated_frames"],
            "pause_resume_single_step_verified": (
                replay["paused_advance_kept_same_frame"]
                and replay["single_step_next_time_s"] is not None
                and replay["walked_discrete_frames"] == len(frames)
            ),
            "commands_allowed": replay["commands_allowed"],
            "latency_statistics": "UNDETERMINED_ACROSS_REPLAY_AND_WALL_CLOCK_DOMAINS_WITHOUT_SYNC",
        },
        "fault_injection": {
            "seed": seed,
            "injection_count": fault_payload["injection_count"],
            "passed_count": fault_payload["passed_count"],
            "failed_count": fault_payload["failed_count"],
            "status": "PASS" if fault_pass else "FAIL",
        },
        "state_mapping": {
            "mapped_station_link_user_drone_fields": True,
            "source_is_saved_simulation_frame": True,
            "measurement_claim": False,
            "all_frames_mapped_without_interpolation": mapped_all,
        },
        "command_feedback_audit": {
            "command_count": len(command_audit["commands"]),
            "command_and_reported_state_separate": True,
            "command_success_requires_feedback_match": command_audit["command_success_requires_matching_feedback"],
            "timeout_success_allowed": False,
        },
        "adapter_status_path": "results/phase17_adapter_status.json",
        "equipment_inventory_path": "results/phase17_environment_inventory.json",
        "limitations": [
            "No real hardware adapter, device protocol, HIL bench, radio transmission, flight, or base-station control was executed.",
            "Software closed-loop values are synthetic acceptance fixtures, not network performance or measured radio results.",
            "OFFLINE_REPLAY uses only saved Phase 6 frames and does not interpolate simulator states.",
            "Clock-domain differences make cross-domain response delay indeterminate without verified synchronization.",
        ],
        "errors": [],
    }
    summary["implementation_bundle_sha256"] = canonical_sha256(summary["implementation_file_sha256"])
    if not deterministic_match:
        summary["errors"].append("same-seed software closed loop did not reproduce its stable output hash")
    if not mapped_all:
        summary["errors"].append("not every discrete replay frame was mapped exactly once")
    if not fault_pass:
        summary["errors"].append("one or more fault injection cases did not match the expected safety outcome")
    if summary["software_closed_loop_status"] != "PASS":
        summary["errors"].append("software closed-loop command feedback did not match all accepted commands")
    if summary["offline_replay_status"] != "PASS":
        summary["errors"].append("offline replay did not traverse all mapped frames")

    _write_json(result_dir / "phase17_validation_summary.json", summary)
    audit = build_audit(ROOT)
    _write_json(result_dir / "phase17_integrity_audit.json", audit)
    summary["integrity_audit_status"] = audit["status"]
    summary["protected_file_count"] = audit["baseline"]["protected_file_count"]
    if audit["status"] != "PASS":
        summary["errors"].extend(audit["errors"])
    summary["status"] = "PASS" if not summary["errors"] else "FAIL"
    _write_json(result_dir / "phase17_validation_summary.json", summary)
    return summary


def main() -> int:
    summary = run()
    print(json.dumps({
        "status": summary["status"],
        "software_closed_loop": summary["software_closed_loop_status"],
        "offline_replay": summary["offline_replay_status"],
        "hardware_in_loop": summary["real_hardware_in_loop_status"],
        "fault_injections": summary["fault_injection"],
        "protected_files": summary.get("protected_file_count"),
        "errors": summary["errors"],
    }, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
