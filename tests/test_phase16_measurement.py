from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from lowalt6g.phase16_measurement import (
    AdapterStatus,
    CalibrationStatus,
    MeasurementSourceType,
    OfflineFileImportAdapter,
    RadioInstrumentAdapter,
    UncertaintyComponent,
    assess_calibration_status,
    acceptance_criteria_sha256,
    audit_measurement_file,
    audit_measurement_records,
    calculate_received_power_dbm,
    calibration_state_record,
    convert_unit,
    initial_uncertainty_budget,
    monte_carlo_propagation,
    propagate_standard_uncertainty,
    validate_experiment_config,
    validate_session_partition,
    write_clean_measurements,
)


def component(name: str, value: float | None, sensitivity: float = 1.0, unit: str = "dB") -> UncertaintyComponent:
    return UncertaintyComponent(name, value, unit, sensitivity, "test", evidence="SYNTHETIC_TEST_ONLY")


def test_linear_unit_conversion_and_unknown_unit_rejection() -> None:
    assert convert_unit(3.5, "GHz", "MHz") == 3500
    assert convert_unit(10, "cm", "m") == pytest.approx(0.1)
    assert convert_unit(180, "deg", "rad") == pytest.approx(3.141592653589793)
    with pytest.raises(ValueError, match="unsupported unit"):
        convert_unit(3500, "MHZ", "Hz")
    with pytest.raises(ValueError, match="incompatible units"):
        convert_unit(1, "m", "Hz")
    with pytest.raises(ValueError, match="incompatible units"):
        convert_unit(-30, "dBm", "dB")


def test_independent_standard_uncertainty_uses_root_sum_square() -> None:
    result = propagate_standard_uncertainty([component("tx", 0.3), component("rx", 0.4, -1)])
    assert result["combined_standard_uncertainty_db"] == pytest.approx(0.5)
    assert result["complete"] is True


def test_known_frequency_and_distance_units_use_explicit_sensitivities() -> None:
    result = propagate_standard_uncertainty([
        component("frequency", 1e6, 1e-6, "Hz"),
        component("distance", 0.2, 2.0, "m"),
    ])
    assert result["combined_standard_uncertainty_db"] == pytest.approx((1.0**2 + 0.4**2) ** 0.5)


def test_covariance_is_included_for_correlated_sources() -> None:
    positive = propagate_standard_uncertainty(
        [component("a", 0.3), component("b", 0.4)], correlations={("a", "b"): 0.5}
    )
    negative_effect = propagate_standard_uncertainty(
        [component("a", 0.3), component("b", 0.4, -1)], correlations={("a", "b"): 0.5}
    )
    assert positive["combined_standard_uncertainty_db"] == pytest.approx((0.37) ** 0.5)
    assert negative_effect["combined_standard_uncertainty_db"] == pytest.approx((0.13) ** 0.5)


def test_invalid_non_positive_semidefinite_correlation_is_rejected() -> None:
    items = [component("a", 0.2), component("b", 0.2), component("c", 0.2)]
    correlations = {("a", "b"): 0.9, ("a", "c"): 0.9, ("b", "c"): -0.9}
    with pytest.raises(ValueError, match="positive semidefinite"):
        propagate_standard_uncertainty(items, correlations=correlations)


def test_unknown_input_is_not_silently_counted_as_zero() -> None:
    result = propagate_standard_uncertainty([component("known", 0.4), component("missing", None)])
    assert result["combined_standard_uncertainty_db"] is None
    assert result["expanded_uncertainty_db"] is None
    assert result["known_only_rss_subtotal_db"] == pytest.approx(0.4)
    assert result["unknown_components"] == ["missing"]
    assert result["assessability"] == "NOT_ASSESSABLE_MISSING_STANDARD_UNCERTAINTIES"


def test_expanded_uncertainty_does_not_infer_coverage_probability() -> None:
    result = propagate_standard_uncertainty([component("a", 0.3), component("b", 0.4)], coverage_factor=2)
    assert result["expanded_uncertainty_db"] == pytest.approx(1.0)
    assert result["coverage_probability"] is None


def test_invalid_uncertainty_values_and_correlation_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        propagate_standard_uncertainty([component("negative", -0.1)])
    with pytest.raises(ValueError, match=r"within \[-1, 1\]"):
        propagate_standard_uncertainty([component("a", 0.2), component("b", 0.3)], correlations={("a", "b"): 1.2})
    with pytest.raises(ValueError, match="unsupported uncertainty unit"):
        propagate_standard_uncertainty([component("absolute_power_level", 0.2, unit="dBm")])


