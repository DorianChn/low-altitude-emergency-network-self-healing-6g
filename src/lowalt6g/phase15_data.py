"""Import and audit provenance-aware wireless measurement tables for Phase 15."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


SOURCE_TYPES = {"field_measurement", "public_measurement", "literature_reference", "synthetic_test_only"}
OPTIONAL_MEASUREMENT_FIELDS = (
    "transmit_power_dbm",
    "tx_antenna_gain_dbi",
    "rx_antenna_gain_dbi",
    "device_model",
    "measurement_uncertainty_db",
    "measured_rsrp_dbm",
    "measured_sinr_db",
    "line_of_sight",
    "obstruction_type",
    "weather_conditions",
)
NUMERIC_RANGES = {
    "frequency_hz": (1e6, 1e11),
    "bandwidth_hz": (1.0, 1e11),
    "sample_rate_hz": (1.0, 1e11),
    "distance_m": (0.1, 1e6),
    "tx_height_m": (-500.0, 10000.0),
    "rx_height_m": (-500.0, 10000.0),
    "time_s": (0.0, 1e12),
    "path_loss_db": (0.0, 300.0),
    "received_power_dbm": (-200.0, 100.0),
    "transmit_power_dbm": (-100.0, 100.0),
    "tx_antenna_gain_dbi": (-30.0, 80.0),
    "rx_antenna_gain_dbi": (-30.0, 80.0),
    "measurement_uncertainty_db": (0.0, 100.0),
    "measured_rsrp_dbm": (-200.0, 100.0),
    "measured_sinr_db": (-100.0, 100.0),
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return math.nan
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number


def read_measurements(path: str | Path) -> list[dict[str, Any]]:
    """Read CSV or JSON without mutating the source file."""
    source = Path(path)
    if source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            return [dict(row) for row in csv.DictReader(stream)]
    if source.suffix.lower() == ".json":
        value = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            value = value.get("records")
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ValueError("JSON measurement data must be an array or an object with a records array")
        return [dict(item) for item in value]
    raise ValueError("measurement import supports CSV and JSON only")


def audit_measurement_records(
    records: Iterable[dict[str, Any]],
    *,
    source_metadata: dict[str, Any],
    source_path: str | Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate rows and return an audit plus normalized valid rows.

    Invalid rows are reported with row numbers and reasons; they are never silently
    deleted. The caller must persist the audit before using the returned subset.
    """
    source_rows = list(records)
    metadata_errors = []
    for key in ("dataset_id", "source_url", "license", "source_type"):
        if not source_metadata.get(key):
            metadata_errors.append(f"missing_source_metadata:{key}")
    source_type = source_metadata.get("source_type")
    if source_type not in SOURCE_TYPES:
        metadata_errors.append("invalid_source_type")

    seen_ids: set[str] = set()
    seen_signatures: set[tuple[str, str, str, str]] = set()
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    missing_counts = {field: 0 for field in OPTIONAL_MEASUREMENT_FIELDS}
    field_counts: dict[str, int] = {}

    for row_number, original in enumerate(source_rows, start=1):
        row = dict(original)
        reasons: list[str] = []
        for field in row:
            field_counts[field] = field_counts.get(field, 0) + 1
        measurement_id = str(row.get("measurement_id") or "").strip()
        session_id = str(row.get("session_id") or "").strip()
        if not measurement_id:
            reasons.append("missing_measurement_id")
        elif measurement_id in seen_ids:
            reasons.append("duplicate_measurement_id")
        else:
            seen_ids.add(measurement_id)
        if not session_id:
            reasons.append("missing_session_id")

        for alias, canonical in (("frequency_mhz", "frequency_hz"), ("frequency_ghz", "frequency_hz"), ("distance_km", "distance_m")):
            if alias in row and canonical not in row:
                reasons.append(f"unsupported_unit_{alias}")
        row_source_type = str(row.get("source_type") or source_type or "").strip()
        if row_source_type not in SOURCE_TYPES:
            reasons.append("invalid_source_type")
        for field in ("source_dataset_doi", "source_file", "source_license"):
            if not str(row.get(field) or "").strip():
                reasons.append(f"missing_provenance:{field}")

        numeric: dict[str, float | None] = {}
        for field, (minimum, maximum) in NUMERIC_RANGES.items():
            value = _number(row.get(field))
            numeric[field] = value
            if value is None:
                if field in {"frequency_hz", "distance_m"}:
                    reasons.append(f"missing_required:{field}")
                continue
            if not math.isfinite(value):
                reasons.append(f"non_finite:{field}")
            elif not minimum <= value <= maximum:
                reasons.append(f"out_of_range:{field}")

        if numeric.get("path_loss_db") is None and numeric.get("received_power_dbm") is None:
            reasons.append("missing_radio_label:path_loss_db_or_received_power_dbm")

        signature = (
            session_id,
            str(row.get("time_s", "")),
            str(row.get("distance_m", "")),
            str(row.get("path_loss_db", row.get("received_power_dbm", ""))),
        )
        if all(signature):
            if signature in seen_signatures:
                reasons.append("duplicate_measurement_signature")
            else:
                seen_signatures.add(signature)

        for field in OPTIONAL_MEASUREMENT_FIELDS:
            if row.get(field) is None or row.get(field) == "":
                missing_counts[field] += 1

        if reasons:
            rejected.append({"row_number": row_number, "measurement_id": measurement_id or None, "reasons": sorted(set(reasons))})
            continue

        normalized = dict(row)
        normalized["measurement_id"] = measurement_id
        normalized["session_id"] = session_id
        normalized["source_type"] = row_source_type
        for field, value in numeric.items():
            if field in row or field in {"frequency_hz", "distance_m"}:
                normalized[field] = value
        valid.append(normalized)

    result = {
        "status": "PASS" if not metadata_errors and not rejected else "FAIL",
        "source_metadata_errors": metadata_errors,
        "row_count": len(source_rows),
        "valid_row_count": len(valid),
        "rejected_row_count": len(rejected),
        "rejection_counts": _count_rejections(rejected),
        "rejected_rows": rejected,
        "field_presence_counts": field_counts,
        "missing_optional_value_counts": missing_counts,
        "source_file_sha256": sha256_file(source_path) if source_path is not None else None,
    }
    return result, valid


def _count_rejections(rejected: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in rejected:
        for reason in item["reasons"]:
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def validate_group_partition(
    records: Iterable[dict[str, Any]],
    fit_groups: Iterable[str],
    holdout_groups: Iterable[str],
    *,
    group_field: str = "session_id",
) -> dict[str, Any]:
    fit = [str(value) for value in fit_groups]
    holdout = [str(value) for value in holdout_groups]
    overlap = sorted(set(fit) & set(holdout))
    duplicate_assignments = sorted(
        {value for value in fit if fit.count(value) > 1}
        | {value for value in holdout if holdout.count(value) > 1}
    )
    observed = {str(row.get(group_field) or "") for row in records}
    assigned = set(fit) | set(holdout)
    missing_groups = sorted(observed - assigned)
    unknown_groups = sorted(assigned - observed)
    return {
        "status": "PASS" if not (overlap or duplicate_assignments or missing_groups or unknown_groups) else "FAIL",
        "group_field": group_field,
        "fit_groups": fit,
        "holdout_groups": holdout,
        "observed_groups": sorted(observed),
        "overlap": overlap,
        "duplicate_assignments": duplicate_assignments,
        "unassigned_observed_groups": missing_groups,
        "assigned_groups_without_rows": unknown_groups,
    }


def write_clean_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("refusing to write a clean dataset with zero valid rows")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
