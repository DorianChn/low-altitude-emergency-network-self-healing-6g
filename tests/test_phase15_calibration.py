from __future__ import annotations

import math

import pytest

from lowalt6g.phase15_calibration import (
    evaluate_holdout_baselines,
    evaluate_independent_holdout,
    fit_fixed_slope_offset_model,
    fit_log_distance_model,
)
from lowalt6g.radio_link import free_space_path_loss_db


def measured_group(group: str, *, pl0: float = 58.0, exponent: float = 2.7) -> list[dict]:
    rows = []
    for index, distance in enumerate((10.0, 20.0, 50.0, 100.0, 200.0, 500.0), start=1):
        rows.append({
            "measurement_id": f"{group}-{index}",
            "session_id": group,
            "distance_m": distance,
            "path_loss_db": pl0 + 10 * exponent * math.log10(distance),
            "time_s": float(index),
            "source_type": "synthetic_test_only",
            "measurement_uncertainty_db": None,
        })
    return rows


def test_log_distance_fit_recovers_known_parameters():
    records = sum((measured_group(group) for group in ("a", "b", "c")), [])
    fit = fit_log_distance_model(records, ["a", "b", "c"], bootstrap_replicates=200, bootstrap_seed=24)
    assert fit["pl0_db_at_reference_distance"] == pytest.approx(58.0, abs=1e-9)
    assert fit["path_loss_exponent"] == pytest.approx(2.7, abs=1e-9)
    assert fit["parameter_uncertainty"]["replicates_valid"] == 200
    assert fit["parameter_uncertainty"]["ci95"]["path_loss_exponent"] == pytest.approx([2.7, 2.7])


def test_cluster_bootstrap_is_reproducible():
    records = sum((measured_group(group) for group in ("a", "b", "c")), [])
    first = fit_log_distance_model(records, ["a", "b", "c"], bootstrap_replicates=200, bootstrap_seed=99)
    second = fit_log_distance_model(records, ["a", "b", "c"], bootstrap_replicates=200, bootstrap_seed=99)
    assert first["parameter_uncertainty"] == second["parameter_uncertainty"]


def test_two_training_groups_are_not_enough_to_fit():
    records = measured_group("a") + measured_group("b")
    with pytest.raises(ValueError, match="at least three distinct training groups"):
        fit_log_distance_model(records, ["a", "b"], bootstrap_replicates=100)


def test_narrow_distance_range_is_not_identifiable():
    records = []
    for group in ("a", "b", "c"):
        for index, distance in enumerate((10.0, 12.0, 15.0), start=1):
            records.append({"measurement_id": f"{group}-{index}", "session_id": group, "distance_m": distance, "path_loss_db": 70 + index})
    with pytest.raises(ValueError, match="at least one decade"):
        fit_log_distance_model(records, ["a", "b", "c"], bootstrap_replicates=100)


def test_independent_holdout_keeps_group_counts_and_uncertainty_limits():
    training = sum((measured_group(group) for group in ("a", "b", "c")), [])
    fit = fit_log_distance_model(training, ["a", "b", "c"], bootstrap_replicates=200, bootstrap_seed=4)
    holdout = measured_group("water-10") + measured_group("water-15")
    baseline = {
        "model_id": "phase14",
        "reference_distance_m": 1.0,
        "pl0_db_at_reference_distance": 48.0,
        "path_loss_exponent": 2.3,
    }
    result = evaluate_independent_holdout(
        holdout,
        ["water-10", "water-15"],
        candidate=fit,
        baseline=baseline,
        bootstrap_replicates=200,
        bootstrap_seed=77,
    )
    assert result["sample_count"] == 12
    assert result["holdout_group_count"] == 2
    assert result["metrics"]["candidate"]["mae_db"] == pytest.approx(0.0, abs=1e-9)
    assert result["acceptance"]["decision"] == "NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING"
    assert result["candidate_error_ci95_cluster_bootstrap"]["group_count"] == 2
    assert "low resolution" in result["candidate_error_ci95_cluster_bootstrap"]["warning"]


def offset_group(group: str, *, offset: float = 4.0) -> list[dict]:
    fspl = free_space_path_loss_db(3600.0, 1.0)
    return [
        {
            "measurement_id": f"{group}-{index}",
            "session_id": group,
            "distance_m": distance,
            "path_loss_db": fspl + 10 * 2.3 * math.log10(distance) + offset,
            "measurement_uncertainty_db": None,
        }
        for index, distance in enumerate((40.0, 60.0, 90.0, 120.0), 1)
    ]


def test_fixed_slope_offset_fit_recovers_group_balanced_offset():
    rows = sum((offset_group(group, offset=value) for group, value in zip(("a", "b", "c", "d"), (2, 4, 6, 8))), [])
    fit = fit_fixed_slope_offset_model(
        rows,
        ["a", "b", "c", "d"],
        carrier_frequency_mhz=3600.0,
        fixed_exponent=2.3,
        bootstrap_replicates=200,
        bootstrap_seed=15,
    )
    assert fit["dataset_offset_db"] == pytest.approx(5.0, abs=1e-10)
    assert fit["path_loss_exponent_status"].startswith("fixed_")
    assert fit["estimated_parameter_count"] == 1


def test_fixed_slope_fit_is_reproducible_and_holdout_compares_two_baselines():
    train = sum((offset_group(group, offset=3.0) for group in ("a", "b", "c", "d")), [])
    fit = fit_fixed_slope_offset_model(
        train,
        ["a", "b", "c", "d"],
        carrier_frequency_mhz=3600.0,
        fixed_exponent=2.3,
        bootstrap_replicates=200,
        bootstrap_seed=516,
    )
    fit_again = fit_fixed_slope_offset_model(
        train,
        ["a", "b", "c", "d"],
        carrier_frequency_mhz=3600.0,
        fixed_exponent=2.3,
        bootstrap_replicates=200,
        bootstrap_seed=516,
    )
    assert fit["parameter_uncertainty"] == fit_again["parameter_uncertainty"]
    holdout = offset_group("h1", offset=3.0) + offset_group("h2", offset=3.0)
    baselines = {
        "exact": {
            "model_id": "exact_phase14",
            "reference_distance_m": 1.0,
            "pl0_db_at_reference_distance": free_space_path_loss_db(3500, 1.0),
            "path_loss_exponent": 2.3,
        },
        "frequency_matched": {
            "model_id": "frequency_matched_unfit",
            "reference_distance_m": 1.0,
            "pl0_db_at_reference_distance": free_space_path_loss_db(3600, 1.0),
            "path_loss_exponent": 2.3,
        },
    }
    result = evaluate_holdout_baselines(
        holdout,
        ["h1", "h2"],
        candidate=fit,
        baselines=baselines,
        bootstrap_replicates=200,
        bootstrap_seed=77,
    )
    assert result["sample_count"] == 8
    assert set(result["comparisons"]) == {"exact", "frequency_matched"}
    assert result["acceptance"]["decision"] == "NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING"
    assert result["comparisons"]["frequency_matched"]["baseline_metrics"]["mae_db"] == pytest.approx(3.0, abs=1e-9)
