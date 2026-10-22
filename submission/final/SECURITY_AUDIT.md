# 安全、依赖与许可审计

- npm audit --json：frontend/package-lock.json 范围 197 包，0 漏洞，2026-10-21；日志 audit/logs/npm-audit-final.json。
- uv audit：36 包，pytest 8.4.2 的 GHSA-6w46-j5rx-g56g / CVE-2025-71176 / PYSEC-2026-1845 各两条别名记录，实际为同一公告；影响描述是 pytest≤9.0.2 在 Unix 使用 /tmp/pytest-of-{user} 目录语义，修复版 9.0.3。本次 Windows 测试通过，但跨平台风险仍在；没有擅自改锁文件。日志 audit/logs/uv-audit-final-clean.json。
- FastAPI 暴露 health、experiments、research、replay、plots 等只读 GET 路由；Phase18 测试含文件哈希、缺失数据 fail-closed 等契约。
- 发布 allowlist 对 .env、私钥和凭证模式进行扫描，敏感值不写入报告。
- Windows 脚本动态分配端口并按进程 ID 清理本次自有服务，不改系统策略。
- Phase17 hardware_output_enabled=false；无真实设备。

许可：根目录未发现 LICENSE/COPYING/NOTICE；首页 CC BY-SA 2.0 照片已有署名；公开数据 CC BY 4.0；依赖许可证标识在锁文件。源码权属与混合许可需权利人确认。npm 扫描通过，Python audit 有一项开发依赖风险，因此整体安全并非全绿。