"""Render the evidence status of Phase 16 uncertainty sources; no magnitudes are imputed."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "tx_power": "发射功率",
    "rx_power": "接收功率",
    "tx_antenna_gain": "发射天线增益",
    "rx_antenna_gain": "接收天线增益",
    "feedline_loss": "馈线与连接损耗",
    "frequency": "载频配置",
    "bandwidth": "带宽配置",
    "distance": "收发距离与定位",
    "antenna_height": "天线高度",
    "antenna_attitude": "天线姿态与指向",
    "temperature_gain_drift": "温度与增益漂移",
    "repeatability": "测量重复性",
    "between_batch": "批次间差异",
    "environmental_variation": "遮挡、多径与环境变化",
    "model_residual": "模型残差",
    "parameter_estimation": "参数估计不确定度",
}


def main() -> int:
    source = ROOT / "results/phase16_uncertainty_budget.json"
    budget = json.loads(source.read_text(encoding="utf-8"))
    sources = budget["sources"]
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(11.5, 8.2), dpi=180)
    fig.patch.set_facecolor("#171515")
    ax.set_facecolor("#171515")
    y_values = list(range(len(sources)))
    ax.set_xlim(0, 1)
    ax.set_ylim(-1, len(sources))
    ax.set_xticks([])
    ax.set_yticks(y_values)
    ax.set_yticklabels([LABELS.get(item["id"], item["id"]) for item in sources], color="#ebe3d7", fontsize=10)
    ax.invert_yaxis()
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(axis="y", length=0, pad=14)
    for y, item in zip(y_values, sources):
        ax.axhline(y, color="#3b3432", lw=0.7, zorder=0)
        value = item.get("standard_uncertainty")
        if value is None:
            ax.scatter([0.13], [y], s=44, marker="s", color="#dba05b", edgecolor="none", zorder=2)
            ax.text(0.19, y, "未知 · 无目标设备量值证据", color="#d2b487", va="center", fontsize=9)
        else:
            ax.scatter([0.13], [y], s=44, marker="s", color="#76bd9d", edgecolor="none", zorder=2)
            ax.text(0.19, y, f"已记录：{value:g} {item['unit']}", color="#a6cfba", va="center", fontsize=9)
    ax.set_title("不确定度来源证据覆盖", loc="left", color="#f0e9df", fontsize=18, fontweight="bold", pad=24)
    ax.text(0, 1.015, "状态矩阵，不是误差幅值图；未知值不按零计算", transform=ax.transAxes, color="#a59c94", fontsize=10, va="bottom")
    ax.text(0.0, -0.07, f"已量化 {sum(item.get('standard_uncertainty') is not None for item in sources)} / {len(sources)} · 合成标准不确定度：不可计算", transform=ax.transAxes, color="#dba05b", fontsize=10, va="top")
    fig.subplots_adjust(left=0.24, right=0.98, top=0.91, bottom=0.10)
    out = ROOT / "plots/phase16"
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "phase16_uncertainty_budget.png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    fig.savefig(out / "phase16_uncertainty_budget.svg", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print(json.dumps({"sources": len(sources), "quantified": sum(item.get("standard_uncertainty") is not None for item in sources), "png": "plots/phase16/phase16_uncertainty_budget.png", "svg": "plots/phase16/phase16_uncertainty_budget.svg"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
