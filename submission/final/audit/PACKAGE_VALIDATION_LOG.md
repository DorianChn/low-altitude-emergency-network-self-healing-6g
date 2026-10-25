# 候选包独立验证与修复记录

日期：2026-10-21。历史 Phase 18 release manifest 与冻结实验文件未改写。下文的临时副本位于系统 Temp 目录，最终压缩包使用独立 `PACKAGE_MANIFEST.json` 和 `SHA256SUMS.txt`。

## 发现并修复的打包缺项

| 验证轮次 | 实际失败 | 归因 | 修复 |
|---|---|---|---|
| 初始离线依赖同步 | 只安装 `dev` 时，FastAPI API 测试在收集阶段报 `ModuleNotFoundError` | 安装说明没有包含 API extra | 测试命令改为 `uv sync --frozen --offline --all-extras --all-groups`；Windows 缺依赖提示包含 `--extra api --extra dev` |
| 初始 Python 测试 | 191 passed、2 failed：缺 `DEVELOPMENT_LOG_PHASE10.md`；Phase18 API 返回 503（缺 release manifest） | 旧 446 项历史 allowlist 未收录后续运行支持文件 | 新候选加入所有 `DEVELOPMENT_LOG_PHASE*.md` 和 `results/phase18/**`；旧清单不变 |
| 前端清单轮次 | 构建无法读取 `frontend/tsconfig.json`，lint 配置未打包 | 旧 allowlist 不完整 | 新候选从前端源树收录构建、lint、测试配置及源代码，排除 `node_modules`、`dist`、测试输出 |
| 前端资源轮次 | Vite 无法解析 `../../assets/mumbai-night-city-18219784390.jpg` | 页面引用的根级运行图片未在旧 allowlist | 新候选加入该明确运行资源，未改页面 import 或替换视觉素材 |

失败原始日志：`logs/package-python-test-missing-api.log`、`logs/package-python-test.log`、`logs/package-build.log`、`logs/package-build-missing-asset.log`。初次失败 lint 日志因扫描整份 `node_modules` 达约 8 MB，未纳入候选包；失败原因是缺少该目录级配置，不是产品 lint 发现。最终 lint 结果见 `logs/package-lint-final.log`。

## 修复后隔离副本结果

验证副本：`<LOCAL_PATH_REDACTED>\AppData\Local\Temp\lowalt6g-phase18-stage-b45cf3d4b49344ce9e6fba68a3b0a233`。该副本按新的候选包源清单组装，未包含 Python/Node 运行时或依赖目录；安装使用当前电脑已有缓存，所以证明的是同机离线缓存下可复现，不证明全新机器无需联网即可安装。

| 检查 | 结果 |
|---|---|
| `uv sync --frozen --offline --all-extras --all-groups` | PASS |
| `uv run --frozen --offline python -m pytest -q` | 193 passed，0 failed，48.71 秒 |
| `npm ci --offline --ignore-scripts --prefix frontend` | PASS，134 个依赖条目，0 漏洞 |
| Vitest | 17 passed，5 个测试文件 |
| Oxlint | PASS，exit 0 |
| TypeScript/Vite production build | PASS，ECharts chunk 533.66 kB，保留体积提示 |
| Playwright | 30 passed，22.6 秒 |
| Windows 一键演示 | PASS：健康检查、页面响应、正常停止本脚本启动的服务 |
| API 直接 smoke | PASS：health 为 ok；Phase18 摘要及 3 个 supporting artifacts 可读取 |
| 候选包高置信凭据扫描 | PASS，556 个源文件，0 项发现 |

ZIP CRC、清单/校验和、完整解压和抽取后运行检查状态由 `audit/package_validation.json` 与 `audit/final_acceptance.json` 记录；只有验证器实际完成后才更新状态。

## 边界

旧 `results/phase18/phase18_release_manifest.json` 描述历史候选，不被重新签发。历史实验完整性和旧 Phase18 发布文件完整性是不同结论：保护实验记录按其对应清单匹配；旧 Phase18 候选仍有已明确列出的哈希漂移。当前候选有新的独立清单，不覆盖旧记录。

## 独立 ZIP 解压复测

2026-10-21 又从临时审阅 ZIP 新建解压副本，并从该副本运行：离线 `uv sync`、pytest 193 passed、`npm ci`、Vitest 17 passed、Oxlint、TypeScript/Vite build、Playwright 30 passed、Windows 启动/健康检查/关闭。所有命令输出见 `logs/package-extracted-*.log`。依赖来自本机缓存；未测试新装、无缓存或物理断网环境。

第一次独立 ZIP 验证器运行正确检测出它自己把阶段报告写成 `submission/final/PHASE18_REPORT.md`，而项目阶段报告实际位于根目录 `PHASE18_REPORT.md`。已修正验证器的 key-file 路径并重新运行：CRC PASS、成员清单与 SHA-256 一致、路径安全、完整解压及关键文件检查 PASS。该问题属于审计脚本路径假设，不是项目包缺文件。最终重建后的正式本地审阅 ZIP 以相邻 `audit/package_validation.json` 中的最终哈希和状态为准。上述句子记录 2026-10-21 验证时的路径；当前仓库里的阶段报告在 `docs/phases/`。

最终交付目录 ZIP 已完成同一套复核，零差异，状态 PASS。最终包中 `submission/final/` 以外的469个载荷文件与已进行全套独立解压测试的临时 ZIP 大小及 SHA-256 全部相同；交付说明和审计资料在最终包中更新。精确压缩包哈希、大小、成员数和抽取路径以旁置 `audit/package_validation.json` 为准。
