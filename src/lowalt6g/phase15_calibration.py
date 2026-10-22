"""Explainable log-distance fitting and environment-group holdout evaluation."""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from .radio_link import free_space_path_loss_db


def _arrays(records: list[dict[str, Any]], distance_field: str = "distance_m", response_field: str = "path_loss_db") -> tuple[np.ndarray, np.ndarray]:
    distance = np.asarray([float(row[distance_field]) for row in records], dtype=float)
    response = np.asarray([float(row[response_field]) for row in records], dtype=float)
    if not np.isfinite(distance).all() or not np.isfinite(response).all() or (distance <= 0).any():
        raise ValueError("distance and path-loss observations must be finite and positive")
    return distance, response


def _weighted_fit(x: np.ndarray, y: np.ndarray, weights: np.ndarray) -> tuple[float, float]:
    if len(x) < 3 or len(np.unique(x)) < 2:
        raise ValueError("insufficient distinct distances for log-distance fitting")
    design = np.column_stack((np.ones(len(x), dtype=float), x))
    scale = np.sqrt(weights)
    coefficients, _, rank, _ = np.linalg.lstsq(design * scale[:, None], y * scale, rcond=None)
    if rank < 2:
        raise ValueError("log-distance parameters are not identifiable")
    pl0_db, slope_db_per_decade = (float(coefficients[0]), float(coefficients[1]))
    exponent = slope_db_per_decade / 10.0
    if not math.isfinite(pl0_db) or not math.isfinite(exponent) or exponent <= 0:
        raise ValueError("fitted path-loss exponent is non-positive or non-finite")
    return pl0_db, exponent


def predict_path_loss(distance_m: Iterable[float], *, pl0_db: float, exponent: float, reference_distance_m: float = 1.0) -> np.ndarray:
    distance = np.asarray(list(distance_m), dtype=float)
    if reference_distance_m <= 0 or exponent <= 0 or not math.isfinite(pl0_db):
        raise ValueError("invalid log-distance model parameters")
    if not np.isfinite(distance).all() or (distance <= 0).any():
        raise ValueError("prediction distances must be finite and positive")
    return pl0_db + 10.0 * exponent * np.log10(np.maximum(distance, reference_distance_m) / reference_distance_m)


def _percentile_interval(values: list[float], low: float = 2.5, high: float = 97.5) -> list[float] | None:
    if len(values) < 20:
        return None
    return [float(v) for v in np.percentile(np.asarray(values, dtype=float), [low, high])]