def test_monte_carlo_is_reproducible_and_reports_distribution_not_ci() -> None:
    values = [component("a", 0.3), component("b", 0.4, -1)]
    first = monte_carlo_propagation(values, seed=20261021, draws=500)
    second = monte_carlo_propagation(values, seed=20261021, draws=500)
    assert first == second
    assert first["interval_type"] == "propagated_distribution_quantiles_not_a_confidence_interval"
    assert first["sample_sd_db"] > 0


def test_received_power_formula_uses_consistent_db_terms() -> None:
    assert calculate_received_power_dbm(
        tx_power_dbm=30, tx_antenna_gain_dbi=2, rx_antenna_gain_dbi=3,
        path_loss_db=110, other_losses_db=5,
    ) == -80
    with pytest.raises(ValueError, match="non-negative"):
        calculate_received_power_dbm(
            tx_power_dbm=30, tx_antenna_gain_dbi=2, rx_antenna_gain_dbi=3,
            path_loss_db=-1, other_losses_db=5,
        )


def test_initial_budget_contains_unknowns_without_numeric_defaults() -> None:
    budget = initial_uncertainty_budget()
    assert budget["status"] == "NOT_ASSESSABLE_NO_TARGET_DEVICE_UNCERTAINTIES"
    assert budget["combined_standard_uncertainty_db"] is None
    assert budget["expanded_uncertainty_db"] is None
    assert all(source["standard_uncertainty"] is None for source in budget["sources"])


def test_template_config_is_not_ready_for_measurement() -> None:
    result = validate_experiment_config({"schema_version": "1.0"})
    assert result["ready_for_measurement"] is False
    assert len(result["missing_fields"]) >= 10


def test_present_but_empty_nested_session_metadata_is_not_treated_as_complete() -> None:
    result = validate_experiment_config({
        "experiment_id": "e1", "measurement_batch_id": "b1", "operator_id": "op",
        "acquisition_mode": "offline_import", "frequency": {"value": None, "unit": "MHz"},
        "bandwidth": {"value": 20, "unit": "MHz"}, "transmitter": {"model": None},
        "receiver": {"model": "rx", "measurement_metric": "CIR"},
        "antennas": {"transmit_model": "txa", "receive_model": "rxa"},
        "measurement_points": [{"point_id": "p1"}], "route_or_site_id": "route",
        "environment": {"scenario": "urban", "weather": "unknown"},
        "calibration": {"status": "unknown", "certificate_reference": "not_available"},
        "time_sync": {"source": "host_clock"}, "data_storage_path": "local/session",
        "authorization": {"status": "documented"},
    })
    assert result["ready_for_measurement"] is False
    assert "frequency.value" in result["missing_fields"]
    assert "transmitter.tx_power_dbm" in result["missing_fields"]


def test_invalid_session_frequency_unit_is_reported() -> None:
    config = {
        "experiment_id": "test", "measurement_batch_id": "batch", "operator_id": "operator",
        "acquisition_mode": "offline_import", "frequency": {"value": 3500, "unit": "MHZ"},
        "bandwidth": {"value": 20, "unit": "MHz"}, "transmitter": {"id": "tx"},
        "receiver": {"id": "rx"}, "antennas": {"tx": "a", "rx": "b"},
        "measurement_points": [{"point_id": "p1"}], "environment": {"status": "pending"},
        "calibration": {"status": "unknown"}, "data_storage_path": "data/phase16/session",
        "authorization": {"status": "not_required_documented"},
    }
    result = validate_experiment_config(config)
    assert result["ready_for_measurement"] is False
    assert any("frequency requires" in error for error in result["errors"])


def test_emission_requires_explicit_authorization_and_flight_evidence() -> None:
    config = {
        "experiment_id": "test", "measurement_batch_id": "batch", "operator_id": "operator",
        "acquisition_mode": "authorized_emission", "frequency": {"value": 3.5, "unit": "GHz"},
        "bandwidth": {"value": 20, "unit": "MHz"}, "transmitter": {"id": "tx"},
        "receiver": {"id": "rx"}, "antennas": {"tx": "a", "rx": "b"},
        "measurement_points": [{"point_id": "p1"}], "environment": {"status": "pending"},
        "calibration": {"status": "unknown"}, "data_storage_path": "data/phase16/session",
        "authorization": {"status": "pending"}, "uses_uav": True,
        "flight_authorization": {"status": "pending"},
    }
    result = validate_experiment_config(config)
    assert result["ready_for_measurement"] is False
    assert any("emission is blocked" in error for error in result["errors"])
    assert any("UAV flight is blocked" in error for error in result["errors"])


