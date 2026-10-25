# Phase 18 可复现性说明

## 运行方式

历史确认实验不在 Phase 18 中重新执行，因为本阶段的任务是冻结历史审计、系统验收和最终材料，不覆盖或重写阶段数据。审计可用以下命令重复：

```powershell
uv run --frozen --offline python scripts/run_phase18_final_audit.py
uv run --frozen --offline python scripts/build_phase18_validation_summary.py
uv run --frozen --offline pytest
Set-Location frontend
npm run test
npm run lint
npm run build
npm run test:e2e -- --grep "Phase 18"
```

## 实验复现依据

逐阶段配置、种子、源码/配置哈希、策略原始行和场景轨迹哈希仍使用各阶段原有文件。Phase 18 不把不同阶段样本混成新实验。跨阶段审计脚本只核查已存行数、策略数、配对种子/轨迹约束和历史清单。

关键已存确认批次：Phase 5 为 80 个场景种子组、400 策略运行；Phase 8 消融/敏感性分别 40 条记录和 80 条记录；Phase 9 为 80 个种子组、480 运行；Phase 10 为 80 个种子、400 运行；Phase 11 为 80 个种子、880 运行；Phase 14 为 80 条轨迹组、480 策略/链路模型运行。

## 计时与统计注意事项

恢复时间是仿真时间，算法决策耗时是主机墙钟时间，两者不可混为一谈。恢复时间须同时报告成功运行数/总数并对失败运行用预先定义的删失终点处理。条件时延只在成功连接样本计算，并显示样本量；不同策略的成功样本可能不同，不可直接当作同一批用户的配对时延改进。多策略结论按场景分层并保留多重比较校正。

## 复现边界

目前无法通过一条统一命令从干净提交重建所有历史阶段，因为现有工作区混合了多阶段代码演进和未提交文件，且没有远程仓库配置。审计可以复核当前可用数据，但“全历史软件环境完全可重建”尚未证明。
