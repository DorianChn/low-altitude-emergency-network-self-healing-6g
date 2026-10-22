# 验收矩阵（T01–T29）

状态只按本次有记录的真实执行填写。前端原始日志在 `vitest-final.log`、`lint-final.log`、`build-final.log`、`playwright-final.log`；Python 全量结果在 `pytest-final-full.log`。首次受限沙盒尝试与最终获准的本机运行分开记录，不能把中断尝试算成测试失败或通过。

| ID | 状态 | 验收点与证据 |
|---|---|---|
| T01 | PASS | 四个冻结 Phase 6 场景及种子逐一加载，最终 Playwright 40/40。 |
| T02 | PASS | 六条旧路由及研究路由存在；选定数据来源与当前页面上下文匹配。 |
| T03 | PASS | 演示页不请求历史回放；研究页显示多种子摘要，不复用演示帧。 |
| T04 | PASS | 延迟旧场景响应测试：切换到最新场景后旧响应不能覆盖当前数据（Playwright）。 |
| T05 | PASS | 空格和方向键逐帧/播放控制，停用路由不响应；焦点与重复按键边界有自动化覆盖。 |
| T06 | PASS | 按钮/表单/链接/contenteditable、Ctrl/Alt/Meta 组合键、输入法组合和重复键不触发页面热键；见 Vitest 与 Playwright。 |
| T07 | PASS | 页面隐藏、路由停用和卸载暂停；页面数据 owner 清理单测及浏览器测试通过。 |
| T08 | PASS | 五分钟演示步骤与实际根目录脚本、场景、路由和数据口径一致；演示指南已更新。 |
| T09 | PASS | 独立启停十轮，10/10 返回码 0；平均 2.497 秒，见 `startup-10-rounds.json`。 |
| T10 | PARTIAL | 冻结数据缺失状态、API 契约/健康检查和独立副本缺少 `.runtime` 时的可恢复报错均验证通过；未分别注入每一种损坏依赖。 |
| T11 | PARTIAL | 含空格路径启动、端口已占用安全退出、两个启动器并发获四个互异端口均通过；只读 ACL 目录未单独测试。 |
| T12 | PASS | 端口冲突后监听器与父会话哨兵仍存活；`port-conflict-result.json`。 |
| T13 | PASS | 关键/全部事件、同一时间戳的多条事件、首尾导航边界通过；专用用例注入了同刻事件。 |
| T14 | PASS | 未知事件显示原始 JSON；无事件场景显示真实空态。Playwright 注入测试通过。 |
| T15 | PASS | 动态分母、样本范围、条件 P95 和 Phase 15 等组/合并样本差异通过前端单测与浏览器检查。 |
| T16 | PASS | 0.5×–4× 按保存帧播放；切换场景重置时钟。 |
| T17 | PASS | 演示与研究页 1920×1080、1366×768、390×844；320/375/414 导航标签布局；截图见 `screenshots/`。 |
| T18 | PARTIAL | 键盘焦点与 prefers-reduced-motion 通过；浏览器缩放组合未单独自动化。 |
| T19 | NOT_TESTED / 豁免 | 真实用户参与及个人信息/报名按用户指定范围豁免；未虚构参与人或签核。 |
| T20 | PASS | 全部 193 项 Python 测试通过（44.95 秒）；6 条 NumPy 零方差相关系数运行警告，无失败断言。 |
| T21 | PASS | 独立 ZIP 解压副本执行锁定 Python 依赖和 npm ci，133 个前端包安装、0 vulnerabilities；固定工具 SHA 校验和生产构建均通过；环境记录见 `environment-final.json`。 |
| T22 | PASS | 最终生产构建上冷加载 3 样本、热切换 120 样本；见性能报告及 JSON。 |
| T23 | N/A | 未新增数据缓存，无缓存失效逻辑。 |
| T24 | PASS | Vite 开发服务和冻结 API 连续 30 分钟：1,072 次场景/路由轮换、2,147 个 API 响应、0 个页面/API 错误；JS heap 分钟样本69.7–162.7 MiB并多次回落。原始序列见 `soak-progress.jsonl`。 |
| T25 | PASS | 原候选 620 文件：569 原样、23 修改、28 个旧生成 `frontend/dist`/`frontend/playwright-report` 文件不打包；62 项新交付物。Phase 15 冻结输入/输出逐文件 SHA-256 一致。详见 `BASELINE_DIFF.json`。 |
| T26 | PASS | Python 193/193、Vitest 21/21、Oxlint 0 错误、生产构建通过、Playwright 40/40。 |
| T27 | PASS | 最终 ZIP 独立解压后，ZIP CRC/路径安全通过；652 个项目文件、653 条 SHA 校验记录全部匹配，外层 SHA-256 与 sidecar 一致；uv 生成的 `*.egg-info` 按规则排除。 |
| T28 | PASS | 最终 ZIP 独立解压副本完成锁文件环境准备；未准备时报错退出码 1；5 秒启动退出码 0；Playwright 40/40（23.9 秒）。准备/启动/E2E 日志以 `independent-final-*` 命名。 |
| T29 | PASS | ZIP 内含改动说明、机器可读逐文件差异与哈希、测试/环境/性能/限制报告、全部独立复验日志和启动方法；最终包完整性及独立运行验收通过。 |

## Python 沙盒运行说明

普通受限会话中，Windows Python 在创建 asyncio 本机 self-pipe 时停留于 `socket.accept`；这发生在首个 Phase 13 API 测试执行前，不是失败断言。之后使用本机提升权限重新运行了同一份全量 pytest，**193 项全部通过**。中断会话片段保留在 `pytest-partial-interrupted.log`，完整最终输出在 `pytest-final-full.log`。NumPy 的六条警告来自冻结 Phase 15 实验代码的零方差相关系数；为保护证据哈希，没有改动该代码或结果。