def test_measurement_record_audit_flags_duplicate_and_bad_units() -> None:
    rows = [
        {"measurement_id": "a", "frequency_hz": "3500000000", "distance_m": "10", "measurement_uncertainty_db": ""},
        {"measurement_id": "a", "frequency_hz": "3500000000", "distance_m": "10"},
        {"measurement_id": "b", "frequency": "3500", "frequency_unit": "MHZ", "distance_m": "10"},
        {"measurement_id": "c", "frequency_hz": "0", "distance_m": "10"},
    ]
    result = audit_measurement_records(rows, device_metadata={"device_model": "", "calibration_status": ""})
    assert result["record_count_before_cleaning"] == 4
    assert result["record_count_after_cleaning"] == 1
    assert result["duplicate_record_count"] == 1
    assert result["rejected_record_count"] == 3
    assert set(result["missing_device_metadata"]) == {"device_model", "calibration_status"}


def test_measurement_file_import_writes_derived_copy_without_mutating_source(tmp_path: Path) -> None:
    raw = tmp_path / "observations.csv"
    with raw.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["measurement_id", "frequency_hz", "distance_m"])
        writer.writeheader()
        writer.writerow({"measurement_id": "m1", "frequency_hz": "3500000000", "distance_m": "10"})
    before = raw.read_bytes()
    audit, cleaned = audit_measurement_file(raw, device_metadata={"device_model": "test", "calibration_status": "unknown"}, source_type="SYNTHETIC_TEST_ONLY")
    output = tmp_path / "derived" / "observations.clean.csv"
    output_hash = write_clean_measurements(output, cleaned)
    assert raw.read_bytes() == before
    assert audit["source_hash_unchanged_after_read"] is True
    assert audit["record_count_before_cleaning"] == 1
    assert audit["record_count_after_cleaning"] == 1
    assert len(output_hash) == 64
    assert output.is_file()


def test_json_measurement_import_supports_record_envelope(tmp_path: Path) -> None:
    raw = tmp_path / "data.json"
    raw.write_text(json.dumps({"records": [{"measurement_id": "m1", "distance_m": 12}]}), encoding="utf-8")
    audit, cleaned = audit_measurement_file(raw)
    assert audit["record_count_after_cleaning"] == 1
    assert cleaned[0]["distance_m"] == 12.0


def test_same_session_cannot_be_split_across_partitions() -> None:
    result = validate_session_partition([
        {"session_id": "s1", "partition": "train"},
        {"session_id": "s1", "partition": "test"},
        {"session_id": "s2", "partition": "train"},
    ])
    assert result["status"] == "FAIL_SESSION_GROUP_LEAKAGE"
    assert result["leakage_groups"] == [{"group": "s1", "partitions": ["test", "train"]}]


def test_session_group_partition_passes_when_each_session_is_whole() -> None:
    result = validate_session_partition([
        {"session_id": "s1", "partition": "train"},
        {"session_id": "s1", "partition": "train"},
        {"session_id": "s2", "partition": "test"},
    ])
    assert result["status"] == "PASS"


def test_state_machine_refuses_synthetic_data_as_real_calibration() -> None:
    result = assess_calibration_status({
        "source_type": MeasurementSourceType.SYNTHETIC_TEST_ONLY.value,
        "pipeline_tests_passed": True,
        "target_device_id": "fake-device",
        "target_device_record_count": 999,
        "measurement_uncertainty_complete": True,
        "acceptance_passed": True,
    })
    assert result["status"] == CalibrationStatus.PIPELINE_VALIDATED.value
    assert "not calibration evidence" in result["reasons"][0]


def test_state_machine_requires_target_device_holdout_and_uncertainty() -> None:
    no_device = assess_calibration_status({"source_type": "public_measurement", "target_device_record_count": 0})
    no_holdout = assess_calibration_status({
        "source_type": MeasurementSourceType.TARGET_DEVICE_MEASUREMENT.value,
        "target_device_id": "dev-1", "target_device_record_count": 100,
        "minimum_records": 50, "metadata_complete": True, "data_quality_pass": True,
        "parameter_identifiable": True, "fit_completed": True,
        "independent_holdout_available": False,
    })
    no_uncertainty = assess_calibration_status({
        "source_type": MeasurementSourceType.TARGET_DEVICE_MEASUREMENT.value,
        "target_device_id": "dev-1", "target_device_record_count": 100,
        "minimum_records": 50, "metadata_complete": True, "data_quality_pass": True,
        "parameter_identifiable": True, "fit_completed": True,
        "independent_holdout_available": True, "measurement_uncertainty_complete": False,
    })
    assert no_device["status"] == CalibrationStatus.NOT_CALIBRATED.value
    assert no_holdout["status"] == CalibrationStatus.CALIBRATED_PENDING_HOLDOUT.value
    assert no_uncertainty["status"] == CalibrationStatus.NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING.value


