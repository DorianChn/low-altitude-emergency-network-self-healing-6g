# 改进交付材料索引

- `ACCEPTANCE_REPORT.md`：验收结论、真实执行结果和未完成项。
- `CHANGELOG.md`：功能改动与安全/依赖说明。
- `FILE_BY_FILE.md`、`BASELINE_DIFF.json`：逐文件状态及原、新 SHA-256。
- `FINAL_MANIFEST.json`、`SHA256SUMS.txt`：包内逐文件大小和哈希；manifest 与 sums 的自校验排除规则见各文件说明。
- `ENVIRONMENT_AND_STARTUP.md`、`environment-final.json`：运行环境、首次准备和本机启动步骤。
- `TEST_MATRIX_T01-T29.md`：执行提示词内每个测试 ID 的状态、覆盖边界和证据。
- `PERFORMANCE.md`、`performance-baseline.json`、`performance-final.json`、`performance-summary.json`：原始性能样本和对比。
- `startup-10-rounds.json`、`port-conflict*.log/json`、`soak-progress.jsonl`：启动稳定、端口安全及 30 分钟运行的原始记录。
- `*-final.log`、`pytest-partial-interrupted.log`：单测、静态检查、构建、浏览器及 Python 部分执行输出。
- `screenshots/`：桌面、笔记本和窄屏演示/研究页截图。
- `independent-final-prepare.log`、`independent-final-startup.log`、`independent-final-e2e.log`：最终候选 ZIP 独立解压后的锁文件准备、启动健康检查和完整 40 项浏览器验收原始输出。
- `KNOWN_LIMITATIONS.md`：技术限制、未验收事项和用户豁免边界。
- `ORIGINAL_PACKAGE_REFERENCE.md`、`BASELINE_MANIFEST.json`：原包身份、校验和及冻结材料保全依据。
- 两份传入的项目改进提示词原文随附在本目录，便于逐项追溯。

外层改进 ZIP 的最终 SHA-256 写在 ZIP 同目录的 `.zip.sha256` 文件中；该外部哈希不写入包内以免产生自指循环。
`scripts/verify_package.py`：解压后逐文件清单和 SHA-256 校验。
`TEST_RUN_HISTORY.md` explains the captured first attempts and their corrections. `playwright-first-attempt.log` and `pytest-partial-interrupted.log` are diagnostic history; the final authoritative results are `playwright-final.log` and `pytest-final-full.log`.
`INDEPENDENT_VERIFICATION.md` 记录从 ZIP 新解压目录执行环境准备、启动和浏览器复验；独立副本测试原始日志以 `independent-` 开头。
