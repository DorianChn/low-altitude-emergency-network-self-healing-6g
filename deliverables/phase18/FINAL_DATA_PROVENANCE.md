# 最终数据来源与溯源

| 数据 | 来源类型 | 位置/标识 | 可主张范围 |
|---|---|---|---|
| Phase 1–5/8–11/14 原始策略运行 | 本项目抽象仿真 | `results/phase*_*.json`、配置和阶段冻结清单 | 仅对应具体代码、配置、种子与模型假设 |
| Phase 3 / Phase 6 离线演示回放 | 仿真保存的离散状态 | `results/phase3_replay_seed_2026.json`、`results/phase6_demo_*.json` | 只能回放已有仿真帧，不是实时网络数据 |
| Phase 15 公共 A2G 数据 | 第三方公开测量数据 | 数据集 Mendeley DOI `10.17632/8p6r8ft4fz.2`，约 3.6 GHz；原始源清单在 `configs/phase15/public_dataset_manifest.json` | 域内候选模型拟合/留出评估；非项目设备校准 |
| Phase 15 清洗数据 | 对公开源文件执行记录清洗 | `results/phase15_measurements_public_clean.csv` | 可追溯的清洗副本，不能称为项目现场数据 |
| Phase 16 设备测量 | 项目设备实测 | 0 条记录 | 尚未获得校准或实测性能证据 |
| Phase 17 安全闭环 | 合成软件测试植物 | `results/phase17_closed_loop_run.json`、命令审计与注入案例 | 软件闭环与安全逻辑验证；不是设备 HIL |
| Phase 18 完整性审计 | 本阶段只读计算 | `results/phase18/phase18_integrity_audit.json` | 仅证明审计时散列和结构核对状态 |

每项保存 JSON 的源 SHA-256、配置哈希、随机种子或冻结清单由相应阶段记录；Phase 18 证据清单额外计算每个引用文件的 SHA-256。Phase 15 14 个原始来源已逐项复核且不被复制进本地 RC 清单。
