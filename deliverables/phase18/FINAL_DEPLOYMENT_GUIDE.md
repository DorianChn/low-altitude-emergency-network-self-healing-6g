# 最终部署与离线启动指南

## 推荐运行环境

Windows 11，项目依赖已安装并缓存；要求 Python/uv、Node.js/npm 以及 `frontend/node_modules` 已就绪。应用使用 FastAPI 只读提供历史 JSON 和离线回放，React 页面由本地 Vite 服务提供。第一次安装依赖需要准备环境；现场离线演示只适用于已验证/预装依赖的机器。

## 一键启动

1. 在项目根目录运行 `scripts/start_demo.cmd`。
2. 等待脚本检查解释器、依赖、API/前端健康状态并打开默认浏览器。
3. 地址和实际日志以本次启动输出为准。首页/演示可进入，研究审计页地址为本地服务下 `/research`。
4. 关闭演示窗口或按脚本提示退出；脚本应只停止它自己创建的服务，不会关闭用户已复用的外部服务。

脚本默认交互模式中按 `Q` 或 `Ctrl+C` 退出。可选的 `-RunDurationSeconds N -NoBrowser` 参数用于验收自动退出和清理，不改变默认一键启动行为；例如：

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/start_demo.ps1 -RunDurationSeconds 5 -NoBrowser
```

脚本正常退出前不需要联网。若脚本报告依赖缺失或缓存不可用，不能把现场演示标为离线就绪。

## 独立调试

后端（使用已安装的项目 extra）：

```powershell
uv run --frozen --offline uvicorn lowalt6g.phase6_api:app --host 127.0.0.1 --port 8123
```

前端另开终端：

```powershell
Set-Location frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

检查 `http://127.0.0.1:8123/api/health` 与浏览器 `/research`。健康响应中的 `live_stream=false` 表明数据为离线保存记录。

## 故障排查

- **Python/uv 未找到：** 使用本机已安装的官方 Python/uv，先完成项目依赖安装；离线模式不会自动联网下载依赖。
- **Node/npm 未找到或版本不合：** 安装/准备项目要求版本；不要静默更改系统 PATH。
- **端口占用：** 读脚本打印的实际端口，停止本次脚本拥有的实例后重试；不要强制关闭未知 PID。
- **API 返回 503：** 核查 `results/` 对应 JSON；API fail-closed，不会用假数据补齐。
- **浏览器未打开：** 使用脚本打印的 URL 手动打开。
- **现场断网：** 先在目标电脑执行离线依赖核查和完整页面测试；本阶段没有验证第二台设备，因此不能据此承诺任何电脑均可离线运行。
