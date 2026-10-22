"""Research plots generated only from Phase 8 raw per-seed records."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .phase8_experiments import BASELINE_ORDER, SCENARIO_ORDER, VARIANT_BY_ID
from .experiment import _stats


SCENE_LABELS = {
    "severe_persistent_faults": "Severe persistent",
    "dynamic_failures": "Dynamic failures",
    "high_mobility_rescue": "High mobility",
    "high_load_backhaul_limit": "High load / backhaul",
}
BASELINE_LABELS = {
    "B_phase1_static_grid": "B · static grid",
    "C_rolling_horizon_mpc": "C · rolling MPC",
    "D_lexicographic_rescue_priority": "D · rescue lexicographic",
}


def _run(row: dict[str, object], key: str) -> dict[str, object]:
    if key in row["baseline_strategy_runs"]:
        return row["baseline_strategy_runs"][key]
    return row["variant_runs"][key]


def _ci_errors(values: list[float]) -> tuple[float, float]:
    summary = _stats(values, include_ci=True)
    interval = summary["mean_ci95_t"]
    mean = float(summary["mean"])
    if interval is None:
        return (0.0, 0.0)
    return (max(0.0, mean - float(interval[0])), max(0.0, float(interval[1]) - mean))


def write_phase8_charts(raw_path: str | Path, output_dir: str | Path) -> list[Path]:
    raw_file = Path(raw_path)
    raw = json.loads(raw_file.read_text(encoding="utf-8"))
    if raw.get("phase") != "validation" or raw.get("status") != "complete":
        raise ValueError("plots require a complete, confirmatory Phase 8 validation raw file")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    records = raw["records"]
    variants = list(raw["variant_ids"])
    generated: list[Path] = []

    plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.22})
    fig, axes = plt.subplots(2, 2, figsize=(19, 11), constrained_layout=True)
    for axis, scene_id in zip(axes.flat, SCENARIO_ORDER, strict=True):
        rows = [row for row in records if row["scenario_id"] == scene_id]
        scene_variants = [variant for variant in variants if variant in VARIANT_BY_ID]
        means: list[float] = []
        lower: list[float] = []
        upper: list[float] = []
        labels: list[str] = []
        colors: list[str] = []
        for variant_id in scene_variants:
            algorithm = VARIANT_BY_ID[variant_id].algorithm
            parent = "C_rolling_horizon_mpc" if algorithm == "C" else "D_lexicographic_rescue_priority"
            differences = [
                float(_run(row, variant_id)["metrics"]["rescue_user_service_success_rate"])
                - float(_run(row, parent)["metrics"]["rescue_user_service_success_rate"])
                for row in rows
            ]
            stats = _stats(differences, include_ci=True)
            mean = float(stats["mean"]) * 100.0
            ci = stats["mean_ci95_t"]
            lo = max(0.0, mean - float(ci[0]) * 100.0) if ci else 0.0
            hi = max(0.0, float(ci[1]) * 100.0 - mean) if ci else 0.0
            means.append(mean)
            lower.append(lo)
            upper.append(hi)
            labels.append(variant_id.replace("C_", "C/").replace("D_", "D/"))
            colors.append("#bd3b2a" if algorithm == "C" else "#d18a31")
        positions = list(range(len(labels)))
        axis.bar(positions, means, color=colors, alpha=0.88, width=0.78)
        axis.errorbar(positions, means, yerr=[lower, upper], fmt="none", ecolor="#211c1b", capsize=2, linewidth=0.8)
        axis.axhline(0, color="#221e1d", linewidth=1)
        axis.set_title(SCENE_LABELS[scene_id], loc="left", fontweight="bold")
        axis.set_ylabel("Paired rescue-service difference vs parent (percentage points)")
        axis.set_xticks(positions, labels, rotation=70, ha="right", fontsize=7)
    fig.suptitle("Phase 8 confirmatory ablations · paired per-seed effects with 95% t intervals", fontsize=15, fontweight="bold")
    for suffix in ("png", "svg"):
        path = output / f"phase8_validation_ablation_effects.{suffix}"
        fig.savefig(path, dpi=180 if suffix == "png" else None, bbox_inches="tight")
        generated.append(path)
    plt.close(fig)

    strategy_ids = tuple(BASELINE_LABELS)
    rows_metrics = (
        ("rescue_user_service_success_rate", "Rescue service success (%)", 100.0),
        ("drone_energy_consumed_wh", "UAV energy (Wh)", 1.0),
        ("algorithm_decision_total_ms", "Decision compute (seconds/run)", 0.001),
    )
    fig, axes = plt.subplots(len(rows_metrics), len(SCENARIO_ORDER), figsize=(17, 10), constrained_layout=True)
    palette = ("#aa3024", "#ce6b28", "#447b86")
    for col, scene_id in enumerate(SCENARIO_ORDER):
        rows = [row for row in records if row["scenario_id"] == scene_id]
        for row_index, (metric, ylabel, scale) in enumerate(rows_metrics):
            axis = axes[row_index, col]
            means: list[float] = []
            errors: list[list[float]] = [[], []]
            for strategy_id in strategy_ids:
                values = [float(_run(row, strategy_id)["metrics"][metric]) * scale for row in rows]
                stats = _stats(values, include_ci=True)
                mean = float(stats["mean"])
                ci = stats["mean_ci95_t"]
                means.append(mean)
                errors[0].append(max(0.0, mean - float(ci[0])) if ci else 0.0)
                errors[1].append(max(0.0, float(ci[1]) - mean) if ci else 0.0)
            bars = axis.bar(range(len(strategy_ids)), means, color=palette, width=0.72)
            axis.errorbar(range(len(strategy_ids)), means, yerr=errors, fmt="none", ecolor="#211c1b", capsize=3, linewidth=0.9)
            axis.set_xticks(range(len(strategy_ids)), ["B", "C", "D"])
            axis.set_ylabel(ylabel if col == 0 else "")
            axis.set_title(SCENE_LABELS[scene_id], loc="left", fontweight="bold")
            for bar, value in zip(bars, means, strict=True):
                axis.annotate(f"{value:.2f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=7)
    fig.suptitle("B / C / D under matched held-out scenarios · mean ± 95% t interval", fontsize=15, fontweight="bold")
    for suffix in ("png", "svg"):
        path = output / f"phase8_validation_policy_comparison.{suffix}"
        fig.savefig(path, dpi=180 if suffix == "png" else None, bbox_inches="tight")
        generated.append(path)
    plt.close(fig)
    return generated