def fit_log_distance_model(
    records: Iterable[dict[str, Any]],
    fit_groups: Iterable[str],
    *,
    reference_distance_m: float = 1.0,
    bootstrap_replicates: int = 4000,
    bootstrap_seed: int = 150042,
) -> dict[str, Any]:
    """Fit PL0 and n with equal total weight per training route/environment group."""
    rows = [dict(row) for row in records]
    groups = [str(value) for value in fit_groups]
    by_group = {group: [row for row in rows if str(row.get("session_id")) == group] for group in groups}
    missing = [group for group, values in by_group.items() if not values]
    if missing:
        raise ValueError(f"training groups have no rows: {missing}")
    if len(set(groups)) != len(groups) or len(groups) < 3:
        raise ValueError("at least three distinct training groups are required")
    training = [row for group in groups for row in by_group[group]]
    distance, response = _arrays(training)
    reference_distance_m = float(reference_distance_m)
    if reference_distance_m <= 0:
        raise ValueError("reference_distance_m must be positive")
    log_distance = np.log10(np.maximum(distance, reference_distance_m) / reference_distance_m)
    distance_span_decades = float(np.max(log_distance) - np.min(log_distance))
    if distance_span_decades < 1.0:
        raise ValueError("training distances must span at least one decade")
    weights = np.concatenate([np.full(len(by_group[group]), 1.0 / len(by_group[group])) for group in groups])
    pl0_db, exponent = _weighted_fit(log_distance, response, weights)
    prediction = predict_path_loss(distance, pl0_db=pl0_db, exponent=exponent, reference_distance_m=reference_distance_m)
    residuals = prediction - response
    residual_sd_db = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else None

    rng = np.random.default_rng(int(bootstrap_seed))
    boot_parameters: list[tuple[float, float, float]] = []
    for _ in range(int(bootstrap_replicates)):
        sampled = rng.choice(groups, size=len(groups), replace=True).tolist()
        sampled_rows = [row for group in sampled for row in by_group[group]]
        try:
            sample_distance, sample_response = _arrays(sampled_rows)
            sample_x = np.log10(np.maximum(sample_distance, reference_distance_m) / reference_distance_m)
            sample_weights = np.concatenate([
                np.full(len(by_group[group]), 1.0 / len(by_group[group])) for group in sampled
            ])
            sample_pl0, sample_n = _weighted_fit(sample_x, sample_response, sample_weights)
            sample_residual = predict_path_loss(
                sample_distance,
                pl0_db=sample_pl0,
                exponent=sample_n,
                reference_distance_m=reference_distance_m,
            ) - sample_response
            sample_sd = float(np.std(sample_residual, ddof=1))
            boot_parameters.append((sample_pl0, sample_n, sample_sd))
        except ValueError:
            continue

    if len(boot_parameters) < max(100, int(bootstrap_replicates * 0.8)):
        raise ValueError("too few valid cluster bootstrap fits; parameters are weakly identified")
    bootstrap_array = np.asarray(boot_parameters, dtype=float)
    parameter_ci = {
        "pl0_db_at_reference_distance": _percentile_interval(bootstrap_array[:, 0].tolist()),
        "path_loss_exponent": _percentile_interval(bootstrap_array[:, 1].tolist()),
        "residual_sd_db": _percentile_interval(bootstrap_array[:, 2].tolist()),
    }
    correlation = float(np.corrcoef(bootstrap_array[:, 0], bootstrap_array[:, 1])[0, 1])
    by_session = {}
    for group in groups:
        group_rows = by_group[group]
        group_distance, group_response = _arrays(group_rows)
        group_residual = predict_path_loss(
            group_distance,
            pl0_db=pl0_db,
            exponent=exponent,
            reference_distance_m=reference_distance_m,
        ) - group_response
        by_session[group] = {
            "sample_count": len(group_rows),
            "mean_bias_db": float(np.mean(group_residual)),
            "mae_db": float(np.mean(np.abs(group_residual))),
            "rmse_db": float(np.sqrt(np.mean(group_residual**2))),
        }
    return {
        "model_id": "phase15_public_a2g_fit_v1",
        "equation": "PL(d) = PL0 + 10*n*log10(max(d,d0)/d0)",
        "reference_distance_m": reference_distance_m,
        "pl0_db_at_reference_distance": pl0_db,
        "path_loss_exponent": exponent,
        "training_sample_count": len(training),
        "training_group_count": len(groups),
        "training_groups": groups,
        "distance_range_m": [float(np.min(distance)), float(np.max(distance))],
        "distance_span_decades": distance_span_decades,
        "training_mean_bias_db": float(np.mean(residuals)),
        "training_mae_db": float(np.mean(np.abs(residuals))),
        "training_rmse_db": float(np.sqrt(np.mean(residuals**2))),
        "training_residual_sd_db": residual_sd_db,
        "training_residual_quantiles_db": {
            "p05": float(np.percentile(residuals, 5)),
            "p50": float(np.percentile(residuals, 50)),
            "p95": float(np.percentile(residuals, 95)),
        },
        "per_training_group": by_session,
        "parameter_uncertainty": {
            "method": "percentile cluster bootstrap; resample whole environment-height measurement files",
            "replicates_requested": int(bootstrap_replicates),
            "replicates_valid": len(boot_parameters),
            "seed": int(bootstrap_seed),
            "confidence_level": 0.95,
            "ci95": parameter_ci,
            "pl0_exponent_bootstrap_correlation": correlation if math.isfinite(correlation) else None,
            "limitation": "four training groups provide a small number of independent clusters; intervals are descriptive",
        },
        "identifiability": {
            "path_loss_distance_slope": "estimated within the public dataset measurement domain",
            "dataset_defined_pl_intercept": "estimated from published derived path-loss labels at the selected reference distance",
            "transmit_power_dbm": "not identifiable from these labels and metadata",
            "antenna_gains_dbi": "not identifiable from these labels and metadata",
            "receiver_sensitivity_dbm": "not identifiable; no receiver failure threshold labels",
            "shadowing_sigma_db": "not separately identifiable; residual spread combines environment, measurement and model error",
            "obstruction_loss_db": "not separately identifiable from three unbalanced environments",
        },
    }


