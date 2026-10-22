"""Phase 17 hardware-in-the-loop interfaces and software-only safety harness.

This module deliberately has no radio, serial, network-control, or flight-control
drivers. The only executable adapters are read-only saved-record replay and an
isolated software test executor. A software test result is never hardware proof.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol


SCHEMA_VERSION = "1.0"
SUPPORTED_MODE = "abstract_6g_research_simulation_not_real_network_test"
_MEASUREMENT_UNITS = {
    "received_power_dbm": "dBm",
    "rssi_dbm": "dBm",
    "frequency_hz": "Hz",
    "bandwidth_hz": "Hz",
    "latency_ms": "ms",
    "battery_wh": "Wh",
    "distance_km": "km",
    "position_x_km": "km",
    "position_y_km": "km",
    "temperature_c": "degC",
    "device_status": "1",
}
_MEASUREMENT_RANGES = {
    "received_power_dbm": (-200.0, 100.0),
    "rssi_dbm": (-200.0, 100.0),
    "frequency_hz": (0.0, 1.0e12),
    "bandwidth_hz": (0.0, 1.0e10),
    "latency_ms": (0.0, 1.0e9),
    "battery_wh": (0.0, 1.0e9),
    "distance_km": (0.0, 1.0e9),
    "position_x_km": (-1.0e9, 1.0e9),
    "position_y_km": (-1.0e9, 1.0e9),
    "temperature_c": (-273.15, 1000.0),
}


class AdapterStatus(StrEnum):
    INTERFACE_ONLY = "INTERFACE_ONLY"
    IMPLEMENTED_UNTESTED = "IMPLEMENTED_UNTESTED"
    IMPLEMENTED_AND_TESTED = "IMPLEMENTED_AND_TESTED"
    UNAVAILABLE = "UNAVAILABLE"
    SIMULATED = "SIMULATED"
    REPLAY_ONLY = "REPLAY_ONLY"


class DeviceType(StrEnum):
    RADIO_MEASUREMENT = "radio_measurement_device"
    LINK_STATE = "wireless_link_state_device"
    UAV_TELEMETRY = "uav_telemetry_device"
    UAV_FLIGHT_CONTROL = "uav_flight_control"
    BASE_STATION_STATUS = "base_station_status_interface"
    FILE_REPLAY = "offline_file_and_record_replay"
    SOFTWARE_EXECUTOR = "isolated_software_test_executor"


class TestMode(StrEnum):
    OFFLINE_REPLAY = "OFFLINE_REPLAY"
    SOFTWARE_CLOSED_LOOP = "SOFTWARE_CLOSED_LOOP"
    HARDWARE_IN_LOOP = "HARDWARE_IN_LOOP"
    LIVE_DEVICE = "LIVE_DEVICE"


class ClockDomain(StrEnum):
    DEVICE_RAW = "device_raw"
    RECEIVER_WALL = "receiver_wall_clock"
    SIMULATION = "simulation_time"
    REPLAY = "replay_time"
    WALL = "wall_clock_utc"


class MessageQuality(StrEnum):
    GOOD = "GOOD"
    SUSPECT = "SUSPECT"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class FaultKind(StrEnum):
    DEVICE_DISCONNECT = "device_disconnect"
    TELEMETRY_GAP = "telemetry_gap"
    MESSAGE_DELAY = "message_delay"
    MESSAGE_REORDER = "message_reorder"
    MESSAGE_DUPLICATE = "message_duplicate"
    COMMAND_FEEDBACK_MISMATCH = "command_feedback_mismatch"
    OUT_OF_RANGE_MEASUREMENT = "out_of_range_measurement"
    BATTERY_STATE_JUMP = "battery_state_jump"
    COMMAND_TIMEOUT = "command_timeout"
    DEVICE_REJECTS_COMMAND = "device_rejects_command"
    CONNECTION_RECOVERY = "connection_recovery"
    BACKHAUL_RECOVERY = "backhaul_recovery"
    CLOCK_OFFSET = "clock_offset"
    BACKHAUL_LOSS = "backhaul_loss"
    UNIT_MISMATCH = "unit_mismatch"
    UNKNOWN_DEVICE = "unknown_device"
    MANUAL_STOP_LATCH = "manual_stop_latch"
    RECONNECT_RECONCILIATION = "reconnect_reconciliation"
    SAFETY_GATE_BYPASS = "safety_gate_bypass"
    UNSUPPORTED_SCHEMA = "unsupported_schema"


class AdapterError(RuntimeError):
    """An adapter cannot perform the requested operation."""


@dataclass(frozen=True)
class ClockStamp:
    value: float
    domain: ClockDomain
    precision_ms: float | None
    offset_to_receiver_ms: float | None = None
    utc_iso: str | None = None

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not math.isfinite(self.value):
            issues.append("timestamp_not_finite")
        if self.precision_ms is not None and (
            not math.isfinite(self.precision_ms) or self.precision_ms < 0
        ):
            issues.append("timestamp_precision_invalid")
        if self.offset_to_receiver_ms is not None and not math.isfinite(self.offset_to_receiver_ms):
            issues.append("clock_offset_invalid")
        return issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "domain": self.domain.value,
            "precision_ms": self.precision_ms,
            "offset_to_receiver_ms": self.offset_to_receiver_ms,
            "utc_iso": self.utc_iso,
        }


@dataclass(frozen=True)
class MeasurementUncertainty:
    standard_uncertainty: float
    unit: str
    coverage_factor: float | None = None


@dataclass(frozen=True)
class TelemetryMessage:
    schema_version: str
    device_id: str
    session_id: str
    sequence_number: int
    timestamp: ClockStamp
    received_at: ClockStamp
    source: str
    measurement_type: str
    value: float | dict[str, Any]
    unit: str
    quality: MessageQuality
    uncertainty: MeasurementUncertainty | None
    validity: bool
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "sequence_number": self.sequence_number,
            "timestamp": self.timestamp.to_dict(),
            "received_at": self.received_at.to_dict(),
            "source": self.source,
            "measurement_type": self.measurement_type,
            "value": self.value,
            "unit": self.unit,
            "quality": self.quality.value,
            "uncertainty": (
                None
                if self.uncertainty is None
                else {
                    "standard_uncertainty": self.uncertainty.standard_uncertainty,
                    "unit": self.uncertainty.unit,
                    "coverage_factor": self.uncertainty.coverage_factor,
                }
            ),
            "validity": self.validity,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class MessageValidation:
    accepted: bool
    trusted_for_control: bool
    reasons: tuple[str, ...]
    age_seconds: float | None
    age_comparable: bool
    message: TelemetryMessage | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "trusted_for_control": self.trusted_for_control,
            "reasons": list(self.reasons),
            "age_seconds": self.age_seconds,
            "age_comparable": self.age_comparable,
        }


def _parse_clock(raw: Any) -> ClockStamp | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        domain = ClockDomain(str(raw["domain"]))
        value = float(raw["value"])
        precision_raw = raw.get("precision_ms")
        offset_raw = raw.get("offset_to_receiver_ms")
        return ClockStamp(
            value=value,
            domain=domain,
            precision_ms=None if precision_raw is None else float(precision_raw),
            offset_to_receiver_ms=None if offset_raw is None else float(offset_raw),
            utc_iso=str(raw["utc_iso"]) if raw.get("utc_iso") is not None else None,
        )
    except (KeyError, TypeError, ValueError):
        return None


class MessageContractValidator:
    """Validate version, identity, units, ordering, freshness, and provenance."""

    def __init__(self, known_devices: set[str] | frozenset[str]) -> None:
        self.known_devices = frozenset(known_devices)
        self._last_sequence: dict[tuple[str, str], int] = {}

    def validate(
        self,
        raw: Mapping[str, Any],
        *,
        now: ClockStamp,
        max_age_seconds: float = 2.0,
    ) -> MessageValidation:
        reasons: list[str] = []
        if not isinstance(raw, Mapping):
            return MessageValidation(False, False, ("message_not_object",), None, False, None)
        if raw.get("schema_version") != SCHEMA_VERSION:
            reasons.append("schema_version_unsupported")
        device_id = raw.get("device_id")
        session_id = raw.get("session_id")
        if not isinstance(device_id, str) or not device_id:
            reasons.append("device_id_missing")
        elif device_id not in self.known_devices:
            reasons.append("unknown_device")
        if not isinstance(session_id, str) or not session_id:
            reasons.append("session_id_missing")
        sequence = raw.get("sequence_number")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            reasons.append("sequence_number_invalid")
            sequence = None

        timestamp = _parse_clock(raw.get("timestamp"))
        received_at = _parse_clock(raw.get("received_at"))
        if timestamp is None:
            reasons.append("timestamp_missing_or_invalid")
        else:
            reasons.extend(timestamp.validate())
        if received_at is None:
            reasons.append("receiver_timestamp_missing_or_invalid")
        else:
            reasons.extend(received_at.validate())

        measurement_type = raw.get("measurement_type")
        unit = raw.get("unit")
        if not isinstance(measurement_type, str) or not measurement_type:
            reasons.append("measurement_type_missing")
            measurement_type = ""
        if not isinstance(unit, str) or not unit:
            reasons.append("unit_missing")
            unit = ""
        expected_unit = _MEASUREMENT_UNITS.get(measurement_type)
        if expected_unit is None:
            reasons.append("measurement_type_unsupported")
        elif unit != expected_unit:
            reasons.append("unit_mismatch")

        value = raw.get("value")
        if measurement_type == "device_status":
            if not isinstance(value, dict):
                reasons.append("device_status_value_invalid")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            reasons.append("measurement_value_invalid")
        elif measurement_type in _MEASUREMENT_RANGES:
            lower, upper = _MEASUREMENT_RANGES[measurement_type]
            if not lower <= float(value) <= upper:
                reasons.append("measurement_value_out_of_range")

        quality_raw = raw.get("quality")
        try:
            quality = MessageQuality(str(quality_raw))
        except ValueError:
            quality = MessageQuality.UNKNOWN
            reasons.append("quality_unknown")
        if quality is not MessageQuality.GOOD:
            reasons.append("quality_not_good")
        if raw.get("validity") is not True:
            reasons.append("message_marked_invalid")

        uncertainty: MeasurementUncertainty | None = None
        uncertainty_raw = raw.get("uncertainty")
        if measurement_type != "device_status":
            if not isinstance(uncertainty_raw, Mapping):
                reasons.append("measurement_uncertainty_missing")
            else:
                try:
                    uncertainty = MeasurementUncertainty(
                        standard_uncertainty=float(uncertainty_raw["standard_uncertainty"]),
                        unit=str(uncertainty_raw["unit"]),
                        coverage_factor=(
                            None
                            if uncertainty_raw.get("coverage_factor") is None
                            else float(uncertainty_raw["coverage_factor"])
                        ),
                    )
                    if not math.isfinite(uncertainty.standard_uncertainty) or uncertainty.standard_uncertainty < 0:
                        reasons.append("measurement_uncertainty_invalid")
                    if uncertainty.unit != unit:
                        reasons.append("uncertainty_unit_mismatch")
                    if uncertainty.coverage_factor is not None and (
                        not math.isfinite(uncertainty.coverage_factor) or uncertainty.coverage_factor <= 0
                    ):
                        reasons.append("coverage_factor_invalid")
                except (KeyError, TypeError, ValueError):
                    uncertainty = None
                    reasons.append("measurement_uncertainty_invalid")

        provenance = raw.get("provenance")
        if not isinstance(provenance, dict) or not provenance:
            reasons.append("provenance_missing")
            provenance = {}
        source = raw.get("source")
        if not isinstance(source, str) or not source:
            reasons.append("source_missing")
            source = ""

        if timestamp is not None and timestamp.domain is now.domain:
            age = now.value - timestamp.value
            comparable = True
            if age < -1e-9:
                reasons.append("timestamp_from_future")
            elif age > max_age_seconds:
                reasons.append("telemetry_stale")
        else:
            age = None
            comparable = False

        if device_id and session_id and sequence is not None:
            stream_key = (device_id, session_id)
            previous = self._last_sequence.get(stream_key)
            if previous is not None and sequence == previous:
                reasons.append("duplicate_message")
            elif previous is not None and sequence < previous:
                reasons.append("sequence_out_of_order")

        message: TelemetryMessage | None = None
        if timestamp is not None and received_at is not None and sequence is not None:
            message = TelemetryMessage(
                schema_version=str(raw.get("schema_version", "")),
                device_id=str(device_id or ""),
                session_id=str(session_id or ""),
                sequence_number=sequence,
                timestamp=timestamp,
                received_at=received_at,
                source=source,
                measurement_type=measurement_type,
                value=value,
                unit=unit,
                quality=quality,
                uncertainty=uncertainty,
                validity=raw.get("validity") is True,
                provenance=provenance,
            )
        accepted = not reasons
        trusted = accepted and (measurement_type == "device_status" or uncertainty is not None)
        if accepted and message is not None:
            self._last_sequence[(message.device_id, message.session_id)] = message.sequence_number
        return MessageValidation(accepted, trusted, tuple(dict.fromkeys(reasons)), age, comparable, message)


@dataclass(frozen=True)
class DeviceCapability:
    device_type: DeviceType
    status: AdapterStatus
    can_read_status: bool
    can_read_measurement: bool
    can_submit_command: bool
    supported_units: tuple[str, ...] = ()
    supported_commands: tuple[str, ...] = ()
    live_device: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_type": self.device_type.value,
            "status": self.status.value,
            "can_read_status": self.can_read_status,
            "can_read_measurement": self.can_read_measurement,
            "can_submit_command": self.can_submit_command,
            "supported_units": list(self.supported_units),
            "supported_commands": list(self.supported_commands),
            "live_device": self.live_device,
        }


class DeviceAdapter(Protocol):
    status: AdapterStatus

    def connect(self) -> dict[str, Any]: ...
    def disconnect(self) -> dict[str, Any]: ...
    def get_capabilities(self) -> DeviceCapability: ...
    def read_status(self) -> dict[str, Any]: ...
    def read_measurement(self) -> dict[str, Any]: ...
    def submit_command(self, command: "ControlCommand") -> "CommandReceipt": ...
    def get_command_result(self, command_id: str) -> "CommandReceipt | None": ...
    def health_check(self) -> dict[str, Any]: ...
    def close(self) -> None: ...


def map_replay_snapshot(snapshot: Mapping[str, Any], *, source_path: str, source_sha256: str) -> dict[str, Any]:
    """Map one saved simulator frame without inventing values or interpolation."""
    time_s = snapshot.get("time_s")
    if isinstance(time_s, bool) or not isinstance(time_s, (int, float)) or not math.isfinite(float(time_s)):
        raise ValueError("simulator snapshot has no valid simulation timestamp")
    stations = snapshot.get("stations")
    links = snapshot.get("links")
    users = snapshot.get("users")
    drone = snapshot.get("drone")
    if not isinstance(stations, list) or not isinstance(links, list) or not isinstance(users, list) or not isinstance(drone, dict):
        raise ValueError("simulator snapshot is missing stations, links, users, or drone")
    required_station = {"id", "healthy", "capacity_mbps"}
    if any(not isinstance(item, dict) or not required_station.issubset(item) for item in stations):
        raise ValueError("station snapshot is incomplete")
    required_user = {"id", "connected", "group"}
    if any(not isinstance(item, dict) or not required_user.issubset(item) for item in users):
        raise ValueError("user snapshot is incomplete")
    if not {"id", "x_km", "y_km", "battery_wh", "backhaul_available"}.issubset(drone):
        raise ValueError("drone snapshot is incomplete")
    rescue = [user for user in users if user["group"] == "rescue"]
    return {
        "schema_version": SCHEMA_VERSION,
        "simulation_time_s": float(time_s),
        "clock_domain": ClockDomain.REPLAY.value,
        "source": {
            "kind": "precomputed_simulator_replay",
            "path": source_path,
            "sha256": source_sha256,
            "live_device": False,
            "interpolated": False,
        },
        "stations": [
            {"id": item["id"], "healthy": bool(item["healthy"]), "capacity_mbps": item["capacity_mbps"]}
            for item in stations
        ],
        "links": links,
        "users": {
            "total": len(users),
            "connected": sum(bool(item["connected"]) for item in users),
            "rescue_total": len(rescue),
            "rescue_connected": sum(bool(item["connected"]) for item in rescue),
        },
        "drone": {
            "id": drone["id"],
            "position_km": [drone["x_km"], drone["y_km"]],
            "battery_wh": drone["battery_wh"],
            "active": bool(drone.get("active", False)),
            "backhaul_available": bool(drone["backhaul_available"]),
        },
        "decision": snapshot.get("decision"),
        "quality": "saved_simulation_frame_not_measurement",
    }


class OfflineReplayAdapter:
    """Read-only cursor over an existing Phase 6 simulator artifact."""

    status = AdapterStatus.REPLAY_ONLY

    def __init__(self, artifact_path: str | Path, scenario_id: str, strategy_id: str) -> None:
        self.path = Path(artifact_path).resolve()
        self.payload = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            self.payload.get("mode") != "precomputed_offline_replay"
            or self.payload.get("live_stream") is not False
            or self.payload.get("model_scope") != SUPPORTED_MODE
            or self.payload.get("scenario_id") != scenario_id
        ):
            raise ValueError("replay artifact is missing valid offline provenance")
        run = self.payload.get("strategies", {}).get(strategy_id)
        frames = run.get("state_snapshots") if isinstance(run, dict) else None
        if not isinstance(frames, list) or not frames:
            raise ValueError("replay strategy has no saved discrete frames")
        times = [frame.get("time_s") for frame in frames]
        if any(not isinstance(value, (int, float)) for value in times):
            raise ValueError("replay contains a frame without a simulation timestamp")
        if any(float(right) <= float(left) for left, right in zip(times, times[1:])):
            raise ValueError("replay timestamps must be strictly increasing")
        self.scenario_id = scenario_id
        self.strategy_id = strategy_id
        self.frames = frames
        self.source_sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self._cursor = 0
        self._paused = True
        self._connected = False

    def connect(self) -> dict[str, Any]:
        self._connected = True
        return {"connected": True, "local_file": True, "live_device": False, "status": self.status.value}

    def disconnect(self) -> dict[str, Any]:
        self._connected = False
        return {"connected": False, "local_file": True, "live_device": False}

    def get_capabilities(self) -> DeviceCapability:
        return DeviceCapability(
            DeviceType.FILE_REPLAY,
            self.status,
            can_read_status=True,
            can_read_measurement=False,
            can_submit_command=False,
            supported_commands=("pause", "resume", "step", "reset"),
            live_device=False,
        )

    def read_status(self) -> dict[str, Any]:
        if not self._connected:
            raise AdapterError("replay adapter is disconnected")
        return map_replay_snapshot(
            self.frames[self._cursor],
            source_path=self.path.name,
            source_sha256=self.source_sha256,
        )

    def read_measurement(self) -> dict[str, Any]:
        raise AdapterError("saved simulator frames are not radio measurements")

    def submit_command(self, command: "ControlCommand") -> "CommandReceipt":
        raise AdapterError("OFFLINE_REPLAY is read-only; device commands are prohibited")

    def get_command_result(self, command_id: str) -> "CommandReceipt | None":
        return None

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "REPLAY_SOURCE_OK" if self.path.is_file() else "REPLAY_SOURCE_MISSING",
            "connected": self._connected,
            "mode": TestMode.OFFLINE_REPLAY.value,
            "live_device": False,
            "source_sha256": self.source_sha256,
        }

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def step(self) -> dict[str, Any] | None:
        """Advance exactly one stored frame, even while paused; never interpolate."""
        if self._cursor + 1 >= len(self.frames):
            return None
        self._cursor += 1
        return self.read_status()

    def advance(self) -> dict[str, Any] | None:
        if self._paused:
            return self.read_status()
        return self.step()

    def reset(self) -> None:
        self._cursor = 0
        self._paused = True

    def close(self) -> None:
        self.disconnect()


class UnavailableHardwareAdapter:
    """Evidence-bearing unavailable adapter; it cannot open or control hardware."""

    status = AdapterStatus.UNAVAILABLE

    def __init__(self, device_type: DeviceType, adapter_id: str) -> None:
        self.device_type = device_type
        self.adapter_id = adapter_id

    def connect(self) -> dict[str, Any]:
        raise AdapterError(f"{self.adapter_id} is unavailable: no verified device driver is installed")

    def disconnect(self) -> dict[str, Any]:
        return {"connected": False, "live_device": False}

    def get_capabilities(self) -> DeviceCapability:
        return DeviceCapability(self.device_type, self.status, False, False, False, live_device=False)

    def read_status(self) -> dict[str, Any]:
        raise AdapterError(f"{self.adapter_id} has no hardware status source")

    def read_measurement(self) -> dict[str, Any]:
        raise AdapterError(f"{self.adapter_id} has no hardware measurement source")

    def submit_command(self, command: "ControlCommand") -> "CommandReceipt":
        raise AdapterError(f"{self.adapter_id} has no command transport")

    def get_command_result(self, command_id: str) -> "CommandReceipt | None":
        return None

    def health_check(self) -> dict[str, Any]:
        return {"status": self.status.value, "adapter_id": self.adapter_id, "live_device": False}

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class ControlCommand:
    command_id: str
    target_device_id: str
    action: str
    parameters: dict[str, Any]
    source: str
    request_time: ClockStamp
    test_mode: TestMode
    experiment_id: str
    simulation_step: int
    authorization_reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "command_id": self.command_id,
            "target_device_id": self.target_device_id,
            "action": self.action,
            "parameters": self.parameters,
            "source": self.source,
            "request_time": self.request_time.to_dict(),
            "test_mode": self.test_mode.value,
            "experiment_id": self.experiment_id,
            "simulation_step": self.simulation_step,
            "authorization_reference": self.authorization_reference,
        }


@dataclass(frozen=True)
class SafetyContext:
    mode: TestMode
    adapter_status: AdapterStatus
    target_known: bool
    allowed_actions: frozenset[str]
    telemetry_fresh: bool | None
    state_known: bool
    emergency_stop_latched: bool = False
    manual_stop_latched: bool = False
    authorized: bool = False
    experiment_policy_allows: bool = True
    reconnect_needs_reconciliation: bool = False
    manual_restart_approved: bool = False
    battery_wh: float | None = None
    reserve_wh: float | None = None
    requested_energy_wh: float = 0.0


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    priority: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CommandReceipt:
    command_id: str
    execution_status: str
    executed_in: str
    requested_state: dict[str, Any]
    reported_state: dict[str, Any] | None
    feedback_matches: bool | None
    completed: bool
    timestamp: ClockStamp
    fault_injection: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "command_id": self.command_id,
            "execution_status": self.execution_status,
            "executed_in": self.executed_in,
            "requested_state": self.requested_state,
            "reported_state": self.reported_state,
            "feedback_matches": self.feedback_matches,
            "completed": self.completed,
            "timestamp": self.timestamp.to_dict(),
            "fault_injection": self.fault_injection,
        }


class SafetyGate:
    """Fail-closed command gate; the only allowed executor is the software test plant."""

    def evaluate(self, command: ControlCommand, context: SafetyContext) -> SafetyDecision:
        if context.mode in {TestMode.HARDWARE_IN_LOOP, TestMode.LIVE_DEVICE}:
            return SafetyDecision(False, "SAFETY", "real_hardware_output_disabled_in_phase17")
        if context.mode is TestMode.OFFLINE_REPLAY:
            return SafetyDecision(False, "SAFETY", "offline_replay_is_read_only")
        if context.adapter_status is not AdapterStatus.SIMULATED:
            return SafetyDecision(False, "SAFETY", "software_executor_not_confirmed")
        if not context.target_known:
            return SafetyDecision(False, "DEVICE_RESTRICTIONS", "unknown_target_device")
        if command.action not in context.allowed_actions:
            return SafetyDecision(False, "DEVICE_RESTRICTIONS", "device_capability_does_not_allow_action")
        if command.action == "emergency_stop":
            return SafetyDecision(True, "EMERGENCY_STOP", "emergency_stop_has_priority")
        if context.emergency_stop_latched and command.action != "clear_emergency_stop":
            return SafetyDecision(False, "EMERGENCY_STOP", "emergency_stop_latched")
        if context.reconnect_needs_reconciliation:
            return SafetyDecision(False, "SAFETY", "device_state_reconciliation_required_after_reconnect")
        if not context.state_known:
            return SafetyDecision(False, "SAFETY", "critical_device_state_unknown")
        if context.telemetry_fresh is not True:
            return SafetyDecision(False, "SAFETY", "telemetry_missing_stale_or_clock_incomparable")
        if context.manual_stop_latched and command.source == "automatic":
            return SafetyDecision(False, "MANUAL_USER_CONTROL", "manual_stop_latched_no_automatic_resume")
        if command.action == "clear_emergency_stop":
            if command.source != "manual" or not context.authorized or not context.manual_restart_approved:
                return SafetyDecision(False, "MANUAL_USER_CONTROL", "explicit_authorized_manual_restart_required")
        elif command.source == "manual" and not context.authorized:
            return SafetyDecision(False, "MANUAL_USER_CONTROL", "manual_command_not_authorized")
        if command.source == "automatic" and not context.experiment_policy_allows:
            return SafetyDecision(False, "EXPERIMENT_POLICY", "experiment_policy_blocks_automatic_action")
        if context.battery_wh is not None or context.reserve_wh is not None:
            if context.battery_wh is None or context.reserve_wh is None:
                return SafetyDecision(False, "SAFETY", "battery_or_return_reserve_unknown")
            if context.battery_wh - context.requested_energy_wh < context.reserve_wh - 1e-9:
                return SafetyDecision(False, "SAFETY", "command_would_breach_return_reserve")
        return SafetyDecision(True, "AUTOMATIC_EXECUTION", "software_test_command_allowed")


class SoftwareTestExecutor:
    """Deterministic in-memory executor; it has no physical output channel."""

    status = AdapterStatus.SIMULATED
    _ACTIONS = frozenset({"set_relay_active", "emergency_stop", "clear_emergency_stop"})

    def __init__(
        self,
        *,
        device_id: str = "uav-test-01",
        initial_battery_wh: float = 120.0,
        relay_activation_energy_wh: float = 8.0,
    ) -> None:
        if not math.isfinite(initial_battery_wh) or initial_battery_wh <= 0:
            raise ValueError("initial test battery must be finite and positive")
        if not math.isfinite(relay_activation_energy_wh) or relay_activation_energy_wh < 0:
            raise ValueError("relay activation energy must be finite and non-negative")
        self.device_id = device_id
        self.relay_activation_energy_wh = float(relay_activation_energy_wh)
        self._connected = False
        self._state: dict[str, Any] = {
            "relay_active": False,
            "battery_wh": float(initial_battery_wh),
            "emergency_stop": False,
            "manual_stop": False,
        }
        self._receipts: dict[str, CommandReceipt] = {}

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    def connect(self) -> dict[str, Any]:
        self._connected = True
        return {"connected": True, "status": self.status.value, "live_device": False}

    def disconnect(self) -> dict[str, Any]:
        self._connected = False
        return {"connected": False, "live_device": False}

    def get_capabilities(self) -> DeviceCapability:
        return DeviceCapability(
            DeviceType.SOFTWARE_EXECUTOR,
            self.status,
            True,
            False,
            True,
            supported_units=("Wh",),
            supported_commands=tuple(sorted(self._ACTIONS)),
            live_device=False,
        )

    def read_status(self) -> dict[str, Any]:
        if not self._connected:
            raise AdapterError("software executor is disconnected")
        return {
            "device_id": self.device_id,
            "status": self.status.value,
            "state": self.state,
            "source": "SYNTHETIC_TEST_ONLY",
            "live_device": False,
        }

    def read_measurement(self) -> dict[str, Any]:
        raise AdapterError("software test executor does not create radio measurements")

    def submit_command(self, command: ControlCommand, *, fault_injection: FaultKind | None = None) -> CommandReceipt:
        if not self._connected:
            raise AdapterError("software executor is disconnected")
        if command.target_device_id != self.device_id:
            raise AdapterError("command target does not match software executor")
        if command.action not in self._ACTIONS:
            raise AdapterError("software executor does not implement this action")
        if command.command_id in self._receipts:
            raise AdapterError("duplicate command_id")

        parameters = dict(command.parameters)
        if fault_injection is FaultKind.COMMAND_TIMEOUT:
            receipt = CommandReceipt(
                command.command_id, "TIMEOUT_UNKNOWN", "SIMULATED", parameters, None,
                None, False, command.request_time, fault_injection.value,
            )
        elif fault_injection is FaultKind.DEVICE_REJECTS_COMMAND:
            receipt = CommandReceipt(
                command.command_id, "REJECTED_BY_TEST_EXECUTOR", "SIMULATED", parameters,
                dict(self._state), False, False, command.request_time, fault_injection.value,
            )
        else:
            if command.action == "set_relay_active":
                active = parameters.get("active")
                if not isinstance(active, bool):
                    raise AdapterError("set_relay_active requires a boolean active parameter")
                if active and not self._state["relay_active"]:
                    self._state["battery_wh"] = round(float(self._state["battery_wh"]) - self.relay_activation_energy_wh, 9)
                self._state["relay_active"] = active
            elif command.action == "emergency_stop":
                self._state["emergency_stop"] = True
                self._state["relay_active"] = False
            elif command.action == "clear_emergency_stop":
                self._state["emergency_stop"] = False
            reported = dict(self._state)
            requested_state = (
                {"relay_active": parameters["active"]}
                if command.action == "set_relay_active"
                else {"emergency_stop": command.action == "emergency_stop"}
            )
            if fault_injection is FaultKind.COMMAND_FEEDBACK_MISMATCH:
                reported["relay_active"] = not bool(reported["relay_active"])
            matches = all(reported.get(key) == value for key, value in requested_state.items())
            receipt = CommandReceipt(
                command.command_id, "COMPLETED" if matches else "FEEDBACK_MISMATCH", "SIMULATED",
                requested_state, reported, matches, matches, command.request_time,
                fault_injection.value if fault_injection else None,
            )
        self._receipts[command.command_id] = receipt
        return receipt

    def get_command_result(self, command_id: str) -> CommandReceipt | None:
        return self._receipts.get(command_id)

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "SOFTWARE_EXECUTOR_READY" if self._connected else "SOFTWARE_EXECUTOR_DISCONNECTED",
            "executor": "in_memory_test_only",
            "live_device": False,
        }

    def close(self) -> None:
        self.disconnect()


@dataclass
class SoftwareWorld:
    simulation_time_s: int | float = 0
    station_healthy: bool = False
    backhaul_available: bool = True
    rescue_total: int = 2
    rescue_connected: int = 0
    telemetry_available: bool = True
    manual_stop: bool = False
    relay_active: bool = False
    battery_wh: float = 120.0
    reserve_wh: float = 30.0


def _status_message(world: SoftwareWorld, sequence_number: int, session_id: str) -> dict[str, Any]:
    stamp = {"value": float(world.simulation_time_s), "domain": ClockDomain.SIMULATION.value, "precision_ms": 1.0}
    return {
        "schema_version": SCHEMA_VERSION,
        "device_id": "uav-test-01",
        "session_id": session_id,
        "sequence_number": sequence_number,
        "timestamp": stamp,
        "received_at": stamp,
        "source": "SYNTHETIC_TEST_ONLY",
        "measurement_type": "device_status",
        "value": {
            "station_healthy": world.station_healthy,
            "backhaul_available": world.backhaul_available,
            "rescue_connected": world.rescue_connected,
            "rescue_total": world.rescue_total,
            "relay_active": world.relay_active,
            "battery_wh": world.battery_wh,
        },
        "unit": "1",
        "quality": MessageQuality.GOOD.value,
        "uncertainty": None,
        "validity": True,
        "provenance": {"classification": "SYNTHETIC_TEST_ONLY", "simulation_step": world.simulation_time_s},
    }


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_software_closed_loop(
    *,
    seed: int = 1717,
    backhaul_available: bool = True,
    initial_battery_wh: float = 120.0,
    reserve_wh: float = 30.0,
    relay_activation_energy_wh: float = 8.0,
    rescue_users: int = 2,
    steps: int = 6,
    time_step_s: float = 1.0,
    telemetry_max_age_s: float = 1.0,
    manual_stop: bool = False,
    telemetry_missing_steps: frozenset[int] = frozenset(),
    backhaul_schedule: Mapping[int, bool] | None = None,
) -> dict[str, Any]:
    """Run a fixed, synthetic test plant through observe→gate→execute→feedback."""
    if isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0:
        raise ValueError("steps must be a positive integer")
    if isinstance(rescue_users, bool) or not isinstance(rescue_users, int) or rescue_users < 0:
        raise ValueError("rescue_users must be a non-negative integer")
    if not math.isfinite(time_step_s) or time_step_s <= 0:
        raise ValueError("time_step_s must be finite and positive")
    if not math.isfinite(telemetry_max_age_s) or telemetry_max_age_s < 0:
        raise ValueError("telemetry_max_age_s must be finite and non-negative")
    executor = SoftwareTestExecutor(
        initial_battery_wh=initial_battery_wh,
        relay_activation_energy_wh=relay_activation_energy_wh,
    )
    executor.connect()
    validator = MessageContractValidator({executor.device_id})
    gate = SafetyGate()
    world = SoftwareWorld(
        backhaul_available=backhaul_available,
        manual_stop=manual_stop,
        battery_wh=initial_battery_wh,
        reserve_wh=reserve_wh,
        rescue_total=rescue_users,
    )
    timeline: list[dict[str, Any]] = []
    command_audit: list[dict[str, Any]] = []
    auto_lockout = False
    rescue_recovery_tick: int | None = None

    for step in range(steps):
        simulation_time_s = step * time_step_s
        world.simulation_time_s = simulation_time_s
        event: dict[str, Any] | None = None
        if backhaul_schedule is not None and step in backhaul_schedule:
            previous_backhaul = world.backhaul_available
            world.backhaul_available = bool(backhaul_schedule[step])
            if world.backhaul_available != previous_backhaul:
                event = {
                    "event_type": "backhaul_state_change",
                    "previous_available": previous_backhaul,
                    "available": world.backhaul_available,
                    "source": "SYNTHETIC_TEST_ONLY",
                }
        world.battery_wh = float(executor.state["battery_wh"])
        world.relay_active = bool(executor.state["relay_active"])
        world.rescue_connected = (
            world.rescue_total
            if executor.state["relay_active"] and world.backhaul_available
            else 0
        )
        message_raw = _status_message(world, step + 1, f"software-loop-{seed}")
        if not world.telemetry_available or step in telemetry_missing_steps:
            validation = MessageValidation(False, False, ("telemetry_missing",), None, False, None)
        else:
            now = ClockStamp(float(simulation_time_s), ClockDomain.SIMULATION, 1.0)
            validation = validator.validate(message_raw, now=now, max_age_seconds=telemetry_max_age_s)

        decision: dict[str, Any] = {"action": "hold", "reason": "no_action_required"}
        command_record: dict[str, Any] | None = None
        if validation.accepted and validation.trusted_for_control and not auto_lockout:
            if world.rescue_connected < world.rescue_total:
                if not world.backhaul_available:
                    decision = {"action": "hold", "reason": "no_end_to_end_backhaul"}
                elif world.battery_wh - relay_activation_energy_wh < world.reserve_wh:
                    decision = {"action": "hold", "reason": "return_reserve_would_be_breached"}
                elif world.manual_stop:
                    decision = {"action": "hold", "reason": "manual_stop_latched"}
                elif not executor.state["relay_active"]:
                    decision = {"action": "set_relay_active", "reason": "synthetic_rescue_path_available"}
            else:
                decision = {"action": "hold", "reason": "rescue_path_confirmed_by_test_plant"}

            if decision["action"] == "set_relay_active":
                command = ControlCommand(
                    command_id=f"phase17-{seed}-step-{step}-relay-on",
                    target_device_id=executor.device_id,
                    action="set_relay_active",
                    parameters={"active": True},
                    source="automatic",
                    request_time=now,
                    test_mode=TestMode.SOFTWARE_CLOSED_LOOP,
                    experiment_id=f"phase17-software-{seed}",
                    simulation_step=step,
                )
                context = SafetyContext(
                    mode=TestMode.SOFTWARE_CLOSED_LOOP,
                    adapter_status=executor.status,
                    target_known=True,
                    allowed_actions=executor.get_capabilities().supported_commands,
                    telemetry_fresh=validation.age_comparable and validation.age_seconds is not None and validation.age_seconds <= telemetry_max_age_s,
                    state_known=True,
                    experiment_policy_allows=True,
                    battery_wh=world.battery_wh,
                    reserve_wh=world.reserve_wh,
                    requested_energy_wh=relay_activation_energy_wh,
                )
                safety = gate.evaluate(command, context)
                receipt = executor.submit_command(command) if safety.allowed else None
                command_record = {
                    "command": command.to_dict(),
                    "safety": safety.to_dict(),
                    "receipt": receipt.to_dict() if receipt else None,
                }
                command_audit.append(command_record)
                if receipt is not None and not receipt.feedback_matches:
                    auto_lockout = True
                if receipt is not None and receipt.feedback_matches:
                    decision["reason"] = "software_executor_feedback_confirmed"

        if world.rescue_connected == world.rescue_total and rescue_recovery_tick is None:
            rescue_recovery_tick = step
        timeline.append({
            "simulation_step": step,
            "simulation_time_s": simulation_time_s,
            "event": event,
            "input_source": "SYNTHETIC_TEST_ONLY",
            "telemetry": validation.to_dict(),
            "observed_state": {
                "station_healthy": world.station_healthy,
                "backhaul_available": world.backhaul_available,
                "rescue_connected": world.rescue_connected,
                "rescue_total": world.rescue_total,
                "relay_active": executor.state["relay_active"],
                "battery_wh": executor.state["battery_wh"],
            },
            "decision": decision,
            "command_id": command_record["command"]["command_id"] if command_record else None,
            "auto_lockout": auto_lockout,
        })

    stable_result = {
        "schema_version": SCHEMA_VERSION,
        "test_mode": TestMode.SOFTWARE_CLOSED_LOOP.value,
        "source_classification": "SYNTHETIC_TEST_ONLY",
        "live_device": False,
        "real_hardware_output_enabled": False,
        "seed": seed,
        "test_configuration": {
            "backhaul_available": backhaul_available,
            "initial_battery_wh": initial_battery_wh,
            "reserve_wh": reserve_wh,
            "manual_stop": manual_stop,
            "telemetry_missing_steps": sorted(telemetry_missing_steps),
            "backhaul_schedule": {str(key): value for key, value in sorted((backhaul_schedule or {}).items())},
        },
        "time_step_s": time_step_s,
        "timeline": timeline,
        "command_audit": command_audit,
        "summary": {
            "steps": len(timeline),
            "commands_requested": len(command_audit),
            "commands_allowed": sum(record["safety"]["allowed"] for record in command_audit),
            "feedback_matches": sum(bool(record["receipt"] and record["receipt"]["feedback_matches"]) for record in command_audit),
            "first_rescue_recovery_step": rescue_recovery_tick,
            "final_rescue_connected": timeline[-1]["observed_state"]["rescue_connected"],
            "final_rescue_total": timeline[-1]["observed_state"]["rescue_total"],
            "final_battery_wh": executor.state["battery_wh"],
            "automatic_lockout": auto_lockout,
        },
    }
    stable_result["deterministic_output_sha256"] = _canonical_sha256(stable_result)
    return stable_result


def _raw_status_message(
    *, device_id: str = "device-1", session_id: str = "s1", sequence: int = 1,
    time_value: float = 1.0, domain: ClockDomain = ClockDomain.SIMULATION,
) -> dict[str, Any]:
    stamp = {"value": time_value, "domain": domain.value, "precision_ms": 1.0}
    return {
        "schema_version": SCHEMA_VERSION,
        "device_id": device_id,
        "session_id": session_id,
        "sequence_number": sequence,
        "timestamp": stamp,
        "received_at": stamp,
        "source": "SYNTHETIC_TEST_ONLY",
        "measurement_type": "device_status",
        "value": {"connected": True},
        "unit": "1",
        "quality": MessageQuality.GOOD.value,
        "uncertainty": None,
        "validity": True,
        "provenance": {"classification": "SYNTHETIC_TEST_ONLY"},
    }


def _fault_record(
    seed: int,
    test_case_index: int,
    kind: FaultKind,
    expected: str,
    actual: str,
    detail: str,
    *,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "seed": seed,
        "test_case_index": test_case_index,
        "trigger_time": {
            "value": None,
            "domain": "synchronous_test_case_order",
            "comparable_to_simulation_time": False,
        },
        "fault_type": kind.value,
        "injection_parameters": parameters or {"deterministic": True},
        "expected_result": expected,
        "actual_result": actual,
        "passed": expected == actual,
        "source": "phase17_test_environment_only",
        "detail": detail,
    }


def reconcile_state_after_reconnect(
    expected: Mapping[str, Any], observed: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare post-reconnect state; equality is required before auto-control."""
    keys = sorted(set(expected) | set(observed))
    differences = {
        key: {"expected": expected.get(key), "observed": observed.get(key)}
        for key in keys
        if expected.get(key) != observed.get(key)
    }
    return {"reconciled": not differences, "differences": differences}


