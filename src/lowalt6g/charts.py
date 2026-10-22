"""Publication-style comparison plots built from actual benchmark output."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from .experiment import STRATEGY_ORDER
from .dynamic_simulation import SeedExperiment


COLORS = ("#7B8794", "#3977B7", "#1D9A78")
SHORT_LABELS = ("A: no recovery", "B: static grid", "C: rolling MPC")
PHASE4_COLORS = ("#7B8794", "#3977B7", "#1D9A78", "#D65B3D")
PHASE4_LABELS = ("A: no UAV", "B: static grid", "C: weighted MPC", "D: rescue-priority MPC")
PHASE5_COLORS = ("#7B8794", "#3977B7", "#D69C35", "#1D9A78", "#D65B3D")
PHASE5_LABELS = {
    "A_no_recovery": "A no UAV",
    "B_phase1_static_grid": "B historical grid",
    "Bprime_static_grid_shared_safety": "B' shared safety",
    "C_rolling_horizon_mpc": "C rolling MPC",
    "D_lexicographic_rescue_priority": "D rescue priority",
}


def write_comparison_charts(
    result: dict[str, Any],
    experiments: list[SeedExperiment],
    output_dir: str | Path,
    *,
    include_latency_distribution: bool = True,
) -> list[Path]:
    """Write a multi-metric dashboard and conditional latency distribution."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    aggregate = result["aggregate"]
    plots: list[Path] = []

    specs = (
        ("Connection success", "user_connection_success_rate", "rate", "metrics"),
        ("Rescue service success", "rescue_user_service_success_rate", "rate", "metrics"),
        ("Recovery success across seeds", "success_rate", "rate", "recovery"),
        ("Recovery time (recovered runs only)", "recovered_only_time_s", "recovery", "recovery"),
        ("Mean latency | successful samples", "average_latency_ms", "latency", "latency"),
        ("Mean per-seed P95 latency", "p95_latency_ms", "p95", "latency"),
        ("Drone energy consumed (Wh)", "drone_energy_consumed_wh", "energy", "metrics"),
        ("Decision compute time per run (ms)", "algorithm_decision_total_ms", "compute", "metrics"),
    )
    fig, axes = plt.subplots(2, 4, figsize=(17, 8.4), constrained_layout=True)
    for axis, (title, metric, source, category) in zip(axes.flat, specs, strict=True):
        values: list[float | None] = []
        errors: list[float] = []
        for strategy_id in STRATEGY_ORDER:
            group = aggregate[strategy_id]
            if category == "metrics":
                summary = group["metrics"][metric]
            elif category == "recovery":
                summary = group["network_recovery"][metric]
            else:
                summary = group["latency_conditioned_on_success"][
                    "per_seed_p95_ms" if source == "p95" else "per_seed_average_ms"
                ]
            if source == "rate":
                if category == "recovery":
                    value = group["network_recovery"]["success_rate"]
                    error = 0.0
                else:
                    value = summary["mean"]
                    error = summary["sample_sd"] or 0.0
            elif source in {"latency", "p95"}:
                value = summary["mean"]
                error = summary["sample_sd"] or 0.0
            else:
                value = summary["mean"]
                error = summary["sample_sd"] or 0.0
            values.append(float(value) if value is not None else None)
            errors.append(float(error))

        positions = list(range(len(STRATEGY_ORDER)))
        for index, (position, value, error, color) in enumerate(zip(positions, values, errors, COLORS, strict=True)):
            if value is None:
                axis.text(position, 0.04, "n/a", ha="center", va="bottom", fontsize=8, color="#666666")
                continue
            axis.bar(position, value, color=color, width=0.62, zorder=3)
            if error > 0:
                axis.errorbar(position, value, yerr=error, color="#263238", capsize=3, linewidth=1, zorder=4)
            if source == "rate":
                annotation = f"{value:.1%}"
            else:
                annotation = f"{value:.1f}"
            axis.text(position, value + max(value * 0.035, 0.01), annotation, ha="center", va="bottom", fontsize=8)
        axis.set_title(title, fontsize=10)
        axis.set_xticks(positions, ["A", "B", "C"])
        axis.grid(axis="y", color="#d9dfe5", linewidth=0.7, zorder=0)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_axisbelow(True)
        if source == "rate":
            axis.set_ylim(0, 1.12)
            axis.set_ylabel("fraction")
        else:
            maximum = max((value + error for value, error in zip(values, errors) if value is not None), default=1.0)
            axis.set_ylim(0, max(1.0, maximum * 1.2))

    seed_count = result["reproducibility"]["seed_count"]
    fig.suptitle(f"Matched dynamic network simulation — {seed_count} fixed seeds", fontsize=15, fontweight="bold")
    fig.text(
        0.5,
        -0.015,
        "Bars: equal-weight seed means (± sample SD where applicable). Recovery time uses recovered runs only; latency uses successful user-time samples.",
        ha="center",
        fontsize=9,
        color="#424b54",
    )
    for extension in ("png", "svg"):
        path = destination / f"phase2_strategy_comparison.{extension}"
        fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
        if extension == "svg":
            _strip_svg_trailing_whitespace(path)
        plots.append(path)
    plt.close(fig)

    if not include_latency_distribution:
        return plots

    samples_by_strategy = {
        strategy_id: [
            latency
            for experiment in experiments
            for latency in experiment.strategies[strategy_id].latency_samples_ms
        ]
        for strategy_id in STRATEGY_ORDER
    }
    fig, axis = plt.subplots(figsize=(8.6, 5.6), constrained_layout=True)
    distributions = [samples_by_strategy[key] for key in STRATEGY_ORDER]
    box = axis.boxplot(
        distributions,
        patch_artist=True,
        showfliers=False,
        tick_labels=[
            f"{label}\n(n={len(distributions[index]):,})"
            for index, label in enumerate(SHORT_LABELS)
        ],
        whis=(5, 95),
        medianprops={"color": "#17202a", "linewidth": 1.5},
        whiskerprops={"color": "#566573"},
        capprops={"color": "#566573"},
    )
    for patch, color in zip(box["boxes"], COLORS, strict=True):
        patch.set_facecolor(color)
        patch.set_alpha(0.78)
    axis.set_title("End-to-end latency on successful user-time samples", fontsize=12, fontweight="bold")
    axis.set_ylabel("latency (ms)")
    axis.grid(axis="y", color="#d9dfe5", linewidth=0.7)
    axis.spines[["top", "right"]].set_visible(False)
    axis.text(
        0.99,
        0.98,
        "Policy sample sets differ; distributions are conditional and unpaired. Whiskers: 5th–95th percentile.",
        transform=axis.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        color="#424b54",
    )
    for extension in ("png", "svg"):
        path = destination / f"phase2_latency_distribution.{extension}"
        fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
        if extension == "svg":
            _strip_svg_trailing_whitespace(path)
        plots.append(path)
    plt.close(fig)
    return plots


