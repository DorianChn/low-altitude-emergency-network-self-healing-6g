# Phase 8 开发与审计记录

## 变更边界

- 日期：2026-10-20（Asia/Shanghai）。
- 分支：`phase8-ablation-sensitivity`，起始HEAD为`7d3eb100ac567aedd7edb462aab7ad1125a3fbb5`。
- 开始前已检查`git status`。Phase 3–6相关源码、前端、报告、配置和结果有未提交/未跟踪改动；均保留，未清理、回退或暂存。
- Phase 5冻结清单SHA-256：`386be3c58f822e326d7283451bcc00c1d2c710c60240c65f5231968c8aa5b6d5`。Phase 5审计函数返回PASS且与已有审计JSON相等（400次策略运行，0项问题）。Phase 6演示API直接读取通过：4个场景、每场景5个策略。
- Phase 2、4、5历史JSON及Phase 6回放未改；实验结果分批保存为新文件。未配置Git remote；未提交混合工作区，也未推送。

## 算法审计和实现

- 根据当前`dynamic_simulation.py`、`optimizer.py`、`phase8_experiments.py`和`phase8_d_optimizer.py`列出B/B′/C/D机制，不以旧报告代替代码检查。
- 新增`phase8_d_optimizer.py`，复制基线D实现并暴露不影响执行层硬约束的实验开关；正式D源码保持冻结。默认首个决策与正式D的一致性测试通过。
- C直接目标方向消融修正为确实只保留9个罗盘动作；测试确认默认10类方向、关闭直接方向后9类。
- 参数范围固定为已实现的低/中/高探针。C的H=1/3/6对应10/30/60秒；D规划周期下限仍为60秒；储备50/75/100 Wh始终正值且返航保护开启。

## 已冻结协议和实验文件

| 批次 | 协议 | 种子数 | 运行数 | 结果文件 |
|---|---|---:|---:|---|
| 开发筛选 | `configs/phase8/experiment_plan.json`、`sensitivity_plan.json` | 12 | 456 | `results/phase8_development_raw.json`、`phase8_development_summary.json` |
| 首批确认 | `configs/phase8/validation_protocol.json` | 40 | 680 | `results/phase8_validation_raw.json`、`phase8_validation_summary.json` |
| 独立机制复验 | `configs/phase8/replication_protocol.json`，SHA=`c8d2fd5067d6cf0959b5d43fa512f4e3ca74c4f0b6b5439d2b2b494bc983b07f` | 80 | 1,360 | `results/phase8_replication_raw.json`、`phase8_replication_summary.json` |
| 独立参数确认 | `configs/phase8/sensitivity_validation_protocol.json` | 80 | 2,000 | `results/phase8_sensitivity_validation_raw.json`、summary及audit |

Phase 8新参数验证协议在新种子开始前创建，记录开发文件SHA、场景配置SHA、Phase 5源码/manifest SHA、算法与脚本SHA、80个新种子、20个参数变体ID和统计方法。种子与旧历史、Phase 5开发/验证、Phase 8开发、首批验证、独立机制复验不重叠。每个新种子下所有策略和变体共享同一条预生成世界轨迹。

## 统计与处理记录

- 统计保留每种子原始数据、实际成功连接时延样本、环境/策略事件、返航和剩余电量、轨迹/配置哈希。
- 连续指标使用配对精确sign-flip检验，二元指标用精确McNemar/binomial检验；报告Student-t配对差区间、Cohen d_z、Hedges g_z、Wilson成功率区间。效能族与资源成本族分别Holm校正；条件时延不做配对推断。
- 独立机制复验完成仿真后，汇总器要求的顶层字段`plan_sha256`缺失。`scripts/finalize_phase8_replication.py`只补入raw中已存在的`experiment_plan_sha256`别名并生成统计；审计文件PASS，80条逐种子记录的canonical SHA前后相同，逐条测量数据未改。
- 恢复失败保留为失败；计算截尾均值时使用600秒仿真时长。持续30秒失败保留在全体种子分母中。

## 图表与测试

- `plots/phase8/phase8_parameter_sensitivity_development.png/.svg`按开发集真实summary生成并人工查看；图中标记每场景n=3和exploratory。
- `plots/phase8_replication/`机制复验对照图由逐种子raw生成并人工查看，包含场景对照及相对父算法服务率差。
- 参数确认独立图生成于`plots/phase8_sensitivity_validation/`，配对服务率差图已人工查看；图中数据来自新留出验证集。
- 原有全量pytest曾为40项通过；新增参数绘图输入分区测试和独立种子清单测试后，两项定向测试也通过。最终全量结果见下方。

## 参数确认完成记录

- 完成时间：2026-10-20；墙钟运行时间：3154.606秒（52分34.606秒）。
- 完成80/80种子、2,000/2,000策略运行；raw大小317,779,704 bytes，物理SHA-256=`0ec158db99b78d00843a5d11685349470535fd9bbbc93e4eed70b725b1549888`。
- 参数确认审计PASS，问题列表为空；无返航储备违反、时延计数不匹配、缺轨迹哈希或无时间戳环境事件。审计规范化raw SHA=`756edbe55bbaccd3e8feaac4d06e6f3667d31483fa37d391bd253ee1a955e5c4`。
- 参数协议SHA=`7ba6453a05365c99b6faa64bf2752f0aca4dffcaa757694ba620011b6502534e`；Phase 5冻结manifest SHA=`386be3c58f822e326d7283451bcc00c1d2c710c60240c65f5231968c8aa5b6d5`。
- 运行中369/2,000未达到首次完整恢复、550/2,000未达到持续30秒恢复；均为保留的仿真结果，不是程序异常。基准首复失败数为A 80、B 6、B′ 6、C 12、D 12。
- 参数父策略比较中，没有救援服务、首次恢复、持续恢复、连接或截尾恢复时间差通过Holm；唯一经校正的能耗变化是C beam宽度3在高负载下减少11.533 Wh和23.204 Wh/(救援用户·小时)。C beam=3四场景的累计决策耗时均下降；C beam=12均上升。D间隔120秒四场景累计计算耗时下降，但无恢复收益证据。没有确认出优于B的稳定救援参数区间。
- 物理能耗模型系数（18 Wh/km、80 W悬停、120 W中继）的高低偏差比例没有实测依据，未在本阶段作模型误差比例校准；已检验的是C/D规划能耗偏好和返航储备阈值。该模型系数误差的调度影响列为后续明确研究缺口。
- 五项主要数据保护/兼容性复核：Phase 5 frozen audit仍PASS且manifest未变；Phase 6场景目录读取正常；四类历史JSON未覆写；历史接口及前端未修改；未发现remote，因此未公开推送。

## 最终验证与Git状态

- `uv run --frozen --offline pytest -q`最终实测：42 passed in 35.72s，完整终端输出保存在`results/phase8_pytest_results.txt`。
- 最终复核：参数确认审计PASS；Phase 5完整性校验PASS；Phase 6演示API四场景读取通过；前序未提交工作保持未暂存、未回退、未覆盖。
- 当前分支为`phase8-ablation-sensitivity`。因工作区含前序阶段混合变更，本阶段未自动提交或推送；没有配置remote。阶段结果保留在独立分支和单独命名的Phase 8文件中。