def fit_fixed_slope_offset_model(
    records: Iterable[dict[str, Any]],
    fit_groups: Iterable[str],
    *,
    carrier_frequency_mhz: float,
    fixed_exponent: float,
    reference_distance_m: float = 1.0,
    bootstrap_replicates: int = 4000,
    bootstrap_seed: int = 150042,
) -> dict[str, Any]:
    """Estimate one dataset-specific offset; hold slope fixed to avoid weak identification."""
    rows = [dict(row) for row in records]
    groups = [str(value) for value in fit_groups]
    if len(groups) < 3 or len(set(groups)) != len(groups):
        raise ValueError("at least three distinct training groups are required")
    if carrier_frequency_mhz <= 0 or fixed_exponent <= 0 or reference_distance_m <= 0:
        raise ValueError("frequency, fixed exponent and reference distance must be positive")
    by_group = {group: [row for row in rows if str(row.get("session_id")) == group] for group in groups}
    missing = [group for group, values in by_group.items() if not values]
    if missing:
        raise ValueError(f"training groups have no rows: {missing}")
    pl0_free_space = free_space_path_loss_db(carrier_frequency_mhz, reference_distance_m)
    group_offsets: dict[str, float] = {}
    training_rows = [row for group in groups for row in by_group[group]]
    distance, response = _arrays(training_rows)
    for group, group_rows in by_group.items():
        group_distance, group_response = _arrays(group_rows)
        reference_prediction = predict_path_loss(
            group_distance,
            pl0_db=pl0_free_space,
            exponent=fixed_exponent,
            reference_distance_m=reference_distance_m,
        )
        group_offsets[group] = float(np.mean(group_response - reference_prediction))
    offset_db = float(np.mean(list(group_offsets.values())))
    pl0_db = pl0_free_space + offset_db
    prediction = predict_path_loss(
        distance,
        pl0_db=pl0_db,
        exponent=fixed_exponent,
        reference_distance_m=reference_distance_m,
    )
    residuals = prediction - response
    rng = np.random.default_rng(int(bootstrap_seed))
    bootstrap_offsets = [
        float(np.mean(rng.choice(list(group_offsets.values()), size=len(groups), replace=True)))
        for _ in range(int(bootstrap_replicates))
    ]
    bootstrap_pl0 = [pl0_free_space + value for value in bootstrap_offsets]
    residual_sd_db = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else None
    distance_span_decades = float(
        np.log10(np.maximum(distance, reference_distance_m) / reference_distance_m).max()
        - np.log10(np.maximum(distance, reference_distance_m) / reference_distance_m).min()
    )
    per_group = {}
    for group, group_rows in by_group.items():
        group_distance, group_response = _arrays(group_rows)
        group_residual = predict_path_loss(
            group_distance,
            pl0_db=pl0_db,
            exponent=fixed_exponent,
            reference_distance_m=reference_distance_m,
        ) - group_response
        per_group[group] = {
            "sample_count": len(group_rows),
            "fitted_offset_db_before_equal_group_average": group_offsets[group],
            "mean_bias_db": float(np.mean(group_residual)),
            "mae_db": float(np.mean(np.abs(group_residual))),
            "rmse_db": float(np.sqrt(np.mean(group_residual**2))),
        }
    return {
        "model_id": "phase15_public_a2g_offset_fit_v2",
        "equation": "PL(d) = FSPL(f,d0) + 10*n_fixed*log10(max(d,d0)/d0) + delta_PL_dataset",
        "reference_distance_m": reference_distance_m,
        "carrier_frequency_mhz": carrier_frequency_mhz,
        "free_space_pl0_db": pl0_free_space,
        "dataset_offset_db": offset_db,
        "pl0_db_at_reference_distance": pl0_db,
        "path_loss_exponent": fixed_exponent,
        "path_loss_exponent_status": "fixed_phase14_project_assumption_not_estimated_from_measurements",
        "estimated_parameter_count": 1,
        "estimated_parameters": ["dataset_offset_db"],
        "training_sample_count": len(training_rows),
        "training_group_count": len(groups),
        "training_groups": groups,
        "distance_range_m": [float(np.min(distance)), float(np.max(distance))],
        "distance_span_decades": distance_span_decades,
        "training_mean_bias_db": float(np.mean(residuals)),
        "training_mae_db": float(np.mean(np.abs(residuals))),
        "training_rmse_db": float(np.sqrt(np.mean(residuals**2))),
        "training_residual_sd_db": residual_sd_db,
        "training_residual_quantiles_db": {
            "p05": float(np.percentile(residuals, 5)),
            "p50": float(np.percentile(residuals, 50)),
            "p95": float(np.percentile(residuals, 95)),
        },
        "per_training_group": per_group,
        "parameter_uncertainty": {
            "method": "percentile cluster bootstrap over whole training measurement groups",
            "replicates_requested": int(bootstrap_replicates),
            "replicates_valid": len(bootstrap_offsets),
            "seed": int(bootstrap_seed),
            "confidence_level": 0.95,
            "ci95": {
                "dataset_offset_db": _percentile_interval(bootstrap_offsets),
                "pl0_db_at_reference_distance": _percentile_interval(bootstrap_pl0),
            },
            "limitation": "four training groups provide few independent clusters; the interval does not include unreported measurement uncertainty",
        },
        "identifiability": {
            "dataset_specific_offset": "estimated from published derived path-loss labels with equal weight per training group",
            "path_loss_exponent": "not estimated because the training distance range is only about half a decade and is confounded with environment/altitude groups; kept fixed at the Phase 14 assumption",
            "transmit_power_dbm": "not identifiable from these labels and metadata",
            "antenna_gains_dbi": "not identifiable from these labels and metadata",
            "receiver_sensitivity_dbm": "not identifiable; no receiver failure threshold labels",
            "shadowing_sigma_db": "not separately identifiable; residual spread combines environment, measurement and model error",
            "obstruction_loss_db": "not separately identifiable from these grouped environments",
        },
    }
