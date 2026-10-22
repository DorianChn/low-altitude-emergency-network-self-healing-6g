"""Plot exploratory paired rescue-service deltas for 3 versus 2 UAVs."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "results/phase11_fleet_size_exploratory.json"
OUT = ROOT / "plots/phase11"


def main() -> None:
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    scenes = data["scenarios"]
    policies = list(next(iter(scenes.values())).keys())
    labels = ["F", "G", "H", "I", "J"]
    colors = ["#315b84", "#d68a36", "#568b68", "#8a6e9b", "#ba5555"]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharey=True, constrained_layout=True)
    for ax, (scene_id, entries) in zip(axes.flat, scenes.items(), strict=True):
        for index, (policy, label, color) in enumerate(zip(policies, labels, colors, strict=True)):
            result = entries[policy]["fleet3_minus_fleet2"]["rescue_user_service_success_rate"]
            mean = 100 * result["mean_difference"]
            low, high = (100 * value for value in result["ci95_t"])
            significant = result.get("p_holm_adjusted", 1.0) < 0.05
            ax.errorbar(
                index,
                mean,
                yerr=[[mean - low], [high - mean]],
                fmt="o",
                color=color,
                ecolor=color,
                capsize=4,
                markersize=7,
                markerfacecolor=color if significant else "white",
                markeredgewidth=1.7,
                linewidth=1.5,
            )
        ax.axhline(0, color="#333333", linewidth=1, linestyle="--")
        ax.set_title(scene_id.replace("_", " "))
        ax.set_xticks(range(len(labels)), labels)
        ax.set_ylabel("Rescue service change, 3 UAV − 2 UAV (pp)")
        ax.grid(axis="y", alpha=0.22)
    fig.suptitle(
        "Exploratory fleet-size contrast: paired mean difference and 95% CI (n=20 per scene)\n"
        "Filled markers: Holm-adjusted p < 0.05 within the exploratory scene-family"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "fleet_size_increment.png", dpi=180)
    fig.savefig(OUT / "fleet_size_increment.svg")
    plt.close(fig)
    print(OUT / "fleet_size_increment.png")
    print(OUT / "fleet_size_increment.svg")


if __name__ == "__main__":
    main()