def run_fault_injection_suite(*, seed: int = 1717) -> list[dict[str, Any]]:
    """Execute deterministic fault cases against validation, gate, and executor."""
    records: list[dict[str, Any]] = []
    now_sim = ClockStamp(1.0, ClockDomain.SIMULATION, 1.0)
    validator = MessageContractValidator({"device-1"})
    good = _raw_status_message()

    missing = validator.validate({}, now=now_sim)
    actual = "REJECTED_MISSING_TELEMETRY" if not missing.accepted and missing.message is None else "ACCEPTED"
    records.append(_fault_record(seed, 0, FaultKind.TELEMETRY_GAP, "REJECTED_MISSING_TELEMETRY", actual, ";".join(missing.reasons)))

    duplicate_validator = MessageContractValidator({"device-1"})
    duplicate_validator.validate(good, now=now_sim)
    duplicate = duplicate_validator.validate(good, now=now_sim)
    actual = "REJECTED_DUPLICATE" if "duplicate_message" in duplicate.reasons else "ACCEPTED"
    records.append(_fault_record(seed, 1, FaultKind.MESSAGE_DUPLICATE, "REJECTED_DUPLICATE", actual, ";".join(duplicate.reasons)))

    order_validator = MessageContractValidator({"device-1"})
    order_validator.validate(_raw_status_message(sequence=4), now=now_sim)
    out_of_order = order_validator.validate(_raw_status_message(sequence=3), now=now_sim)
    actual = "REJECTED_OUT_OF_ORDER" if "sequence_out_of_order" in out_of_order.reasons else "ACCEPTED"
    records.append(_fault_record(seed, 2, FaultKind.MESSAGE_REORDER, "REJECTED_OUT_OF_ORDER", actual, ";".join(out_of_order.reasons)))

    delayed = MessageContractValidator({"device-1"}).validate(
        _raw_status_message(time_value=1.0), now=ClockStamp(4.0, ClockDomain.SIMULATION, 1.0), max_age_seconds=1.0
    )
    actual = "REJECTED_STALE" if "telemetry_stale" in delayed.reasons else "ACCEPTED"
    records.append(_fault_record(seed, 3, FaultKind.MESSAGE_DELAY, "REJECTED_STALE", actual, ";".join(delayed.reasons), parameters={"delay_seconds": 3.0, "max_age_seconds": 1.0}))

    cross_clock = MessageContractValidator({"device-1"}).validate(
        _raw_status_message(domain=ClockDomain.REPLAY),
        now=ClockStamp(1.0, ClockDomain.RECEIVER_WALL, 1.0),
    )
    actual = "AGE_UNDETERMINED" if not cross_clock.age_comparable and cross_clock.age_seconds is None else "COMPARABLE"
    records.append(_fault_record(seed, 4, FaultKind.CLOCK_OFFSET, "AGE_UNDETERMINED", actual, "No verified cross-clock mapping is supplied."))

    unknown = MessageContractValidator({"device-1"}).validate(
        _raw_status_message(device_id="unknown-device"), now=now_sim
    )
    actual = "REJECTED_UNKNOWN_DEVICE" if "unknown_device" in unknown.reasons else "ACCEPTED"
    records.append(_fault_record(seed, 5, FaultKind.UNKNOWN_DEVICE, "REJECTED_UNKNOWN_DEVICE", actual, ";".join(unknown.reasons)))

    incompatible_schema = _raw_status_message()
    incompatible_schema["schema_version"] = "9.9"
    version_check = MessageContractValidator({"device-1"}).validate(incompatible_schema, now=now_sim)
    actual = "REJECTED_SCHEMA" if "schema_version_unsupported" in version_check.reasons else "ACCEPTED"
    records.append(_fault_record(seed, 6, FaultKind.UNSUPPORTED_SCHEMA, "REJECTED_SCHEMA", actual, ";".join(version_check.reasons)))

    bad_unit = _raw_status_message()
    bad_unit.update({"measurement_type": "latency_ms", "value": 20.0, "unit": "dBm", "uncertainty": {"standard_uncertainty": 1.0, "unit": "dBm"}})
    invalid_unit = MessageContractValidator({"device-1"}).validate(bad_unit, now=now_sim)
    actual = "REJECTED_UNIT_MISMATCH" if "unit_mismatch" in invalid_unit.reasons else "ACCEPTED"
    records.append(_fault_record(seed, 7, FaultKind.UNIT_MISMATCH, "REJECTED_UNIT_MISMATCH", actual, ";".join(invalid_unit.reasons)))

    out_of_range = _raw_status_message()
    out_of_range.update({"measurement_type": "battery_wh", "value": -4.0, "unit": "Wh", "uncertainty": {"standard_uncertainty": 0.5, "unit": "Wh"}})
    invalid_range = MessageContractValidator({"device-1"}).validate(out_of_range, now=now_sim)
    actual = "REJECTED_OUT_OF_RANGE" if "measurement_value_out_of_range" in invalid_range.reasons else "ACCEPTED"
    records.append(_fault_record(seed, 8, FaultKind.OUT_OF_RANGE_MEASUREMENT, "REJECTED_OUT_OF_RANGE", actual, ";".join(invalid_range.reasons), parameters={"battery_wh": -4.0, "allowed_range_wh": [0.0, 1.0e9]}))

    missing_uncertainty = _raw_status_message()
    missing_uncertainty.update({"measurement_type": "received_power_dbm", "value": -75.0, "unit": "dBm", "uncertainty": None})
    missing_u = MessageContractValidator({"device-1"}).validate(missing_uncertainty, now=now_sim)
    actual = "REJECTED_UNTRUSTED_MISSING_UNCERTAINTY" if "measurement_uncertainty_missing" in missing_u.reasons and not missing_u.trusted_for_control else "ACCEPTED"
    records.append(_fault_record(seed, 9, FaultKind.OUT_OF_RANGE_MEASUREMENT, "REJECTED_UNTRUSTED_MISSING_UNCERTAINTY", actual, ";".join(missing_u.reasons)))

    executor = SoftwareTestExecutor()
    executor.connect()
    gate = SafetyGate()
    command = ControlCommand("fault-low-battery", executor.device_id, "set_relay_active", {"active": True}, "automatic", now_sim, TestMode.SOFTWARE_CLOSED_LOOP, "phase17-faults", 10)
    caps = executor.get_capabilities().supported_commands

    disconnected = gate.evaluate(command, SafetyContext(TestMode.SOFTWARE_CLOSED_LOOP, AdapterStatus.UNAVAILABLE, True, caps, True, True))
    actual = "BLOCKED_DISCONNECTED" if not disconnected.allowed else "ALLOWED"
    records.append(_fault_record(seed, 10, FaultKind.DEVICE_DISCONNECT, "BLOCKED_DISCONNECTED", actual, disconnected.reason))

    low_battery = gate.evaluate(command, SafetyContext(TestMode.SOFTWARE_CLOSED_LOOP, AdapterStatus.SIMULATED, True, caps, True, True, battery_wh=35.0, reserve_wh=30.0, requested_energy_wh=8.0))
    actual = "BLOCKED_RETURN_RESERVE" if not low_battery.allowed and low_battery.reason == "command_would_breach_return_reserve" else "ALLOWED"
    records.append(_fault_record(seed, 11, FaultKind.BATTERY_STATE_JUMP, "BLOCKED_RETURN_RESERVE", actual, low_battery.reason, parameters={"battery_wh": 35.0, "reserve_wh": 30.0, "requested_energy_wh": 8.0}))

    timeout = executor.submit_command(command, fault_injection=FaultKind.COMMAND_TIMEOUT)
    actual = "TIMEOUT_NOT_SUCCESS" if timeout.execution_status == "TIMEOUT_UNKNOWN" and not timeout.completed else "SUCCESS"
    records.append(_fault_record(seed, 12, FaultKind.COMMAND_TIMEOUT, "TIMEOUT_NOT_SUCCESS", actual, timeout.execution_status))

    reject_command = ControlCommand("fault-reject", executor.device_id, "set_relay_active", {"active": True}, "automatic", now_sim, TestMode.SOFTWARE_CLOSED_LOOP, "phase17-faults", 13)
    rejected = executor.submit_command(reject_command, fault_injection=FaultKind.DEVICE_REJECTS_COMMAND)
    actual = "REJECTED_NOT_SUCCESS" if rejected.execution_status == "REJECTED_BY_TEST_EXECUTOR" and not rejected.completed else "SUCCESS"
    records.append(_fault_record(seed, 13, FaultKind.DEVICE_REJECTS_COMMAND, "REJECTED_NOT_SUCCESS", actual, rejected.execution_status))

    mismatch_command = ControlCommand("fault-mismatch", executor.device_id, "set_relay_active", {"active": True}, "automatic", now_sim, TestMode.SOFTWARE_CLOSED_LOOP, "phase17-faults", 14)
    mismatch = executor.submit_command(mismatch_command, fault_injection=FaultKind.COMMAND_FEEDBACK_MISMATCH)
    actual = "LOCK_AFTER_FEEDBACK_MISMATCH" if mismatch.feedback_matches is False and not mismatch.completed else "NO_LOCK"
    records.append(_fault_record(seed, 14, FaultKind.COMMAND_FEEDBACK_MISMATCH, "LOCK_AFTER_FEEDBACK_MISMATCH", actual, mismatch.execution_status))

    emergency_command = ControlCommand("fault-estop", executor.device_id, "emergency_stop", {}, "emergency_stop", now_sim, TestMode.SOFTWARE_CLOSED_LOOP, "phase17-faults", 15)
    estop = gate.evaluate(emergency_command, SafetyContext(TestMode.SOFTWARE_CLOSED_LOOP, AdapterStatus.SIMULATED, True, caps, None, False))
    actual = "EMERGENCY_STOP_ALLOWED" if estop.allowed else "BLOCKED"
    records.append(_fault_record(seed, 15, FaultKind.TELEMETRY_GAP, "EMERGENCY_STOP_ALLOWED", actual, estop.reason))

    manual_stop = gate.evaluate(command, SafetyContext(TestMode.SOFTWARE_CLOSED_LOOP, AdapterStatus.SIMULATED, True, caps, True, True, manual_stop_latched=True))
    actual = "AUTOMATIC_RESUME_BLOCKED" if not manual_stop.allowed and manual_stop.priority == "MANUAL_USER_CONTROL" else "ALLOWED"
    records.append(_fault_record(seed, 16, FaultKind.MANUAL_STOP_LATCH, "AUTOMATIC_RESUME_BLOCKED", actual, manual_stop.reason))

    expected_device_state = executor.state
    disconnected_state = executor.disconnect()
    try:
        executor.read_status()
        disconnected_read_blocked = False
    except AdapterError:
        disconnected_read_blocked = True
    reconnect_state = executor.connect()
    observed_device_state = executor.read_status()["state"]
    reconciled = reconcile_state_after_reconnect(expected_device_state, observed_device_state)
    reconnect_gate = gate.evaluate(command, SafetyContext(TestMode.SOFTWARE_CLOSED_LOOP, AdapterStatus.SIMULATED, True, caps, True, True, reconnect_needs_reconciliation=True))
    post_reconcile = gate.evaluate(command, SafetyContext(TestMode.SOFTWARE_CLOSED_LOOP, AdapterStatus.SIMULATED, True, caps, True, True, reconnect_needs_reconciliation=not reconciled["reconciled"]))
    actual = "BLOCK_THEN_ALLOW_AFTER_MATCH" if (
        disconnected_read_blocked
        and disconnected_state["connected"] is False
        and reconnect_state["connected"] is True
        and not reconnect_gate.allowed
        and reconciled["reconciled"]
        and post_reconcile.allowed
    ) else "INCORRECT_RECOVERY"
    reconnect_record = _fault_record(seed, 17, FaultKind.RECONNECT_RECONCILIATION, "BLOCK_THEN_ALLOW_AFTER_MATCH", actual, reconnect_gate.reason)
    reconnect_record["reconnection_trace"] = {
        "disconnect": disconnected_state,
        "read_while_disconnected_blocked": disconnected_read_blocked,
        "reconnect": reconnect_state,
        "state_reconciliation": reconciled,
        "automatic_action_before_reconciliation_allowed": reconnect_gate.allowed,
        "automatic_action_after_reconciliation_allowed": post_reconcile.allowed,
    }
    records.append(reconnect_record)

    hardware_mode = gate.evaluate(command, SafetyContext(TestMode.HARDWARE_IN_LOOP, AdapterStatus.SIMULATED, True, caps, True, True))
    actual = "REAL_HARDWARE_MODE_BLOCKED" if not hardware_mode.allowed and hardware_mode.reason == "real_hardware_output_disabled_in_phase17" else "ALLOWED"
    records.append(_fault_record(seed, 18, FaultKind.SAFETY_GATE_BYPASS, "REAL_HARDWARE_MODE_BLOCKED", actual, hardware_mode.reason))

    no_backhaul_run = run_software_closed_loop(seed=seed, backhaul_available=False)
    no_path_summary = no_backhaul_run["summary"]
    actual = "NO_END_TO_END_PATH_REPORTED" if no_path_summary["first_rescue_recovery_step"] is None and no_path_summary["commands_requested"] == 0 else "CLAIMED_RECOVERY"
    records.append(_fault_record(seed, 19, FaultKind.BACKHAUL_LOSS, "NO_END_TO_END_PATH_REPORTED", actual, ";".join(item["decision"]["reason"] for item in no_backhaul_run["timeline"])))

    recovery_run = run_software_closed_loop(seed=seed, backhaul_schedule={1: False, 2: True})
    outage_tick = recovery_run["timeline"][1]
    restored_tick = recovery_run["timeline"][2]
    recovery_ok = (
        outage_tick["event"] is not None
        and outage_tick["observed_state"]["rescue_connected"] == 0
        and restored_tick["event"] is not None
        and restored_tick["observed_state"]["rescue_connected"] == restored_tick["observed_state"]["rescue_total"]
        and recovery_run["summary"]["first_rescue_recovery_step"] == 2
    )
    recovery_record = _fault_record(
        seed,
        20,
        FaultKind.BACKHAUL_RECOVERY,
        "SERVICE_RESTORED_AFTER_BACKHAUL_RECOVERY",
        "SERVICE_RESTORED_AFTER_BACKHAUL_RECOVERY" if recovery_ok else "UNEXPECTED_STATE",
        ";".join(item["decision"]["reason"] for item in recovery_run["timeline"]),
        parameters={"backhaul_schedule": {"1": False, "2": True}},
    )
    recovery_record["recovery_step"] = recovery_run["summary"]["first_rescue_recovery_step"]
    recovery_record["observed_simulation_events"] = [
        {
            "simulation_time_s": outage_tick["simulation_time_s"],
            "event_type": outage_tick["event"]["event_type"],
            "backhaul_available": outage_tick["observed_state"]["backhaul_available"],
        },
        {
            "simulation_time_s": restored_tick["simulation_time_s"],
            "event_type": restored_tick["event"]["event_type"],
            "backhaul_available": restored_tick["observed_state"]["backhaul_available"],
        },
    ]
    recovery_record["command_audit"] = recovery_run["command_audit"]
    records.append(recovery_record)
    return records