def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float | int | dict[str, float]]:
    residual = predicted - observed
    return {
        "sample_count": int(len(observed)),
        "mae_db": float(np.mean(np.abs(residual))),
        "rmse_db": float(np.sqrt(np.mean(residual**2))),
        "mean_bias_db": float(np.mean(residual)),
        "residual_sd_db": float(np.std(residual, ddof=1)) if len(residual) > 1 else 0.0,
        "residual_quantiles_db": {
            "p05": float(np.percentile(residual, 5)),
            "p50": float(np.percentile(residual, 50)),
            "p95": float(np.percentile(residual, 95)),
        },
    }


def _metrics_for_rows(rows: list[dict[str, Any]], predictor) -> dict[str, Any]:
    distance, observed = _arrays(rows)
    return _metrics(observed, np.asarray(predictor(distance), dtype=float))


def _cluster_bootstrap_metric_intervals(
    rows_by_group: dict[str, list[dict[str, Any]]],
    predictor,
    *,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    groups = list(rows_by_group)
    if not groups:
        return {"group_count": 0, "ci95": None, "warning": "no independent holdout groups"}
    rng = np.random.default_rng(seed)
    boot: dict[str, list[float]] = {key: [] for key in ("mae_db", "rmse_db", "mean_bias_db")}
    for _ in range(replicates):
        sampled = rng.choice(groups, size=len(groups), replace=True).tolist()
        sample_rows = [row for group in sampled for row in rows_by_group[group]]
        metrics = _metrics_for_rows(sample_rows, predictor)
        for key in boot:
            boot[key].append(float(metrics[key]))
    return {
        "method": "resample whole environment-height measurement files",
        "group_count": len(groups),
        "replicates": replicates,
        "seed": seed,
        "confidence_level": 0.95,
        "ci95": {key: _percentile_interval(values) for key, values in boot.items()},
        "warning": "only two independent holdout groups; percentile intervals are descriptive and have low resolution" if len(groups) < 5 else None,
    }


def evaluate_independent_holdout(
    records: Iterable[dict[str, Any]],
    holdout_groups: Iterable[str],
    *,
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    bootstrap_replicates: int = 4000,
    bootstrap_seed: int = 150043,
) -> dict[str, Any]:
    rows = [dict(row) for row in records]
    holdout = [str(value) for value in holdout_groups]
    by_group = {group: [row for row in rows if str(row.get("session_id")) == group] for group in holdout}
    if any(not values for values in by_group.values()) or len(set(holdout)) != len(holdout):
        raise ValueError("holdout groups must be unique and present")
    test_rows = [row for group in holdout for row in by_group[group]]
    test_distance, observed = _arrays(test_rows)
    d0 = float(candidate["reference_distance_m"])
    candidate_predictor = lambda distances: predict_path_loss(
        distances,
        pl0_db=float(candidate["pl0_db_at_reference_distance"]),
        exponent=float(candidate["path_loss_exponent"]),
        reference_distance_m=d0,
    )
    baseline_predictor = lambda distances: predict_path_loss(
        distances,
        pl0_db=float(baseline["pl0_db_at_reference_distance"]),
        exponent=float(baseline["path_loss_exponent"]),
        reference_distance_m=float(baseline["reference_distance_m"]),
    )
    candidate_prediction = candidate_predictor(test_distance)
    baseline_prediction = baseline_predictor(test_distance)
    candidate_metrics = _metrics(observed, candidate_prediction)
    baseline_metrics = _metrics(observed, baseline_prediction)
    per_group: dict[str, Any] = {}
    group_mae_differences: list[float] = []
    for group, group_rows in by_group.items():
        candidate_group = _metrics_for_rows(group_rows, candidate_predictor)
        baseline_group = _metrics_for_rows(group_rows, baseline_predictor)
        delta = float(candidate_group["mae_db"] - baseline_group["mae_db"])
        group_mae_differences.append(delta)
        per_group[group] = {
            "sample_count": len(group_rows),
            "candidate": candidate_group,
            "phase14_baseline": baseline_group,
            "candidate_minus_phase14_mae_db": delta,
        }
    rng = np.random.default_rng(int(bootstrap_seed))
    delta_boot = []
    for _ in range(int(bootstrap_replicates)):
        sampled = rng.choice(holdout, size=len(holdout), replace=True).tolist()
        candidate_mae, baseline_mae = [], []
        for group in sampled:
            candidate_mae.append(float(_metrics_for_rows(by_group[group], candidate_predictor)["mae_db"]))
            baseline_mae.append(float(_metrics_for_rows(by_group[group], baseline_predictor)["mae_db"]))
        delta_boot.append(float(np.mean(candidate_mae) - np.mean(baseline_mae)))
    group_std = float(np.std(group_mae_differences, ddof=1)) if len(group_mae_differences) > 1 else None
    effect_size = (
        float(np.mean(group_mae_differences) / group_std)
        if group_std is not None and group_std > 0
        else None
    )
    return {
        "status": "EVALUATED",
        "holdout_groups": holdout,
        "holdout_group_count": len(holdout),
        "sample_count": len(test_rows),
        "candidate_model_id": candidate.get("model_id"),
        "baseline_model_id": baseline.get("model_id"),
        "metrics": {"candidate": candidate_metrics, "phase14_baseline": baseline_metrics},
        "candidate_minus_phase14_mae_db": float(np.mean(group_mae_differences)),
        "paired_group_mae_differences_db": group_mae_differences,
        "paired_cohen_dz_by_holdout_group": effect_size,
        "paired_mae_difference_ci95_cluster_bootstrap_db": _percentile_interval(delta_boot),
        "candidate_error_ci95_cluster_bootstrap": _cluster_bootstrap_metric_intervals(
            by_group,
            candidate_predictor,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed,
        ),
        "baseline_error_ci95_cluster_bootstrap": _cluster_bootstrap_metric_intervals(
            by_group,
            baseline_predictor,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed + 1,
        ),
        "per_holdout_group": per_group,
        "distance_bins_m": [0, 50, 100, 200, 500, None],
        "distance_bin_metrics": _distance_bin_metrics(test_rows, candidate_predictor),
        "acceptance": {
            "measurement_uncertainty_documented": all(
                row.get("measurement_uncertainty_db") not in (None, "") for row in test_rows
            ),
            "criterion": "Only claim model improvement if candidate MAE improves over the exact Phase 14 baseline with a cluster-level 95% interval wholly below zero and the improvement exceeds documented measurement uncertainty.",
            "decision": "NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING" if not all(
                row.get("measurement_uncertainty_db") not in (None, "") for row in test_rows
            ) else "REVIEW_PAIRED_INTERVAL_AND_UNCERTAINTY",
            "warning": "two holdout environment-height groups do not support broad generalization claims",
        },
        "interpretation_scope": "public 3.6 GHz A2G dataset only; not a project-device calibration or city-network validation",
    }


def evaluate_holdout_baselines(
    records: Iterable[dict[str, Any]],
    holdout_groups: Iterable[str],
    *,
    candidate: dict[str, Any],
    baselines: dict[str, dict[str, Any]],
    bootstrap_replicates: int = 4000,
    bootstrap_seed: int = 150043,
) -> dict[str, Any]:
    """Compare a candidate with multiple fixed baselines on identical holdout groups."""
    rows = [dict(row) for row in records]
    holdout = [str(value) for value in holdout_groups]
    if not baselines:
        raise ValueError("at least one baseline is required")
    by_group = {group: [row for row in rows if str(row.get("session_id")) == group] for group in holdout}
    if any(not values for values in by_group.values()) or len(set(holdout)) != len(holdout):
        raise ValueError("holdout groups must be unique and present")
    test_rows = [row for group in holdout for row in by_group[group]]
    distance, observed = _arrays(test_rows)
    reference_distance = float(candidate["reference_distance_m"])
    candidate_predictor = lambda values: predict_path_loss(
        values,
        pl0_db=float(candidate["pl0_db_at_reference_distance"]),
        exponent=float(candidate["path_loss_exponent"]),
        reference_distance_m=reference_distance,
    )
    predictors = {
        name: lambda values, model=model: predict_path_loss(
            values,
            pl0_db=float(model["pl0_db_at_reference_distance"]),
            exponent=float(model["path_loss_exponent"]),
            reference_distance_m=float(model["reference_distance_m"]),
        )
        for name, model in baselines.items()
    }
    candidate_metrics = _metrics(observed, candidate_predictor(distance))
    baseline_metrics = {name: _metrics(observed, predictor(distance)) for name, predictor in predictors.items()}
    per_group: dict[str, Any] = {}
    group_deltas: dict[str, list[float]] = {name: [] for name in baselines}
    for group, group_rows in by_group.items():
        candidate_group = _metrics_for_rows(group_rows, candidate_predictor)
        comparison_metrics = {}
        for name, predictor in predictors.items():
            baseline_group = _metrics_for_rows(group_rows, predictor)
            delta = float(candidate_group["mae_db"] - baseline_group["mae_db"])
            group_deltas[name].append(delta)
            comparison_metrics[name] = {
                "baseline": baseline_group,
                "candidate_minus_baseline_mae_db": delta,
            }
        per_group[group] = {
            "sample_count": len(group_rows),
            "candidate": candidate_group,
            "comparisons": comparison_metrics,
        }

    comparisons: dict[str, Any] = {}
    for offset, (name, predictor) in enumerate(predictors.items()):
        deltas = group_deltas[name]
        delta_std = float(np.std(deltas, ddof=1)) if len(deltas) > 1 else None
        rng = np.random.default_rng(int(bootstrap_seed) + offset)
        delta_boot = []
        for _ in range(int(bootstrap_replicates)):
            sampled = rng.choice(holdout, size=len(holdout), replace=True).tolist()
            candidate_mae = [float(_metrics_for_rows(by_group[group], candidate_predictor)["mae_db"]) for group in sampled]
            baseline_mae = [float(_metrics_for_rows(by_group[group], predictor)["mae_db"]) for group in sampled]
            delta_boot.append(float(np.mean(candidate_mae) - np.mean(baseline_mae)))
        comparisons[name] = {
            "baseline_model_id": baselines[name].get("model_id"),
            "baseline_metrics": baseline_metrics[name],
            "candidate_minus_baseline_mae_db": float(np.mean(deltas)),
            "paired_group_mae_differences_db": deltas,
            "paired_cohen_dz_by_holdout_group": float(np.mean(deltas) / delta_std) if delta_std is not None and delta_std > 0 else None,
            "paired_mae_difference_ci95_cluster_bootstrap_db": _percentile_interval(delta_boot),
            "baseline_error_ci95_cluster_bootstrap": _cluster_bootstrap_metric_intervals(
                by_group,
                predictor,
                replicates=bootstrap_replicates,
                seed=int(bootstrap_seed) + offset + 1,
            ),
        }
    measurement_uncertainty_documented = all(
        row.get("measurement_uncertainty_db") not in (None, "") for row in test_rows
    )
    return {
        "status": "EVALUATED",
        "holdout_groups": holdout,
        "holdout_group_count": len(holdout),
        "sample_count": len(test_rows),
        "candidate_model_id": candidate.get("model_id"),
        "candidate_metrics": candidate_metrics,
        "comparisons": comparisons,
        "per_holdout_group": per_group,
        "distance_bins_m": [0, 50, 100, 200, 500, None],
        "distance_bin_metrics": _distance_bin_metrics(test_rows, candidate_predictor),
        "candidate_error_ci95_cluster_bootstrap": _cluster_bootstrap_metric_intervals(
            by_group,
            candidate_predictor,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed,
        ),
        "acceptance": {
            "measurement_uncertainty_documented": measurement_uncertainty_documented,
            "criterion": "Improvement requires a candidate MAE reduction against the exact Phase 14 model with a group-bootstrap 95% interval below zero and an improvement larger than documented measurement uncertainty.",
            "decision": "NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING" if not measurement_uncertainty_documented else "REVIEW_PAIRED_INTERVAL_AND_UNCERTAINTY",
            "warning": "only two independent holdout groups; bootstrap intervals are descriptive and cannot establish broad environmental generalization",
        },
        "interpretation_scope": "public 3.6 GHz A2G dataset only; not a project-device calibration or city-network validation",
    }


def _distance_bin_metrics(rows: list[dict[str, Any]], predictor) -> list[dict[str, Any]]:
    edges = [0.0, 50.0, 100.0, 200.0, 500.0, math.inf]
    labels = ["[0,50)", "[50,100)", "[100,200)", "[200,500)", "[500,+inf)"]
    result = []
    for low, high, label in zip(edges[:-1], edges[1:], labels, strict=True):
        subset = [row for row in rows if low <= float(row["distance_m"]) < high]
        result.append({
            "distance_bin_m": label,
            "sample_count": len(subset),
            "metrics": _metrics_for_rows(subset, predictor) if subset else None,
        })
    return result