def test_state_machine_records_failure_and_never_manually_sets_success() -> None:
    criteria = {
        "frozen_before_holdout": True, "maximum_error_db": 1.0,
        "holdout_error_db": 1.4,
    }
    criteria["criteria_sha256"] = acceptance_criteria_sha256(criteria)
    failed_evidence = {
        "source_type": MeasurementSourceType.TARGET_DEVICE_MEASUREMENT.value,
        "target_device_id": "dev-1", "target_device_record_count": 100,
        "minimum_records": 50, "metadata_complete": True, "data_quality_pass": True,
        "parameter_identifiable": True, "fit_completed": True,
        "independent_holdout_available": True, "measurement_uncertainty_complete": True,
        "acceptance_criteria": criteria,
    }
    result = calibration_state_record(failed_evidence, input_hashes={"data": "a" * 64}, model_version="phase16-test", timestamp_utc="2026-10-21T00:00:00+00:00")
    assert result["status"] == CalibrationStatus.FAILED_VALIDATION.value
    assert result["state_transitions"][0]["to"] == CalibrationStatus.FAILED_VALIDATION.value
    assert result["state_transitions"][0]["input_hashes"]["data"] == "a" * 64


def test_state_machine_requires_frozen_acceptance_evidence_for_success() -> None:
    base = {
        "source_type": MeasurementSourceType.TARGET_DEVICE_MEASUREMENT.value,
        "target_device_id": "dev-1", "target_device_record_count": 100,
        "minimum_records": 50, "metadata_complete": True, "data_quality_pass": True,
        "parameter_identifiable": True, "fit_completed": True,
        "independent_holdout_available": True, "measurement_uncertainty_complete": True,
    }
    assert assess_calibration_status(base)["status"] == CalibrationStatus.INSUFFICIENT_DATA.value
    criteria = {
        "frozen_before_holdout": True, "maximum_error_db": 2.0,
        "holdout_error_db": 1.5,
    }
    criteria["criteria_sha256"] = acceptance_criteria_sha256(criteria)
    base["acceptance_criteria"] = criteria
    assert assess_calibration_status(base)["status"] == CalibrationStatus.HOLDOUT_VALIDATED.value


def test_public_measurement_cannot_be_mislabeled_as_target_device_calibration() -> None:
    result = assess_calibration_status({
        "source_type": MeasurementSourceType.PUBLIC_MEASUREMENT.value,
        "target_device_id": "some-device", "target_device_record_count": 1000,
        "data_quality_pass": True, "metadata_complete": True,
    })
    assert result["status"] == CalibrationStatus.NOT_CALIBRATED.value


def test_acceptance_criteria_digest_detects_changed_threshold() -> None:
    criteria = {"frozen_before_holdout": True, "maximum_error_db": 1.0}
    digest = acceptance_criteria_sha256(criteria)
    changed = {"frozen_before_holdout": True, "maximum_error_db": 1.1, "criteria_sha256": digest}
    assert acceptance_criteria_sha256(changed) != digest
    result = assess_calibration_status({
        "source_type": MeasurementSourceType.TARGET_DEVICE_MEASUREMENT.value,
        "target_device_id": "dev-1", "target_device_record_count": 100,
        "minimum_records": 50, "metadata_complete": True, "data_quality_pass": True,
        "parameter_identifiable": True, "fit_completed": True,
        "independent_holdout_available": True, "measurement_uncertainty_complete": True,
        "acceptance_criteria": {
            "frozen_before_holdout": True, "maximum_error_db": 1.1,
            "holdout_error_db": 1.0, "criteria_sha256": digest,
        },
    })
    assert result["status"] == CalibrationStatus.INSUFFICIENT_DATA.value


def test_adapter_status_distinguishes_file_import_from_real_device() -> None:
    assert OfflineFileImportAdapter().identify() == {
        "adapter_id": "offline_file_import", "status": AdapterStatus.IMPLEMENTED_AND_TESTED.value, "live_device": False
    }
    assert RadioInstrumentAdapter.status == AdapterStatus.UNAVAILABLE

