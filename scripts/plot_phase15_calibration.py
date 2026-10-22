"""Render evidence plots from the saved Phase 15 dataset and holdout results."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np


CJK_FONT = Path("C:/Windows/Fonts/msyh.ttc")
if CJK_FONT.is_file():
    font_manager.fontManager.addfont(str(CJK_FONT))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(CJK_FONT)).get_name()


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUTPUT = ROOT / "plots/phase15"
SUMMARY = json.loads((RESULTS / "phase15_calibration_summary.json").read_text(encoding="utf-8"))
HOLDOUT = json.loads((RESULTS / "phase15_holdout_validation.json").read_text(encoding="utf-8"))
with (RESULTS / "phase15_measurements_public_clean.csv").open("r", encoding="utf-8", newline="") as stream:
    ROWS = list(csv.DictReader(stream))


def palette() -> dict[str, str]:
    return {
        "background": "#101416",
        "panel": "#171d20",
        "ink": "#e8e4da",
        "muted": "#9ca6a2",
        "grid": "#344044",
        "candidate": "#ed794c",
        "phase14": "#63b4bc",
        "matched": "#cab473",
        "fit": "#88a9c2",
        "holdout": "#e4d8be",
    }


def style(ax, colors: dict[str, str]) -> None:
    ax.set_facecolor(colors["panel"])
    ax.tick_params(colors=colors["muted"], labelsize=9)
    ax.xaxis.label.set_color(colors["ink"])
    ax.yaxis.label.set_color(colors["ink"])
    ax.title.set_color(colors["ink"])
    for spine in ax.spines.values():
        spine.set_color(colors["grid"])
    ax.grid(color=colors["grid"], linewidth=0.6, alpha=0.65)


def save(fig, stem: str) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT / f"{stem}.png", dpi=180, facecolor=fig.get_facecolor(), bbox_inches="tight")
    fig.savefig(OUTPUT / f"{stem}.svg", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def _prediction(distance: np.ndarray, model: dict) -> np.ndarray:
    d0 = float(model["reference_distance_m"])
    return float(model["pl0_db_at_reference_distance"]) + 10 * float(model["path_loss_exponent"]) * np.log10(np.maximum(distance, d0) / d0)


def plot_fit_and_holdout() -> None:
    c = palette()
    candidate = SUMMARY["candidate_fit"]
    baseline = SUMMARY["baselines"]["phase14_exact"]
    matched = SUMMARY["baselines"]["frequency_matched_unfitted"]
    dist = np.asarray([float(row["distance_m"]) for row in ROWS])
    loss = np.asarray([float(row["path_loss_db"]) for row in ROWS])
    groups = np.asarray([row["session_id"] for row in ROWS])
    holdout_groups = set(HOLDOUT["holdout_groups"])
    is_holdout = np.isin(groups, list(holdout_groups))
    fig, ax = plt.subplots(figsize=(10.5, 6.2), facecolor=c["background"])
    style(ax, c)
    ax.scatter(dist[~is_holdout], loss[~is_holdout], s=12, color=c["fit"], alpha=0.28, label="训练组：实测 CIR 派生 PL")
    ax.scatter(dist[is_holdout], loss[is_holdout], s=16, color=c["holdout"], alpha=0.45, label="留出组：过水环境实测 CIR 派生 PL")
    x = np.linspace(float(dist.min()), float(dist.max()), 300)
    for model, color, label in (
        (candidate, c["candidate"], "候选：3.6 GHz，n 固定 2.3，拟合数据集偏移"),
        (baseline, c["phase14"], "Phase 14 精确基线：3.5 GHz，n=2.3"),
        (matched, c["matched"], "频率匹配未拟合：3.6 GHz，n=2.3"),
    ):
        ax.plot(x, _prediction(x, model), color=color, linewidth=2.0, label=label)
    ax.set_title("公开空地测量：训练数据与冻结留出组", loc="left", pad=14, fontsize=15, fontweight="semibold", color=c["ink"])
    ax.set_xlabel("Tx–Rx 三维距离 (m)")
    ax.set_ylabel("作者派生路径损耗 (dB)")
    ax.legend(frameon=False, fontsize=8, labelcolor=c["ink"], loc="best")
    ax.text(0.99, 0.02, "不代表项目设备校准", transform=ax.transAxes, ha="right", color=c["muted"], fontsize=8)
    save(fig, "phase15_fit_and_holdout")


def plot_holdout_residuals() -> None:
    c = palette()
    candidate = SUMMARY["candidate_fit"]
    baseline = SUMMARY["baselines"]["phase14_exact"]
    rows = [row for row in ROWS if row["session_id"] in set(HOLDOUT["holdout_groups"])]
    dist = np.asarray([float(row["distance_m"]) for row in rows])
    observed = np.asarray([float(row["path_loss_db"]) for row in rows])
    pred_candidate = _prediction(dist, candidate)
    pred_baseline = _prediction(dist, baseline)
    fig, ax = plt.subplots(figsize=(10.5, 5.8), facecolor=c["background"])
    style(ax, c)
    ax.axhline(0, color=c["ink"], linewidth=1.0, alpha=0.8)
    ax.scatter(dist, pred_candidate - observed, s=18, color=c["candidate"], alpha=0.48, label="候选模型残差")
    ax.scatter(dist, pred_baseline - observed, s=18, color=c["phase14"], alpha=0.30, label="Phase 14 基线残差")
    ax.set_title("最终留出组残差（只含 Over-water 10m / 15m）", loc="left", pad=14, fontsize=15, fontweight="semibold", color=c["ink"])
    ax.set_xlabel("Tx–Rx 三维距离 (m)")
    ax.set_ylabel("预测 PL − 观测 PL (dB)")
    ax.legend(frameon=False, fontsize=9, labelcolor=c["ink"])
    ax.text(0.99, 0.02, "570 个相同留出样本；两条残差不等于设备验证", transform=ax.transAxes, ha="right", color=c["muted"], fontsize=8)
    save(fig, "phase15_holdout_residuals")


def plot_parameter_interval() -> None:
    c = palette()
    fit = SUMMARY["candidate_fit"]
    offsets = fit["per_training_group"]
    names = list(offsets)
    values = [float(offsets[name]["fitted_offset_db_before_equal_group_average"]) for name in names]
    estimate = float(fit["dataset_offset_db"])
    interval = fit["parameter_uncertainty"]["ci95"]["dataset_offset_db"]
    fig, ax = plt.subplots(figsize=(10.5, 5.8), facecolor=c["background"])
    style(ax, c)
    y = np.arange(len(names))
    ax.scatter(values, y, s=48, color=c["fit"], zorder=3, label="每个训练文件的偏移估计")
    ax.axvline(estimate, color=c["candidate"], linewidth=2.0, label=f"等组均值估计：{estimate:.2f} dB")
    ax.axvspan(float(interval[0]), float(interval[1]), color=c["candidate"], alpha=0.16, label="整组 Bootstrap 95% 区间")
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.set_title("单参数校准与分组不确定性", loc="left", pad=14, fontsize=15, fontweight="semibold", color=c["ink"])
    ax.set_xlabel("数据集路径损耗偏移 ΔPL (dB)")
    ax.set_ylabel("训练环境 / 高度组")
    ax.legend(frameon=False, fontsize=9, labelcolor=c["ink"], loc="lower right")
    ax.text(0.99, 0.02, "n=2.3 固定；未拟合斜率；4 个独立训练组", transform=ax.transAxes, ha="right", color=c["muted"], fontsize=8)
    save(fig, "phase15_parameter_uncertainty")


def main() -> int:
    if not SUMMARY.get("candidate_fit") or HOLDOUT.get("status") != "EVALUATED":
        raise SystemExit("Phase 15 calibration summary and holdout evaluation must exist before plotting")
    plot_fit_and_holdout()
    plot_holdout_residuals()
    plot_parameter_interval()
    print(json.dumps({"status": "PASS", "plots": 3, "directory": "plots/phase15"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
