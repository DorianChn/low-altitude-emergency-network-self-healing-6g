"""Create Phase 10 figures and an artifact integrity manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lowalt6g.experiment import _stats  # noqa: E402
from lowalt6g.phase10_experiments import _historical_hashes  # noqa: E402


SCENES = (
    ("severe_persistent_faults", "Severe"),
    ("dynamic_failures", "Dynamic"),
    ("high_mobility_rescue", "Mobile rescue"),
    ("high_load_backhaul_limit", "High load"),
)
POLICIES = (
    ("Bprime_static_grid_shared_safety_uav1", "B′ · 1 UAV", "#384152"),
    ("F_independent_greedy_uav2", "F · 2 UAV", "#e17b24"),
    ("G_centralized_coordination_uav2", "G · 2 UAV", "#b83a36"),
    ("F_independent_greedy_uav3", "F · 3 UAV", "#4e81a8"),
    ("G_centralized_coordination_uav3", "G · 3 UAV", "#4c8366"),
)


def main() -> None:
    summary_path = ROOT / "results/phase10_confirmation_summary.json"
    raw_path = ROOT / "results/phase10_confirmation_raw.json"
    protocol_path = ROOT / "configs/phase10/validation_protocol.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if raw["seed_count_total"] != 80 or raw["policy_run_count"] != 400:
        raise ValueError("confirmation result does not contain the frozen 80-seed / 400-run plan")
    if protocol["source_sha256"] != raw["phase10_source_sha256"]:
        raise ValueError("confirmation source hash differs from frozen protocol")
    current_history = _historical_hashes()
    if current_history != protocol["protected_phase1_to_phase9_sha256"]:
        raise ValueError("a protected Phase 1-9 artifact changed after the frozen protocol")

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "DejaVu Sans"],
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.labelcolor": "#313640",
            "text.color": "#252a32",
            "xtick.color": "#505761",
            "ytick.color": "#505761",
            "figure.facecolor": "white",
            "axes.facecolor": "#fbfbfa",
            "savefig.facecolor": "white",
        }
    )
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 9.5))
    _bar_panel(
        axes[0, 0], summary, "rescue_user_service_success_rate", "Rescue user service success", "%", percent=True
    )
    _bar_panel(
        axes[0, 1], summary, "first_full_recovery_success", "First full rescue recovery", "%", percent=True, binary=True
    )
    _bar_panel(
        axes[1, 0], summary, "uav_energy_total_wh", "Fleet energy consumed", "Wh"
    )
    _bar_panel(
        axes[1, 1], summary, "coordination_compute_total_ms", "Total planning compute per run", "ms"
    )
    axes[0, 0].set_ylim(0, 100)
    axes[0, 1].set_ylim(0, 105)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        frameon=False,
        ncol=5,
        fontsize=9,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.925),
    )
    fig.suptitle(
        "Phase 10 · Multi-UAV coordination under matched disaster traces",
        fontsize=17,
        fontweight="bold",
        y=0.985,
    )
    fig.text(
        0.01,
        0.018,
        "Bars show 20-seed means; whiskers show 95% CIs. Recovery successes retain failures in the denominator. "
        "B′ is a single-UAV reference; F/G comparisons at equal fleet size isolate the coordination-policy contrast. "
        "Abstract simulation; no RF interference or calibrated aircraft power model.",
        fontsize=8.5,
        color="#5e6570",
    )
    output_dir = ROOT / "plots/phase10"
    output_dir.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(top=0.84, bottom=0.105, left=0.07, right=0.98, hspace=0.32, wspace=0.1)
    png_path = output_dir / "confirmation_policy_comparison.png"
    svg_path = output_dir / "confirmation_policy_comparison.svg"
    fig.savefig(png_path, dpi=180, bbox_inches="tight")
    fig.savefig(svg_path, bbox_inches="tight")
    plt.close(fig)

    _plot_recovery_heatmap(summary, output_dir)
    _write_event_timeline(raw)
    _write_per_uav_energy_summary(raw)

    manifest_paths = [
        "configs/phase10/multi_uav_plan.json",
        "configs/phase10/validation_protocol.json",
        "results/phase10_development_raw.json",
        "results/phase10_development_summary.json",
        "results/phase10_confirmation_raw.json",
        "results/phase10_confirmation_summary.json",
        "plots/phase10/confirmation_policy_comparison.png",
        "plots/phase10/confirmation_policy_comparison.svg",
        "plots/phase10/confirmation_recovery_heatmap.png",
        "results/phase10_confirmation_event_timeline.json",
        "results/phase10_uav_energy_summary.json",
        "scripts/plot_phase10_results.py",
    ]
    for relative in (
        "PHASE10_MODEL_DESIGN.md",
        "PHASE10_REPORT.md",
        "DEVELOPMENT_LOG_PHASE10.md",
    ):
        if (ROOT / relative).is_file():
            manifest_paths.append(relative)
    manifest = {
        "schema_version": "1.0",
        "phase": "phase10_multi_uav_coordination",
        "confirmation_seed_count": raw["seed_count_total"],
        "confirmation_policy_run_count": raw["policy_run_count"],
        "frozen_protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        "phase10_experiment_source_sha256": raw["phase10_source_sha256"],
        "protected_phase1_to_phase9_match": True,
        "artifacts_sha256": {
            relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            for relative in sorted(set(manifest_paths))
        },
    }
    manifest_path = ROOT / "results/phase10_artifact_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "figure_png": str(png_path),
                "figure_svg": str(svg_path),
                "recovery_heatmap": str(output_dir / "confirmation_recovery_heatmap.png"),
                "event_timeline": str(ROOT / "results/phase10_confirmation_event_timeline.json"),
                "per_uav_energy_summary": str(ROOT / "results/phase10_uav_energy_summary.json"),
                "artifact_manifest": str(manifest_path),
                "historical_artifacts_unchanged": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _plot_recovery_heatmap(summary: dict, output_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.5), constrained_layout=True)
    for axis, metric, title in (
        (axes[0], "first_full_recovery_success", "First full rescue recovery"),
        (axes[1], "sustained_30s_recovery_success", "Sustained ≥30 s recovery"),
    ):
        values = np.array(
            [
                [
                    summary["scenarios"][scene_id]["policies"][policy_id][metric]["mean"]
                    for scene_id, _ in SCENES
                ]
                for policy_id, _, _ in POLICIES
            ],
            dtype=float,
        )
        image = axis.imshow(values, vmin=0.0, vmax=1.0, cmap="YlGnBu", aspect="auto")
        axis.set_title(title, loc="left", fontsize=12)
        axis.set_xticks(np.arange(len(SCENES)), [label for _, label in SCENES])
        axis.set_yticks(np.arange(len(POLICIES)), [label for _, label, _ in POLICIES])
        for row_index, (policy_id, _, _) in enumerate(POLICIES):
            for column_index, (scene_id, _) in enumerate(SCENES):
                stats = summary["scenarios"][scene_id]["policies"][policy_id][metric]
                axis.text(
                    column_index,
                    row_index,
                    f"{int(stats['success_count'])}/{int(stats['total_count'])}",
                    ha="center",
                    va="center",
                    color="#17202a" if values[row_index, column_index] < 0.8 else "white",
                    fontsize=9,
                    fontweight="bold",
                )
        fig.colorbar(image, ax=axis, fraction=0.046, pad=0.04, ticks=[0, 0.25, 0.5, 0.75, 1])
    fig.suptitle("Recovery reliability · 20 held-out paired seeds", fontsize=15, fontweight="bold")
    fig.savefig(output_dir / "confirmation_recovery_heatmap.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_event_timeline(raw: dict) -> None:
    timeline = {
        "schema_version": "1.0",
        "source_raw_file": "results/phase10_confirmation_raw.json",
        "protocol_sha256": raw["protocol_sha256"],
        "event_count": 0,
        "runs": [],
    }
    for row in raw["records"]:
        for policy_id, run in row["strategy_runs"].items():
            events = run.get("event_log", [])
            timeline["event_count"] += len(events)
            timeline["runs"].append(
                {
                    "scenario_id": row["scenario_id"],
                    "seed": row["seed"],
                    "policy_id": policy_id,
                    "world_trace_sha256": row["world_trace_sha256"],
                    "events": events,
                }
            )
    destination = ROOT / "results/phase10_confirmation_event_timeline.json"
    destination.write_text(json.dumps(timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_per_uav_energy_summary(raw: dict) -> None:
    rows: dict[tuple[str, str, str], list[float]] = {}
    for record in raw["records"]:
        for policy_id, run in record["strategy_runs"].items():
            for uav_id, energy in run["metrics"].get("uav_energy_by_id_wh", {}).items():
                rows.setdefault((record["scenario_id"], policy_id, uav_id), []).append(float(energy))
    summary_rows = []
    for (scene_id, policy_id, uav_id), values in sorted(rows.items()):
        stats = _stats(values, include_ci=True)
        summary_rows.append(
            {
                "scenario_id": scene_id,
                "policy_id": policy_id,
                "uav_id": uav_id,
                "n": len(values),
                "mean_wh": stats["mean"],
                "sample_sd_wh": stats["sample_sd"],
                "median_wh": stats["median"],
                "ci95_t_wh": stats.get("mean_ci95_t"),
            }
        )
    destination = ROOT / "results/phase10_uav_energy_summary.json"
    destination.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "source_raw_file": "results/phase10_confirmation_raw.json",
                "unit": "Wh",
                "scope": "per-aircraft cumulative simulated energy over one run",
                "rows": summary_rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _bar_panel(
    axis,
    summary: dict,
    metric_name: str,
    title: str,
    ylabel: str,
    *,
    percent: bool = False,
    binary: bool = False,
) -> None:
    x = np.arange(len(SCENES), dtype=float)
    width = 0.145
    for index, (policy_id, label, color) in enumerate(POLICIES):
        means = []
        lower = []
        upper = []
        for scene_id, _ in SCENES:
            stats = summary["scenarios"][scene_id]["policies"][policy_id][metric_name]
            mean = float(stats["mean"] or 0.0)
            if percent:
                interval = stats.get("ci95_wilson") if binary else stats.get("mean_ci95_t")
            else:
                interval = stats.get("mean_ci95_t")
            means.append(mean * 100 if percent else mean)
            if interval:
                low, high = float(interval[0]), float(interval[1])
                scale = 100 if percent else 1
                lower.append(max(0.0, (mean - low) * scale))
                upper.append(max(0.0, (high - mean) * scale))
            else:
                lower.append(0.0)
                upper.append(0.0)
        offset = (index - (len(POLICIES) - 1) / 2) * width
        axis.bar(
            x + offset,
            means,
            width,
            color=color,
            label=label,
            edgecolor="white",
            linewidth=0.5,
            yerr=np.array([lower, upper]),
            capsize=2,
            error_kw={"elinewidth": 0.8, "capthick": 0.8},
        )
    axis.set_title(title, loc="left", fontsize=11.5, pad=9)
    axis.set_ylabel(ylabel)
    axis.set_xticks(x, [label for _, label in SCENES])
    axis.grid(axis="y", alpha=0.2, linewidth=0.7)
    axis.set_axisbelow(True)


if __name__ == "__main__":
    main()
