from __future__ import annotations

import json
from pathlib import Path

import pytest

from lowalt6g.phase17_hil import (
    AdapterError,
    AdapterStatus,
    ClockDomain,
    ClockStamp,
    ControlCommand,
    FaultKind,
    MessageContractValidator,
    OfflineReplayAdapter,
    SafetyContext,
    SafetyGate,
    SoftwareTestExecutor,
    TestMode as HilMode,
    map_replay_snapshot,
    reconcile_state_after_reconnect,
    run_fault_injection_suite,
    run_software_closed_loop,
)


ROOT = Path(__file__).resolve().parents[1]
REPLAY_PATH = ROOT / "results" / "phase6_demo_dynamic_failures.json"


def _status_message(**overrides):
    stamp = {"value": 3.0, "domain": ClockDomain.SIMULATION.value, "precision_ms": 1.0}
    payload = {
        "schema_version": "1.0",
        "device_id": "device-1",
        "session_id": "session-1",
        "sequence_number": 1,
        "timestamp": stamp,
        "received_at": stamp,
        "source": "SYNTHETIC_TEST_ONLY",
        "measurement_type": "device_status",
        "value": {"connected": True},
        "unit": "1",
        "quality": "GOOD",
        "uncertainty": None,
        "validity": True,
        "provenance": {"classification": "SYNTHETIC_TEST_ONLY"},
    }
    payload.update(overrides)
    return payload


def _measurement_message(**overrides):
    payload = _status_message()
    payload.update({
        "measurement_type": "received_power_dbm",
        "value": -78.0,
        "unit": "dBm",
        "uncertainty": {"standard_uncertainty": 1.5, "unit": "dBm", "coverage_factor": 2.0},
    })
    payload.update(overrides)
    return payload


def _command(executor, *, action="set_relay_active", source="automatic", params=None):
    return ControlCommand(
        command_id=f"test-{action}-{source}",
        target_device_id=executor.device_id,
        action=action,
        parameters=params or {"active": True},
        source=source,
        request_time=ClockStamp(3.0, ClockDomain.SIMULATION, 1.0),
        test_mode=HilMode.SOFTWARE_CLOSED_LOOP,
        experiment_id="phase17-tests",
        simulation_step=3,
    )


def _context(executor, **overrides):
    values = {
        "mode": HilMode.SOFTWARE_CLOSED_LOOP,
        "adapter_status": AdapterStatus.SIMULATED,
        "target_known": True,
        "allowed_actions": frozenset(executor.get_capabilities().supported_commands),
        "telemetry_fresh": True,
        "state_known": True,
    }
    values.update(overrides)
    return SafetyContext(**values)


def test_contract_accepts_status_without_measurement_uncertainty():
    validator = MessageContractValidator({"device-1"})
    result = validator.validate(
        _status_message(), now=ClockStamp(3.0, ClockDomain.SIMULATION, 1.0)
    )
    assert result.accepted is True
    assert result.trusted_for_control is True
    assert result.age_seconds == 0.0
    assert result.age_comparable is True


def test_contract_accepts_measurement_with_explicit_uncertainty():
    result = MessageContractValidator({"device-1"}).validate(
        _measurement_message(), now=ClockStamp(3.0, ClockDomain.SIMULATION, 1.0)
    )
    assert result.accepted is True
    assert result.trusted_for_control is True
    assert result.message is not None
    assert result.message.uncertainty is not None
    assert result.message.uncertainty.standard_uncertainty == 1.5


@pytest.mark.parametrize("field", ["device_id", "session_id", "sequence_number", "timestamp", "received_at", "measurement_type", "unit", "source", "provenance"])
def test_contract_rejects_missing_required_fields(field):
    payload = _status_message()
    payload.pop(field)
    result = MessageContractValidator({"device-1"}).validate(
        payload, now=ClockStamp(3.0, ClockDomain.SIMULATION, 1.0)
    )
    assert result.accepted is False


def test_unknown_device_and_incompatible_schema_are_rejected():
    unknown = MessageContractValidator({"device-1"}).validate(
        _status_message(device_id="not-registered"),
        now=ClockStamp(3.0, ClockDomain.SIMULATION, 1.0),
    )
    incompatible = MessageContractValidator({"device-1"}).validate(
        _status_message(schema_version="8.0"),
        now=ClockStamp(3.0, ClockDomain.SIMULATION, 1.0),
    )
    assert "unknown_device" in unknown.reasons
    assert "schema_version_unsupported" in incompatible.reasons


