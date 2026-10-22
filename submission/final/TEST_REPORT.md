# 测试与运行报告

核验环境：Windows 11、Python 3.12（uv）、Node.js 22、Edge/Chromium 与 Playwright。以下结果只证明列出的本机软件检查。

| 检查 | 实际结果 | 证据 |
|---|---|---|
| Python 全量 pytest | 193 passed，0 failed，0 skipped，45.98 s | `audit/logs/pytest-final-rerun.log` |
| React/Vitest | 17 passed，5 个测试文件 | `audit/logs/vitest-final.log` |
| Oxlint | exit 0，0 warnings | `audit/logs/lint-final.log` |
| TypeScript/Vite production build | exit 0；ECharts chunk 533.66 kB，超过 500 kB 建议线 | `audit/logs/build-final.log` |
| Playwright E2E | 30 passed，六路由、回放、策略/场景切换及窄屏导航 | `audit/logs/playwright-final.log` |
| 独立浏览器视口审计 | 6 路由 × 3 视口 = 18；HTTP 200，无 page/console error 和水平溢出 | `audit/screenshots/browser-audit.json` |
| 手机导航 | 320/375/390/414 px 断言通过 | Playwright 日志 |
| Windows 启动 | API/页面健康检查、正常关闭通过；只清理本次启动的服务 | `audit/logs/windows-startup-final.log` |
| npm audit | 197 个依赖，0 项已知漏洞 | `audit/logs/npm-audit-final.json` |
| uv audit | pytest 8.4.2 开发依赖存在公告，exit 1；修复版为 9.0.3 | `audit/logs/uv-audit-final-clean.json` |
| Impeccable detector | 0 primary findings | `audit/logs/impeccable-final.json` |
| 方案 PDF | 5 页 A4、160,373 bytes；题名17字、摘要351个 CJK 字符，逐页检查 | `audit/logs/proposal-render-final.log`、`audit/document-render/proposal-summary-final/` |
| 答辩 PDF | 16 页；修正第13页指标卡后逐页渲染检查 | `audit/logs/presentation-render-final.log`、`audit/document-render/deck-fix-13.png` |
| 佐证材料 PDF | 6 页、2,105,744 bytes；页面/图表/表格逐页检查，无明显裁切或重叠 | `audit/logs/evidence-pdf-render-final.log`、`audit/document-render/evidence-final/` |
| 演示 MP4 | 1920×1080、H.264/AAC、约4:24、8,783,029 bytes；本机页面回放录制，无浏览器错误 | `audit/logs/video-encode-final.log`、`audit/document-render/video-contact-sheet.png`、`VIDEO_SCRIPT.md` |

## 候选 ZIP 解压复测

由独立临时候选 ZIP 解压的副本，依次通过离线安装、193 项 pytest、npm ci、17 项 Vitest、Oxlint、Vite build、30 项 Playwright E2E、Windows 启动/停止。依赖安装使用本机缓存，不能代表全新无缓存设备离线安装。最终交付 ZIP 已单独完成 CRC、成员清单、每文件 SHA-256、安全路径及完整解压核验，结果为 PASS。比较最终 ZIP 与测试 ZIP 的清单后，排除 `submission/final/` 交付文档和审计记录，剩余469个载荷文件大小和SHA-256完全一致；也就是实测运行源码、配置和实验文件与最终包一致。最终压缩包哈希及解压位置见交付目录旁置的 `audit/package_validation.json`。

复测日志：`audit/logs/package-extracted-uv-sync.log`、`package-extracted-pytest.log`、`package-extracted-npm-ci.log`、`package-extracted-vitest.log`、`package-extracted-lint.log`、`package-extracted-build.log`、`package-extracted-playwright.log`、`package-extracted-windows-startup.log`。候选包缺项修复过程见 `audit/PACKAGE_VALIDATION_LOG.md`。

## 已知限制

- `uv audit` 中 pytest 8.4.2 的公告描述涉及 Unix `/tmp/pytest-of-{user}` 临时目录语义；本轮 Windows 测试通过，但跨平台开发依赖风险未在本阶段升级处理。
- ECharts 体积提示保留；coverage 工具未安装，也未运行覆盖率测试。
- PDF 通过同内容 HTML/Edge 渲染并对照检查，不是 Microsoft Word/PowerPoint 原生渲染。
- 未测无缓存干净机器、物理断网现场、第二台 Windows 设备、真实 HIL、飞行、射频发射或项目目标设备校准。
- 视频合成旁白须由团队听审；队伍须按赛事规定披露 AI 辅助。
- 以上软件结果不构成真实 6G 网络或设备测试。
