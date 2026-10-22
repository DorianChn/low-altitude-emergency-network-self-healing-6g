import { useMemo, useState } from "react";
import type { ResearchArtifactEnvelope, ResearchSceneId } from "./research-model";

type Row = Record<string, unknown>;

const POLICY_LABELS: Record<string, string> = {
  Bprime_static_grid_shared_safety: "B′ · 单机静态网格",
  F_independent_greedy: "F3 · 三机独立贪心",
  G_centralized_coordination: "G3 · 三机集中协同",
};

function object(value: unknown): Row {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function pct(value: unknown): string {
  const n = number(value);
  return n === null ? "—" : `${(n * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`;
}

function percentagePoints(value: unknown): string {
  const n = number(value);
  if (n === null) return "—";
  const text = (Math.abs(n) * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  return `${n < 0 ? "−" : n > 0 ? "+" : ""}${text} pp`;
}

function decimal(value: unknown, digits = 2): string {
  const n = number(value);
  return n === null ? "—" : n.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function pValue(value: unknown): string {
  const n = number(value);
  if (n === null) return "—";
  if (n === 0) return "<1e-12";
  return n < 0.0001 ? n.toExponential(2) : n.toFixed(4);
}

function interval(value: unknown, scale = 1): string {
  if (!Array.isArray(value) || value.length !== 2) return "未保存区间";
  const low = number(value[0]);
  const high = number(value[1]);
  return low === null || high === null ? "未保存区间" : `[${decimal(low * scale)}, ${decimal(high * scale)}]`;
}

function sceneLabel(scene: ResearchSceneId): string {
  return ({
    severe_persistent_faults: "严重持续故障",
    dynamic_failures: "动态故障",
    high_mobility_rescue: "高移动救援",
    high_load_backhaul_limit: "高负载 / 回传受限",
  } satisfies Record<ResearchSceneId, string>)[scene];
}

function recovery(value: unknown): string {
  const stats = object(value);
  const success = number(stats.success_count);
  const total = number(stats.total_runs);
  const failures = number(stats.unrecovered_count);
  return success === null || total === null ? "未记录" : `${success}/${total} 成功 · ${failures ?? total - success} 次未恢复`;
}

export function Phase14ResearchSection({
  envelope,
  scene,
}: {
  envelope: ResearchArtifactEnvelope;
  scene: ResearchSceneId;
}) {
  const [sensitivityPolicy, setSensitivityPolicy] = useState("G_centralized_coordination");
  const summary = envelope.artifact;
  const scenario = object(object(summary.scenarios)[scene]);
  const probes = object(object(summary.link_feasibility_probe_summary)[scene]);
  const sensitivityEnvelope = envelope.supporting_artifacts?.sensitivity;
  const sensitivity = object(sensitivityEnvelope?.artifact);
  const sensitivityRows = useMemo(() => {
    const sensitivityScenes = object(sensitivity.scenarios ?? sensitivity);
    const policy = object(object(sensitivityScenes[scene])[sensitivityPolicy]);
    return Object.entries(policy)
      .filter(([id]) => id !== "baseline")
      .map(([id, value]) => ({ id, value: object(value) }));
  }, [scene, sensitivity, sensitivityPolicy]);
  const primary = Array.isArray(summary.primary_comparisons_holm)
    ? summary.primary_comparisons_holm.map(object)
    : [];
  const policies = Object.keys(scenario).filter((key) => key in POLICY_LABELS);
  const seedCount = number(object(summary.seed_count_per_scenario)[scene]);

  if (policies.length === 0) {
    return <section className="radio-validation-empty" role="status"><b>尚无可验证结果</b><p>该场景的 Phase 14 配对实验汇总不存在或不包含策略数据；页面不会补造实验数值。</p></section>;
  }

  return (
    <div className="radio-validation" data-testid="phase14-research">
      <header className="radio-validation-head">
        <div><span className="panel-kicker">PHASE 14 / PROPAGATION MODEL CHECK</span><h2>链路预算如何改变服务判断</h2><p>{sceneLabel(scene)} · {seedCount ?? "—"} 个确认种子 · 同轨迹配对 · 只读保存结果</p></div>
        <div className="radio-validation-badge"><i />模型对照</div>
      </header>

      <section className="radio-model-band" aria-label="链路模型假设">
        <article><span>历史基线</span><b>距离阈值</b><p>仅检查场景配置中的距离半径、基站健康、回传状态和共享容量。</p></article>
        <div className="radio-model-arrow" aria-hidden="true">→</div>
        <article className="radio-model-new"><span>新增研究模型</span><b>对数距离链路预算</b><p>自由空间参考损耗 + 路径损耗指数 + 静态阴影 + 接收功率余量门限。</p></article>
        <article className="radio-boundary-note"><span>模型边界</span><b>抽象假设</b><p>没有真实设备校准、SINR、干扰、建筑传播或完整 3GPP 信道。</p></article>
      </section>

      <section className="radio-results-block" aria-labelledby="radio-policy-title">
        <div className="radio-block-heading"><div><span className="panel-kicker">POLICY × MODEL</span><h3 id="radio-policy-title">救援服务、恢复与资源对照</h3></div><small>差值均为新模型 − 距离阈值模型</small></div>
        <div className="radio-table-scroll" role="region" tabIndex={0} aria-label="链路模型策略对照表，可横向滚动">
          <table className="research-table radio-table">
            <thead><tr><th>策略</th><th>距离阈值<br />救援服务率</th><th>链路预算<br />救援服务率</th><th>配对差值<br />95% 区间</th><th>首次完整恢复</th><th>成功运行<br />恢复耗时</th><th>持续 30 秒</th><th>条件时延<br />均值 / P95</th><th>机队能耗</th><th>单位救援服务能耗</th><th>决策计算</th></tr></thead>
            <tbody>{policies.map((policy) => {
              const row = object(scenario[policy]);
              const legacy = object(row.legacy_distance);
              const budget = object(row.link_budget_v1);
              const delta = object(object(row.paired_link_budget_minus_legacy).rescue_user_service_success_rate);
              const test = primary.find((item) => item.scenario_id === scene && item.policy_id === policy);
              const oldMetric = object(legacy.rescue_user_service_success_rate);
              const newMetric = object(budget.rescue_user_service_success_rate);
              const newRecovery = object(budget.first_full_recovery);
              const latency = object(budget.conditional_latency);
              return <tr key={policy}>
                <th scope="row">{POLICY_LABELS[policy]}</th>
                <td><b>{pct(oldMetric.mean)}</b><small>95% CI {interval(oldMetric.ci95, 100)}% · n={number(oldMetric.n) ?? "—"}</small></td>
                <td><b>{pct(newMetric.mean)}</b><small>95% CI {interval(newMetric.ci95, 100)}% · n={number(newMetric.n) ?? "—"}</small></td>
                <td><b className={number(delta.mean_difference_new_minus_legacy) !== null && Number(delta.mean_difference_new_minus_legacy) < 0 ? "radio-negative" : ""}>{percentagePoints(delta.mean_difference_new_minus_legacy)}</b><small>95% CI {interval(delta.ci95_mean_difference, 100)} pp</small><small>dz {decimal(delta.paired_cohen_dz)} · Holm p {pValue(test?.p_value_holm)}</small></td>
                <td><b>{recovery(newRecovery)}</b><small>Wilson 95% {interval(newRecovery.success_rate_wilson95, 100)}%</small></td>
                <td><b>{decimal(object(newRecovery.successful_run_time_s).mean)} s</b><small>成功样本均值 · 全运行截尾 {decimal(object(newRecovery.all_run_horizon_censored_time_s).mean)} s</small></td>
                <td><b>{recovery(object(budget.sustained_30s_recovery))}</b><small>30 秒持续判据</small></td>
                <td><b>{decimal(latency.pooled_mean_ms)} / {decimal(latency.pooled_p95_ms)} ms</b><small>成功用户时刻 n={number(latency.pooled_successful_user_time_sample_count)?.toLocaleString("zh-CN") ?? "—"}</small></td>
                <td><b>{decimal(object(budget.uav_energy_total_wh).mean)} Wh</b><small>抽象模型量</small></td>
                <td><b>{decimal(object(budget.energy_wh_per_uav_rescue_user_hour).mean)}</b><small>Wh / 用户小时</small></td>
                <td><b>{decimal(object(budget.decision_compute_total_ms).mean)} ms</b><small>按策略计时边界</small></td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        <p className="radio-table-foot">恢复失败始终留在恢复成功率分母中；恢复耗时的成功样本与全运行截尾统计见原始汇总。时延按成功连接样本条件统计，各模型样本集合可能不同，不作同用户配对解释。</p>
      </section>

      <section className="radio-evidence-grid">
        <article className="radio-evidence-panel">
          <span className="panel-kicker">GEOMETRY PROBE / SAME SAVED TRAJECTORY</span>
          <h3>潜在链路段可行性变化</h3>
          <div className="radio-probe-values"><div><b>{pct(probes.legacy_feasibility_rate)}</b><span>距离门限判可行</span></div><div><b>{pct(probes.link_budget_feasibility_rate)}</b><span>预算门限判可行</span></div><div><b>{pct(probes.model_disagreement_rate)}</b><span>判断不一致</span></div></div>
          <p>检查 {number(probes.checked_link_segments)?.toLocaleString("zh-CN") ?? "—"} 个潜在链路段。此探针固定在旧模型策略轨迹上，仅比较射频门限，不包含完整容量分配；不代替策略实际仿真。</p>
          <div className="radio-probe-foot">预算模型拒绝旧模型可行链路：{number(probes.budget_rejected_legacy_feasible_count)?.toLocaleString("zh-CN") ?? "—"} 条 / {pct(probes.budget_rejection_rate_among_legacy_feasible)}</div>
        </article>

        <article className="radio-evidence-panel radio-sensitivity-panel">
          <div className="radio-block-heading"><div><span className="panel-kicker">DEVELOPMENT ONLY / ONE FACTOR AT A TIME</span><h3>参数敏感性筛查</h3></div>
            <label><span>策略</span><select value={sensitivityPolicy} onChange={(event) => setSensitivityPolicy(event.target.value)} aria-label="参数敏感性策略"><option value="Bprime_static_grid_shared_safety">B′ · 单机静态网格</option><option value="G_centralized_coordination">G3 · 三机集中协同</option></select></label>
          </div>
          {sensitivityRows.length ? <div className="radio-sensitivity-list">{sensitivityRows.map(({ id, value }) => {
            const stats = object(value.rescue_user_service_success_rate);
            const delta = object(value.paired_service_delta_from_baseline);
            return <div className="radio-sensitivity-row" key={id}><span><b>{String(value.parameter ?? id)}</b><small>{String(value.level ?? "")}</small></span><b>{pct(stats.mean)}</b><span className="radio-sensitivity-delta">Δ {pct(delta.mean)} <small>开发种子配对差</small></span></div>;
          })}</div> : <div className="radio-validation-empty">尚无可验证的参数筛查数据。</div>}
          <p>每次只改变一个链路预算因素；样本用于筛查，不作为独立确认。安全与容量约束始终开启。</p>
        </article>
      </section>

      <section className="radio-provenance-grid">
        <article><span>确认实验原始汇总</span><code>{envelope.artifact_path}</code><code>SHA-256 {envelope.artifact_sha256}</code></article>
        <article><span>链路参数</span><code>{String(summary.link_budget_config_path ?? "configs/phase14/link_budget_v1.toml")}</code><code>SHA-256 {String(summary.link_budget_config_sha256 ?? "未记录")}</code></article>
        <article><span>敏感性筛查</span><code>{sensitivityEnvelope?.artifact_path ?? "尚无可验证结果"}</code><code>SHA-256 {sensitivityEnvelope?.artifact_sha256 ?? "—"}</code></article>
      </section>

      <footer className="radio-sources">
        <p>自由空间参考损耗采用 ITU-R P.525-5 的计算公式；发射功率、灵敏度、路径损耗指数、衰落余量和阴影标准差均为本项目设定的研究假设。3GPP TR 38.901 是更完整的场景信道研究，本实现没有复现该信道模型。</p>
        <div><a href="https://www.itu.int/rec/R-REC-P.525-5-202411-I/en" target="_blank" rel="noreferrer">ITU-R P.525-5 ↗</a><a href="https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=3173" target="_blank" rel="noreferrer">3GPP TR 38.901 ↗</a><a href="https://www.itu.int/rec/R-REC-M.2160-0-202311-I/en" target="_blank" rel="noreferrer">IMT-2030 M.2160-0 ↗</a></div>
      </footer>
    </div>
  );
}