def write_phase4_comparison_chart(
    result: dict[str, Any],
    output_dir: str | Path,
) -> list[Path]:
    """Write held-out A/B/C/D plots with seed-level 95% confidence intervals."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    aggregate = result["aggregate"]
    strategy_order = result["strategy_order"]
    if len(strategy_order) != 4:
        raise ValueError("Phase 4 comparison chart requires A/B/C/D strategy results")
    short = ("A", "B", "C", "D")
    specs = (
        ("All-user service", "user_connection_success_rate", "metrics", True),
        ("Rescue service", "rescue_user_service_success_rate", "metrics", True),
        ("First full rescue recovery rate", "success_rate", "network_recovery", True),
        ("Sustained recovery rate (30 s)", "success_rate", "sustained_network_recovery_30s", True),
        ("Recovery time (s, recovered only)", "recovered_only_time_s", "network_recovery", False),
        ("Conditional mean latency (ms/seed)", "average_latency_ms", "latency_conditioned_on_success", False),
        ("UAV energy (Wh/run)", "drone_energy_consumed_wh", "metrics", False),
        ("Decision compute (ms/run)", "algorithm_decision_total_ms", "metrics", False),
    )
    fig, axes = plt.subplots(2, 4, figsize=(17, 8.8), constrained_layout=True)
    for axis, (title, metric, group_name, rate) in zip(axes.flat, specs, strict=True):
        values: list[float | None] = []
        lower: list[float] = []
        upper: list[float] = []
        for strategy_id in strategy_order:
            group = aggregate[strategy_id]
            if group_name == "metrics":
                summary = group["metrics"][metric]
            elif group_name == "latency_conditioned_on_success":
                summary = group[group_name]["per_seed_average_ms"]
            else:
                summary = group[group_name][metric]
            if isinstance(summary, dict):
                value = summary.get("mean", summary)
                ci = summary.get("mean_ci95_t")
            else:
                value = summary
                ci = None
            if rate and group_name in {"network_recovery", "sustained_network_recovery_30s"}:
                value = group[group_name]["success_rate"]
                ci = group["metrics"][
                    "network_recovery_success" if group_name == "network_recovery" else "sustained_rescue_recovery_success"
                ]["ci95_wilson"]
            values.append(float(value) if value is not None else None)
            if ci:
                lower.append(float(value) - float(ci[0]))
                upper.append(float(ci[1]) - float(value))
            else:
                lower.append(0.0)
                upper.append(0.0)

        x = list(range(4))
        bars = [value if value is not None else 0.0 for value in values]
        axis.bar(x, bars, color=PHASE4_COLORS, width=0.62, zorder=3)
        if any(error > 0 for error in lower + upper):
            axis.errorbar(x, bars, yerr=[lower, upper], fmt="none", color="#263238", capsize=3, linewidth=1, zorder=4)
        for i, value in enumerate(values):
            if value is None:
                axis.text(i, 0.02, "n/a", ha="center", va="bottom", fontsize=8)
            else:
                label = f"{value:.1%}" if rate else f"{value:.1f}"
                axis.text(i, value + max(abs(value) * 0.035, 0.01), label, ha="center", va="bottom", fontsize=8)
        axis.set_title(title, fontsize=9.5)
        axis.set_xticks(x, short)
        axis.grid(axis="y", color="#d9dfe5", linewidth=0.7, zorder=0)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_axisbelow(True)
        if rate:
            axis.set_ylim(0, 1.12)
            axis.set_ylabel("fraction")
        else:
            max_bound = max((value + up for value, up in zip(bars, upper, strict=True)), default=1.0)
            axis.set_ylim(0, max(1.0, max_bound * 1.2))

    seed_count = result["reproducibility"]["seed_count"]
    fig.suptitle(
        f"Held-out matched simulation — {seed_count} seeds (95% CI: Student-t / Wilson)",
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.5,
        -0.015,
        "Recovery time is conditional on recovery; latency is conditional on each policy's own successful user-time samples.",
        ha="center",
        fontsize=9,
        color="#424b54",
    )
    paths: list[Path] = []
    for extension in ("png", "svg"):
        path = destination / f"phase4_validation_metrics.{extension}"
        fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
        if extension == "svg":
            _strip_svg_trailing_whitespace(path)
        paths.append(path)
    plt.close(fig)

    experiments = result["seed_experiments"]
    latency_by_strategy = {
        strategy_id: [
            sample
            for experiment in experiments
            for sample in experiment["strategies"][strategy_id]["latency_samples_ms"]
        ]
        for strategy_id in strategy_order
    }
    fig, axis = plt.subplots(figsize=(9, 5.8), constrained_layout=True)
    distributions = [latency_by_strategy[strategy_id] for strategy_id in strategy_order]
    box = axis.boxplot(
        distributions,
        patch_artist=True,
        showfliers=False,
        tick_labels=[f"{label}\n(n={len(distributions[i]):,})" for i, label in enumerate(PHASE4_LABELS)],
        whis=(5, 95),
        medianprops={"color": "#17202a", "linewidth": 1.5},
        whiskerprops={"color": "#566573"},
        capprops={"color": "#566573"},
    )
    for patch, color in zip(box["boxes"], PHASE4_COLORS, strict=True):
        patch.set_facecolor(color)
        patch.set_alpha(0.78)
    axis.set_title("Conditional latency on raw successful user-time samples", fontsize=12, fontweight="bold")
    axis.set_ylabel("latency (ms)")
    axis.grid(axis="y", color="#d9dfe5", linewidth=0.7)
    axis.spines[["top", "right"]].set_visible(False)
    axis.text(
        0.99,
        0.98,
        "Policy sample sets differ; distributions are conditional and unpaired. Whiskers: 5th–95th percentile.",
        transform=axis.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        color="#424b54",
    )
    for extension in ("png", "svg"):
        path = destination / f"phase4_validation_latency.{extension}"
        fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
        if extension == "svg":
            _strip_svg_trailing_whitespace(path)
        paths.append(path)
    plt.close(fig)
    return paths


def write_phase5_comparison_charts(
    scenario_results: dict[str, dict[str, Any]],
    output_dir: str | Path,
) -> list[Path]:
    """Plot held-out multi-hazard results with seed-level confidence intervals."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    scenario_ids = list(scenario_results)
    if not scenario_ids:
        raise ValueError("Phase 5 chart requires at least one validation scenario")
    strategy_order = scenario_results[scenario_ids[0]]["strategy_order"]
    if len(strategy_order) != 5:
        raise ValueError("Phase 5 chart requires A/B/B'/C/D strategy results")

    reliability_specs = (
        ("Rescue service rate", "rescue_user_service_success_rate", "metric", True),
        ("Sustained all-rescue recovery (30 s)", "sustained_rescue_recovery_success", "sustained", True),
        ("Recovery or censoring time", "recovery_or_censoring_time_s", "restricted", False),
        ("Recovered-only time (n recovered / 20)", "recovered_only_time_s", "recovered", False),
    )
    cost_specs = (
        ("Ground-only rescue service rate", "ground_only_rescue_service_success_rate", "metric", True),
        ("UAV extra rescue service (user-hours)", "drone_extra_rescue_user_seconds", "metric_hours", False),
        ("UAV-relayed rescue service (user-hours)", "drone_rescue_user_seconds", "metric_hours", False),
        ("Conditional mean latency (ms/seed)", "per_seed_average_ms", "latency_mean", False),
        ("Conditional P95 latency (ms/seed)", "per_seed_p95_ms", "latency_p95", False),
        ("UAV energy consumed (Wh/run)", "drone_energy_consumed_wh", "metric", False),
        ("Energy per UAV rescue-user-hour (Wh)", "drone_energy_wh_per_rescue_user_hour", "metric", False),
        ("Decision compute per run (ms)", "algorithm_decision_total_ms", "metric", False),
    )

    def draw_figure(specs, filename: str, rows: int, columns: int, caption: str) -> list[Path]:
        fig, axes = plt.subplots(rows, columns, figsize=(18, 4.4 * rows), constrained_layout=True)
        flat_axes = list(axes.flat) if hasattr(axes, "flat") else [axes]
        for axis, (title, key, kind, is_rate) in zip(flat_axes, specs, strict=False):
            centers = list(range(len(scenario_ids)))
            group_width = 0.78
            bar_width = group_width / len(strategy_order)
            top_bound = 0.0
            for strategy_index, strategy_id in enumerate(strategy_order):
                means: list[float] = []
                lower: list[float] = []
                upper: list[float] = []
                for scenario_id in scenario_ids:
                    aggregate = scenario_results[scenario_id]["aggregate"][strategy_id]
                    summary: dict[str, Any] | None
                    ci: list[float] | None = None
                    if kind == "metric":
                        summary = aggregate["metrics"][key]
                        ci = summary.get("mean_ci95_t")
                    elif kind == "metric_hours":
                        summary = aggregate["metrics"][key]
                        ci = summary.get("mean_ci95_t")
                    elif kind == "sustained":
                        summary = aggregate["metrics"][key]
                        ci = summary.get("ci95_wilson")
                    elif kind == "restricted":
                        summary = aggregate["network_recovery"][key]
                        ci = summary.get("mean_ci95_t")
                    elif kind == "recovered":
                        summary = aggregate["network_recovery"][key]
                        ci = summary.get("mean_ci95_t")
                    elif kind == "latency_mean":
                        summary = aggregate["latency_conditioned_on_success"]["per_seed_average_ms"]
                        ci = summary.get("mean_ci95_t")
                    else:
                        summary = aggregate["latency_conditioned_on_success"]["per_seed_p95_ms"]
                        ci = summary.get("mean_ci95_t")
                    value = summary.get("mean") if summary is not None else None
                    if value is None:
                        means.append(float("nan"))
                        lower.append(0.0)
                        upper.append(0.0)
                        continue
                    value = float(value)
                    if kind == "metric_hours":
                        value /= 3600.0
                        ci = [float(bound) / 3600.0 for bound in ci] if ci else None
                    means.append(value)
                    if ci:
                        lower.append(max(0.0, value - float(ci[0])))
                        upper.append(max(0.0, float(ci[1]) - value))
                    else:
                        lower.append(0.0)
                        upper.append(0.0)
                    top_bound = max(top_bound, value + upper[-1])

                offsets = [
                    center - group_width / 2.0 + (strategy_index + 0.5) * bar_width
                    for center in centers
                ]
                for point_index, (x, value) in enumerate(zip(offsets, means, strict=True)):
                    if not math.isfinite(value):
                        continue
                    axis.bar(
                        x,
                        value,
                        width=bar_width * 0.88,
                        color=PHASE5_COLORS[strategy_index],
                        label=None,
                        zorder=3,
                    )
                    if lower[point_index] > 0 or upper[point_index] > 0:
                        axis.errorbar(
                            x,
                            value,
                            yerr=[[lower[point_index]], [upper[point_index]]],
                            fmt="none",
                            color="#263238",
                            capsize=2,
                            linewidth=0.8,
                            zorder=4,
                        )
                    if kind == "recovered":
                        recovery = scenario_results[scenario_ids[point_index]]["aggregate"][strategy_id]["network_recovery"]
                        text_value = f"{recovery['recovered_runs']}/20"
                        axis.text(x, value + max(abs(value) * 0.025, 0.02), text_value, ha="center", va="bottom", fontsize=6, rotation=90)
            axis.set_title(title, fontsize=10)
            axis.set_xticks(centers, [scene.replace("_", "\n") for scene in scenario_ids], fontsize=8)
            axis.grid(axis="y", color="#d9dfe5", linewidth=0.7, zorder=0)
            axis.spines[["top", "right"]].set_visible(False)
            axis.set_axisbelow(True)
            axis.set_ylabel("fraction" if is_rate else "hours" if kind == "metric_hours" else "value")
            axis.set_ylim(0, 1.12 if is_rate else max(1.0, top_bound * 1.25))
        for axis in flat_axes[len(specs):]:
            axis.remove()
        fig.legend(
            [Patch(facecolor=PHASE5_COLORS[index]) for index in range(len(strategy_order))],
            [PHASE5_LABELS[strategy_id] for strategy_id in strategy_order],
            loc="lower center",
            bbox_to_anchor=(0.5, -0.025),
            ncol=len(strategy_order),
            frameon=False,
        )
        fig.suptitle("Phase 5 held-out multi-hazard validation (95% intervals)", fontsize=15, fontweight="bold")
        fig.text(0.5, -0.06, caption, ha="center", fontsize=8, color="#424b54")
        paths: list[Path] = []
        for extension in ("png", "svg"):
            path = destination / f"{filename}.{extension}"
            fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
            if extension == "svg":
                _strip_svg_trailing_whitespace(path)
            paths.append(path)
        plt.close(fig)
        return paths

    return (
        draw_figure(
            reliability_specs,
            "phase5_reliability",
            2,
            2,
            "Unrecovered runs remain failures; the restricted time uses the horizon for censored runs, while recovered-only time is annotated with recovered/total counts.",
        )
        + draw_figure(
            cost_specs,
            "phase5_service_and_cost",
            2,
            4,
            "Latency is conditional on each policy's own successful user-time samples. Service time counts actual rescue-user paths routed via the UAV; intervals are across held-out seeds.",
        )
    )


def _strip_svg_trailing_whitespace(path: Path) -> None:
    """Keep generated vector artifacts clean in Git diffs without changing SVG geometry."""
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")