def test_duplicate_and_out_of_order_sequences_are_rejected():
    validator = MessageContractValidator({"device-1"})
    now = ClockStamp(3.0, ClockDomain.SIMULATION, 1.0)
    assert validator.validate(_status_message(sequence_number=4), now=now).accepted
    assert "duplicate_message" in validator.validate(_status_message(sequence_number=4), now=now).reasons
    assert "sequence_out_of_order" in validator.validate(_status_message(sequence_number=3), now=now).reasons


def test_stale_and_cross_clock_messages_do_not_produce_comparable_age():
    validator = MessageContractValidator({"device-1"})
    stale = validator.validate(
        _status_message(), now=ClockStamp(8.0, ClockDomain.SIMULATION, 1.0), max_age_seconds=1.0
    )
    cross_clock = MessageContractValidator({"device-1"}).validate(
        _status_message(timestamp={"value": 3.0, "domain": ClockDomain.REPLAY.value, "precision_ms": 1.0}),
        now=ClockStamp(3.0, ClockDomain.RECEIVER_WALL, 1.0),
    )
    assert "telemetry_stale" in stale.reasons
    assert cross_clock.age_seconds is None
    assert cross_clock.age_comparable is False


def test_units_ranges_and_missing_uncertainty_are_rejected():
    now = ClockStamp(3.0, ClockDomain.SIMULATION, 1.0)
    bad_unit = MessageContractValidator({"device-1"}).validate(
        _measurement_message(measurement_type="latency_ms", value=20.0, unit="dBm", uncertainty={"standard_uncertainty": 1.0, "unit": "dBm"}),
        now=now,
    )
    bad_range = MessageContractValidator({"device-1"}).validate(
        _measurement_message(measurement_type="battery_wh", value=-1.0, unit="Wh", uncertainty={"standard_uncertainty": 0.1, "unit": "Wh"}),
        now=now,
    )
    missing = MessageContractValidator({"device-1"}).validate(
        _measurement_message(uncertainty=None), now=now
    )
    assert "unit_mismatch" in bad_unit.reasons
    assert "measurement_value_out_of_range" in bad_range.reasons
    assert "measurement_uncertainty_missing" in missing.reasons
    assert missing.trusted_for_control is False


def test_emergency_stop_is_allowed_in_software_mode_even_if_telemetry_is_stale():
    executor = SoftwareTestExecutor()
    command = _command(executor, action="emergency_stop", source="emergency_stop", params={})
    decision = SafetyGate().evaluate(command, _context(executor, telemetry_fresh=None, state_known=False))
    assert decision.allowed is True
    assert decision.priority == "EMERGENCY_STOP"


@pytest.mark.parametrize("mode", [HilMode.HARDWARE_IN_LOOP, HilMode.LIVE_DEVICE])
def test_hardware_and_live_modes_are_blocked_even_with_simulated_adapter(mode):
    executor = SoftwareTestExecutor()
    command = _command(executor)
    decision = SafetyGate().evaluate(command, _context(executor, mode=mode))
    assert decision.allowed is False
    assert decision.reason == "real_hardware_output_disabled_in_phase17"


def test_replay_mode_is_read_only_and_unknown_targets_are_rejected():
    executor = SoftwareTestExecutor()
    command = _command(executor)
    gate = SafetyGate()
    replay = gate.evaluate(command, _context(executor, mode=HilMode.OFFLINE_REPLAY))
    unknown = gate.evaluate(command, _context(executor, target_known=False))
    assert replay.reason == "offline_replay_is_read_only"
    assert unknown.reason == "unknown_target_device"


def test_capability_mismatch_and_unauthorized_manual_commands_are_rejected():
    executor = SoftwareTestExecutor()
    unsupported = _command(executor, action="transmit_radio_signal", params={})
    manual = _command(executor, source="manual")
    gate = SafetyGate()
    assert gate.evaluate(unsupported, _context(executor)).reason == "device_capability_does_not_allow_action"
    assert gate.evaluate(manual, _context(executor, authorized=False)).reason == "manual_command_not_authorized"