def build_replay_validation(artifact_path: str | Path, *, scenario_id: str, strategy_id: str) -> dict[str, Any]:
    """Exercise pause, resume, single-step, and snapshot mapping on saved frames."""
    adapter = OfflineReplayAdapter(artifact_path, scenario_id, strategy_id)
    connection = adapter.connect()
    health = adapter.health_check()
    capabilities = adapter.get_capabilities()
    adapter.pause()
    first = adapter.read_status()
    paused_advance = adapter.advance()
    step_one = adapter.step()
    step_time = None if step_one is None else step_one["simulation_time_s"]
    adapter.resume()
    walked = 2
    while adapter.advance() is not None:
        walked += 1
    adapter.close()
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": TestMode.OFFLINE_REPLAY.value,
        "source_type": "saved_abstract_simulation_not_hardware_measurement",
        "source_path": adapter.path.relative_to(adapter.path.parents[1]).as_posix() if adapter.path.is_relative_to(adapter.path.parents[1]) else adapter.path.name,
        "source_sha256": adapter.source_sha256,
        "scenario_id": scenario_id,
        "strategy_id": strategy_id,
        "frame_count": len(adapter.frames),
        "mapped_frame_count": len(adapter.frames),
        "mapping_sample_first": first,
        "connection": connection,
        "health_check": health,
        "capabilities": capabilities.to_dict(),
        "paused_advance_kept_same_frame": paused_advance["simulation_time_s"] == first["simulation_time_s"],
        "single_step_next_time_s": step_time,
        "walked_discrete_frames": walked,
        "interpolated_frames": 0,
        "commands_allowed": False,
        "live_device": False,
        "clock_domain": ClockDomain.REPLAY.value,
        "cross_domain_latency": "UNDETERMINED_WITHOUT_CLOCK_SYNC",
    }


