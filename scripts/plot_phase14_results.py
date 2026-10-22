"""Render publication-style Phase 14 model comparison figures from saved JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCENES = (
    "severe_persistent_faults",
    "dynamic_failures",
    "high_mobility_rescue",
    "high_load_backhaul_limit",
)
POLICIES = (
    ("Bprime_static_grid_shared_safety", "B′ / one UAV"),
    ("F_independent_greedy", "F3 / independent"),
    ("G_centralized_coordination", "G3 / centralized"),
)
SHORT_SCENES = {
    "severe_persistent_faults": "Persistent faults",
    "dynamic_failures": "Dynamic failures",
    "high_mobility_rescue": "Mobile rescue",
    "high_load_backhaul_limit": "Load / backhaul",
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _mean_ci(view):
    mean = view.get("mean")
    ci = view.get("ci95")
    if mean is None or not isinstance(ci, list) or len(ci) != 2:
        return float("nan"), 0.0, 0.0
    return float(mean), float(mean) - float(ci[0]), float(ci[1]) - float(mean)


def plot_service(summary: dict, out: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.2), sharey=True, constrained_layout=True)
    colors = ("#9a6f5b", "#e18d58", "#cf4d3b")
    offsets = (-0.22, 0.0, 0.22)
    for axis, scene in zip(axes.flat, SCENES):
        view = summary.get("scenarios", {}).get(scene, {})
        for (policy, label), color, offset in zip(POLICIES, colors, offsets):
            row = view.get(policy, {})
            if not row:
                continue
            for model_id, marker, x_delta in (("legacy_distance", "o", -0.055), ("link_budget_v1", "D", 0.055)):
                mean, low, high = _mean_ci(row[model_id]["rescue_user_service_success_rate"])
                center = offset + x_delta
                axis.errorbar(
                    center, mean, yerr=[[low], [high]], marker=marker, color=color,
                    capsize=3, markersize=5, linewidth=1.3,
                    label=f"{label} · {'distance' if model_id == 'legacy_distance' else 'budget'}",
                )
        axis.set_title(SHORT_SCENES[scene], loc="left", fontweight="bold")
        axis.set_xticks(offsets, ["B′", "F3", "G3"])
        axis.set_xlim(-0.48, 0.48)
        axis.set_ylim(0, 1)
        axis.grid(axis="y", color="#dddddd", linewidth=.65)
        axis.set_axisbelow(True)
    axes[0, 0].set_ylabel("Rescue user-time service rate")
    axes[1, 0].set_ylabel("Rescue user-time service rate")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    dedup = dict(zip(labels, handles))
    fig.legend(dedup.values(), dedup.keys(), loc="outside lower center", ncol=3, frameon=False, fontsize=8)
    fig.suptitle("Paired radio-model comparison · mean and 95% t interval", fontsize=15, fontweight="bold")
    fig.savefig(out / "phase14_model_service.png", dpi=180, facecolor="white")
    fig.savefig(out / "phase14_model_service.svg", facecolor="white")
    plt.close(fig)


def plot_feasibility(summary: dict, out: Path) -> None:
    probes = summary.get("link_feasibility_probe_summary", {})
    old = [float(probes.get(scene, {}).get("legacy_feasibility_rate") or 0.0) for scene in SCENES]
    new = [float(probes.get(scene, {}).get("link_budget_feasibility_rate") or 0.0) for scene in SCENES]
    positions = np.arange(len(SCENES))
    fig, axis = plt.subplots(figsize=(10.5, 5.2), constrained_layout=True)
    axis.bar(positions - .19, old, .36, color="#9a6f5b", label="Distance threshold")
    axis.bar(positions + .19, new, .36, color="#cf4d3b", label="Link budget")
    axis.set_xticks(positions, [SHORT_SCENES[item] for item in SCENES])
    axis.set_ylim(0, max(old + new + [.1]) * 1.18)
    axis.set_ylabel("Potential segments meeting link gate")
    axis.set_title("Link feasibility on saved legacy-strategy geometries", loc="left", fontweight="bold")
    axis.grid(axis="y", color="#dddddd", linewidth=.65)
    axis.set_axisbelow(True)
    axis.legend(frameon=False)
    fig.savefig(out / "phase14_link_feasibility.png", dpi=180, facecolor="white")
    fig.savefig(out / "phase14_link_feasibility.svg", facecolor="white")
    plt.close(fig)


def plot_sensitivity(sensitivity: dict, out: Path) -> None:
    variants = (
        "pathloss_exponent_low", "pathloss_exponent_high", "tx_power_low", "tx_power_high",
        "rx_sensitivity_low", "rx_sensitivity_high", "fade_margin_low", "fade_margin_high",
        "shadowing_low", "shadowing_high", "obstruction_low", "obstruction_high",
    )
    labels = ("n−", "n+", "Ptx−", "Ptx+", "Rx−", "Rx+", "M−", "M+", "σ−", "σ+", "Lobs−", "Lobs+")
    scenarios = sensitivity.get("scenarios", {})
    policy_id = "G_centralized_coordination"
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharey=True, constrained_layout=True)
    x = np.arange(len(variants))
    for axis, scene in zip(axes.flat, SCENES):
        policy = scenarios.get(scene, {}).get(policy_id, {})
        deltas = [
            policy.get(variant, {}).get("paired_service_delta_from_baseline", {}).get("mean")
            for variant in variants
        ]
        axis.axhline(0, color="#555555", linewidth=.8)
        axis.bar(x, [0.0 if value is None else float(value) for value in deltas], color=["#cf4d3b" if value is not None and value < 0 else "#768d71" for value in deltas])
        axis.set_xticks(x, labels, rotation=45, ha="right")
        axis.set_title(SHORT_SCENES[scene], loc="left", fontweight="bold")
        axis.grid(axis="y", color="#dddddd", linewidth=.6)
        axis.set_axisbelow(True)
    axes[0, 0].set_ylabel("Paired rescue-service change")
    axes[1, 0].set_ylabel("Paired rescue-service change")
    fig.suptitle("G3 one-factor screening · development seeds only", fontsize=15, fontweight="bold")
    fig.savefig(out / "phase14_model_sensitivity.png", dpi=180, facecolor="white")
    fig.savefig(out / "phase14_model_sensitivity.svg", facecolor="white")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", default="results/phase14_confirmation_summary.json")
    parser.add_argument("--sensitivity", default="results/phase14_model_sensitivity_summary.json")
    parser.add_argument("--out", default="plots/phase14")
    args = parser.parse_args()
    summary = _json(ROOT / args.summary)
    sensitivity = _json(ROOT / args.sensitivity)
    output = ROOT / args.out
    output.mkdir(parents=True, exist_ok=True)
    plot_service(summary, output)
    plot_feasibility(summary, output)
    plot_sensitivity(sensitivity, output)
    print(json.dumps({"output_dir": str(output), "figures": 6}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