def test_stale_unknown_manual_stop_and_reserve_states_fail_closed():
    executor = SoftwareTestExecutor()
    command = _command(executor)
    gate = SafetyGate()
    assert gate.evaluate(command, _context(executor, telemetry_fresh=False)).reason == "telemetry_missing_stale_or_clock_incomparable"
    assert gate.evaluate(command, _context(executor, state_known=False)).reason == "critical_device_state_unknown"
    assert gate.evaluate(command, _context(executor, manual_stop_latched=True)).reason == "manual_stop_latched_no_automatic_resume"
    assert gate.evaluate(command, _context(executor, battery_wh=35.0, reserve_wh=30.0, requested_energy_wh=8.0)).reason == "command_would_breach_return_reserve"
    assert gate.evaluate(command, _context(executor, battery_wh=35.0, reserve_wh=None)).reason == "battery_or_return_reserve_unknown"


def test_emergency_stop_cannot_be_cleared_without_explicit_manual_authorization():
    executor = SoftwareTestExecutor()
    command = _command(executor, action="clear_emergency_stop", source="manual", params={})
    gate = SafetyGate()
    denied = gate.evaluate(command, _context(executor, emergency_stop_latched=True, authorized=False, manual_restart_approved=False))
    allowed = gate.evaluate(command, _context(executor, emergency_stop_latched=True, authorized=True, manual_restart_approved=True))
    assert denied.reason == "explicit_authorized_manual_restart_required"
    assert allowed.allowed is True


def test_executor_logs_timeout_rejection_and_feedback_mismatch_as_not_success():
    executor = SoftwareTestExecutor()
    executor.connect()
    now = ClockStamp(3.0, ClockDomain.SIMULATION, 1.0)
    timeout = executor.submit_command(_command(executor, params={"active": True}), fault_injection=FaultKind.COMMAND_TIMEOUT)
    rejection = executor.submit_command(ControlCommand("reject", executor.device_id, "set_relay_active", {"active": True}, "automatic", now, HilMode.SOFTWARE_CLOSED_LOOP, "t", 1), fault_injection=FaultKind.DEVICE_REJECTS_COMMAND)
    mismatch = executor.submit_command(ControlCommand("mismatch", executor.device_id, "set_relay_active", {"active": True}, "automatic", now, HilMode.SOFTWARE_CLOSED_LOOP, "t", 2), fault_injection=FaultKind.COMMAND_FEEDBACK_MISMATCH)
    assert timeout.execution_status == "TIMEOUT_UNKNOWN" and timeout.completed is False
    assert timeout.to_dict()["schema_version"] == "1.0"
    assert rejection.execution_status == "REJECTED_BY_TEST_EXECUTOR" and rejection.completed is False
    assert mismatch.execution_status == "FEEDBACK_MISMATCH" and mismatch.feedback_matches is False
    assert mismatch.requested_state != mismatch.reported_state
    assert _command(executor).to_dict()["schema_version"] == "1.0"


def test_reconnect_requires_exact_status_reconciliation():
    same = reconcile_state_after_reconnect({"relay_active": False, "battery_wh": 100}, {"relay_active": False, "battery_wh": 100})
    changed = reconcile_state_after_reconnect({"relay_active": False, "battery_wh": 100}, {"relay_active": True, "battery_wh": 99})
    assert same == {"reconciled": True, "differences": {}}
    assert changed["reconciled"] is False
    assert set(changed["differences"]) == {"relay_active", "battery_wh"}


def test_software_closed_loop_is_deterministic_and_feedback_driven():
    first = run_software_closed_loop(seed=9)
    second = run_software_closed_loop(seed=9)
    assert first["deterministic_output_sha256"] == second["deterministic_output_sha256"]
    assert first["summary"]["first_rescue_recovery_step"] == 1
    assert first["summary"]["final_rescue_connected"] == first["summary"]["final_rescue_total"]
    assert first["summary"]["commands_allowed"] == first["summary"]["feedback_matches"] == 1
    assert first["source_classification"] == "SYNTHETIC_TEST_ONLY"
    assert first["live_device"] is False


def test_software_closed_loop_parameters_change_the_actual_test_plant():
    result = run_software_closed_loop(
        seed=12, steps=3, time_step_s=2.0, rescue_users=1,
        initial_battery_wh=80.0, reserve_wh=20.0, relay_activation_energy_wh=5.0,
    )
    assert [item["simulation_time_s"] for item in result["timeline"]] == [0.0, 2.0, 4.0]
    assert result["summary"]["final_rescue_total"] == 1
    assert result["summary"]["final_battery_wh"] == 75.0
    assert result["timeline"][0]["observed_state"]["rescue_total"] == 1


@pytest.mark.parametrize("kwargs", [{"steps": 0}, {"time_step_s": 0.0}, {"rescue_users": -1}])
def test_software_closed_loop_rejects_invalid_time_and_population_parameters(kwargs):
    with pytest.raises(ValueError):
        run_software_closed_loop(**kwargs)


