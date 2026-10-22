"""Normalize and quality-audit the CC BY 4.0 Mendeley A2G measurement files."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

import openpyxl
from scipy.io import loadmat


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.phase15_data import (  # noqa: E402
    audit_measurement_records,
    read_measurements,
    sha256_file,
    validate_group_partition,
    write_clean_csv,
)


MANIFEST_PATH = ROOT / "configs/phase15/public_dataset_manifest.json"
PROTOCOL_PATH = ROOT / "configs/phase15/calibration_protocol.json"
DOWNLOAD_AUDIT_PATH = ROOT / "results/phase15_dataset_download_audit.json"
DATA_DIR = ROOT / "data/phase15/raw/mendeley_8p6r8ft4fz_v2"
CLEAN_PATH = ROOT / "results/phase15_measurements_public_clean.csv"
AUDIT_PATH = ROOT / "results/phase15_dataset_audit.json"


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    horizontal = 2.0 * radius_m * math.asin(math.sqrt(a))
    return horizontal


def _file_entry(manifest: dict, filename: str) -> dict:
    matches = [item for item in manifest["files"] if item["filename"] == filename]
    if len(matches) != 1:
        raise ValueError(f"manifest must have exactly one file entry for {filename}")
    return matches[0]


def _verified_source_files(manifest: dict) -> list[dict[str, object]]:
    download_audit = json.loads(DOWNLOAD_AUDIT_PATH.read_text(encoding="utf-8"))
    if download_audit.get("status") != "PASS" or download_audit.get("dataset_doi") != manifest["doi"]:
        raise ValueError("public dataset download audit is absent or does not match the manifest")
    fetched = {item["filename"]: item for item in download_audit.get("files", [])}
    result = []
    for item in manifest["files"]:
        path = DATA_DIR / item["filename"]
        fetched_item = fetched.get(item["filename"])
        if not path.is_file() or not fetched_item:
            raise FileNotFoundError(f"verified public data file is missing: {item['filename']}; run fetch_phase15_public_dataset.py")
        actual_sha = sha256_file(path)
        actual_size = path.stat().st_size
        if actual_sha != item["sha256"] or actual_size != int(item["size_bytes"]):
            raise ValueError(f"public data file no longer matches its published SHA-256/size: {item['filename']}")
        if fetched_item.get("sha256") != actual_sha or int(fetched_item.get("size_bytes", -1)) != actual_size:
            raise ValueError(f"download audit does not match file bytes: {item['filename']}")
        result.append({
            "filename": item["filename"],
            "file_id": item["file_id"],
            "role": item["role"],
            "size_bytes": actual_size,
            "sha256": actual_sha,
            "verified": True,
        })
    return result


def _read_one_session(manifest: dict, file_item: dict) -> tuple[list[dict], dict]:
    filename = str(file_item["filename"])
    workbook_path = DATA_DIR / filename
    scenario = str(file_item["scenario"])
    altitude_nominal = int(file_item["altitude_m"])
    session_id = f"{scenario}_{altitude_nominal}m"
    stem = filename.removesuffix(".xlsx")
    mat_name = f"{stem.removesuffix('_10').removesuffix('_15')}_PL{altitude_nominal}.mat"
    mat_item = _file_entry(manifest, mat_name)
    mat_path = DATA_DIR / mat_name
    matrix_dict = loadmat(mat_path)
    key = Path(mat_name).stem
    if key not in matrix_dict:
        raise ValueError(f"path-loss MAT file lacks expected array {key}: {mat_name}")
    matrix = matrix_dict[key]
    if matrix.ndim != 2 or matrix.shape[0] != 2:
        raise ValueError(f"expected two rows [distance_m, path_loss_db] in {mat_name}, got {matrix.shape}")
    distances = [float(value) for value in matrix[0].tolist()]
    path_losses = [float(value) for value in matrix[1].tolist()]

    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    sheet = workbook.active
    iterator = sheet.iter_rows(values_only=True)
    header = next(iterator, None)
    receiver = next(iterator, None)
    if header is None or receiver is None or tuple(header[:6]) != (
        "lat", "lon", "alt(m)", "time(s)", "freq(GHz)", "sample rate(MHz)"
    ):
        raise ValueError(f"unexpected Mendeley worksheet header/layout: {filename}")
    if not all(isinstance(receiver[index], (int, float)) for index in (0, 1, 2)):
        raise ValueError(f"reference receiver coordinates/height are missing: {filename}")
    receiver_lat, receiver_lon, receiver_height = map(float, receiver[:3])
    raw_rows = [tuple(row) for row in iterator if row and row[0] is not None]
    workbook.close()
    if len(raw_rows) != len(distances) or len(raw_rows) != len(path_losses):
        raise ValueError(
            f"sample count mismatch for {session_id}: xlsx={len(raw_rows)}, distance={len(distances)}, path_loss={len(path_losses)}"
        )

    source_url = manifest["source_url"]
    license_name = manifest["license"]["name"]
    records: list[dict] = []
    geometry_deltas: list[float] = []
    nonfinite_cir = 0
    cir_tap_counts: set[int] = set()
    frequency_values: set[float] = set()
    sample_rate_values: set[float] = set()
    for index, (raw, distance_m, path_loss_db) in enumerate(zip(raw_rows, distances, path_losses, strict=True), start=1):
        if len(raw) < 206:
            raise ValueError(f"raw CIR row has fewer than 200 channel taps in {session_id}, row {index}")
        tx_lat, tx_lon, tx_alt, time_s, frequency_ghz, sample_rate_mhz = (float(raw[i]) for i in range(6))
        taps = raw[6:206]
        cir_tap_counts.add(len(taps))
        nonfinite_cir += sum(
            1 for value in taps
            if not isinstance(value, (int, float)) or not math.isfinite(float(value))
        )
        frequency_hz = frequency_ghz * 1_000_000_000.0
        sample_rate_hz = sample_rate_mhz * 1_000_000.0
        frequency_values.add(frequency_hz)
        sample_rate_values.add(sample_rate_hz)
        horizontal_m = haversine_distance_m(receiver_lat, receiver_lon, tx_lat, tx_lon)
        geometry_distance_m = math.hypot(horizontal_m, tx_alt - receiver_height)
        geometry_deltas.append(abs(geometry_distance_m - distance_m))
        source_row_index = index + 2
        records.append({
            "measurement_id": f"{session_id}:sample-{index:04d}",
            "session_id": session_id,
            "source_type": "public_measurement",
            "source_dataset_doi": manifest["doi"],
            "source_url": source_url,
            "source_file": filename,
            "source_file_sha256": file_item["sha256"],
            "source_row_index": source_row_index,
            "source_license": license_name,
            "scenario": scenario,
            "frequency_hz": frequency_hz,
            "bandwidth_hz": float(manifest["measurement_scope"]["bandwidth_hz"]),
            "sample_rate_hz": sample_rate_hz,
            "tx_height_m": tx_alt,
            "rx_height_m": receiver_height,
            "time_s": time_s,
            "distance_m": distance_m,
            "geometry_distance_m_from_published_coordinates": geometry_distance_m,
            "geometry_distance_delta_m": abs(geometry_distance_m - distance_m),
            "path_loss_db": path_loss_db,
            "received_power_dbm": None,
            "transmit_power_dbm": None,
            "tx_antenna_gain_dbi": None,
            "rx_antenna_gain_dbi": None,
            "device_model": None,
            "measurement_uncertainty_db": None,
            "line_of_sight": None,
            "obstruction_type": None,
            "weather_conditions": None,
            "raw_cir_tap_count": len(taps),
            "calibration_status": "source_derived_path_loss_from_measured_cir; system_uncertainty_not_reported_per_sample",
        })

    diagnostics = {
        "session_id": session_id,
        "scenario": scenario,
        "nominal_uav_altitude_m": altitude_nominal,
        "source_receiver_height_m": receiver_height,
        "sample_count": len(records),
        "raw_cir_tap_counts": sorted(cir_tap_counts),
        "raw_cir_nonfinite_tap_count": nonfinite_cir,
        "frequency_hz_values": sorted(frequency_values),
        "sample_rate_hz_values": sorted(sample_rate_values),
        "path_loss_distance_m_range": [min(distances), max(distances)],
        "path_loss_db_range": [min(path_losses), max(path_losses)],
        "geometry_distance_delta_m": {
            "max": max(geometry_deltas),
            "median": sorted(geometry_deltas)[len(geometry_deltas) // 2],
            "over_5m_count": sum(value > 5.0 for value in geometry_deltas),
        },
        "raw_cir_file_sha256": file_item["sha256"],
        "derived_path_loss_file": mat_name,
        "derived_path_loss_file_sha256": mat_item["sha256"],
    }
    return records, diagnostics


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    verified_files = _verified_source_files(manifest)
    cir_files = [item for item in manifest["files"] if item["role"] == "raw_measured_cir"]
    all_rows: list[dict] = []
    session_diagnostics = []
    for item in cir_files:
        rows, diagnostic = _read_one_session(manifest, item)
        all_rows.extend(rows)
        session_diagnostics.append(diagnostic)

    source_metadata = {
        "dataset_id": manifest["dataset_id"],
        "source_url": manifest["source_url"],
        "license": manifest["license"]["spdx_id"],
        "source_type": "public_measurement",
    }
    row_audit, clean_rows = audit_measurement_records(all_rows, source_metadata=source_metadata)
    partition_audit = validate_group_partition(
        clean_rows,
        protocol["fit_groups"],
        protocol["holdout_groups"],
        group_field="session_id",
    )
    clean_file = ROOT / "results/phase15_measurements_public_clean.csv"
    if row_audit["status"] == "PASS" and partition_audit["status"] == "PASS":
        write_clean_csv(clean_file, clean_rows)
    result = {
        "schema_version": "1.0",
        "phase": "phase15_dataset_quality_audit",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_id": manifest["dataset_id"],
        "dataset_title": manifest["title"],
        "dataset_doi": manifest["doi"],
        "source_url": manifest["source_url"],
        "source_type": "public_measurement",
        "license": manifest["license"],
        "status": "PASS" if row_audit["status"] == "PASS" and partition_audit["status"] == "PASS" else "FAIL",
        "measurement_scope": manifest["measurement_scope"],
        "source_file_integrity": {
            "manifest_file_count": len(manifest["files"]),
            "verified_file_count": len(verified_files),
            "files": verified_files,
        },
        "raw_measurement_layout": {
            "raw_measurement_session_count": len(session_diagnostics),
            "raw_cir_row_count": sum(item["sample_count"] for item in session_diagnostics),
            "derived_path_loss_row_count": sum(item["sample_count"] for item in session_diagnostics),
            "sessions": session_diagnostics,
        },
        "quality_rules": [
            "field units are normalized to SI before fitting",
            "frequency 1 MHz to 100 GHz; distance 0.1 m to 1000 km; path loss 0 to 300 dB",
            "unique measurement_id and source provenance are required",
            "original workbook and MAT files remain read-only",
            "invalid rows remain listed with row number and explicit rejection reasons",
            "no missing RF metadata is imputed",
            "exact latitude/longitude are omitted from the normalized CSV; only geometry cross-check deltas are retained",
        ],
        "row_audit": row_audit,
        "missing_measurement_metadata_counts": row_audit["missing_optional_value_counts"],
        "group_partition_audit": partition_audit,
        "cleaned_dataset": {
            "path": clean_file.relative_to(ROOT).as_posix() if clean_file.exists() else None,
            "sha256": sha256_file(clean_file) if clean_file.exists() else None,
            "row_count": len(clean_rows),
            "coordinates_included": False,
        },
        "calibration_identifiability": {
            "estimable": ["path-loss distance slope on the observed dataset domain", "dataset-defined PL intercept at the selected reference distance"],
            "not_estimable": ["project transmitter power", "project antenna gains", "project receiver sensitivity", "SINR threshold", "separate shadowing sigma", "urban obstruction loss"],
            "reason": "the public labels are author-derived path loss from measured CIR; the source files do not provide a complete project-equivalent link budget or per-sample measurement uncertainty",
        },
        "project_application": {
            "status": "NOT_APPLIED",
            "reason": "3.6 GHz open-environment measurements and unknown sounder link-budget details do not establish applicability to the 3.5 GHz abstract urban project model or target hardware",
        },
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if result["status"] != "PASS":
        print(json.dumps({"status": result["status"], "rejected_rows": row_audit["rejected_row_count"], "partition": partition_audit["status"]}, ensure_ascii=False))
        return 2
    # Verify the persisted interchange file is readable and has the same count.
    roundtrip_rows = read_measurements(clean_file)
    if len(roundtrip_rows) != len(clean_rows):
        raise RuntimeError("clean CSV round-trip count mismatch")
    result["cleaned_dataset"]["csv_round_trip_count"] = len(roundtrip_rows)
    result["cleaned_dataset"]["csv_round_trip_verified"] = True
    AUDIT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "measurement_count": len(clean_rows),
        "session_count": len(session_diagnostics),
        "rejected_count": row_audit["rejected_row_count"],
        "holdout_groups": protocol["holdout_groups"],
        "clean_csv_sha256": result["cleaned_dataset"]["sha256"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Phase 15 data preparation failed: {error}", file=sys.stderr)
        raise SystemExit(2)
