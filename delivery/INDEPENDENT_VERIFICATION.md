# 独立解压验收记录

## 独立副本身份

验收对象为从 `6G-RESCUE-改进版-20261022.zip` 解压至 `6G-RESCUE-签收复验-20261022/6G-RESCUE` 的副本，不是原工程目录。解压器检查 ZIP CRC、成员路径与包内清单。第一版归档因未含最终清单而作废；修正后第一份清单归档 SHA-256 为 `fe69a8d0087fc7dd8e58cf2b0b7400f61c2d9a970da2e9b3f89d05cb73b12a9a`。该历史包不作为交付，最终包校验值以 ZIP 同目录 `.zip.sha256` 为准。

## 结果

- 最终 ZIP 清单核对：652 个项目文件大小和 SHA-256 全部匹配，`SHA256SUMS.txt` 653 条校验记录全部通过；`scripts/verify_package.py` 返回成功。Python 环境准备生成的 `*.egg-info` 目录按清单、归档和复验脚本统一排除。ZIP 成员为单一 `6G-RESCUE/` 根目录，归档器 CRC 与安全路径检查通过。
- 未准备环境时运行启动器：预期退出码 1，明确提示先执行 `prepare_environment.cmd`；未终止其他进程。
- 独立副本执行锁定环境准备：`uv sync --locked --all-extras` 成功，`npm ci` 安装 133 个前端包，npm audit 报告 0 vulnerabilities。固定运行时及缓存从本机缓存复制到临时解压副本，运行环境本身仍由交付脚本重建；日志 `independent-final-prepare.log`。依赖源首次受网络 DNS 限制，使用授权网络环境完成准备。
- 独立副本启动器：5 秒后正常退出（码 0），API 契约和 health 均通过；实际 UI/API 地址记录于 `independent-final-startup.log`。普通沙盒子进程未能绑定环回 API；在获准的本机环回执行中复验成功。
- 独立副本 Playwright：完整 40/40 通过，23.9 秒；覆盖完整核心浏览器流程。日志 `independent-final-e2e.log`。

此记录对应交付目录中最终归档的独立解压复验。原 Reviewer Kit 和冻结实验材料仍按 `ORIGINAL_PACKAGE_REFERENCE.md` 所列哈希保全。外层 ZIP 的校验值见同目录 `.zip.sha256`，不写入包内以避免循环哈希。