def adapter_status_catalog() -> dict[str, Any]:
    """Return implemented capabilities and explicit device availability."""
    return {
        "schema_version": SCHEMA_VERSION,
        "hardware_output_enabled": False,
        "adapters": [
            {
                "adapter_id": "phase16_offline_measurement_file_import",
                "device_type": "measurement_file_import",
                "status": AdapterStatus.IMPLEMENTED_AND_TESTED.value,
                "implementation": "CSV/JSON read-only import and audit",
                "live_device": False,
            },
            {
                "adapter_id": "phase17_saved_simulation_replay",
                "device_type": DeviceType.FILE_REPLAY.value,
                "status": AdapterStatus.REPLAY_ONLY.value,
                "implementation": "offline discrete frame cursor with pause/resume/step",
                "live_device": False,
            },
            {
                "adapter_id": "phase17_software_test_executor",
                "device_type": DeviceType.SOFTWARE_EXECUTOR.value,
                "status": AdapterStatus.SIMULATED.value,
                "implementation": "isolated in-memory executor; test data only",
                "live_device": False,
            },
            {
                "adapter_id": "radio_measurement_driver",
                "device_type": DeviceType.RADIO_MEASUREMENT.value,
                "status": AdapterStatus.UNAVAILABLE.value,
                "implementation": "no verified hardware driver",
                "live_device": False,
            },
            {
                "adapter_id": "wireless_link_state_driver_contract",
                "device_type": DeviceType.LINK_STATE.value,
                "status": AdapterStatus.INTERFACE_ONLY.value,
                "implementation": "versioned software contract only",
                "live_device": False,
            },
            {
                "adapter_id": "uav_telemetry_driver_contract",
                "device_type": DeviceType.UAV_TELEMETRY.value,
                "status": AdapterStatus.INTERFACE_ONLY.value,
                "implementation": "versioned software contract only",
                "live_device": False,
            },
            {
                "adapter_id": "uav_flight_control_driver",
                "device_type": DeviceType.UAV_FLIGHT_CONTROL.value,
                "status": AdapterStatus.UNAVAILABLE.value,
                "implementation": "not implemented; physical commands disabled",
                "live_device": False,
            },
            {
                "adapter_id": "base_station_status_driver_contract",
                "device_type": DeviceType.BASE_STATION_STATUS.value,
                "status": AdapterStatus.INTERFACE_ONLY.value,
                "implementation": "versioned software contract only",
                "live_device": False,
            },
        ],
        "mode_availability": {
            TestMode.OFFLINE_REPLAY.value: "AVAILABLE_READ_ONLY",
            TestMode.SOFTWARE_CLOSED_LOOP.value: "AVAILABLE_SYNTHETIC_TEST_ONLY",
            TestMode.HARDWARE_IN_LOOP.value: "UNAVAILABLE_NO_VERIFIED_HARDWARE_OR_DRIVER",
            TestMode.LIVE_DEVICE.value: "UNAVAILABLE_AND_BLOCKED_BY_SAFETY_GATE",
        },
    }


