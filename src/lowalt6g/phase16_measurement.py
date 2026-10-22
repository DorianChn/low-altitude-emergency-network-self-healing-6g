"""Phase 16 measurement readiness, uncertainty propagation, and acceptance gates.

This module deliberately separates software checks, public measurements, and
target-device calibration. Unknown uncertainty inputs remain unknown; they are
never silently replaced with zero or a convenient default.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class AdapterStatus(StrEnum):
    IMPLEMENTED_AND_TESTED = "IMPLEMENTED_AND_TESTED"
    INTERFACE_ONLY = "INTERFACE_ONLY"
    UNAVAILABLE = "UNAVAILABLE"


class CalibrationStatus(StrEnum):
    NOT_CALIBRATED = "NOT_CALIBRATED"
    PIPELINE_VALIDATED = "PIPELINE_VALIDATED"
    CALIBRATED_PENDING_HOLDOUT = "CALIBRATED_PENDING_HOLDOUT"
    HOLDOUT_VALIDATED = "HOLDOUT_VALIDATED"
    NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING = "NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FAILED_VALIDATION = "FAILED_VALIDATION"


class MeasurementSourceType(StrEnum):
    TARGET_DEVICE_MEASUREMENT = "target_device_measurement"
    PUBLIC_MEASUREMENT = "public_measurement"
    LITERATURE_REFERENCE = "literature_reference"
    SYNTHETIC_TEST_ONLY = "SYNTHETIC_TEST_ONLY"


class MeasurementAdapter:
    """Future device adapter contract; this base class has no acquisition logic."""

    status = AdapterStatus.INTERFACE_ONLY

    def identify(self) -> dict[str, Any]:
        raise NotImplementedError("device identification is not implemented")

    def acquire(self) -> list[dict[str, Any]]:
        raise NotImplementedError("hardware acquisition is not implemented")


class OfflineFileImportAdapter(MeasurementAdapter):
    """Implemented file reader for saved CSV/JSON measurements; not a live device."""

    status = AdapterStatus.IMPLEMENTED_AND_TESTED

    def identify(self) -> dict[str, Any]:
        return {"adapter_id": "offline_file_import", "status": self.status.value, "live_device": False}

    def acquire(self) -> list[dict[str, Any]]:
        raise RuntimeError("offline file import requires an explicit source path")


class RadioInstrumentAdapter(MeasurementAdapter):
    """Explicit placeholder documenting that no radio instrument driver exists."""

    status = AdapterStatus.UNAVAILABLE


_UNIT_FACTORS: dict[str, tuple[str, float]] = {
    "Hz": ("frequency", 1.0), "kHz": ("frequency", 1e3),
    "MHz": ("frequency", 1e6), "GHz": ("frequency", 1e9),
    "m": ("length", 1.0), "cm": ("length", 1e-2), "mm": ("length", 1e-3),
    "km": ("length", 1e3), "s": ("time", 1.0), "ms": ("time", 1e-3),
    "us": ("time", 1e-6), "ns": ("time", 1e-9),
    # Logarithmic absolute levels and gain/difference quantities are distinct:
    # unit conversion must never silently turn dBm into dB or dBi.
    "dB": ("log_delta", 1.0), "dBm": ("power_level", 1.0), "dBi": ("antenna_gain", 1.0),
    "deg": ("angle", 1.0), "rad": ("angle", 180.0 / math.pi),
}
_STANDARD_UNCERTAINTY_UNITS = set(_UNIT_FACTORS) - {"dBm", "dBi"}


def convert_unit(value: float, source_unit: str, target_unit: str) -> float:
    """Convert supported linear units; dB/dBm/dBi conversions are for deltas only."""
    try:
        source_dimension, source_factor = _UNIT_FACTORS[source_unit]
        target_dimension, target_factor = _UNIT_FACTORS[target_unit]
    except KeyError as error:
        raise ValueError(f"unsupported unit: {error.args[0]}") from error
    if source_dimension != target_dimension:
        raise ValueError(f"incompatible units: {source_unit} and {target_unit}")
    if not math.isfinite(float(value)):
        raise ValueError("unit conversion value must be finite")
    return float(value) * source_factor / target_factor


@dataclass(frozen=True)
class UncertaintyComponent:
    name: str
    standard_uncertainty: float | None
    unit: str
    sensitivity: float
    category: str
    distribution: str = "normal"
    evidence: str | None = None

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("uncertainty component name is required")
        if self.standard_uncertainty is not None:
            if not math.isfinite(self.standard_uncertainty) or self.standard_uncertainty < 0:
                raise ValueError(f"{self.name}: standard uncertainty must be finite and non-negative")
        if not math.isfinite(self.sensitivity):
            raise ValueError(f"{self.name}: sensitivity must be finite")
        if self.unit not in _STANDARD_UNCERTAINTY_UNITS:
            raise ValueError(f"{self.name}: unsupported uncertainty unit {self.unit}")
        if self.distribution not in {"normal", "rectangular", "triangular"}:
            raise ValueError(f"{self.name}: unsupported distribution {self.distribution}")


def _correlation_matrix(
    names: Sequence[str], correlations: Mapping[tuple[str, str], float] | None,
) -> list[list[float]]:
    n = len(names)
    matrix = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    indices = {name: index for index, name in enumerate(names)}
    for pair, raw_value in (correlations or {}).items():
        if len(pair) != 2 or pair[0] not in indices or pair[1] not in indices:
            raise ValueError(f"correlation references an unknown component: {pair}")
        rho = float(raw_value)
        if not math.isfinite(rho) or rho < -1.0 or rho > 1.0:
            raise ValueError("correlation coefficients must be within [-1, 1]")
        left, right = indices[pair[0]], indices[pair[1]]
        if left == right:
            if abs(rho - 1.0) > 1e-12:
                raise ValueError("a component's self-correlation must equal 1")
            continue
        matrix[left][right] = rho
        matrix[right][left] = rho
    if not _is_positive_semidefinite(matrix):
        raise ValueError("correlation matrix must be positive semidefinite")
    return matrix


def _is_positive_semidefinite(matrix: list[list[float]], tolerance: float = 1e-10) -> bool:
    """Jacobi eigenvalue check for the small symmetric correlation matrices used here."""
    n = len(matrix)
    if n < 2:
        return True
    a = [row[:] for row in matrix]
    for _ in range(max(1, n * n * 50)):
        p, q, largest = 0, 1, 0.0
        for i in range(n):
            for j in range(i + 1, n):
                if abs(a[i][j]) > largest:
                    p, q, largest = i, j, abs(a[i][j])
        if largest <= tolerance:
            break
        angle = 0.5 * math.atan2(2.0 * a[p][q], a[q][q] - a[p][p])
        cosine, sine = math.cos(angle), math.sin(angle)
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        a[p][p] = cosine * cosine * app - 2 * sine * cosine * apq + sine * sine * aqq
        a[q][q] = sine * sine * app + 2 * sine * cosine * apq + cosine * cosine * aqq
        a[p][q] = a[q][p] = 0.0
        for k in range(n):
            if k in (p, q):
                continue
            akp, akq = a[k][p], a[k][q]
            a[k][p] = a[p][k] = cosine * akp - sine * akq
            a[k][q] = a[q][k] = sine * akp + cosine * akq
    return min(a[i][i] for i in range(n)) >= -tolerance


def propagate_standard_uncertainty(
    components: Sequence[UncertaintyComponent],
    *,
    correlations: Mapping[tuple[str, str], float] | None = None,
    coverage_factor: float | None = None,
) -> dict[str, Any]:
    """Propagate standard uncertainty, refusing to treat missing inputs as zero."""
    if not components:
        raise ValueError("at least one uncertainty component is required")
    for component in components:
        component.validate()
    names = [item.name for item in components]
    if len(set(names)) != len(names):
        raise ValueError("uncertainty component names must be unique")
    if coverage_factor is not None and (not math.isfinite(coverage_factor) or coverage_factor <= 0):
        raise ValueError("coverage factor must be a finite positive value")
    unknown = [item.name for item in components if item.standard_uncertainty is None]
    known = [item for item in components if item.standard_uncertainty is not None]
    known_only = math.sqrt(sum((item.sensitivity * float(item.standard_uncertainty)) ** 2 for item in known))
    result: dict[str, Any] = {
        "output_unit": "dB",
        "component_count": len(components),
        "known_component_count": len(known),
        "unknown_components": unknown,
        "known_only_rss_subtotal_db": known_only,
        "complete": not unknown,
        "combined_standard_uncertainty_db": None,
        "expanded_uncertainty_db": None,
        "coverage_factor": coverage_factor,
        "coverage_probability": None,
        "interpretation": "Expanded uncertainty is U = k * u_c; a coverage probability is not inferred from k alone.",
    }
    if unknown:
        result["assessability"] = "NOT_ASSESSABLE_MISSING_STANDARD_UNCERTAINTIES"
        return result
    # Sensitivity is expressed as output dB per component unit (for example,
    # dB/Hz for frequency or dB/m for distance), so unlike units are valid.
    matrix = _correlation_matrix(names, correlations)
    weighted = [item.sensitivity * float(item.standard_uncertainty) for item in components]
    variance = sum(weighted[i] * matrix[i][j] * weighted[j] for i in range(len(components)) for j in range(len(components)))
    if variance < -1e-10:
        raise ValueError("propagated variance is negative; check correlation assumptions")
    standard = math.sqrt(max(0.0, variance))
    result["combined_standard_uncertainty_db"] = standard
    result["expanded_uncertainty_db"] = None if coverage_factor is None else coverage_factor * standard
    result["assessability"] = "ASSESSABLE_WITH_RECORDED_INPUTS"
    return result


def monte_carlo_propagation(
    components: Sequence[UncertaintyComponent], *, seed: int, draws: int = 20_000,
) -> dict[str, Any]:
    """Reproducible independent-input propagation; reports distribution quantiles, not a CI."""
    if draws < 100:
        raise ValueError("draws must be at least 100")
    if any(item.standard_uncertainty is None for item in components):
        raise ValueError("Monte Carlo propagation requires every standard uncertainty")
    # Each sensitivity converts its sampled input perturbation to output dB.
    for item in components:
        item.validate()
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(draws):
        total = 0.0
        for item in components:
            standard = float(item.standard_uncertainty)
            if item.distribution == "normal":
                error = rng.gauss(0.0, standard)
            elif item.distribution == "rectangular":
                half_width = math.sqrt(3.0) * standard
                error = rng.uniform(-half_width, half_width)
            else:
                half_width = math.sqrt(6.0) * standard
                error = rng.triangular(-half_width, half_width, 0.0)
            total += item.sensitivity * error
        values.append(total)
    ordered = sorted(values)
    mean = sum(values) / draws
    variance = sum((value - mean) ** 2 for value in values) / (draws - 1)
    return {
        "seed": seed,
        "draws": draws,
        "mean_db": mean,
        "sample_sd_db": math.sqrt(variance),
        "distribution_quantiles_2p5_97p5_db": [_quantile(ordered, 0.025), _quantile(ordered, 0.975)],
        "interval_type": "propagated_distribution_quantiles_not_a_confidence_interval",
        "independent_inputs_assumed": True,
    }


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    index = (len(sorted_values) - 1) * probability
    low = int(math.floor(index))
    high = int(math.ceil(index))
    if low == high:
        return sorted_values[low]
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (index - low)


def calculate_received_power_dbm(
    *, tx_power_dbm: float, tx_antenna_gain_dbi: float, rx_antenna_gain_dbi: float,
    path_loss_db: float, other_losses_db: float,
) -> float:
    """Pr = Pt + Gt + Gr - PL - Lother using dBm/dBi/dB consistently."""
    values = (tx_power_dbm, tx_antenna_gain_dbi, rx_antenna_gain_dbi, path_loss_db, other_losses_db)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("link-budget values must be finite")
    if path_loss_db < 0 or other_losses_db < 0:
        raise ValueError("path loss and other losses must be non-negative")
    return tx_power_dbm + tx_antenna_gain_dbi + rx_antenna_gain_dbi - path_loss_db - other_losses_db


UNCERTAINTY_SOURCE_SPECS: tuple[dict[str, str], ...] = (
    {"id": "tx_power", "category": "instrument", "quantity": "transmit power", "unit": "dB", "effect": "received-power budget"},
    {"id": "rx_power", "category": "instrument", "quantity": "received power", "unit": "dB", "effect": "path-loss/received-power reference"},
    {"id": "tx_antenna_gain", "category": "systematic", "quantity": "transmit antenna gain", "unit": "dB", "effect": "received-power budget"},
    {"id": "rx_antenna_gain", "category": "systematic", "quantity": "receive antenna gain", "unit": "dB", "effect": "received-power budget"},
    {"id": "feedline_loss", "category": "systematic", "quantity": "cable/connector/feedline loss", "unit": "dB", "effect": "received-power budget"},
    {"id": "frequency", "category": "configuration", "quantity": "carrier frequency", "unit": "Hz", "effect": "frequency-dependent path loss"},
    {"id": "bandwidth", "category": "configuration", "quantity": "measurement bandwidth", "unit": "Hz", "effect": "measurement definition and noise floor"},
    {"id": "distance", "category": "geometry", "quantity": "Tx-Rx distance", "unit": "m", "effect": "path-loss predictor"},
    {"id": "antenna_height", "category": "geometry", "quantity": "antenna height", "unit": "m", "effect": "propagation geometry"},
    {"id": "antenna_attitude", "category": "geometry", "quantity": "antenna attitude/orientation", "unit": "deg", "effect": "antenna pattern alignment; needs pattern/model"},
    {"id": "temperature_gain_drift", "category": "systematic", "quantity": "temperature and gain drift", "unit": "dB", "effect": "calibration stability"},
    {"id": "repeatability", "category": "repeatability", "quantity": "repeat measurement variation", "unit": "dB", "effect": "within-session repeatability"},
    {"id": "between_batch", "category": "repeatability", "quantity": "between-batch variation", "unit": "dB", "effect": "cross-session reproducibility"},
    {"id": "environmental_variation", "category": "natural_variability", "quantity": "shadowing, obstruction and multipath variation", "unit": "dB", "effect": "population variability; not instrument error"},
    {"id": "model_residual", "category": "model_residual", "quantity": "model residual", "unit": "dB", "effect": "predictive residual; distinct from measurement uncertainty"},
    {"id": "parameter_estimation", "category": "parameter_estimation", "quantity": "fitted parameter uncertainty", "unit": "dB", "effect": "estimated-model parameter uncertainty"},
)


def initial_uncertainty_budget() -> dict[str, Any]:
    """Build an evidence inventory with null numerical values, never invented precision."""
    sources = [
        {**spec, "standard_uncertainty": None, "evidence": None, "status": "UNKNOWN_NO_PROJECT_DEVICE_EVIDENCE"}
        for spec in UNCERTAINTY_SOURCE_SPECS
    ]
    return {
        "schema_version": "1.0",
        "phase": "phase16_measurement_uncertainty_budget",
        "status": "NOT_ASSESSABLE_NO_TARGET_DEVICE_UNCERTAINTIES",
        "output_quantity": "received power / path-loss difference",
        "output_unit": "dB",
        "sources": sources,
        "coverage": {
            "instrument_measurement_uncertainty": "not quantified",
            "systematic_error": "sources identified; magnitudes and correlations unknown",
            "natural_sample_variability": "must be estimated from independent repeat routes/batches",
            "model_residual": "Phase 15 public-domain residual exists but is not target-device measurement uncertainty",
            "parameter_estimation": "Phase 15 public candidate interval is public-domain only, not target-device calibration uncertainty",
        },
        "combined_standard_uncertainty_db": None,
        "expanded_uncertainty_db": None,
        "coverage_factor": None,
        "coverage_probability": None,
        "reason": "No project-device measurement values, calibration certificates, or per-sample uncertainty metadata are present.",
    }


def acceptance_criteria_sha256(criteria: Mapping[str, Any]) -> str:
    """Hash the frozen rule content, excluding the digest and observed result."""
    content = {
        key: value for key, value in criteria.items()
        if key not in {"criteria_sha256", "holdout_error_db", "holdout_result_reference"}
    }
    return evidence_sha256(content)


SESSION_REQUIRED_FIELDS = (
    "experiment_id", "measurement_batch_id", "operator_id", "acquisition_mode", "frequency",
    "bandwidth", "transmitter", "receiver", "antennas", "measurement_points", "environment",
    "calibration", "data_storage_path", "authorization", "privacy",
)
ACQUISITION_MODES = {"authorized_emission", "receive_only", "offline_import", "lab_calibrated"}


def validate_experiment_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a field-session plan and report incomplete evidence explicitly."""
    missing = [field for field in SESSION_REQUIRED_FIELDS if _is_missing(config.get(field))]
    required_nested_paths = (
        "frequency.value", "frequency.unit", "bandwidth.value", "bandwidth.unit",
        "transmitter.equipment_id", "transmitter.model", "transmitter.tx_power_dbm",
        "receiver.equipment_id", "receiver.model", "receiver.measurement_metric",
        "antennas.transmit_model", "antennas.receive_model", "antennas.tx_gain_dbi",
        "antennas.rx_gain_dbi", "antennas.feedline_loss_db", "route_or_site_id",
        "environment.scenario", "environment.weather", "calibration.status",
        "calibration.certificate_reference", "time_sync.source", "time_sync.estimated_uncertainty_ms",
        "data_storage_path", "authorization.status", "privacy.raw_coordinates_storage",
    )
    for field_path in required_nested_paths:
        current: Any = config
        for part in field_path.split("."):
            current = current.get(part) if isinstance(current, Mapping) else None
        if _is_missing(current):
            missing.append(field_path)
    missing = list(dict.fromkeys(missing))
    errors: list[str] = []
    warnings: list[str] = []
    mode = config.get("acquisition_mode")
    if mode is not None and mode not in ACQUISITION_MODES:
        errors.append("acquisition_mode must be one of " + ", ".join(sorted(ACQUISITION_MODES)))
    frequency = config.get("frequency")
    bandwidth = config.get("bandwidth")
    if not _is_missing(frequency):
        try:
            frequency_hz = convert_unit(float(frequency["value"]), str(frequency["unit"]), "Hz")
            if frequency_hz <= 0:
                errors.append("frequency must be greater than zero")
        except (KeyError, TypeError, ValueError):
            errors.append("frequency requires a positive value and a supported unit")
    if not _is_missing(bandwidth):
        try:
            bandwidth_hz = convert_unit(float(bandwidth["value"]), str(bandwidth["unit"]), "Hz")
            if bandwidth_hz <= 0:
                errors.append("bandwidth must be greater than zero")
        except (KeyError, TypeError, ValueError):
            errors.append("bandwidth requires a positive value and a supported unit")
    points = config.get("measurement_points")
    if points is not None and (not isinstance(points, list) or not points):
        errors.append("measurement_points must contain at least one planned point")
    if mode == "authorized_emission":
        auth = config.get("authorization", {})
        auth = auth if isinstance(auth, Mapping) else {}
        if auth.get("status") != "verified" or not auth.get("evidence_reference"):
            errors.append("emission is blocked until authorization is verified with an evidence reference")
        flight = config.get("flight_authorization", {})
        flight = flight if isinstance(flight, Mapping) else {}
        if config.get("uses_uav") and (flight.get("status") != "verified" or not flight.get("evidence_reference")):
            errors.append("UAV flight is blocked until airspace/flight authorization is verified")
    privacy = config.get("privacy", {})
    privacy = privacy if isinstance(privacy, Mapping) else {}
    if privacy.get("export_reviewed") is not True and privacy.get("export_destination"):
        errors.append("data export is blocked until the export destination has been privacy reviewed")
    if mode == "receive_only":
        auth = config.get("authorization", {})
        auth = auth if isinstance(auth, Mapping) else {}
        if auth.get("status") not in {"verified", "not_required_documented"}:
            warnings.append("receive-only collection still requires a documented legal/spectrum check")
    if missing:
        warnings.append("required fields are incomplete; do not start a measurement session")
    return {
        "ready_for_measurement": not missing and not errors,
        "acquisition_mode": mode,
        "missing_fields": missing,
        "errors": errors,
        "warnings": warnings,
    }


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def read_measurement_file(path: str | Path) -> list[dict[str, Any]]:
    """Read CSV or JSON records without writing to or mutating the source file."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    elif suffix == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("records") if isinstance(payload, dict) else None
    else:
        raise ValueError("measurement import supports CSV and JSON files only")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("JSON measurement file must contain an array of object records")
    return [dict(row) for row in rows]


_NUMERIC_FIELDS: dict[str, tuple[str, bool]] = {
    "frequency_hz": ("Hz", True), "bandwidth_hz": ("Hz", True), "sample_rate_hz": ("Hz", True),
    "distance_m": ("m", True), "geometry_distance_m_from_published_coordinates": ("m", True),
    "tx_height_m": ("m", False), "rx_height_m": ("m", False), "time_s": ("s", False),
    "path_loss_db": ("dB", False), "received_power_dbm": ("dBm", False),
    "transmit_power_dbm": ("dBm", False), "tx_antenna_gain_dbi": ("dBi", False),
    "rx_antenna_gain_dbi": ("dBi", False), "measurement_uncertainty_db": ("dB", False),
}


def _optional_number(value: Any, field: str, positive: bool) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    if positive and result <= 0:
        raise ValueError(f"{field} must be greater than zero")
    if field in {"measurement_uncertainty_db", "path_loss_db", "distance_m", "tx_height_m", "rx_height_m", "bandwidth_hz", "frequency_hz", "sample_rate_hz"} and result < 0:
        raise ValueError(f"{field} must be non-negative")
    return result


def audit_measurement_records(
    rows: Sequence[Mapping[str, Any]], *, device_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate units, values, duplicate IDs and metadata while retaining raw input."""
    metadata = dict(device_metadata or {})
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_records: set[str] = set()
    duplicates = 0
    for index, raw_row in enumerate(rows, start=1):
        row = dict(raw_row)
        record_id = str(row.get("measurement_id") or row.get("sample_id") or row.get("record_id") or "").strip()
        fingerprint = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
        duplicate_id = bool(record_id and record_id in seen_ids)
        duplicate_record = fingerprint in seen_records
        if record_id:
            seen_ids.add(record_id)
        seen_records.add(fingerprint)
        if duplicate_id or duplicate_record:
            duplicates += 1
            rejected.append({"row_number": index, "record_id": record_id or None, "reason": "duplicate_record"})
            continue
        try:
            normalized = dict(row)
            for field, (unit, positive) in _NUMERIC_FIELDS.items():
                if field in row:
                    parsed = _optional_number(row.get(field), field, positive)
                    if parsed is not None:
                        normalized[field] = parsed
            for base_name, canonical, target_unit, positivity in (
                ("frequency", "frequency_hz", "Hz", True),
                ("bandwidth", "bandwidth_hz", "Hz", True),
                ("distance", "distance_m", "m", True),
                ("tx_height", "tx_height_m", "m", False),
                ("rx_height", "rx_height_m", "m", False),
            ):
                if base_name in row and row.get(base_name) not in (None, ""):
                    value = float(row[base_name])
                    converted = convert_unit(value, str(row.get(f"{base_name}_unit", "")), target_unit)
                    if not math.isfinite(converted) or (positivity and converted <= 0) or (not positivity and converted < 0):
                        raise ValueError(f"{base_name} is outside its valid range")
                    normalized[canonical] = converted
        except (TypeError, ValueError) as error:
            rejected.append({"row_number": index, "record_id": record_id or None, "reason": str(error)})
            continue
        valid.append(normalized)
    required_device_metadata = ("device_model", "calibration_status")
    missing_device_metadata = [name for name in required_device_metadata if _is_missing(metadata.get(name))]
    if not metadata and rows:
        missing_device_metadata = list(required_device_metadata)
    sessions = sorted({str(row.get("session_id")) for row in rows if row.get("session_id") not in (None, "")})
    groups = sorted({str(row.get("measurement_group_id") or row.get("session_id") or row.get("source_file") or "") for row in rows})
    return {
        "record_count_before_cleaning": len(rows),
        "record_count_after_cleaning": len(valid),
        "rejected_record_count": len(rejected),
        "duplicate_record_count": duplicates,
        "rejected_records": rejected,
        "missing_device_metadata": missing_device_metadata,
        "required_device_metadata_fields": list(required_device_metadata),
        "device_metadata_complete": not missing_device_metadata,
        "session_count": len(sessions),
        "group_count": len([group for group in groups if group]),
        "sessions": sessions,
        "cleaned_records": valid,
    }


