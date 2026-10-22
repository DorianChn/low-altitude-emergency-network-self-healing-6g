from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUT = RESULTS / "phase18" / "phase18_validation_summary.json"


def read_json(relative: str) -> dict[str, Any]:
    path = RESULTS / relative if relative.startswith("phase") else ROOT / relative
    return json.loads(path.read_text(encoding="utf-8"))


def percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def pp(value: float) -> str:
    return f"{value * 100:+.2f} 个百分点"


def metric_mean(policy: dict[str, Any], name: str) -> float:
    return float(policy["metrics"][name]["mean"])


def build() -> dict[str, Any]:
    audit = read_json("results/phase18/phase18_integrity_audit.json")
    evidence = read_json("results/phase18/phase18_evidence_manifest.json")
    release_path = RESULTS / "phase18" / "phase18_release_manifest.json"
    release = json.loads(release_path.read_text(encoding="utf-8")) if release_path.is_file() else {"items": [], "file_count": 0}
    test_path = RESULTS / "phase18" / "phase18_test_execution.json"
    test_execution = json.loads(test_path.read_text(encoding="utf-8")) if test_path.is_file() else {"checks": []}

    phase2 = read_json("results/phase2_20_seed_results.json")
    phase4 = read_json("results/phase4_validation_4000_4019.json")
    phase5 = read_json("results/phase5_validation_summary.json")
    phase9 = read_json("results/phase9_corrected_confirmation_summary.json")
    phase11 = read_json("results/phase11_confirmation_summary.json")
    phase14 = read_json("results/phase14_confirmation_summary.json")
    phase15 = read_json("results/phase15_calibration_summary.json")
    phase16 = read_json("results/phase16_measurement_readiness.json")
    phase17 = read_json("results/phase17_validation_summary.json")

    b2 = metric_mean(phase2["aggregate"]["B_phase1_static_grid"], "rescue_user_service_success_rate")
    c2 = metric_mean(phase2["aggregate"]["C_rolling_horizon_mpc"], "rescue_user_service_success_rate")
    b4 = metric_mean(phase4["aggregate"]["B_phase1_static_grid"], "rescue_user_service_success_rate")
    c4 = metric_mean(phase4["aggregate"]["C_rolling_horizon_mpc"], "rescue_user_service_success_rate")
    d4 = metric_mean(phase4["aggregate"]["D_lexicographic_rescue_priority"], "rescue_user_service_success_rate")
    phase4_seed_count = len(phase4.get("seed_experiments", []))
    severe = phase5["scenarios"]["severe_persistent_faults"]["aggregate"]
    b5 = severe["Bprime_static_grid_shared_safety"]["metrics"]
    a5 = severe["A_no_recovery"]["metrics"]
    phase5_seed_count = int(b5["rescue_user_service_success_rate"]["n"])
    phase9_e = next(item for item in phase9["paired_tests"] if item.get("scenario_id") == "dynamic_failures" and item.get("metric") == "rescue_user_service_success_rate" and item.get("comparison") == "E_minus_Bprime_static_grid_shared_safety")
    phase11_dyn = phase11["scenarios"]["dynamic_failures"]["paired_comparisons"]["F_independent_greedy_uav3__minus__G_centralized_coordination_uav3"]["metrics"]["rescue_user_service_success_rate"]
    phase11_load = phase11["scenarios"]["high_load_backhaul_limit"]["paired_comparisons"]["F_independent_greedy_uav3__minus__G_centralized_coordination_uav3"]["metrics"]["rescue_user_service_success_rate"]
    phase14_primary = phase14.get("primary_comparisons_holm", [])
    phase14_negative_count = sum(1 for item in phase14_primary if item.get("paired_difference", 0) < 0)
    phase14_significant_count = sum(1 for item in phase14_primary if item.get("p_value_holm", 1) < 0.05)

    protected = audit.get("protected_history", {})
    workspace = audit.get("workspace", {})
    phase7 = audit.get("phase7_evidence", {})
    audit_checks = audit.get("raw_experiment_count_audit", {}).get("checks", [])
    phase9_manifest = protected.get("artifact_manifests", {}).get("phase9", [])
    phase10_manifest = protected.get("artifact_manifests", {}).get("phase10", [])
    phase11_manifest = protected.get("artifact_manifests", {}).get("phase11", [])
    source_drift = int(protected.get("phase5_source_snapshot_drift_count", 0))
    release_count = int(release.get("file_count", len(release.get("items", []))))

    test_rows = [
        {
            "id": item.get("id", f"check-{index + 1}"),
            "name": item.get("name", "未命名验证"),
            "status": item.get("status", "NOT_TESTED"),
            "result": item.get("result", "未执行"),
            "evidence_path": item.get("evidence_path", ""),
        }
        for index, item in enumerate(test_execution.get("checks", []))
    ]

    findings = [
        {
            "id": "phase2_phase4_rolling_horizon",
            "title": "滚动优化没有稳定超过静态网格基线",
            "result": f"Phase 2 的 20 个种子中，C={percent(c2)}、B={percent(b2)}；Phase 4 的 {phase4_seed_count} 个验证种子中，B={percent(b4)}、C={percent(c4)}、D={percent(d4)}。两个批次的场景/协议不可合并为同一个总体估计。",
            "sample_definition": "Phase 2 与 Phase 4 分批报告；救援用户服务成功率",
            "evidence_path": "results/phase2_20_seed_results.json · results/phase4_validation_4000_4019.json",
            "status": "PARTIAL",
            "status_label": "反向证据已保留",
        },
        {
            "id": "phase5_ground_and_uav",
            "title": "严重持续故障中，恢复增益与无人机策略分开记录",
            "result": f"Phase 5 严重故障场景：A 的首次恢复成功率为 {percent(float(a5['network_recovery_success']['mean']))}；共享安全约束的 B′ 为 {percent(float(b5['network_recovery_success']['mean']))}，持续 30 秒成功率为 {percent(float(b5['sustained_rescue_recovery_success']['mean']))}。这是模型条件下的仿真结果。",
            "sample_definition": f"{phase5_seed_count} 个留出种子，A/B′ 同场景配对仿真",
            "evidence_path": "results/phase5_validation_summary.json",
            "status": "PASS",
            "status_label": "仿真证据可核",
        },
        {
            "id": "phase9_event_driven",
            "title": "事件驱动策略 E 在动态故障确认集中低于 B′",
            "result": f"E−B′ 救援服务率配对差 {pp(float(phase9_e['mean_difference']))}，95% CI [{float(phase9_e['ci95_t'][0]) * 100:.2f}, {float(phase9_e['ci95_t'][1]) * 100:.2f}] pp，Holm 校正 p={phase9_e['p_holm_adjusted']:.6g}；E 的增量计算成本不能被描述为已经换来服务提升。",
            "sample_definition": f"{int(phase9_e['n'])} 个动态故障确认种子；同种子配对",
            "evidence_path": "results/phase9_corrected_confirmation_summary.json",
            "status": "PARTIAL",
            "status_label": "限制性结论",
        },
        {
            "id": "phase11_scene_dependence",
            "title": "集中协同 G 的收益取决于灾害场景",
            "result": f"三机动态场景 G−F={pp(-float(phase11_dyn['mean_difference']))}（Holm p={phase11_dyn['p_holm_adjusted']:.6g}）；三机高负载场景 G−F={pp(-float(phase11_load['mean_difference']))}（Holm p={phase11_load['p_holm_adjusted']:.6g}）。没有全场景统一赢家。",
            "sample_definition": "每场景 20 个配对确认种子；11 种配置",
            "evidence_path": "results/phase11_confirmation_summary.json · PHASE11_REPORT.md",
            "status": "PASS",
            "status_label": "分场景结论",
        },
        {
            "id": "phase14_link_model",
            "title": "链路预算假设显著改变可行性与服务结果",
            "result": f"Phase 14 的 {len(phase14_primary)} 项模型配对比较中，救援服务率差值有 {phase14_negative_count} 项为负，其中 {phase14_significant_count} 项经 Holm 校正显著。链路模型未完成目标设备校准，不代表真实网络预测。",
            "sample_definition": "四场景、每场景20个确认种子、两种抽象链路模型",
            "evidence_path": "results/phase14_confirmation_summary.json · PHASE14_REPORT.md",
            "status": "PARTIAL",
            "status_label": "抽象模型结果",
        },
        {
            "id": "phase15_public_measurement",
            "title": "公开空地测量集留出评估不等于项目设备校准",
            "result": f"公开数据候选管线为 {phase15.get('pipeline_status')}，项目设备状态为 {phase15.get('project_device_calibration_status')}；留出验收为 {phase15.get('holdout_acceptance_decision')}。Phase 16 记录的项目设备测量为 {phase16.get('project_measurement_records')} 条。",
            "sample_definition": f"公开数据清洗记录 {phase15.get('dataset', {}).get('cleaned_measurement_count')} 条；设备测量另计",
            "evidence_path": "results/phase15_calibration_summary.json · results/phase16_measurement_readiness.json",
            "status": "PARTIAL",
            "status_label": "缺少不确定度/设备实测",
        },
        {
            "id": "phase17_software_not_hil",
            "title": "软件闭环与回放已验证，物理 HIL 尚未执行",
            "result": f"Phase 17 的软件闭环={phase17.get('software_closed_loop_status')}、离线回放={phase17.get('offline_replay_status')}、故障软件案例={phase17.get('fault_injection', {}).get('passed_count')}；真实 HIL={phase17.get('real_hardware_in_loop_status')}，硬件输出={phase17.get('hardware_output_enabled')}。",
            "sample_definition": f"{phase17.get('offline_replay', {}).get('mapped_frame_count')} 个已保存离散帧；软件测试植物非真实网络设备",
            "evidence_path": "results/phase17_validation_summary.json",
            "status": "PARTIAL",
            "status_label": "仅软件验证",
        },
    ]

    phase_statuses = [
        {"id": f"phase{number}", "label": f"PHASE {number:02d}", "title": title, "status": status, "note": note}
        for number, title, status, note in [
            (1, "仿真基线", "PARTIAL", "单场景基线存档；不作为统计性结论。"),
            (2, "规则与滚动优化", "PARTIAL", "20种子结果可复核；C未超过B。"),
            (3, "离线演示数据", "PASS", "保存回放由历史离散仿真帧构成。"),
            (4, "优化策略验证", "PARTIAL", "确认结果保留了B优于C/D的反向证据。"),
            (5, "多灾害验证", "PASS", "80个留出种子、400条策略运行已列入冻结审计。"),
            (6, "系统集成演示", "PASS", "历史演示与接口证据保留；本阶段不改演示数据。"),
            (7, "阶段证据", "NOT_ASSESSABLE", "未找到可核验的阶段报告、命名产物或Git记录。"),
            (8, "消融与敏感性", "PASS", "原始记录、配对统计和配置清单通过核对。"),
            (9, "事件驱动自愈", "PASS", "确认集完整；负面结论保留。"),
            (10, "多无人机协调", "PASS", "80种子、400条策略运行和策略清单可核。"),
            (11, "算法基线扩展", "PASS", "80种子、880条策略运行；存在场景依赖的差异。"),
            (12, "6G架构映射", "PARTIAL", "技术映射不是标准符合性认证。"),
            (13, "科研可视化", "PASS", "当前研究界面显示已保存证据。"),
            (14, "无线链路模型", "PARTIAL", "使用抽象链路预算，未完成设备校准。"),
            (15, "公开数据评估", "PARTIAL", "完成公开数据候选拟合和留出；验收缺测量不确定度。"),
            (16, "实测准备", "NOT_READY", "无项目设备实测记录，未达到外场测量准备条件。"),
            (17, "软件闭环与HIL", "PARTIAL", "软件闭环和离线回放通过；物理HIL未执行。"),
            (18, "最终审计交付", "PARTIAL", "本地候选资料在审阅前；未创建提交、标签或远程发布。"),
        ]
    ]

    gates = [
        {"id": "phase7_evidence", "title": "Phase 7 历史证据缺失", "status": "NOT_ASSESSABLE", "detail": "在报告、命名产物、分支及提交检索中未找到可核验记录；未重建该阶段。", "evidence_path": "results/phase18/phase18_integrity_audit.json#phase7_evidence"},
        {"id": "phase5_source_drift", "title": "Phase 5 源码快照与当前源码有差异", "status": "PARTIAL" if source_drift else "PASS", "detail": f"发现 {source_drift} 个源码版本差异；受保护历史数据的独立哈希校验为 {protected.get('matched_file_count')}/{protected.get('protected_file_count')}。由于缺少逐阶段提交，无法精确归因版本演进。", "evidence_path": "results/phase5_frozen_manifest.json · results/phase18/phase18_integrity_audit.json"},
        {"id": "device_calibration", "title": "目标设备校准与测量不确定度未完成", "status": "NOT_READY", "detail": "公开数据不替代项目设备实测；Phase 16 记录设备测量为0条，未达到现场测量准备条件。", "evidence_path": "results/phase15_calibration_summary.json · results/phase16_measurement_readiness.json"},
        {"id": "physical_hil", "title": "真实硬件在环验证未执行", "status": "NOT_TESTED", "detail": "当前只有软件测试植物和离线回放，真实设备/驱动不可用，物理输出保持关闭。", "evidence_path": "results/phase17_validation_summary.json"},
        {"id": "external_repository", "title": "未建立可审阅的干净提交", "status": "PARTIAL", "detail": f"当前分支为 {workspace.get('branch')}，HEAD={workspace.get('head')}；工作区有跨阶段未提交变更，未创建提交、Git 标签或远程推送。", "evidence_path": "results/phase18/phase18_integrity_audit.json#workspace"},
        {"id": "secondary_machine", "title": "第二台设备及现场离线环境未实测", "status": "NOT_TESTED", "detail": "本阶段只核验当前工作环境中的本地离线启动和预生成回放；不声称第二台设备/比赛现场已验证。", "evidence_path": "PHASE18_FINAL_ACCEPTANCE_MATRIX.md"},
    ]

    checks = audit.get("errors", [])
    readiness = "CONDITIONAL" if audit.get("status") == "PASS" and not checks else "NOT_READY"
    return {
        "schema_version": "1.0",
        "phase": "phase18_final_audit_snapshot",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PARTIAL" if readiness == "CONDITIONAL" else "FAIL",
        "executive_summary": "冻结证据与实验结构审计通过；研究结论保留了规则策略胜出、智能策略失效和模型敏感性的反向结果。项目仍有历史阶段证据、目标设备校准、物理HIL和干净提交等开放门槛。",
        "competition_readiness": {"status": readiness, "label": "本地候选 · 需要人工审阅及现场条件核验"},
        "phase_statuses": phase_statuses,
        "research_findings": findings,
        "delivery_gates": gates,
        "test_matrix": test_rows,
        "integrity_snapshot": {
            "protected_history_matched": protected.get("matched_file_count", 0),
            "protected_history_total": protected.get("protected_file_count", 0),
            "raw_experiment_checks_matched": sum(bool(item.get("matches")) for item in audit_checks),
            "raw_experiment_checks_total": len(audit_checks),
            "phase5_source_snapshot_drift_count": source_drift,
            "phase9_manifest_matched": sum(bool(item.get("matches")) for item in phase9_manifest),
            "phase10_manifest_matched": sum(bool(item.get("matches")) for item in phase10_manifest),
            "phase11_manifest_matched": sum(bool(item.get("matches")) for item in phase11_manifest),
            "evidence_manifest_items": len(evidence.get("items", [])),
            "release_file_count": release_count,
        },
        "workspace_snapshot": {key: workspace.get(key) for key in ("branch", "head", "status_entry_count_expanded", "staged_path_count", "untracked_status_count", "conflict_count", "phase18_commit_created", "remote_push_performed")},
        "model_scope": "abstract_6g_research_simulation_and_software_validation_not_real_6g_network_test",
        "source_artifacts": [
            {"path": "results/phase18/phase18_integrity_audit.json", "sha256": __import__("hashlib").sha256((RESULTS / "phase18" / "phase18_integrity_audit.json").read_bytes()).hexdigest()},
            {"path": "results/phase18/phase18_evidence_manifest.json", "sha256": __import__("hashlib").sha256((RESULTS / "phase18" / "phase18_evidence_manifest.json").read_bytes()).hexdigest()},
        ],
        "phase7_conclusion": phase7.get("conclusion", "NOT_ASSESSABLE"),
    }


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = build()
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "readiness": payload["competition_readiness"]["status"], "findings": len(payload["research_findings"]), "tests": len(payload["test_matrix"]), "protected": f"{payload['integrity_snapshot']['protected_history_matched']}/{payload['integrity_snapshot']['protected_history_total']}"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
