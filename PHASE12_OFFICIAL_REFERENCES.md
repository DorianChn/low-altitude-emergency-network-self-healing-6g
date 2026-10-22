# Phase 12：官方参考资料清单

检索与状态核验日期：2026-10-20。以下均优先选用 ITU、3GPP、ETSI 官方页面或官方交付文件。正式发布、研究报告和草案状态分别列明；“官方文件”不自动代表本项目符合该文件。

| ID | 文件与状态 | 版本/日期/编号 | 本项目引用位置 | 官方来源与访问日期 |
|---|---|---|---|---|
| R1 | ITU-R Recommendation，正式发布、In force | Recommendation ITU-R M.2160-0，2023-11-13 批准；“Framework and overall objectives of the future development of IMT for 2030 and beyond” | §2.1（p.6，安全/韧性与持续服务）；§2.2.4（p.8，数字孪生）；§2.2.9（p.9，可持续性）；§3（pp.13–14，HRLLC、AI and Communication 等场景）；§4（pp.15–17，能力定义） | [ITU 推荐书信息页](https://www.itu.int/rec/R-REC-M.2160-0-202311-I/en)；[ITU 官方英文 PDF](https://www.itu.int/dms_pubrec/itu-r/rec/m/R-REC-M.2160-0-202311-I%21%21PDF-E.pdf)。访问 2026-10-20。 |
| R2 | ITU-R 官方 IMT-2030 过程与状态页面 | 页面持续更新；本次访问显示 2026 年 2 月已完成技术性能要求报告草案，提交 SG 5 计划在 2026 年 12 月审批；候选 RIT 提交时间窗口为 2027-02 至 2029-02 | 用于区分框架建议书与尚在审批流程中的性能要求/评估报告，不把草案称为已批准标准 | [ITU-R IMT-2030 页面](https://www.itu.int/en/ITU-R/study-groups/rsg5/rwp5d/IMT-2030/Pages/default.aspx)。访问 2026-10-20；页面所述 2026-12 是未来日期，故相应文件在本次审计时仍为草案/待审批状态。 |
| R3 | 3GPP Rel-21 当前 Open；相关 TS 仍为 Draft | 3GPP portal 显示 Rel-21 于 2025-11-04 开始且状态 Open；TS 22.270 “6G Service Requirements”创建于 2026-03-25，最新版本 0.3.0 上传于 2026-09-14，状态 Draft | 仅作为 3GPP 进入 Rel-21 并开展 6G 服务需求工作的证据；Release 状态不等于 22.270 已成为正式规范 | [3GPP Rel-21 官方条目](https://portal.3gpp.org/desktopmodules/Release/ReleaseDetails.aspx?releaseId=197)；[3GPP TS 22.270 官方条目](https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=5521)。访问 2026-10-20。 |
| R8 | 3GPP Work Item，工作项目而非正式规范 | WI 1110085 / 6G-REQ，“6G Service Requirements”；Rel-21，PCG approved；官方页记录 start 2026-03-17、end 2027-03-03、完成率更新至 40%（2026-09-09） | 用于记录 3GPP SA1 的 6G 需求研究项目状态；与 R3 草案状态分开引用 | [3GPP WI 1110085 官方条目](https://portal.3gpp.org/desktopmodules/WorkItem/WorkItemDetails.aspx?workitemId=1110085)。访问 2026-10-20。 |
| R4 | 3GPP TR，已发布技术报告/Under change control | 3GPP TR 38.821，Release 16，“Solutions for NR to support Non-Terrestrial Networks (NTN)”；最新条目显示版本 16.2.0，2023-04-03，Type=TR | 说明 3GPP 曾研究 NR 支持 NTN 的解决方案；项目 UAV 是地面基站回传中继，不据此声称实现 NTN | [3GPP TR 38.821 官方条目](https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=3525)。访问 2026-10-20。 |
| R5 | ETSI Group Report，正式发布但属研究报告 | ETSI GR ZSM 015 V1.1.1（2024-02），“Zero-touch network and Service Management; Network Digital Twin” | §1 Scope、§4.1（NDT 概念及其与通用行为仿真的差异）、§5 和 §6（应用示例与管理能力） | [ETSI GR ZSM 015 官方 PDF](https://www.etsi.org/deliver/etsi_gr/ZSM/001_099/015/01.01.01_60/gr_ZSM015v010101p.pdf)。访问 2026-10-20。该文件明确为 Group Report；不视为项目接口符合性规范。 |
| R6 | ETSI Group Specification，正式发布 | ETSI GS ZSM 018 V1.1.1（2024-12），“Network Digital Twin for enhanced zero-touch network and service management” | §5 中 NDT 能力、预测、可视化、历史 what-if 等内容；用于形成未来验证差距 | [ETSI GS ZSM 018 官方 PDF](https://www.etsi.org/deliver/etsi_gs/ZSM/001_099/018/01.01.01_60/gs_zsm018v010101p.pdf)。访问 2026-10-20。文件讨论的是 ZSM Network Digital Twin 能力；本项目尚无物理网络数据映射/同步，不能宣称符合。 |
| R7 | ETSI Group Specification，正式发布 | ETSI GS ENI 005 V4.1.1（2026-01），“Experiential Networked Intelligence; ENI System Architecture”；ETSI 官方发布记录为 2026-01 | §5.2 架构参考：模块化功能块、模型驱动和闭环控制等概念，用于检查本项目分层设计的结构完整性 | [ETSI GS ENI 005 官方 PDF](https://www.etsi.org/deliver/etsi_gs/ENI/001_099/005/04.01.01_60/gs_ENI005v040101p.pdf)；[ETSI 发布目录](https://www.etsi.org/deliver/etsi_gs/ENI/001_099/005/04.01.01_60/)。访问 2026-10-20。该文件不是本项目算法规范，也不是 IMT-2030 合规认证。 |

## 解释规则

1. R1 是已经生效的 IMT-2030 总体框架建议书。它描述总体愿景、场景和能力，不规定本项目 A–J 算法、API JSON 结构或仿真软件接口。M.2160 中的能力值是后续研究目标，不是本项目可直接采用的合格/不合格阈值。
2. R2 页面的性能要求和评估报告状态必须按审批进展读取。截止本次访问，相关 2026 年报告仍在后续 SG 5 审批流程，不能引用为已批准的正式报告。
3. R3 是 Draft 状态 TS。3GPP 有该研究工作，不等于其具体内容已形成正式规范。
4. R4 是 3GPP TR 研究报告。非地面网络（例如卫星/高空平台）与本项目当前的低空 UAV 到地面基站中继不是同一实现。
5. R5 是 Group Report，R6/R7 是 Group Specification。它们用于分析研究架构与能力边界，不能直接作为本项目通过符合性测试的证据。
6. 本清单未将新闻文章、二手标准解读或未核验提案作为正式技术依据。无法从官方资料核实的项目接口或算法要求均标记为“未找到依据”。