def audit_measurement_file(
    path: str | Path, *, device_metadata: Mapping[str, Any] | None = None,
    source_type: str = "unknown",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Audit a source and verify its hash remains unchanged after read-only access."""
    source = Path(path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    rows = read_measurement_file(source)
    details = audit_measurement_records(rows, device_metadata=device_metadata)
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    result = {key: value for key, value in details.items() if key != "cleaned_records"}
    result.update({
        "schema_version": "1.0",
        "source_file": source.name,
        "source_type": source_type,
        "source_sha256": before,
        "source_hash_unchanged_after_read": before == after,
        "source_read_only": True,
        "device_metadata": dict(device_metadata or {}),
        "import_status": "PASS" if not details["rejected_record_count"] else "PASS_WITH_REJECTIONS",
    })
    return result, details["cleaned_records"]


def write_clean_measurements(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> str:
    """Write derived clean CSV/JSON output; never write to the raw source path."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".csv":
        columns: list[str] = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)
        with output.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    elif output.suffix.lower() == ".json":
        output.write_text(json.dumps(list(rows), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        raise ValueError("clean output must use CSV or JSON extension")
    return hashlib.sha256(output.read_bytes()).hexdigest()


def validate_session_partition(
    rows: Iterable[Mapping[str, Any]], *, group_field: str = "session_id", partition_field: str = "partition",
) -> dict[str, Any]:
    """Prevent records from one session/route leaking across train/validation/test partitions."""
    partitions_by_group: dict[str, set[str]] = {}
    for row in rows:
        group = row.get(group_field)
        partition = row.get(partition_field)
        if group in (None, "") or partition in (None, ""):
            continue
        partitions_by_group.setdefault(str(group), set()).add(str(partition))
    violations = [
        {"group": group, "partitions": sorted(partitions)}
        for group, partitions in sorted(partitions_by_group.items()) if len(partitions) > 1
    ]
    return {
        "status": "PASS" if not violations else "FAIL_SESSION_GROUP_LEAKAGE",
        "group_field": group_field,
        "partition_field": partition_field,
        "group_count": len(partitions_by_group),
        "leakage_groups": violations,
    }


def assess_calibration_status(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Derive a conservative state from evidence; callers cannot supply the state itself."""
    reasons: list[str] = []
    source_type = evidence.get("source_type")
    if source_type == MeasurementSourceType.SYNTHETIC_TEST_ONLY.value:
        if evidence.get("pipeline_tests_passed"):
            state = CalibrationStatus.PIPELINE_VALIDATED
            reasons.append("Synthetic data verified software behavior only; it is not calibration evidence.")
        else:
            state = CalibrationStatus.FAILED_VALIDATION
            reasons.append("Synthetic pipeline checks did not pass.")
    elif source_type != MeasurementSourceType.TARGET_DEVICE_MEASUREMENT.value:
        state = CalibrationStatus.NOT_CALIBRATED
        reasons.append("Only explicitly identified target-device measurements can support device calibration.")
    elif not evidence.get("target_device_id") or int(evidence.get("target_device_record_count", 0)) <= 0:
        state = CalibrationStatus.NOT_CALIBRATED
        reasons.append("No target-device measurement records are available.")
    elif not evidence.get("data_quality_pass") or not evidence.get("metadata_complete") or int(evidence.get("target_device_record_count", 0)) < int(evidence.get("minimum_records", 1)):
        state = CalibrationStatus.INSUFFICIENT_DATA
        reasons.append("Target-device data quality, required metadata, or minimum sample count is insufficient.")
    elif evidence.get("parameter_identifiable") is False:
        state = CalibrationStatus.INSUFFICIENT_DATA
        reasons.append("The requested model parameter is not identifiable from the recorded design.")
    elif not evidence.get("fit_completed"):
        state = CalibrationStatus.NOT_CALIBRATED
        reasons.append("No valid target-device fit has been recorded.")
    elif not evidence.get("independent_holdout_available"):
        state = CalibrationStatus.CALIBRATED_PENDING_HOLDOUT
        reasons.append("A fit exists, but no independent route/session holdout was evaluated.")
    elif not evidence.get("measurement_uncertainty_complete"):
        state = CalibrationStatus.NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING
        reasons.append("Independent holdout exists, but measurement uncertainty is incomplete.")
    else:
        acceptance = evidence.get("acceptance_criteria")
        if not isinstance(acceptance, Mapping) or not acceptance.get("frozen_before_holdout"):
            state = CalibrationStatus.INSUFFICIENT_DATA
            reasons.append("No predeclared, frozen acceptance criteria are attached to the holdout evidence.")
            return {"status": state.value, "reasons": reasons}
        threshold = acceptance.get("maximum_error_db")
        observed = acceptance.get("holdout_error_db")
        criteria_hash = acceptance.get("criteria_sha256")
        if (
            not isinstance(threshold, (int, float)) or not math.isfinite(float(threshold)) or float(threshold) < 0
            or not isinstance(observed, (int, float)) or not math.isfinite(float(observed)) or float(observed) < 0
            or not isinstance(criteria_hash, str) or len(criteria_hash) != 64
        ):
            state = CalibrationStatus.INSUFFICIENT_DATA
            reasons.append("Frozen acceptance evidence is incomplete or malformed.")
            return {"status": state.value, "reasons": reasons}
        if str(criteria_hash).lower() != acceptance_criteria_sha256(acceptance):
            state = CalibrationStatus.INSUFFICIENT_DATA
            reasons.append("Frozen acceptance criteria hash does not match the recorded criterion contents.")
            return {"status": state.value, "reasons": reasons}
        if float(observed) > float(threshold):
            state = CalibrationStatus.FAILED_VALIDATION
            reasons.append("The measured holdout error exceeded the predeclared maximum; failure is retained.")
        else:
            state = CalibrationStatus.HOLDOUT_VALIDATED
            reasons.append("Target-device fit, independent holdout, uncertainty budget, and frozen criteria all passed.")
    return {"status": state.value, "reasons": reasons}


def calibration_state_record(
    evidence: Mapping[str, Any], *, input_hashes: Mapping[str, str], model_version: str,
    previous_status: str | None = None, timestamp_utc: str | None = None,
) -> dict[str, Any]:
    """Record the computed state and auditable state transition with evidence provenance."""
    decision = assess_calibration_status(evidence)
    transition = {
        "from": previous_status,
        "to": decision["status"],
        "reason": "; ".join(decision["reasons"]),
        "input_hashes": dict(sorted(input_hashes.items())),
        "model_version": model_version,
        "timestamp_utc": timestamp_utc or datetime.now(timezone.utc).isoformat(),
    }
    return {
        "schema_version": "1.0",
        "phase": "phase16_calibration_acceptance_state",
        "status": decision["status"],
        "reasons": decision["reasons"],
        "input_hashes": dict(sorted(input_hashes.items())),
        "model_version": model_version,
        "state_transitions": [transition] if previous_status != decision["status"] else [],
        "state_source": "computed_from_evidence",
    }


def evidence_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def to_jsonable_component(component: UncertaintyComponent) -> dict[str, Any]:
    return asdict(component)

