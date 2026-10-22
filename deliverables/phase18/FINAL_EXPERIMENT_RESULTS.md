# 最终实验结果摘要

所有统计按阶段报告各自的实验协议呈现；不把不同链路模型、场景定义、种子集或策略集合合并成单一总体估计。完整逐种子原始数据、配对检验和置信区间见下表路径。

| 发现 | 真实结果摘录 | 数据依据 |
|---|---|---|
| C/D 未普遍超过静态 B | Phase 2：B 28.504%、C 25.195%；Phase 4：B 28.709%、C 25.574%、D 24.908% | `results/phase2_20_seed_results.json`；`results/phase4_validation_4000_4019.json` |
| 动态场景下 C/D 首次/持续恢复较弱 | Phase 8 B 为 14/20、7/20；C/D 为 8/20、0/20 | `results/phase8_replication_summary.json`；`PHASE8_REPORT.md` |
| E 未改善动态救援服务 | E−B′ −7.05 pp，95% CI [−8.74, −5.35]，Holm p=0.000183；持续恢复 0/20 | `results/phase9_corrected_confirmation_summary.json`；`PHASE9_REPORT.md` |
| G/F 具有场景交互 | 3机动态 G−F +2.38 pp；3机高负载 G−F −3.99 pp，均经校正显著 | `results/phase11_confirmation_summary.json`；`PHASE11_REPORT.md` |
| 链路预算敏感且结果收紧 | 12 项救援服务配对差均为负，8 项校正后显著 | `results/phase14_confirmation_summary.json`；`PHASE14_REPORT.md` |

解释：以上不是实时服务 QoS、真实无人机能耗或 6G 空口 KPI。恢复时间受失败运行删失定义约束；条件时延使用各策略成功连接样本，应附样本数，不能当作完全相同用户集合的效果对照。