def environment_inventory(*, root: str | Path, equipment_scan: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    phase16 = json.loads((root / "results" / "phase16_environment_inventory.json").read_text(encoding="utf-8"))
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "phase17_hil_environment_inventory",
        "project_root": str(root),
        "equipment_scan": equipment_scan,
        "phase16_equipment_scan": phase16.get("equipment_scan"),
        "device_adapter_status": adapter_status_catalog(),
        "project_device_measurements": phase16.get("project_device_measurements"),
        "manuals_and_calibration_certificates": phase16.get("project_device_manuals_and_calibration_certificates"),
        "authorization_evidence": phase16.get("spectrum_and_flight_authorization"),
        "verified_real_device_count": len(equipment_scan.get("matched_devices", [])) if equipment_scan.get("status") == "COMPLETED" else None,
        "verified_serial_port_count": equipment_scan.get("serial_port_count"),
        "software_executor_is_hardware": False,
        "limitations": [
            "Name-filtered Windows PnP enumeration cannot prove no unrecognized or off-machine equipment exists.",
            "No project wireless measurement device, UAV telemetry unit, flight controller, or base-station status driver has been verified.",
            "No software test executor or saved replay is counted as a physical device adapter.",
        ],
    }


def canonical_sha256(value: Any) -> str:
    """Public stable serializer used by audit scripts and determinism tests."""
    return _canonical_sha256(value)
