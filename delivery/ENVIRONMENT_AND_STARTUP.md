# 环境准备与启动

## 支持环境

Windows 10/11、PowerShell 7 或 Windows PowerShell；联网仅用于第一次准备所需的官方固定版本分发包和锁定依赖。准备脚本会验证下载 SHA-256。前端演示绑定 `127.0.0.1`，不向局域网开放。

## 首次准备

在项目根目录双击 `prepare_environment.cmd`，或在 PowerShell 执行：

```powershell
.\scripts\prepare_environment.ps1
```

准备内容：Python 3.12、Node.js 24.19.0、npm 11、uv 0.13.4、`uv sync --locked --all-extras` 和 `npm ci`。工具和依赖位于 `.runtime`、`frontend/node_modules`；无需写入系统 PATH。日志在 `.runtime/logs`。

## 启动

双击根目录 `start_demo.cmd`，或运行：

```powershell
.\scripts\start_demo.ps1
```

启动后终端显示本机演示 URL 与 API 健康检查地址，默认打开浏览器。按 Q 可退出。端口占用时启动器报告冲突并安全退出，可指定空闲端口：

```powershell
.\scripts\start_demo.ps1 -ApiPort 18123 -FrontendPort 15197
```

项目只绑定 loopback。退出时启动器结束自己创建的前端/API 进程树并保留日志。运行时 `.runtime` 不打包，解压后的副本需先执行准备脚本。

## 演示操作

首页选择“5 分钟演示”进入 Phase 6；场景下拉菜单切换四个保存回放，时间滑块和播放控制逐个展示保存帧。空格播放/暂停、左右键逐帧；焦点在按钮/表单时热键不起作用。事件可切换关键/全部记录，未知字段能展开查看。数据说明面板说明单个种子回放与多种子研究汇总的区别。研究工作台用于查阅各阶段冻结证据，不与当前演示帧混用。

## 已验证工具版本

Python 3.12.10；Node.js 24.19.0；npm 11.17.0；uv 0.13.4。完整环境记录见 `environment-final.json`。建议更换/升级依赖后重新执行前端和 Python 测试。
