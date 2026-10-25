# Phase 12：系统架构与模块审计

审计日期：2026-10-20。本文以当前可见源码、配置、API、前端和实验文件为准；模块机器清单见 [`docs/phase12/module_inventory.json`](../phase12/module_inventory.json)。

## 总体架构

![系统总体架构](../phase12/system_architecture.png)

![关键数据流与证据隔离](../phase12/research_dataflow.png)

可编辑源文件：[`system_architecture.mmd`](../phase12/system_architecture.mmd)、[`research_dataflow.mmd`](../phase12/research_dataflow.mmd)。图像可由 `python scripts/render_phase12_architecture.py` 重新生成。

## 分层与代码追踪

| 层 | 实际代码位置 | 输入 | 输出 | 状态与边界 |
|---|---|---|---|---|
| 灾害与业务场景 | `src/lowalt6g/config.py`、`dynamic_config.py`、`scenario.py`、`dynamic_world.py`；`configs/phase5/` | TOML、固定随机种子 | 网络初态、用户/需求、动态位置轨迹和环境事件 | 已实现的离散抽象场景；随机种子生成的城市不等于实测城市数据。 |
| 网络状态与链路 | `src/lowalt6g/models.py`、`engine.py`、`multi_uav.py::evaluate_fleet` | 基站健康/容量、回传、用户与无人机位置、距离阈值 | 可行端到端候选路径、连接状态、资源占用和模型时延 | 距离/容量模型；没有传播衰落、建筑遮挡、无线干扰、协议栈或真实空口。 |
| 资源分配与策略 | `policies.py`、`optimizer.py`、`phase8_d_optimizer.py`、`phase9_strategy_e.py`、`multi_uav.py::plan_fleet`、`phase11_algorithms.py` | 控制器当前可观察的网络快照、电量、策略配置 | 目标位置、机队目标、用户路径分配、不可行原因 | A–J 为基线、确定性启发式或有限候选优化；均非训练型机器学习。 |
| 仿真执行与安全 | `simulation.py`、`dynamic_simulation.py`、`multi_uav_simulation.py`、`phase11_simulation.py`、`energy_budget.py` | 策略动作和当前环境状态 | 更新后的节点/用户/无人机状态、事件日志、能耗和安全检查结果 | 仿真器应用未来配置事件；策略仅观察当前状态。执行路径执行速度、边界、电池/返航、链路和多机间距等约束。 |
| 实验与数据审计 | `phase5.py`、`experiment.py`、`phase8_experiments.py`、`phase9_experiments.py`、`phase10_experiments.py`、`phase11_experiments.py`；`scripts/phase5_audit.py` | 场景、种子分区、策略、冻结协议 | 逐种子 JSON、统计摘要、图表、配置/源码/轨迹哈希 | Phase 5/8/9/10/11 有冻结或确认记录；Phase 12 只增加自己的审计输出。 |
| API 与数据服务 | `src/lowalt6g/api.py`、`phase6_api.py`、`phase6_demo.py` | HTTP GET 和场景/种子 ID | 健康状态、Phase 2/5 指标、Phase 3/6 已生成回放 JSON | 只读、离线；不接收控制命令、不运行策略、不接收基站遥测。 |
| 展示与交互 | `frontend/src/App.tsx`、`data.tsx`、`pages.tsx`、`Phase6DemoPage.tsx`、`types.ts` | 现有 API JSON 与保存帧 | 首页、指挥/决策/实验/演示路由和离散回放 | 当前 UI 消费 Phase 2/5/6 数据；Phase 8–11 原始确认集尚未进入交互页面。 |

完整模块的输入、输出、依赖、状态和证据路径逐项记录在 [`module_inventory.json`](../phase12/module_inventory.json)，并由 Phase 12 审计脚本检查路径是否存在。

## 策略清单

