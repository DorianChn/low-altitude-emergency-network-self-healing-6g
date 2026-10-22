# Phase 18 历史候选清单差异复核

Phase18 原发布清单 results/phase18/phase18_release_manifest.json 保持不变。它记录历史候选 446 文件、2,100,787,227 字节，创建时分支 phase18-final-audit-delivery、HEAD 7d3eb100ac567aedd7edb462aab7ad1125a3fbb5。

本轮回归时发现早期 E2E 测试把 4 张截图写回旧 artifacts 路径，导致相应截图与旧 SHA 不同；已经将 6 个 spec 改为 Playwright per-test outputPath。另有 UI 源码和测试源变更，意味着旧候选目前不能代表当前工作树。原清单没有重签或覆盖。

Phase17 protected start manifest 182 项是另一个时间点和范围。当前审计重新计算每个文件大小/SHA，结果写入 audit/final_acceptance.json。Phase14/15/16以及 Phase5/8/9/10/11历史数据另按冻结清单核对。新发布候选在 package/ 中有独立哈希，不冒用旧清单身份。

因此当前结论：旧Phase18 RC 的完整性状态 BLOCKED/STALE；这不等于原始冻结实验数据受损。详细 hash 差异在 audit/history_integrity.json，原始清单保留。

本轮还对一个新的、独立命名的审阅候选重新构建。隔离打包验证曾暴露旧 446 项 allowlist 对后续前端构建配置、Phase18 API 支持文件、Phase10 开发日志及首页运行图片的遗漏；这些已作为新候选支持文件补齐。遗漏及原始错误日志见 `audit/PACKAGE_VALIDATION_LOG.md`。新候选不改变历史 manifest 的含义，也不使旧清单重新变为当前工作树校验和。
