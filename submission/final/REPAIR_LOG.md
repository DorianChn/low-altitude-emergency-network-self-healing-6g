# 修复与审计差异记录

## UI-01 — 移动导航裁切（P2）
复现：390px viewport 下最后一个入口被裁切。修复：手机端改为两行三列，并保持链接单行。新增 320/375/414px Playwright 断言。结果：E2E 30 passed，18视口无溢出。无科研数据影响。

## UI-02 — 单侧色条（P3）
Impeccable detector 报状态卡左侧 2px 强调线。移除色条，保留暗红背景和状态灯。原 CSS 备份在 audit/source-backup/index.css.pre-impeccable-p3。修复后 detector 0 primary findings；Vitest/lint/build/E2E 均通过。无科研数据影响。

## AUDIT-01 — Phase 18 截图副作用（P2）
旧 E2E 将截图写入历史 artifacts，造成旧 manifest 4张截图哈希不同。6个测试改为 Playwright per-test output path，新增窄屏用例。原清单保留、不重签。人工需决定旧候选过期处置；Frozen experiment JSON 无影响。

## SEC-01 — pytest Unix tmpdir 公告（P2）
锁定 pytest 8.4.2，公告修复版本 9.0.3。当前 Windows测试通过；未在本轮改锁，避免把依赖升级混入历史混合工作区。公开/跨平台分发前需接受风险或单独升级回归。

## DOC-01 — 答辩材料第 13 页指标卡换行（P2）
复现：逐页检查最新答辩 PDF 时，第 13 页将三段说明误解析为 25pt 指标值，产生逐字换行。根因是 HTML/PDF 渲染器把说明文本当作卡片主数值，和 PPTX 内的数值卡片模型不一致。将四组“数值/标签”改为生成源的共同数据，并调整 PDF 卡片排版；重新生成 16 页 PPTX/PDF。第 13 页最新渲染无异常换行或溢出，PPTX 仍包含可编辑文本和形状。未修改任何实验图表或实验数据。

## DOC-02 — 方案简介长度超限（P2）
按官方模板口径复核发现方案简介超过500字。缩写文字并重新生成 DOCX/PDF；最新简介为351个 CJK 字符，方案 PDF 为5页、160,373 bytes。逐页 Edge 渲染检查通过。原生成源和旧文件保存在 `audit/source-backup/proposal-summary-20261021/`。

## PKG-01 — 候选包运行文件和前端构建配置缺项（P1）
按独立临时副本安装和运行发现，历史446项白名单未含后续 Phase10 开发日志、Phase18 API 支持文件、前端 TypeScript/lint 配置及运行图片。新候选包构建清单只扩展可审计运行所需内容，旧清单未改；隔离副本 Python、前端测试、生产构建、E2E、启动和API smoke通过。旧清单过期状态继续单独披露。

## MEDIA-01 — 录制正式演示与佐证材料（P2）
基于本地 React 页面和已保存仿真回放生成4分24秒、1920×1080 MP4，旁白为 Windows SAPI 合成语音；视频及字幕明确标注仿真边界。另制作6页佐证 PDF，包含软件界面、既有实验图和测试范围，逐页检查无明显裁切/重叠。素材不是实地测量、真实 6G、设备校准或物理 HIL 证据。