| 策略 | 当前实际机制 | 主要位置 | 明确限制 |
|---|---|---|---|
| A | 不部署无人机的无恢复对照 | `dynamic_simulation.py::_NoRecoveryController` | 地面网络自身仍可能服务仍健康且可达的用户；A 并不等于“网络全部断开”。 |
| B | 首次观测时进行静态网格搜索，后续保留同一目标；历史规划能耗边界较弱 | `policies.py::GreedyRelayPolicy`、`dynamic_simulation.py::_StaticGridController` | 保留为历史比较策略，不能和 B′ 的安全约束含义混同。 |
| B′ | 一次性网格选址，并使用共享 sortie 能耗、健康回传可达性和返航储备检查 | `dynamic_simulation.py::_SafeStaticGridController`、`energy_budget.py::sortie_energy_wh` | 单无人机强基线，非全局最优策略。 |
| C | 加权滚动候选搜索，按配置周期重新规划 | `optimizer.py::RollingHorizonOptimizer` | Phase 8/9 的动态故障结果显示，规划复杂度没有转化为稳定服务优势。 |
| D | 救援优先的词典序滚动优化 | `optimizer.py::RescuePriorityOptimizer`、`phase8_d_optimizer.py` | 规则/优化算法，不是训练模型；未证明普遍优于 B/B′。 |
| E | 对已观察到的状态事件触发重规划，包含事件去重、冷却和超时保护 | `phase9_strategy_e.py::EventDrivenController` | 不使用未来故障表；确认实验未超过动态故障场景 B′。 |
| F | 按 UAV 逐个独立排序动作，再由共享机队安全仲裁处理间距冲突 | `multi_uav.py::plan_fleet` | 独立决策会遇到资源竞争；最终分配由共享引擎执行。 |
| G | 集中式有限候选联合搜索，带计算期限和共享资源评价 | `multi_uav.py::plan_fleet` | 在 Phase 11 动态故障三机队对 F 有显著收益，在高负载三机队则显著较差。 |
| H | 顺序选址并最大化唯一救援服务边际增益，每次重算共享资源 | `phase11_algorithms.py::plan_h_marginal_greedy` | 贪心顺序可能影响后续 UAV 的候选机会。 |
| I | 固定当前 UAV 位置，对可行端到端用户路径做有界救援优先分配 | `phase11_algorithms.py::plan_i_constrained_matching` | 用户资源分配基线，不规划 UAV 移动。 |
| J | 在 G 的每架 UAV 候选短名单上作限宽联合 beam search | `phase11_algorithms.py::plan_j_budgeted_joint_beam` | 搜索空间与 G 不完全相同，不能无条件声称等算力比较。 |

## 端到端数据与安全边界

1. 场景配置和种子经 `load_dynamic_config` 解析；`build_world_trace` 为同一场景/种子生成可复现环境轨迹。
2. 每个策略在当前时间片看到当前网络快照。动态事件由 `dynamic_simulation.py` 应用；Phase 9 E 根据当前变化触发决策，不读取未来计划事件。
3. 策略返回的是动作建议。执行器和共享网络分配器再验证移动、距离、容量、电量、返航储备、用户唯一服务及 UAV 最小间距。
4. 仿真结果由 phase-specific experiment runner 写入新的逐种子 JSON，并在确认方案/清单中保留哈希、种子、配置、轨迹和策略运行数。
5. `api.py` 与 `phase6_api.py` 只读现有结果。React 展示存档帧，不向策略发控制命令。
6. Phase 12 通过 Phase 5/8/9/10/11 的冻结清单校验历史数据，并只写新的 `results/phase12_integrity_audit.json` 与本阶段文档/图。

## 历史结果核验摘要

- Phase 5：实际审计覆盖 4 场景、80 个留出种子、400 次策略运行；冻结清单审计结果及各场景文件哈希见 [`results/phase12_integrity_audit.json`](../../results/phase12_integrity_audit.json)。
- Phase 8：敏感性确认记录 80 个种子、2,000 次策略运行；审计文件报告零电量储备违规、零时延样本计数差异、零缺少 trace hash、零无时间戳环境事件。
- Phase 9：确认集覆盖 80 个种子、480 次策略运行。动态故障中，E 的救援服务率均值 13.15%，B′ 为 20.19%；E 的持续 30 秒恢复为 0/20，B′ 为 12/20。E 决策总耗时均值约 802.5 ms，B′ 约 249.5 ms。上述结果不支持“事件触发必然提升恢复”的主张。
- Phase 10：4 场景、80 个种子、400 次策略运行；Phase 11 冻结校验检查 15 个 Phase 10 工件，0 个哈希差异、0 个轨迹不匹配。
- Phase 11：4 场景、80 个留出种子、880 次策略运行；确认清单记录 0 条轨迹不匹配、0 次速度/边界/机间距/容量/重复用户服务违规和 0 次决策超时。
- Phase 11 的三机队 G 相对 F：动态故障救援服务率高 2.38 个百分点，95% 配对区间为 1.54–3.21 个百分点，Holm 校正后 p=0.000916；高负载回传受限场景 G 相对 F 低 3.99 个百分点，95% 配对区间为 2.37–5.60 个百分点（按 F−G 差值），Holm 校正后 p=0.004799。结论只适用于对应抽象场景与配置。

## 兼容与已知缺口

- 保留原有 API 路由：`/api/health`、`/api/experiments/phase2`、`/api/experiments/phase5`、`/api/experiments/phase5/{scenario_id}`、`/api/replay/{seed}`、`/api/demo/phase6` 和 `/api/demo/phase6/{scenario_id}`。
- 前端保留 `/`、`/command`、`/decision`、`/lab`、`/demo` 路由；本阶段不修改其视觉与交互实现。
- 当前根目录没有 `PHASE7_REPORT.md`。Phase 12 不据此推断 Phase 7 是否做过，只记录审计材料缺口。
- 本系统缺少真实物理网络对应物、实时数据采集与同步、射频/协议层模型、数字孪生物理映射校准，以及设备实测参数。按 ETSI ZSM 的定义，只有离散回放还不能证明已具备持续映射物理网络状态的 Network Digital Twin。
