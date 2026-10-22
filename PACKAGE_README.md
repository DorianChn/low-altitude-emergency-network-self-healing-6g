# 6G / RESCUE 本地审阅候选包

状态：本地审阅候选，不是正式发布，也未提交赛事平台。

## 结构与启动

压缩包根目录为 `6G-RESCUE/`，保留完整项目相对路径。首次联网运行 `prepare_environment.cmd`，随后运行 `start_demo.cmd`。环境准备脚本下载有哈希校验的 Node.js 与 uv，在现有 Python 3.12 上或 uv 托管的 Python 3.12 下安装锁定依赖。启动器组合加载完整 API、校验冻结 Phase 6 数据并动态分配本机端口。按 Q 或 Ctrl+C 停止本次启动的服务。

ZIP 不含 `.runtime`、虚拟环境和 `node_modules`。首次准备必须能访问 Python/Node 包源；若处于隔离环境，应提前准备这些锁定依赖缓存。已在本机准备环境和独立解压副本中验证启动。完整命令、运行日志、冷启动性能数据和限制见 `delivery/`。

包内包含预生成离散实验回放、演示 MP4 浏览器录屏和佐证材料 PDF，现场展示不需要重新运行数百次实验。视频播放项目页面与已保存仿真 JSON，不是实时物理网络遥测；Windows SAPI 合成旁白不代表参赛团队的人工陈述。

## 数据与再现范围

原 Phase 18 的 446 项源文件白名单及历史交付材料保留在项目中；本改进 ZIP 还包含完整项目源文件、本次新增文档、测试日志、截图和逐文件清单，实际文件数以 `delivery/FINAL_MANIFEST.json` 为准。14 个原始 Mendeley 工作簿/MAT 源文件未复制；其 DOI、许可和逐文件哈希保留在项目数据谱系中。若要从原始公开数据重新执行完整 Phase 15 处理，应依官方数据来源另行获取并核验该数据包。清洗数据、校准结果、配置和脚本已包含。

本改进 ZIP 的逐文件大小和 SHA-256 见 `delivery/FINAL_MANIFEST.json` 与 `delivery/SHA256SUMS.txt`。根目录 `PACKAGE_MANIFEST.json` 和 `SHA256SUMS.txt` 是保留的原 Phase 18 候选材料；最终新包的权威清单是 `delivery/` 下这两份新文件。清单不包含自身及校验和文件，校验和文件包含清单哈希。

## 安全与提交限制

仓库没有根级 LICENSE/COPYING/NOTICE，源码权属和许可选择仍待权利人确认。第三方图片和数据的署名/再分发范围见包内 `submission/final/SECURITY_AUDIT.md`、`DATA_PROVENANCE.md`。公开、提交、补充队伍身份、原创声明及 AI 辅助披露须由队伍人工确认。

正式比赛当前截止信息和视频规格见 `submission/final/OFFICIAL_COMPETITION_REFERENCES.md`；提交前应再次核对赛事系统。此包没有自动填写身份资料、上传作品、提交报名、改许可证、执行射频发射或控制设备。

## 研究边界

这是面向 IMT-2030 研究主题的抽象仿真与软件验证原型，不是真实 6G 网络测试；确定性规则/优化策略不是训练型机器学习。目标设备校准、真实 HIL、外场测量、第二台设备和断网现场验收仍未完成。
