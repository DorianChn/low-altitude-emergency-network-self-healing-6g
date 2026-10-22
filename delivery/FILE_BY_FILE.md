# 逐文件变更摘要

完整机器可读清单 `BASELINE_DIFF.json` 按路径记录了相对原始候选的新增、修改、删除状态、原/新大小及 SHA-256；`FINAL_MANIFEST.json` 列出 ZIP 中每个文件的大小和 SHA-256。以下按职责归类，机器清单覆盖所有文件。

| 文件或范围 | 改动 |
|---|---|
| `README.md`, `PACKAGE_README.md`, `frontend/README.md`, `submission/final/DEMO_GUIDE.md` | 统一准确启动脚本名、五分钟流程、页面路由、数据口径和回放操作。 |
| `prepare_environment.cmd`, `scripts/prepare_environment.ps1` | 下载校验固定工具链，准备 Python/Node/uv、锁定 Python 依赖、执行 npm ci 并记录环境。 |
| `start_demo.cmd`, `scripts/start_demo.ps1` | 自动端口、启动健康检查、演示数据契约校验、进程树清理与日志记录。 |
| `pyproject.toml`, `uv.lock` | 锁定 pytest 安全修复版本。 |
| `frontend/src/current-data-context.tsx`, `CurrentPageDataProvider.tsx`, `useCurrentPageData.ts` | 页面所有权和当前数据上下文状态。 |
| `frontend/src` 中回放 provider、键盘钩子、页头、Phase 6 演示与研究组件/样式 | 上下文隔离、热键边界、事件解释、指标口径、首次使用和窄屏体验。 |
| `frontend/src/test`、新增上下文/热键测试 | 单元回归覆盖。 |
| `frontend/e2e/phase6-demo.spec.ts`, Playwright 配置 | 页面、场景、研究来源、响应式、键盘、首屏和回放速度浏览器验收。 |
| `frontend/measure_performance.mjs` | 固定三次冷加载、120 次热场景切换、资源量和 JS 堆采样。 |
| `frontend/soak_test.mjs` | 30 分钟场景/路由持续切换及逐分钟 API/页面/heap 记录。 |
| `scripts/package_project.py`, `scripts/verify_package.py`, `delivery/generate_manifests.ps1` | ZIP 归档/安全解压与 CRC 检查；解压后逐文件大小和 SHA-256 核验；一致排除运行时、缓存、可再生构建产物及 Python `*.egg-info`。 |
| `delivery/` | 原始候选基线、性能样本、启动轮次、冲突验收、最终说明、测试矩阵、逐文件清单与截图。 |
| 其他文件 | 逐一以 `BASELINE_DIFF.json` 的哈希/状态为准；仅排除可重生的旧 `frontend/dist` 构建和 `frontend/playwright-report` 页面，不打包；未改动的冻结数据和证据仍列入最终文件清单。 |

`BASELINE_DIFF.json`、清单和报告属于本次新增交付记录；包自身的 `FINAL_MANIFEST.json` 和 `SHA256SUMS.txt` 不对自身做递归哈希，规则写在文件头部。
