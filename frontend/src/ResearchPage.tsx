import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { OfflineNotice, PageTransition } from "./components";
import { Phase14ResearchSection } from "./Phase14ResearchSection";
import { Phase15ResearchSection } from "./Phase15ResearchSection";
import { Phase16ResearchSection } from "./Phase16ResearchSection";
import { Phase17ResearchSection } from "./Phase17ResearchSection";
import { Phase18ResearchSection } from "./Phase18ResearchSection";
import { useCurrentPageData } from "./useCurrentPageData";
import {
  normalizeResearchArtifact,
  RESEARCH_PHASES,
  RESEARCH_SCENES,
  type ResearchArtifactEnvelope,
  type ResearchEstimate,
  type ResearchPhaseId,
  type ResearchSceneId,
  type ResearchStrategy,
} from "./research-model";

const PCT = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const NUM = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });

export function ResearchPage() {
  const { register, clear } = useCurrentPageData();
  const [phase, setPhase] = useState<ResearchPhaseId>("phase11");
  const [scene, setScene] = useState<ResearchSceneId>("dynamic_failures");
  const [loadState, setLoadState] = useState<{ key: string; loading: boolean; envelope: ResearchArtifactEnvelope | null; error: string | null }>({ key: "", loading: true, envelope: null, error: null });
  const [retry, setRetry] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [baselineId, setBaselineId] = useState("");
  const [includeAblations, setIncludeAblations] = useState(false);
  const requestKey = `${phase}:${retry}`;
  const currentLoad = loadState.key === requestKey ? loadState : null;
  const loading = !currentLoad || currentLoad.loading;
  const envelope = currentLoad?.envelope ?? null;
  const error = currentLoad?.error ?? null;

  useEffect(() => () => clear("research"), [clear]);
  useEffect(() => {
    const phaseLabel = RESEARCH_PHASES.find((item) => item.id === phase)?.label ?? phase;
    const sceneLabel = RESEARCH_SCENES.find((item) => item.id === scene)?.label ?? scene;
    register("research", {
      sourceId: phase,
      sourceLabel: `${phaseLabel} · ${sceneLabel}`,
      mode: "multi-seed",
      status: loading ? "loading" : error || !envelope ? "error" : "ready",
      seed: null,
      scenarioId: scene,
      scenarioLabel: sceneLabel,
      error,
    });
  }, [clear, envelope, error, loading, phase, register, scene]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    fetch(`/api/research/${phase}`, { signal: controller.signal, headers: { Accept: "application/json" } })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => null) as { detail?: string } | null;
          throw new Error(body?.detail ?? `实验数据接口返回 ${response.status}`);
        }
        return response.json() as Promise<ResearchArtifactEnvelope>;
      })
      .then((payload) => {
        if (payload.dataset_id !== phase || !payload.artifact_path.startsWith("results/")) {
          throw new Error("数据集标识或来源路径与所选阶段不一致。");
        }
        if (active) setLoadState({ key: requestKey, loading: false, envelope: payload, error: null });
      })
      .catch((cause: unknown) => {
        if (!active || (cause instanceof DOMException && cause.name === "AbortError")) return;
        setLoadState({ key: requestKey, loading: false, envelope: null, error: cause instanceof Error ? cause.message : "无法读取该阶段的实验汇总。" });
      })
      ;
    return () => { active = false; controller.abort(); };
  }, [phase, requestKey]);

  const dataset = useMemo(() => envelope && phase !== "phase14" && phase !== "phase15" && phase !== "phase16" && phase !== "phase17" && phase !== "phase18" ? normalizeResearchArtifact(
    envelope,
    phase,
    scene,
    selectedId || undefined,
    baselineId || undefined,
  ) : null, [envelope, phase, scene, selectedId, baselineId]);

  if (phase === "phase14") {
    if (loading) {
      return <PageTransition className="research-page"><div className="research-state" role="status"><span className="status-led" />正在读取 Phase 14 链路模型结果…</div></PageTransition>;
    }
    if (error || !envelope) {
      return <PageTransition className="research-page"><section className="research-state research-error" role="alert"><span className="data-state-symbol">!</span><h1>链路模型结果不可用</h1><p>{error ?? "没有可验证的 Phase 14 实验文件；不会用演示值填充。"}</p><button type="button" className="research-button" onClick={() => setRetry((value) => value + 1)}>重新读取</button></section></PageTransition>;
    }
    return (
      <PageTransition className="research-page">
        <header className="page-heading research-heading" data-enter>
          <div><h1>让链路预算<br className="research-mobile-break" />接受检验</h1><p>同轨迹配对比较距离阈值与可配置链路预算。每项数值均来自保存的仿真运行。</p></div>
          <div className="research-heading-meta"><span className="research-record-mark"><i />研究数据 / 只读</span><OfflineNotice compact /></div>
        </header>
        <section className="research-selector" aria-label="研究数据选择">
          <div className="research-control-block"><span className="research-control-label">实验阶段</span><div className="research-stage-list" role="tablist" aria-label="实验阶段">
            {RESEARCH_PHASES.map((item) => <button key={item.id} type="button" role="tab" aria-selected={phase === item.id} className={phase === item.id ? "selected" : ""} onClick={() => { setPhase(item.id); setSelectedId(""); setBaselineId(""); setIncludeAblations(false); }}>{item.label}</button>)}
          </div></div>
          <label className="research-scene-control"><span>灾害场景</span><select value={scene} onChange={(event) => setScene(event.target.value as ResearchSceneId)} aria-label="选择灾害场景">{RESEARCH_SCENES.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
        </section>
        <Phase14ResearchSection envelope={envelope} scene={scene} />
        <footer className="research-provenance-footer"><div><span className="panel-kicker">TRACEABLE SOURCE</span><b>{envelope.artifact_path}</b><code>SHA-256 {envelope.artifact_sha256}</code></div><p>确认性汇总与开发阶段参数筛查分开保存。开发筛查不作为验证证据。链路预算是抽象假设模型，不是实测无线信号、真实 6G 网络或标准符合性认证。</p></footer>
      </PageTransition>
    );
  }

  if (phase === "phase15") {
    if (loading) {
      return <PageTransition className="research-page"><div className="research-state" role="status"><span className="status-led" />正在读取 Phase 15 测量校准证据…</div></PageTransition>;
    }
    if (error || !envelope) {
      return <PageTransition className="research-page"><section className="research-state research-error" role="alert"><span className="data-state-symbol">!</span><h1>测量校准证据不可用</h1><p>{error ?? "没有保存的 Phase 15 结果；不会用演示数据填充。"}</p><button type="button" className="research-button" onClick={() => setRetry((value) => value + 1)}>重新读取</button></section></PageTransition>;
    }
    return (
      <PageTransition className="research-page">
        <header className="page-heading research-heading" data-enter>
          <div><h1>让链路模型<br className="research-mobile-break" />对照测量</h1><p>公开空地测量数据用于验证导入、分组拟合和留出评估流程。项目设备仍未校准。</p></div>
          <div className="research-heading-meta"><span className="research-record-mark"><i />研究数据 / 只读</span><OfflineNotice compact /></div>
        </header>
        <section className="research-selector" aria-label="研究数据选择">
          <div className="research-control-block"><span className="research-control-label">实验阶段</span><div className="research-stage-list" role="tablist" aria-label="实验阶段">
            {RESEARCH_PHASES.map((item) => <button key={item.id} type="button" role="tab" aria-selected={phase === item.id} className={phase === item.id ? "selected" : ""} onClick={() => { setPhase(item.id); setSelectedId(""); setBaselineId(""); setIncludeAblations(false); }}>{item.label}</button>)}
          </div></div>
        </section>
        <Phase15ResearchSection envelope={envelope} />
        <footer className="research-provenance-footer"><div><span className="panel-kicker">TRACEABLE SOURCE</span><b>{envelope.artifact_path}</b><code>SHA-256 {envelope.artifact_sha256}</code></div><p>公开 3.6 GHz 非城市 A2G 数据上的留出评估已完成。候选参数没有写入 Phase 14，也不表示项目硬件或真实城市应急网络已校准。</p></footer>
      </PageTransition>
    );
  }

  if (phase === "phase16") {
    if (loading) {
      return <PageTransition className="research-page"><div className="research-state" role="status"><span className="status-led" />正在读取 Phase 16 测量准备与不确定度证据…</div></PageTransition>;
    }
    if (error || !envelope) {
      return <PageTransition className="research-page"><section className="research-state research-error" role="alert"><span className="data-state-symbol">!</span><h1>测量准备证据不可用</h1><p>{error ?? "没有保存的 Phase 16 准备文件；不会用演示值填充。"}</p><button type="button" className="research-button" onClick={() => setRetry((value) => value + 1)}>重新读取</button></section></PageTransition>;
    }
    return (
      <PageTransition className="research-page">
        <header className="page-heading research-heading" data-enter>
          <div><h1>从实测准备<br className="research-mobile-break" />走向校准验收</h1><p>查看设备盘点、公开数据导入、不确定度缺口与外场准备门槛。所有状态来自本地保存的证据文件。</p></div>
          <div className="research-heading-meta"><span className="research-record-mark"><i />准备状态 / 只读</span><OfflineNotice compact /></div>
        </header>
        <section className="research-selector" aria-label="研究数据选择">
          <div className="research-control-block"><span className="research-control-label">实验阶段</span><div className="research-stage-list" role="tablist" aria-label="实验阶段">
            {RESEARCH_PHASES.map((item) => <button key={item.id} type="button" role="tab" aria-selected={phase === item.id} className={phase === item.id ? "selected" : ""} onClick={() => { setPhase(item.id); setSelectedId(""); setBaselineId(""); setIncludeAblations(false); }}>{item.label}</button>)}
          </div></div>
        </section>
        <Phase16ResearchSection envelope={envelope} />
        <footer className="research-provenance-footer"><div><span className="panel-kicker">SAVED READINESS EVIDENCE</span><b>{envelope.artifact_path}</b><code>SHA-256 {envelope.artifact_sha256}</code></div><p>公开数据上的留出误差不等于目标设备校准。没有目标设备实测、计量不确定度和合规授权时，系统保持未校准状态。</p></footer>
      </PageTransition>
    );
  }

  if (phase === "phase17") {
    if (loading) {
      return <PageTransition className="research-page"><div className="research-state" role="status"><span className="status-led" />正在读取 Phase 17 软件闭环与回放证据…</div></PageTransition>;
    }
    if (error || !envelope) {
      return <PageTransition className="research-page"><section className="research-state research-error" role="alert"><span className="data-state-symbol">!</span><h1>HIL 验证证据不可用</h1><p>{error ?? "没有保存的 Phase 17 验证结果；不会使用演示数据填充。"}</p><button type="button" className="research-button" onClick={() => setRetry((value) => value + 1)}>重新读取</button></section></PageTransition>;
    }
    return <PageTransition className="research-page">
      <header className="page-heading research-heading" data-enter>
        <div><h1>把安全边界<br className="research-mobile-break" />做成可验证证据</h1><p>从离线记录回放到软件闭环验收；物理输出保持关闭，真实硬件在环状态明确标为未执行。</p></div>
        <div className="research-heading-meta"><span className="research-record-mark phase17-record-mark"><i />安全验证 / 软件与回放</span><OfflineNotice compact /></div>
      </header>
      <section className="research-selector" aria-label="研究数据选择">
        <div className="research-control-block"><span className="research-control-label">实验阶段</span><div className="research-stage-list" role="tablist" aria-label="实验阶段">
          {RESEARCH_PHASES.map((item) => <button key={item.id} type="button" role="tab" aria-selected={phase === item.id} className={phase === item.id ? "selected" : ""} onClick={() => { setPhase(item.id); setSelectedId(""); setBaselineId(""); setIncludeAblations(false); }}>{item.label}</button>)}
        </div></div>
      </section>
      <Phase17ResearchSection key={envelope.artifact_sha256} envelope={envelope} />
      <footer className="research-provenance-footer"><div><span className="panel-kicker">SAVED PHASE 17 EVIDENCE</span><b>{envelope.artifact_path}</b><code>SHA-256 {envelope.artifact_sha256}</code></div><p>软件闭环由合成测试植物产生；离线回放来自已保存的 Phase 6 仿真离散帧。没有执行真实无线发射、飞行或基站控制。</p></footer>
    </PageTransition>;
  }

  if (phase === "phase18") {
    if (loading) {
      return <PageTransition className="research-page"><div className="research-state" role="status"><span className="status-led" />正在读取最终验收与发布候选证据…</div></PageTransition>;
    }
    if (error || !envelope) {
      return <PageTransition className="research-page"><section className="research-state research-error" role="alert"><span className="data-state-symbol">!</span><h1>最终审计证据不可用</h1><p>{error ?? "没有完整的 Phase 18 审计文件；不会以占位数据替代。"}</p><button type="button" className="research-button" onClick={() => setRetry((value) => value + 1)}>重新读取</button></section></PageTransition>;
    }
    return <PageTransition className="research-page">
      <header className="page-heading research-heading" data-enter>
        <div><h1>把结论带回<br className="research-mobile-break" />可核验的证据</h1><p>查看冻结数据、研究结论、测试状态与发布边界。状态按检查结果呈现，未完成的真实设备验证不会显示为通过。</p></div>
        <div className="research-heading-meta"><span className="research-record-mark phase18-record-mark"><i />最终审计 / 本地 RC</span><OfflineNotice compact /></div>
      </header>
      <section className="research-selector" aria-label="研究数据选择">
        <div className="research-control-block"><span className="research-control-label">实验阶段</span><div className="research-stage-list" role="tablist" aria-label="实验阶段">
          {RESEARCH_PHASES.map((item) => <button key={item.id} type="button" role="tab" aria-selected={phase === item.id} className={phase === item.id ? "selected" : ""} onClick={() => { setPhase(item.id); setSelectedId(""); setBaselineId(""); setIncludeAblations(false); }}>{item.label}</button>)}
        </div></div>
      </section>
      <Phase18ResearchSection envelope={envelope} onOpenPhase={(nextPhase) => { setPhase(nextPhase); setSelectedId(""); setBaselineId(""); setIncludeAblations(false); }} />
      <footer className="research-provenance-footer"><div><span className="panel-kicker">RELEASE CANDIDATE SOURCE</span><b>{envelope.artifact_path}</b><code>SHA-256 {envelope.artifact_sha256}</code></div><p>该页面展示的是保存的最终审计快照，不是实时网络状态或标准认证。建议版本名不等于已创建 Git tag、提交或公开发布。</p></footer>
    </PageTransition>;
  }

  if (loading) {
    return <PageTransition className="research-page"><div className="research-state" role="status"><span className="status-led" />正在读取冻结实验汇总…</div></PageTransition>;
  }
  if (error || !envelope || !dataset || dataset.strategies.length === 0) {
    return (
      <PageTransition className="research-page">
        <section className="research-state research-error" role="alert">
          <span className="data-state-symbol">!</span><h1>实验数据不可用</h1>
          <p>{error ?? "所选实验汇总缺少该场景的策略统计；不会用示例值填充。"}</p>
          <button type="button" className="research-button" onClick={() => setRetry((value) => value + 1)}>重新读取</button>
        </section>
      </PageTransition>
    );
  }

  const visibleStrategies = phase === "phase8" && !includeAblations
    ? dataset.strategies.filter((item) => ["A_no_recovery", "B_phase1_static_grid", "Bprime_static_grid_shared_safety", "C_rolling_horizon_mpc", "D_lexicographic_rescue_priority"].includes(item.id))
    : dataset.strategies;
  const preferredStrategy = phase === "phase5" || phase === "phase8" ? "D_lexicographic_rescue_priority"
    : phase === "phase9" ? "E_event_driven_rescue_recovery"
      : "G_centralized_coordination_uav3";
  const activeStrategy = dataset.strategies.find((item) => item.id === selectedId)
    ?? dataset.strategies.find((item) => item.id === preferredStrategy)
    ?? visibleStrategies[0]
    ?? dataset.strategies[0];
  const defaultBaseline = phase === "phase10" || phase === "phase11"
    ? "Bprime_static_grid_shared_safety_uav1"
    : phase === "phase9" ? "Bprime_static_grid_shared_safety" : "B_phase1_static_grid";
  const effectiveBaseline = dataset.strategies.some((item) => item.id === baselineId)
    ? baselineId : dataset.strategies.some((item) => item.id === defaultBaseline) ? defaultBaseline : dataset.strategies[0].id;
  const view = normalizeResearchArtifact(envelope, phase, scene, activeStrategy.id, effectiveBaseline);
  const selected = view.strategies.find((item) => item.id === activeStrategy.id) ?? activeStrategy;

  return (
    <PageTransition className="research-page">
      <header className="page-heading research-heading" data-enter>
        <div><h1>把每个结论<br className="research-mobile-break" />带回证据</h1><p>同一阶段、同一灾害场景内对照冻结统计；不同实验设计保持分开展示。</p></div>
        <div className="research-heading-meta"><span className="research-record-mark"><i />研究数据 / 只读</span><OfflineNotice compact /></div>
      </header>

      <section className="research-selector" aria-label="研究数据选择">
        <div className="research-control-block">
          <span className="research-control-label">实验阶段</span>
          <div className="research-stage-list" role="tablist" aria-label="实验阶段">
            {RESEARCH_PHASES.map((item) => <button key={item.id} type="button" role="tab" aria-selected={phase === item.id} className={phase === item.id ? "selected" : ""} onClick={() => { setPhase(item.id); setSelectedId(""); setBaselineId(""); setIncludeAblations(false); }}>{item.label}</button>)}
          </div>
        </div>
        <label className="research-scene-control"><span>灾害场景</span><select value={scene} onChange={(event) => { setScene(event.target.value as ResearchSceneId); setSelectedId(""); setBaselineId(""); }} aria-label="选择灾害场景">{RESEARCH_SCENES.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
      </section>

      <section className="research-source-line" aria-label="数据来源">
        <div><span className="source-led" /><b>{view.phaseLabel}</b><span>{view.experimentRole}</span></div>
        <div className="research-source-meta"><span>{view.seedCount} 个同场景种子</span><span>{view.strategyCount} 种策略 / 变体</span><span>全阶段 {view.runCount?.toLocaleString("zh-CN") ?? "—"} 次运行</span></div>
        <code title={view.sourcePath}>{view.sourcePath}</code>
        <button type="button" className="research-copy" onClick={() => navigator.clipboard?.writeText(view.sourceSha256)} aria-label="复制数据文件 SHA-256">复制 SHA-256</button>
      </section>

      <section className="research-stat-definition" aria-label="统计口径说明">
        <p>{view.metricDefinition}</p>
        <p>{view.latencyDefinition}</p>
      </section>

      <section className="research-evidence-layout">
        <section className="research-rate-panel" aria-labelledby="rescue-plot-title">
          <div className="research-section-head">
            <div><span className="panel-kicker">PAIRED WORLD / RESCUE SERVICE</span><h2 id="rescue-plot-title">救援服务率</h2><p>点为每种策略跨种子均值；线段仅在原汇总提供 95% 区间时显示。</p></div>
            {phase === "phase8" && <label className="research-variant-toggle"><input type="checkbox" checked={includeAblations} onChange={(event) => setIncludeAblations(event.target.checked)} />显示 C/D 机制变体</label>}
          </div>
          <RescueRatePlot strategies={visibleStrategies} selectedId={selected.id} onSelect={(id) => setSelectedId(id)} />
          <div className="research-plot-foot"><span>0%</span><span>救援用户—采样时刻服务比例 (%)</span><span>100%</span></div>
        </section>

        <aside className="research-pair-panel" aria-labelledby="pair-title">
          <span className="panel-kicker">SAME-SEED CONTRAST</span>
          <h2 id="pair-title">所选策略 − 基线</h2>
          <label><span>分析策略</span><select value={selected.id} onChange={(event) => setSelectedId(event.target.value)} aria-label="分析策略">{dataset.strategies.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label><span>基线</span><select value={effectiveBaseline} onChange={(event) => setBaselineId(event.target.value)} aria-label="选择配对基线">{dataset.strategies.filter((item) => item.id !== selected.id).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          {view.pairDifference.available ? <div className="paired-value">
            <strong className={differenceTone(view.pairDifference.meanDifference)}>{formatPointDifference(view.pairDifference.meanDifference)}</strong>
            <span>95% 配对区间 {formatPointInterval(view.pairDifference.ci95)}</span>
            <span>同种子 n = {view.pairDifference.n ?? "—"} · 效应量 dz {formatNumber(view.pairDifference.effectSize)}</span>
            <span>{view.pairDifference.adjustedP === null ? `未校正 p = ${formatNumber(view.pairDifference.rawP)}` : `Holm 校正 p = ${formatP(view.pairDifference.adjustedP)}`}</span>
            <small>差值方向：所选策略 − 基线。正值表示服务率较高；是否有证据支持应结合区间与校正后检验。</small>
          </div> : <div className="paired-unavailable"><b>本阶段没有保存这组配对结果</b><span>{view.pairDifference.note}</span><small>不从两个均值相减伪造配对区间或显著性。</small></div>}
        </aside>
      </section>

      <section className="research-recovery-panel" aria-labelledby="recovery-title">
        <div className="research-section-head"><div><span className="panel-kicker">RECOVERY / FAILURES STAY IN THE DENOMINATOR</span><h2 id="recovery-title">恢复结局与删失时间</h2><p>恢复成功数与未恢复数使用全部留出运行作为分母。</p></div><span className="research-sample-note">场景样本 n = {view.seedCount}</span></div>
        <div className="research-recovery-table-wrap" role="region" tabIndex={0} aria-label="策略恢复结局表，可横向滚动">
          <table className="research-table">
            <thead><tr><th scope="col">策略</th><th scope="col">首次完整恢复</th><th scope="col">持续 30 秒</th><th scope="col">成功运行恢复均值</th><th scope="col">全运行恢复 / 截尾均值</th></tr></thead>
            <tbody>{visibleStrategies.map((item) => <tr key={item.id} className={item.id === selected.id ? "selected" : ""}>
              <th scope="row"><StrategyMark strategy={item} />{item.label}</th>
              <td><b>{countPair(item.firstRecovery)}</b><small>{item.firstRecovery.failures ?? "—"} 次未恢复</small></td>
              <td><b>{countPair(item.sustainedRecovery)}</b><small>{item.sustainedRecovery.failures ?? "—"} 次未持续</small></td>
              <td><b>{formatSeconds(item.firstRecovery.successfulMeanSeconds)}</b><small>仅首次恢复成功运行</small></td>
              <td><b>{formatSeconds(item.firstRecovery.allRunCensorMeanSeconds)}</b><small>失败按场景时长截尾；非生存分析估计</small></td>
            </tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className="research-cost-layout">
        <section className="research-cost-panel" aria-labelledby="cost-title">
          <div className="research-section-head"><div><span className="panel-kicker">RESOURCE / COMPUTE / CONDITIONAL QOS</span><h2 id="cost-title">成本与条件时延</h2><p>能耗、计算时间和时延采用原阶段汇总保存的均值。</p></div></div>
          <div className="research-cost-table-wrap" role="region" tabIndex={0} aria-label="资源成本和条件时延表，可横向滚动">
            <table className="research-table research-cost-table">
              <thead><tr><th scope="col">策略</th><th scope="col">机队能耗</th><th scope="col">单位救援服务能耗</th><th scope="col">条件平均 / P95 时延</th><th scope="col">计算耗时</th></tr></thead>
              <tbody>{visibleStrategies.map((item) => <tr key={item.id} className={item.id === selected.id ? "selected" : ""}>
                <th scope="row"><StrategyMark strategy={item} />{item.label}</th>
                <td><b>{formatEstimate(item.energyWh, "Wh")}</b><small>每运行/机队汇总</small></td>
                <td><b>{formatEstimate(item.energyPerRescueHour, "Wh / 用户小时")}</b><small>分母为模型中的 UAV 救援用户服务时长</small></td>
                <td><b>{formatLatency(item.conditionalMeanLatencyMs)} / {formatLatency(item.conditionalP95LatencyMs)} ms</b><small>成功用户—时刻样本 n = {item.latencySamples?.toLocaleString("zh-CN") ?? "—"}</small></td>
                <td><b>{formatEstimate(item.computeTotalMs, "ms")}</b><small>{item.computeLabel}</small></td>
              </tr>)}</tbody>
            </table>
          </div>
        </section>
      </section>

      <section className="research-strategy-panel" aria-labelledby="strategy-analysis-title">
        <div className="research-strategy-heading"><div><span className="panel-kicker">POLICY TRACE / CODE-VERIFIED CLASSIFICATION</span><h2 id="strategy-analysis-title">策略结构与适用边界</h2><p>分类依据项目当前实现模块；这组统计汇总没有记录单次运行的内部决策过程。</p></div><label><span>查看策略</span><select value={selected.id} onChange={(event) => setSelectedId(event.target.value)} aria-label="查看策略结构">{dataset.strategies.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label></div>
        <div className="research-strategy-detail">
          <div className="research-strategy-title"><StrategyMark strategy={selected} /><div><h3>{selected.label}</h3><span>{selected.category}</span></div><code>{selected.module}</code></div>
          <dl><div><dt>控制器观测</dt><dd>{selected.observation}</dd></div><div><dt>触发与决策</dt><dd>{selected.trigger}</dd></div><div><dt>安全与通信约束</dt><dd>{selected.constraints}</dd></div></dl>
          <div className="research-interpretation"><b>当前数据能说明</b><span>在 {view.scenarioLabel} 的 {view.seedCount} 个同阶段种子中，救援服务率均值为 {formatPercent(selected.rescueService.mean)}；恢复成功数、能耗、时延和计算耗时见上表。</span><small>不能由该汇总还原具体动作：该阶段汇总未包含与所选种子对应的完整逐帧策略决策日志。</small></div>
        </div>
      </section>

      {(phase === "phase10" || phase === "phase11") && <section className="research-replay-boundary" role="note"><div><span className="research-record-mark"><i />多机统计可用</span><b>多无人机逐帧回放不可用</b><p>Phase 10/11 提供按种子汇总的机队实验结果，没有可由 API 核验的逐帧多机坐标与链路状态。本页只展示保存的统计量，不补造轨迹。</p></div><Link to="/demo">打开已有单机离线回放</Link></section>}

      <footer className="research-provenance-footer">
        <div><span className="panel-kicker">TRACEABLE SOURCE</span><b>{view.sourcePath}</b><code>SHA-256 {view.sourceSha256}</code></div>
        <p>{view.statisticalMethod}</p>
        <p>数据来自冻结的抽象研究仿真汇总。不同阶段实验设计与种子集合不同，不能跨阶段直接混池。C/D/E/F/G/H/I/J 是规则或确定性优化实现，并非已训练的机器学习模型。该平台不是实测 6G 网络，也不构成标准符合性认证。</p>
      </footer>
    </PageTransition>
  );
}

function RescueRatePlot({ strategies, selectedId, onSelect }: { strategies: ResearchStrategy[]; selectedId: string; onSelect: (id: string) => void }) {
  return <div className="research-plot" role="group" aria-label="救援服务率均值和 95% 置信区间">
    <div className="research-plot-axis" aria-hidden="true"><span>策略</span><div><i>0</i><i>25</i><i>50</i><i>75</i><i>100%</i></div></div>
    {strategies.map((strategy) => {
      const value = strategy.rescueService.mean;
      const interval = strategy.rescueService.ci95;
      const point = value === null ? 0 : Math.max(0, Math.min(100, value * 100));
      const low = interval ? Math.max(0, Math.min(100, interval[0] * 100)) : point;
      const high = interval ? Math.max(0, Math.min(100, interval[1] * 100)) : point;
      const label = `${strategy.label}: ${formatPercent(value)}${interval ? `，95% 区间 ${formatPointInterval(interval)}` : "，未记录 95% 区间"}，n=${strategy.rescueService.n ?? "—"}`;
      return <button type="button" key={strategy.id} className={`research-plot-row ${strategy.id === selectedId ? "selected" : ""}`} onClick={() => onSelect(strategy.id)} aria-pressed={strategy.id === selectedId} aria-label={label} title={label}>
        <span className="research-plot-policy"><StrategyMark strategy={strategy} /><span>{strategy.label}</span></span>
        <span className="research-plot-track" aria-hidden="true">
          <span className="research-plot-interval" style={{ left: `${low}%`, width: `${Math.max(high - low, interval ? 0.6 : 0)}%` }} />
          {interval && <><i className="research-plot-cap low" style={{ left: `${low}%` }} /><i className="research-plot-cap high" style={{ left: `${high}%` }} /></>}
          <i className="research-plot-dot" style={{ left: `${point}%` }} />
        </span>
        <b className="research-plot-value">{formatPercent(value)}</b>
      </button>;
    })}
  </div>;
}

function StrategyMark({ strategy }: { strategy: ResearchStrategy }) {
  const letter = strategy.id.match(/^[A-Z]/)?.[0] ?? "·";
  return <span className={`research-strategy-mark strategy-${letter.toLowerCase()}`} aria-hidden="true">{letter}</span>;
}

function countPair(value: ResearchStrategy["firstRecovery"]): string {
  return value.successes === null || value.total === null ? "未记录" : `${value.successes} / ${value.total}`;
}

function formatPercent(value: number | null): string {
  return value === null ? "未记录" : `${PCT.format(value * 100)}%`;
}

function formatPointDifference(value: number | null): string {
  if (value === null) return "未记录";
  return `${value < 0 ? "−" : value > 0 ? "+" : ""}${PCT.format(Math.abs(value) * 100)} pp`;
}

function formatPointInterval(value: [number, number] | null): string {
  return value ? `[${PCT.format(value[0] * 100)}, ${PCT.format(value[1] * 100)}] pp` : "未保存";
}

function formatNumber(value: number | null): string {
  return value === null ? "未记录" : NUM.format(value);
}

function formatP(value: number): string {
  if (value <= 0) return NUM.format(value);
  return value < 0.001 ? Number(value.toPrecision(3)).toString() : NUM.format(value);
}

function formatSeconds(value: number | null): string {
  return value === null ? "未恢复 / 未记录" : `${NUM.format(value)} s`;
}

function formatLatency(value: number | null): string {
  return value === null ? "—" : NUM.format(value);
}

function formatEstimate(value: ResearchEstimate, unit: string): string {
  return value.mean === null ? "—" : `${NUM.format(value.mean)} ${unit}`;
}

function differenceTone(value: number | null): string {
  return value === null ? "" : value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
}
