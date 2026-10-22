# Phase 18 最终验收矩阵

验收状态应以 `results/phase18/phase18_test_execution.json` 的本次执行记录和浏览器截图为准。

| 验收项 | 状态 | 证据/判据 |
|---|---|---|
| 冻结文件哈希 | PASS | 182/182，与 Phase 17 保护启动清单逐项核对 |
| 本地候选清单内容哈希 | PASS | `scripts/verify_phase18_release_manifest.py` 对发布清单的文件大小、SHA-256、相对路径及原始数据排除项逐条复核 |
| Phase 9/10/11 产物清单 | PASS | 32/32、15/15、26/26 |
| 实验结构与配对记录 | PASS | 26/26 项通过；逐项细节见 `phase18_integrity_audit.json` |
| Python 完整测试 | PASS | `uv run --frozen --offline pytest -q`：193 passed、0 failed |
| Phase 18 API 合约 | PASS | 3 tests passed；哈希、503 fail-closed、历史只读路由 |
| 前端组件测试 | PASS | 5 test files、17 tests passed；含 Phase 18 3 项 |
| 前端 lint | PASS | oxlint exit code 0 |
| 前端生产构建 | PASS_WITH_WARNING | TypeScript/Vite exit code 0；ECharts chunk 533.66 kB advisory |
| 浏览器 E2E | PASS | 27/27 passed；包括 `/research` 数值一致、证据跳转、Phase 6 四场景和历史页面 |
| 响应式布局 | PASS | 1920×1080、1366×768、390×844，无页面级水平溢出；Phase 18 截图已保存 |
| 本地启动/关闭 | PASS | Windows 11 一键入口实际启动；API/页面状态 200；限时验收退出0并关闭两项自有服务端口 |
| 第二台设备/现场网络 | NOT_TESTED | 本阶段未在另一台机器或正式比赛场地验证 |
| 设备校准/外场测量 | NOT_READY | Phase 16 状态 `NOT_READY_FOR_FIELD_MEASUREMENT`，设备测量为 0 |
| 物理 HIL | NOT_TESTED | Phase 17 仅软件闭环和保存回放；真实设备/驱动未接入 |
| Phase 7 | NOT_ASSESSABLE | 缺少历史证据 |
| Git 干净交付 | BLOCKED_BY_MIXED_WORKTREE | 大量跨阶段未提交状态，无法安全创建仅含 Phase 18 的提交 |

**总体判断：** 软件/离线演示验收通过（构建体积提示单列）；完整科研/设备发布仍为 CONDITIONAL。开放项目不应由界面颜色或首页动画覆盖。

