# 测试运行历史与更正

- Windows 沙盒下的第一次 Python 全量运行在 21 项已显示通过后停留于 `tests/test_phase13_api.py`。延时堆栈确认 Python 3.12 asyncio 在 `socket.accept` 创建 self-pipe 时受本机沙盒限制。原片段见 `pytest-partial-interrupted.log`。本机提升权限用同一环境重跑全量后，`pytest-final-full.log` 记录 193/193 通过（44.95 秒）。
- 新增未知事件浏览器用例的首次运行为 39/40：检查器把原始冻结回放中原有的一条未知记录也计入测试断言。确认 UI 正确显示三条后，将断言收窄到两条合成记录的唯一 `target_id`，最终 40/40 通过。首次输出保存在 `playwright-first-attempt.log`；最终输出保存在 `playwright-final.log`。
- 对 Phase 13 子集和排除该文件后的 Python 子集曾做定位尝试，定位到相同 Windows self-pipe 限制；这些没有替代最终全量报告，也没有据此修改应用或冻结数据。
- 独立解压检查首轮 ZIP 时发现打包脚本意外排除了包内 `FINAL_MANIFEST.json` 与 `SHA256SUMS.txt`。已修正归档器保留这两份交付文件；该首轮 ZIP 不作为最终交付，最终 ZIP 会重新生成并从头复验。

- 最终独立复验发现 `uv sync` 会改写 Python 生成的 `*.egg-info/PKG-INFO`，使复验副本哈希与固定 ZIP 清单不一致。将 `*.egg-info` 作为生成元数据同时从 manifest、归档和 verify 脚本排除；重新打包后，环境准备后的独立副本再次逐文件校验成功，启动和 Playwright 40/40 通过。
