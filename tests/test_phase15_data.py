from __future__ import annotations

import csv
import json

from lowalt6g.phase15_data import (
    audit_measurement_records,
    read_measurements,
    sha256_file,
    validate_group_partition,
    write_clean_csv,
)


def valid_row(measurement_id: str = "m1", session_id: str = "route-a") -> dict:
    return {
        "measurement_id": measurement_id,
        "session_id": session_id,
        "source_type": "synthetic_test_only",
        "source_dataset_doi": "test:fixture",
        "source_file": "fixture.csv",
        "source_license": "test-only",
        "frequency_hz": 3_600_000_000,
        "bandwidth_hz": 61_440_000,
        "distance_m": 50.0,
        "path_loss_db": 82.0,
    }


def source_metadata() -> dict:
    return {
        "dataset_id": "test-fixture",
        "source_url": "https://example.invalid/fixture",
        "license": "test-only",
        "source_type": "synthetic_test_only",
    }


def test_csv_and_json_import_and_clean_copy(tmp_path):
    row = valid_row()
    csv_path = tmp_path / "measurement.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    json_path = tmp_path / "measurement.json"
    json_path.write_text(json.dumps({"records": [row]}), encoding="utf-8")

    csv_rows = read_measurements(csv_path)
    json_rows = read_measurements(json_path)
    audit, valid = audit_measurement_records(csv_rows, source_metadata=source_metadata(), source_path=csv_path)
    clean_path = tmp_path / "clean" / "measurements.csv"
    write_clean_csv(clean_path, valid)

    assert len(json_rows) == len(csv_rows) == 1
    assert audit["status"] == "PASS"
    assert audit["source_file_sha256"] == sha256_file(csv_path)
    assert read_measurements(clean_path)[0]["measurement_id"] == "m1"
    assert csv_path.read_text(encoding="utf-8").count("m1") == 1


def test_missing_provenance_is_reported_and_not_accepted():
    row = valid_row()
    row.pop("source_license")
    audit, accepted = audit_measurement_records([row], source_metadata=source_metadata())
    assert audit["status"] == "FAIL"
    assert audit["rejected_rows"][0]["reasons"] == ["missing_provenance:source_license"]
    assert accepted == []


def test_unsupported_units_and_non_finite_values_are_rejected():
    wrong_unit = valid_row("m1")
    wrong_unit.pop("frequency_hz")
    wrong_unit["frequency_mhz"] = 3600
    bad_number = valid_row("m2", "route-b")
    bad_number["path_loss_db"] = "NaN"
    audit, accepted = audit_measurement_records([wrong_unit, bad_number], source_metadata=source_metadata())
    assert audit["status"] == "FAIL"
    assert audit["rejection_counts"]["unsupported_unit_frequency_mhz"] == 1
    assert audit["rejection_counts"]["missing_required:frequency_hz"] == 1
    assert audit["rejection_counts"]["non_finite:path_loss_db"] == 1
    assert accepted == []


def test_duplicate_ids_and_duplicate_measurement_signatures_are_not_silently_dropped():
    first = valid_row("m1", "route-a")
    second = valid_row("m1", "route-a")
    second["time_s"] = 1.0
    third = valid_row("m3", "route-b")
    third["time_s"] = 1.0
    audit, accepted = audit_measurement_records([first, second, third], source_metadata=source_metadata())
    assert audit["rejected_row_count"] == 1
    assert audit["rejection_counts"]["duplicate_measurement_id"] == 1
    assert len(accepted) == 2


def test_duplicate_signature_with_distinct_id_is_reported():
    first = valid_row("m1", "route-a")
    first["time_s"] = 3.0
    duplicate = dict(first, measurement_id="m2")
    audit, accepted = audit_measurement_records([first, duplicate], source_metadata=source_metadata())
    assert audit["rejection_counts"]["duplicate_measurement_signature"] == 1
    assert len(accepted) == 1


def test_source_hash_changes_when_original_file_changes(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("immutable source\n", encoding="utf-8")
    before = sha256_file(source)
    audit_before, _ = audit_measurement_records([valid_row()], source_metadata=source_metadata(), source_path=source)
    source.write_text("changed source\n", encoding="utf-8")
    audit_after, _ = audit_measurement_records([valid_row()], source_metadata=source_metadata(), source_path=source)
    assert before == audit_before["source_file_sha256"]
    assert audit_after["source_file_sha256"] != before


def test_group_split_rejects_leakage_and_unassigned_groups():
    rows = [valid_row("m1", "route-a"), valid_row("m2", "route-b")]
    leakage = validate_group_partition(rows, ["route-a"], ["route-a", "route-b"])
    missing = validate_group_partition(rows, ["route-a"], ["route-c"])
    assert leakage["status"] == "FAIL"
    assert leakage["overlap"] == ["route-a"]
    assert missing["unassigned_observed_groups"] == ["route-b"]
    assert missing["assigned_groups_without_rows"] == ["route-c"]
