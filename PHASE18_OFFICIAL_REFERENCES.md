# Phase 18 官方资料核验清单

**核验日期：2026-10-21**。仅将官方站点所能确认的内容作为外部依据；文件状态按官方页面表述区分。引用用于研究方向映射，不构成符合性声明。

| 来源 | 版本/日期与状态 | 本报告可引用的范围 | 官方链接 |
|---|---|---|---|
| ITU-R Recommendation M.2160-0, *Framework and overall objectives of the future development of IMT for 2030 and beyond* | 11/2023；ITU 页面标为 In force，2023-11-13 批准 | IMT-2030 的框架、愿景、使用场景和总体目标；不能据此声称本项目算法或接口符合 IMT-2030 | [Recommendation 页面](https://www.itu.int/rec/R-REC-M.2160-0-202311-I/en) · [官方 PDF](https://www.itu.int/dms_pubrec/itu-r/rec/m/R-REC-M.2160-0-202311-I%21%21PDF-E.pdf) |
| 3GPP Working Group Reports to RAN Plenary #113 | 2026-09-14 官方新闻摘要 | 3GPP Rel-20 的 6G study item 仍在推进；报道中的 6GR 主题属于研究进展，不能表述为已冻结的 6G 规范 | [3GPP RAN#113 报告](https://www.3gpp.org/news-events/3gpp-news/ran113-reports) |
| 3GPP specification study item: *Study on 6G Use Cases and Service Requirements* | 3GPP Portal 条目；计划 Release 20 的研究项目 | 证明 3GPP 存在 6G 用例和服务需求研究条目；不代表条目已成为规范，也不代表本项目实现了其中要求 | [3GPP Portal 条目](https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=4374) |
| ETSI TS 128 561 V19.2.0 (2026-04), *Management aspects of Network Digital Twins*（3GPP TS 28.561 Rel-19） | Technical Specification；ETSI 发布版本 | 标准化管理系统中的 Network Digital Twin 术语、用例、需求与方案；这是实际网络管理规范范围，不等同于本项目的离线二维回放 | [ETSI 官方 PDF](https://www.etsi.org/deliver/etsi_ts/128500_128599/128561/19.02.00_60/ts_128561v190200p.pdf) |
| ETSI GR ZSM 015 V1.1.1 (2024-02), *Zero-touch network and Service Management; Network Digital Twin* | Group Report；研究/报告文件，不作为强制技术规范 | 网络数字孪生背景和术语讨论；只用于研究语境，不作为本系统验收标准 | [ETSI 官方 PDF](https://www.etsi.org/deliver/etsi_gr/ZSM/001_099/015/01.01.01_60/gr_ZSM015v010101p.pdf) |

## 官方事实与项目推断的边界

- **官方事实：** M.2160-0 是现行的 IMT-2030 框架建议书；3GPP 官方报道在 2026 年仍将 6G 工作描述为研究项目；ETSI TS 128 561 是 3GPP Release 19 的网络数字孪生管理技术规范。
- **项目对应关系：** 灾害恢复、AI/优化调度、低空中继、离线仿真、能耗分析与上述研究方向有问题域关联，这是项目架构映射，不是标准指定或认证。
- **未确认事项：** 没有找到上述文件规定本项目当前 JSON API、无人机选址算法、链路阈值或仿真软件接口。报告不作此类声称。

## 访问记录

2026-10-21 通过官方 ITU、3GPP 与 ETSI 页面/文件核验上述标题、编号、版本/日期和状态。具体章节定位及项目映射见 `PHASE12_STANDARDS_MAPPING.md`；如果该映射中的段落号与下载版本存在差异，应以对应官方版本原文为准。
