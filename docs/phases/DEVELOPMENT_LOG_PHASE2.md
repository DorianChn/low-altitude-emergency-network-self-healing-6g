# 第二阶段开发记录

日期：2026-10-18

工作分支：`phase2-dynamic-ai-scheduling`

项目版本：保留 `0.1.0`，以确保第一阶段 JSON 不发生版本字段回归。
远程仓库：未配置。

## 审查和回归基线

- 检查 `README.md`、`PHASE1_REPORT.md`、配置/引擎/模型/策略/仿真/CLI 核心源码及现有测试。
- 第一阶段原始验证：默认仿真输出与 `results/phase1_benchmark.json` 逐字节一致；第一阶段原有 `7 passed`。
- 检查 Git 状态并从第一阶段分支建立独立分支 `phase2-dynamic-ai-scheduling`；未修改其他项目目录。
- 初次升级软件包版本会导致 phase1 JSON 中 `project_version` 不同；为保持要求中的基准结果，撤销版本号变更并重新锁定依赖。最终 phase1 输出逐字节一致。

## 实现顺序

1. 添加独立动态配置 schema，保持第一阶段 TOML 兼容。
2. 给网络模型增加可选电池状态与无人机回传可用状态，默认回传可用；仅在动态回传故障时禁止中继链路。
3. 实现按种子预生成的故障、恢复、负载、回传和用户随机游走事件轨迹，确保同一 seed 下 A/B/C 环境输入一致。
4. 实现时间戳动态事件仿真，增加 A 无 UAV、B 静态首选网格目标、C 动态滚动 beam-search 控制器。
5. 实现基站/用户/拥塞/回传诊断，滚动多目标收益、飞行速度/地图/链路/容量/电池/返航限制和显式不可行原因。
6. 增加多种子统计、未恢复场景 null 处理、时延样本口径、决策墙钟耗时和 PNG/SVG 图表。
7. 恢复并重写 README，撰写第二阶段报告和本记录。

## 验证和问题修复记录

- 首次动态算法测试发现目标集合在健康基站变量初始化前使用；修复初始化顺序。
- 速度约束测试发现单位向量舍入使生成的预测坐标超出单步速度约 `6e-8 km`；保留归一化向量精度后通过约束测试。
- 三次 20 种子实验运行中，发现并修复图表使用了错误的恢复汇总字段、当前 Matplotlib 仅支持 `tick_labels`，以及 P95 子图误读均值统计列。最终指标摘要从已保存的 20 种子真实汇总重绘，逐样本时延分布图来自同轮内存样本。
- 图表已通过本地 PNG 视觉检查；未改动第一阶段结果 JSON。

## 最终实验和检查命令

```bash
uv run pytest -q
uv run lowalt6g run --config configs/disaster_scenario.toml --output /tmp/phase1_after.json
cmp results/phase1_benchmark.json /tmp/phase1_after.json
uv run lowalt6g run-dynamic --config configs/dynamic_scenario.toml --output results/phase2_20_seed_results.json --plots plots
```

实际结果：

- 自动化测试：`13 passed`（7 项第一阶段 + 6 项动态阶段）。
- 第一阶段基准：`PHASE1_BASELINE_BYTE_IDENTICAL`。
- 第二阶段：种子 2026–2045，20/20 完成；同一 seed 三策略共用一个轨迹 hash。
- 结果文件：`results/phase2_20_seed_results.json`；图表：`plots/phase2_strategy_comparison.{png,svg}`、`plots/phase2_latency_distribution.{png,svg}`。
- `git remote -v` 无输出；没有远程仓库，因此无法创建 PR。

## 结果摘要和待办

三策略关键指标、成功条件、失败决策原因、统计口径和技术限制见 `PHASE2_REPORT.md`。C 相对 B 的平均救援服务率低 3.31 个百分点、恢复慢 50 秒，连接率接近、能耗低约 4.17 Wh、pooled 平均时延低约 3.33 ms，但 pooled P95 略高且每次运行决策计算耗时约 1.43 秒。因此下一步应先改善多用户救援覆盖目标与 MPC 终端价值/预测，再用独立故障配置验证，不应把本阶段算法描述为已验证优于静态策略。
