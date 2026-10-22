# Phase 18 证据索引

证据清单 `results/phase18/phase18_evidence_manifest.json` 逐文件记录相对路径、字节数、SHA-256、来源阶段、证据类别、是否纳入本地 RC 和是否属于冻结历史数据。公共测量集的 14 个源文件留在原位置核验，并标记为不复制进 RC；本索引不声称拥有其再分发权。

## 主要证据组

| 主张 | 主要机器可读证据 | 对应解释文档 |
|---|---|---|
| 冻结历史未变 | `results/phase18/phase18_integrity_audit.json` → `protected_history.files` | `PHASE18_DATA_INTEGRITY_REPORT.md` |
| Phase 5–17 实验条目和运行数符合已保存文件 | 同上 → `raw_experiment_count_audit.checks` | `PHASE18_REPRODUCIBILITY_REPORT.md` |
| Phase 9/10/11 产物内容与历史清单相同 | `results/phase9_artifact_manifest.json`、`results/phase10_artifact_manifest.json`、`results/phase11_artifact_manifest.json` | `PHASE18_DATA_INTEGRITY_REPORT.md` |
| Phase 15 公共源文件未变化 | `results/phase18/phase18_integrity_audit.json` → `protected_history.phase15_public_sources` | `PHASE15_REPORT.md`、`PHASE18_KNOWN_ISSUES.md` |
| 研究结论含负面证据 | `results/phase2_20_seed_results.json`、`results/phase4_validation_4000_4019.json`、`results/phase8_replication_summary.json`、`results/phase9_corrected_confirmation_summary.json`、`results/phase11_confirmation_summary.json`、`results/phase14_confirmation_summary.json` | 各阶段报告与 `PHASE18_REPORT.md` |
| 设备校准状态 | `results/phase15_calibration_summary.json`、`results/phase16_measurement_readiness.json` | `FINAL_SCIENTIFIC_LIMITATIONS.md` |
| HIL 与回放状态 | `results/phase17_validation_summary.json` 及 `results/phase17/*.json` | `FINAL_DATA_PROVENANCE.md` |
| 测试/浏览器/启动证据 | `results/phase18/phase18_test_execution.json`、`results/phase18/browser/` | `PHASE18_FINAL_ACCEPTANCE_MATRIX.md` |

## 交付物结构

- 本目录根的 `PHASE18_*.md`：最终审计、完整性、验收、限制、复现和答辩口径。
- `deliverables/phase18/`：项目报告、架构、实验、限制、部署、用户手册、演示脚本、数据溯源、复现清单、需求追踪。
- `results/phase18/`：审计 JSON、证据清单、测试执行矩阵、验证摘要、RC 文件清单及浏览器截图。
- `frontend/src/Phase18ResearchSection.tsx`、`src/lowalt6g/api.py`：研究页和只读 API 实现。
- `scripts/run_phase18_final_audit.py`、`scripts/build_phase18_validation_summary.py`：可重复执行的审计和数据摘要生成器。

证据只支持它明确记录的范围。测试软件接口不能外推为无线发射、飞行安全或真实网络性能证据。
