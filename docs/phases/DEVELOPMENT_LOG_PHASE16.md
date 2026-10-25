# Phase 16 开发记录

## 2026-10-21

1. 检查工作区：已有 213 项未提交变更。保留所有已有状态；从现有 HEAD 创建 `phase16-field-measurement-readiness`，未 reset/clean、未整体暂存、未提交/推送。
2. 开始时完整 Python 基线 120 项通过。Phase14/15 持久化审计均为 PASS，受保护清单 104 项，Phase15 14 个原始公开源哈希匹配。
3. 只读检查 Windows PnP 测量设备名称与串口：匹配仪器 0，串口 0。项目范围未发现目标设备测量、手册、证书或无线/飞行批准文件。该枚举有明确范围限制。
4. 导入 Phase15 公开清洗 CSV 的 Phase16 派生副本：1,370 行进入、1,370 行有效、拒绝 0、重复 0；输入 SHA-256 读前读后一致；原文件未写入。
5. 实现 Phase16 模块：单位区分、接收功率表达式、不确定度传播/协方差 PSD 检查、显式未知值、可复现 MC 分布分位数、配置门槛、只读数据导入、session 分组泄漏校验、证据状态机。
6. 初次 Phase16 定向测试有 1 个 API 测试期望错误文案与实际“文件不可用”不同；只修正测试断言以接受实际的安全不可用响应；没有放宽安全条件。会话校验器初次全量复测还发现检查被其他缺项短路，已改为独立检查每项频率/授权门槛，专测和全测通过。
7. 新增 Phase16 API read-only artifact envelope 和路径约束；增加 Research 工作台 Phase16 只读数据展示，所有数值读自保存结果文件。
8. 初次 E2E 因 `NOT_CALIBRATED` 文本命中两个语义正确位置触发 strict locator；将断言收窄到“目标设备校准”字段后通过。保存了 1920×1080、1366×768、390×844 截图；浏览器无页错误，三个宽度均无横向溢出。
9. 增加会话 JSON 模板验证 CLI；模板验证返回 NOT_READY，不会启动采集或访问硬件。添加 16 来源未知不确定度状态图；图中无假数值。
10. 重分析已存在 Phase14 exploratory sensitivity summary，写入 `results/phase16_exploratory_model_sensitivity_context.json`。该动作无新仿真，保留源结果哈希并限定解释边界。
11. 第一轮收尾 Python 全量为 148 passed / 53.80 s，随后状态机摘要加固增加 2 个用例。最终 Python 全量为 150 passed / 47.67 s（`results/phase16/pytest_junit_final_v2.xml`），Phase16 定向 30 passed（`pytest_targeted_junit_final_v2.xml`）。
12. 最终 Vitest 12 passed，Oxlint passed，TypeScript/Vite build passed（ECharts chunk >500 kB 警告）。在最终代码上完整 Playwright 19 passed；包含 Phase16 页面三种视口截图，并回归 Phase14/15 页面和 Phase6 路由。冻结哈希审计最终 104 项 PASS；Phase15 原始 14 个数据源与来源包匹配。
13. 校准状态机只接受明确标记的目标设备测量来源，并校验验收判据 SHA-256 与判据内容一致；新增公开数据误标和阈值篡改测试。无项目数据时状态仍为 `NOT_CALIBRATED`。

## 可复现命令

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest tests/test_phase16_measurement.py tests/test_phase16_api.py -q
.venv\Scripts\python.exe scripts/import_phase16_measurements.py results/phase15_measurements_public_clean.csv --source-type public_measurement --metadata-file configs/phase16/public_dataset_metadata.json --output-dir results/phase16/imports/<new-output-directory>
.venv\Scripts\python.exe scripts/build_phase16_readiness.py
.venv\Scripts\python.exe scripts/validate_phase16_session.py configs/phase16/measurement_session_template.json
.venv\Scripts\python.exe scripts/summarize_phase16_model_sensitivity_context.py
.venv\Scripts\python.exe scripts/plot_phase16_uncertainty_budget.py
cd frontend
npm test
npm run lint
npm run build
npm run test:e2e
```

导入命令输出目录必须是新目录；工具拒绝覆盖已有审计/清洗结果。数据导入读取本地冻结 Phase15 CSV，不需要下载数据或访问测量设备。