def test_backhaul_unavailable_and_telemetry_gap_do_not_claim_recovery():
    no_backhaul = run_software_closed_loop(seed=7, backhaul_available=False)
    no_telemetry = run_software_closed_loop(seed=7, telemetry_missing_steps=frozenset({0}))
    assert no_backhaul["summary"]["first_rescue_recovery_step"] is None
    assert no_backhaul["summary"]["commands_requested"] == 0
    assert no_telemetry["timeline"][0]["telemetry"]["reasons"] == ["telemetry_missing"]
    assert no_telemetry["timeline"][0]["command_id"] is None
    assert no_telemetry["summary"]["commands_requested"] == 1
    assert no_telemetry["command_audit"][0]["command"]["simulation_step"] >= 1


def test_backhaul_loss_and_restoration_are_recorded_at_discrete_steps():
    result = run_software_closed_loop(seed=7, backhaul_schedule={1: False, 2: True})
    assert result["timeline"][1]["event"]["event_type"] == "backhaul_state_change"
    assert result["timeline"][1]["observed_state"]["rescue_connected"] == 0
    assert result["timeline"][2]["event"]["available"] is True
    assert result["timeline"][2]["observed_state"]["rescue_connected"] == 2
    assert result["summary"]["first_rescue_recovery_step"] == 2


def test_saved_replay_cursor_pauses_resumes_and_steps_without_commands():
    adapter = OfflineReplayAdapter(REPLAY_PATH, "dynamic_failures", "D_lexicographic_rescue_priority")
    adapter.connect()
    first = adapter.read_status()
    assert adapter.advance()["simulation_time_s"] == first["simulation_time_s"]
    second = adapter.step()
    assert second["simulation_time_s"] == 10.0
    adapter.resume()
    third = adapter.advance()
    assert third["simulation_time_s"] == 20.0
    with pytest.raises(AdapterError, match="read-only"):
        adapter.submit_command(_command(SoftwareTestExecutor()))
    adapter.close()


def test_replay_refuses_live_or_invalid_artifacts(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"mode": "live", "live_stream": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="offline provenance"):
        OfflineReplayAdapter(path, "dynamic_failures", "D_lexicographic_rescue_priority")


def test_snapshot_mapping_preserves_real_saved_fields_and_marks_simulation_provenance():
    artifact = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
    snapshot = artifact["strategies"]["D_lexicographic_rescue_priority"]["state_snapshots"][0]
    mapped = map_replay_snapshot(snapshot, source_path=REPLAY_PATH.name, source_sha256="a" * 64)
    assert mapped["simulation_time_s"] == snapshot["time_s"]
    assert mapped["stations"][0]["id"] == snapshot["stations"][0]["id"]
    assert mapped["users"]["total"] == len(snapshot["users"])
    assert mapped["drone"]["position_km"] == [snapshot["drone"]["x_km"], snapshot["drone"]["y_km"]]
    assert mapped["source"]["interpolated"] is False
    assert mapped["quality"] == "saved_simulation_frame_not_measurement"


def test_fault_injection_suite_reports_only_executed_successful_cases():
    results = run_fault_injection_suite(seed=5)
    assert len(results) == 21
    assert all(item["passed"] for item in results)
    assert all(item["seed"] == 5 and item["source"] == "phase17_test_environment_only" for item in results)
    assert all(item["trigger_time"]["value"] is None for item in results)
    assert all(item["trigger_time"]["comparable_to_simulation_time"] is False for item in results)
    recovery = next(item for item in results if item["fault_type"] == "backhaul_recovery")
    assert [event["simulation_time_s"] for event in recovery["observed_simulation_events"]] == [1, 2]
    reconnect = next(item for item in results if item["fault_type"] == "reconnect_reconciliation")
    assert reconnect["reconnection_trace"]["read_while_disconnected_blocked"] is True
    assert reconnect["reconnection_trace"]["automatic_action_before_reconciliation_allowed"] is False
    assert reconnect["reconnection_trace"]["automatic_action_after_reconciliation_allowed"] is True
    assert {item["fault_type"] for item in results} >= {
        "device_disconnect", "telemetry_gap", "message_delay", "message_reorder",
        "message_duplicate", "command_feedback_mismatch", "out_of_range_measurement",
        "battery_state_jump", "command_timeout", "device_rejects_command",
        "backhaul_recovery", "clock_offset", "backhaul_loss",
    }
