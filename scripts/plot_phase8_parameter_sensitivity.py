"""Plot Phase 8 development-only one-factor parameter sensitivity results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
SCENE_ORDER = (
    "severe_persistent_faults",
    "dynamic_failures",
    "high_mobility_rescue",
    "high_load_backhaul_limit",
)
SCENE_LABELS = {
    "severe_persistent_faults": "Severe persistent",
    "dynamic_failures": "Dynamic failures",
    "high_mobility_rescue": "High mobility",
    "high_load_backhaul_limit": "High load / backhaul",
}
SCENE_COLORS = {
    "severe_persistent_faults": "#a83225",
    "dynamic_failures": "#cf7130",
    "high_mobility_rescue": "#357b86",
    "high_load_backhaul_limit": "#778454",
}

# Each level maps to the named one-factor variant. None denotes the formal
# parent policy used as the midpoint, so plotted effects are within-algorithm
# differences in rescue service, not cross-algorithm comparisons.
PANELS = (
    ("C · replanning interval (s)", "C_rolling_horizon_mpc", (("10", "C_interval_10"), ("20 base", None), ("40", "C_interval_40"))),
    ("D · replanning interval (s)", "D_lexicographic_rescue_priority", (("60 base", "D_interval_60"), ("90", "D_interval_90"), ("120", "D_interval_120"))),
    ("C · prediction horizon (steps)", "C_rolling_horizon_mpc", (("1", "C_horizon_1"), ("3 base", None), ("6", "C_horizon_6"))),
    ("D · prediction horizon (steps)", "D_lexicographic_rescue_priority", (("1", "D_horizon_1"), ("3 base", None), ("6", "D_horizon_6"))),
    ("C · target quantization (km)", "C_rolling_horizon_mpc", (("0.125", "C_target_grid_0p125"), ("0.25 base", None), ("0.5", "C_target_grid_0p5"))),
    ("D · grid spacing (km)", "D_lexicographic_rescue_priority", (("0.125", "D_grid_0p125"), ("0.25 base", None), ("0.5", "D_grid_0p5"))),
    ("D · grid shortlist cap", "D_lexicographic_rescue_priority", (("16", "D_candidate_cap_16"), ("64 base", None), ("128", "D_candidate_cap_128"))),
    ("D · target-switch penalty", "D_lexicographic_rescue_priority", (("0", "D_switch_penalty_0"), ("1 base", None), ("10", "D_switch_penalty_10"))),
    ("C · energy objective weight", "C_rolling_horizon_mpc", (("0", "C_energy_weight_0"), ("2 base", None), ("4", "C_energy_weight_4"))),
    ("D · energy tie-break", "D_lexicographic_rescue_priority", (("off", "D_energy_tiebreak_off"), ("on base", None))),
    ("C · reserve (Wh)", "C_rolling_horizon_mpc", (("50 base", None), ("75", "C_reserve_75"), ("100", "C_reserve_100"))),
    ("D · reserve (Wh)", "D_lexicographic_rescue_priority", (("50 base", None), ("75", "D_reserve_75"), ("100", "D_reserve_100"))),
    ("C · rescue weight", "C_rolling_horizon_mpc", (("5", "C_rescue_weight_5"), ("10 base", None), ("20", "C_rescue_weight_20"))),
    ("D · rescue priority", "D_lexicographic_rescue_priority", (("off", "D_rescue_priority_off"), ("on base", None))),
    ("C · beam width", "C_rolling_horizon_mpc", (("3", "C_beam_width_3"), ("6 base", None), ("12", "C_beam_width_12"))),
)


def create_sensitivity_charts(
    summary_path: str | Path,
    output_dir: str | Path,
) -> list[Path]:
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    if summary.get("phase") != "development" or summary.get("status") != "complete":
        raise ValueError("parameter screening chart requires complete development data")
    scenarios = summary["scenarios"]
    if any(int(scenarios[scene]["seed_count"]) < 1 for scene in SCENE_ORDER):
        raise ValueError("each scenario needs at least one development seed")

    plt.rcParams.update({"font.size": 8.5, "axes.grid": True, "grid.alpha": 0.22})
    fig, axes = plt.subplots(4, 4, figsize=(18, 13), constrained_layout=True)
    for axis, (title, parent, levels) in zip(axes.flat, PANELS, strict=False):
        for scene in SCENE_ORDER:
            policy_summaries = scenarios[scene]["all_strategy_and_variant_summaries"]
            base_rate = float(policy_summaries[parent]["metrics"]["rescue_user_service_success_rate"]["mean"])
            values: list[float] = []
            for _label, variant_id in levels:
                policy_id = variant_id or parent
                rate = float(policy_summaries[policy_id]["metrics"]["rescue_user_service_success_rate"]["mean"])
                values.append((rate - base_rate) * 100.0)
            axis.plot(
                range(len(levels)),
                values,
                marker="o",
                linewidth=1.5,
                markersize=3.5,
                color=SCENE_COLORS[scene],
                label=SCENE_LABELS[scene],
            )
        axis.axhline(0, color="#282320", linewidth=0.8)
        axis.set_title(title, loc="left", fontweight="bold", fontsize=9)
        axis.set_xticks(range(len(levels)), [label for label, _variant_id in levels], rotation=25, ha="right", fontsize=7)
        axis.set_ylabel("Δ rescue service (pp)", fontsize=7)
        axis.tick_params(axis="y", labelsize=7)
    for axis in axes.flat[len(PANELS):]:
        axis.set_visible(False)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 1.015))
    fig.suptitle(
        "Phase 8 · one-factor parameter screening (development only; n=3 seeds per scenario)",
        fontsize=14,
        fontweight="bold",
        y=1.045,
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = [output / f"phase8_parameter_sensitivity_development.{suffix}" for suffix in ("png", "svg")]
    for path in paths:
        fig.savefig(path, dpi=180 if path.suffix == ".png" else None, bbox_inches="tight")
    plt.close(fig)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "results/phase8_development_summary.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "plots/phase8")
    args = parser.parse_args()
    paths = create_sensitivity_charts(args.input, args.output_dir)
    print(json.dumps({"charts": [str(path) for path in paths]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
