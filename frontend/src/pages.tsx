import { lazy, Suspense, useState } from "react";
import type { EChartsOption } from "echarts";
import { Link } from "react-router-dom";
import mumbaiNight from "../../assets/mumbai-night-city-18219784390.jpg";
import {
  CityTwinScene,
  DataState,
  EventTimeline,
  Icon,
  OfflineNotice,
  PageTransition,
  ReplayControls,
  StatValue,
  StrategyPicker,
} from "./components";
import { formatTime, strategyLabel } from "./presentation";
import { useReplay } from "./useReplay";
import {
  PHASE5_SCENARIOS,
  type Phase5Estimate,
  type Phase5ScenarioId,
  type Phase5StrategyAggregate,
  type Phase5StrategyId,
  STRATEGIES,
  type StrategyAggregate,
  type StrategyId,
} from "./types";

const EChartsView = lazy(() => import("./EChartsView"));

const STRATEGY_ABBR: Record<StrategyId, string> = {
  A_no_recovery: "A",
  B_phase1_static_grid: "B",
  C_rolling_horizon_mpc: "C",
};

const PHASE5_ABBR: Record<Phase5StrategyId, string> = {
  A_no_recovery: "A",
  B_phase1_static_grid: "B",
  Bprime_static_grid_shared_safety: "B′",
  C_rolling_horizon_mpc: "C",
  D_lexicographic_rescue_priority: "D",
};

const SCENARIO_LABEL: Record<Phase5ScenarioId, string> = {
  severe_persistent_faults: "严重持续故障",
  dynamic_failures: "动态故障",
  high_mobility_rescue: "高移动救援",
  high_load_backhaul_limit: "高负载 / 回传受限",
};

export function HomePage() {
  const {
    replay,
    benchmark,
    phase5Benchmark,
    selectedRun,
    currentFrame,
    loading,
    error,
    selectedStrategy,
    setSelectedStrategy,
  } = useReplay();

  if (loading || error || !replay || !benchmark || !currentFrame || !selectedRun) {
    return <DataState title="项目回放暂不可用" />;
  }

  const connected = currentFrame.users.filter((user) => user.connected).length;
  const rescueUsers = currentFrame.users.filter((user) => user.group === "rescue");
  const rescueConnected = rescueUsers.filter((user) => user.connected).length;
  const healthy = currentFrame.stations.filter((station) => station.healthy).length;
  const failure = [...replay.environment_events]
    .filter((event) => event.event_type === "station_failure")
    .sort((a, b) => a.time_s - b.time_s)[0];
  const firstPlan = [...selectedRun.event_log]
    .filter((event) => event.event_type === "optimizer_decision")
    .sort((a, b) => a.time_s - b.time_s)[0];
  const recoveryTime = selectedRun.metrics.network_recovery_time_s;
  const strategyOrder = benchmark.strategy_order.length ? benchmark.strategy_order : [...STRATEGIES];
  const comparisonRows = strategyOrder.map((strategy) => {
    const run = replay.strategies[strategy];
    const frame = run.state_snapshots[Math.min(
      Math.round(currentFrame.time_s / replay.time_step_s),
      Math.max(0, run.state_snapshots.length - 1),
    )];
    return { strategy, frame, summary: benchmark.aggregate[strategy] };
  });

  return (
    <PageTransition className="home-page">
      <section className="home-hero" aria-labelledby="home-title">
        <img className="hero-city-image" src={mumbaiNight} alt="" aria-hidden="true" />
        <div className="home-hero-grid">
          <div className="hero-copy" data-enter>
            <h1 id="home-title"><span>6G /</span><strong>RESCUE</strong></h1>
            <p className="hero-subtitle">面向 6G 的低空应急网络智能自愈平台</p>
            <p className="hero-thesis">地面链路中断后，沿着真实仿真轨迹追踪通信如何重连。</p>
            <div className="hero-actions">
              <Link to="/demo" className="hero-primary-action">开始五分钟演示 <Icon name="arrow" /></Link>
              <Link to="/research" className="hero-secondary-action">查看研究证据</Link>
              <Link to="/command" className="hero-secondary-action">进入应急指挥中心</Link>
            </div>
            <div className="hero-metadata">
              <div><span>随机种子</span><b>{replay.seed}</b></div>
              <div><span>当前策略</span><b>{strategyLabel(selectedStrategy)}</b></div>
              <div><span>仿真时钟</span><b>T+{formatTime(currentFrame.time_s)}</b></div>
            </div>
            <a className="hero-photo-credit" href="https://commons.wikimedia.org/w/index.php?curid=44424580" target="_blank" rel="noreferrer">
              背景影像：孟买夜景 · Skye Vidur · CC BY-SA 2.0
            </a>
          </div>

          <div className="hero-twin" data-enter>
            <div className="hero-twin-head">
              <span>城市网络 / 当前仿真帧</span>
              <span><i className="status-led" /> {formatTime(currentFrame.time_s)} / {formatTime(replay.duration_s)}</span>
            </div>
            <CityTwinScene frame={currentFrame} className="hero-scene" labels={false} />
            <div className="hero-map-readout" aria-live="polite">
              <div><span>基站在线</span><b>{healthy}<small> / {currentFrame.stations.length}</small></b></div>
              <div><span>用户连接</span><b>{connected}<small> / {currentFrame.users.length}</small></b></div>
              <div className="rescue-readout"><span>救援服务</span><b>{rescueConnected}<small> / {rescueUsers.length}</small></b></div>
              <div><span>无人机</span><b>{currentFrame.drone.active ? "中继中" : "待命"}</b></div>
            </div>
            <p className="hero-map-disclosure">网络坐标来自仿真帧；城市影像仅作背景，不对应仿真地图。</p>
          </div>
        </div>

        <div className="hero-playback">
          <ReplayControls compact />
          <div className="hero-model-note"><OfflineNotice compact /><span>seed {replay.seed} · 每 {replay.time_step_s} 秒采样</span></div>
        </div>
      </section>

      <section className="home-trace section-shell" data-reveal aria-labelledby="trace-title">
        <div className="section-intro">
          <h2 id="trace-title">让每一次重连<br />都可以被追溯</h2>
          <p>选择策略并拖动仿真时钟，城市图、事件序列和连接状态会同步更新。指标始终来自保存的 Python 仿真结果。</p>
        </div>
        <div className="trace-list">
          <TraceStep time={failure ? formatTime(failure.time_s) : "—"} title="网络故障" detail={failure ? String(failure.target_id ?? "基站故障事件") : "当前轨迹没有记录基站故障"} tone="alert" />
          <TraceStep time={firstPlan ? formatTime(firstPlan.time_s) : "—"} title="策略响应" detail={firstPlan ? String(firstPlan.reason ?? "仿真引擎记录到调度决策") : "当前策略没有生成新的调度记录"} tone="active" />
          <TraceStep time={recoveryTime === null ? "未恢复" : formatTime(recoveryTime)} title={recoveryTime === null ? "尚未达到恢复判据" : "网络恢复"} detail={recoveryTime === null ? "失败运行按未恢复保留，不填补恢复时间。" : "本次策略的恢复耗时来自实际运行指标。"} tone={recoveryTime === null ? "alert" : "healthy"} />
        </div>
      </section>

      <section className="home-evidence" data-reveal aria-labelledby="evidence-title">
        <div className="section-shell evidence-shell">
          <div className="section-heading-row">
            <div><h2 id="evidence-title">同一时刻，三种策略</h2><p>当前用户连接来自同一组 seed {replay.seed} 的配对世界轨迹。</p></div>
            <Link className="inline-link" to="/decision">查看调度依据 <Icon name="arrow" /></Link>
          </div>
          <div className="strategy-comparison" data-ui="measured-strategy-comparison">
            {comparisonRows.map(({ strategy, frame, summary }) => {
              if (!frame || !summary) return null;
              const frameRescue = frame.users.filter((user) => user.group === "rescue");
              const served = frameRescue.filter((user) => user.connected).length;
              const meanRecovery = summary.network_recovery.recovered_only_time_s.mean;
              return (
                <button type="button" className={"comparison-row " + (strategy === selectedStrategy ? "selected" : "")} key={strategy} onClick={() => setSelectedStrategy(strategy)} aria-pressed={strategy === selectedStrategy}>
                  <span className="comparison-policy">{strategyLabel(strategy)}</span>
                  <span><small>当前连接</small><b>{frame.users.filter((user) => user.connected).length}<i> / {frame.users.length}</i></b></span>
                  <span><small>救援用户服务</small><b>{served}<i> / {frameRescue.length}</i></b></span>
                  <span><small>20 种子恢复均值</small><b>{meanRecovery === null ? "未恢复" : meanRecovery.toFixed(0) + " s"}</b></span>
                  <span className="comparison-state">{strategy === selectedStrategy ? "正在回放" : "切换策略"} <Icon name="arrow" /></span>
                </button>
              );
            })}
          </div>
          <div className="evidence-footline">
            <span>{benchmark.reproducibility.seed_count} 个固定种子 · 历史 Phase 2 对照结果</span>
            <Link to="/lab">读取原始统计口径 <Icon name="arrow" /></Link>
          </div>
        </div>
      </section>

      {phase5Benchmark && (
        <section className="home-validation section-shell" data-reveal aria-labelledby="validation-title">
          <div className="validation-lead">
            <h2 id="validation-title">四类灾害<br />留出验证</h2>
            <p>Phase 5 在独立种子上比较五种策略，结果按场景展示；优化策略并非在所有场景都占优。</p>
            <Link className="inline-link" to="/lab">打开多灾种验证 <Icon name="arrow" /></Link>
          </div>
          <div className="validation-list">
            {PHASE5_SCENARIOS.map((scenario) => {
              const item = phase5Benchmark.scenarios[scenario];
              const delta = item.paired_differences.D_minus_B_phase1_static_grid.rescue_user_service_success_rate.mean;
              const deltaPercentagePoints = delta === null ? null : delta * 100;
              return (
                <div className="validation-row" key={scenario}>
                  <b>{SCENARIO_LABEL[scenario]}</b>
                  <span>{item.validation_seed_count} 留出种子</span>
                  <strong className={deltaPercentagePoints === null ? "" : deltaPercentagePoints >= 0 ? "value-good" : "value-alert"}>
                    {deltaPercentagePoints === null ? "暂无配对值" : (deltaPercentagePoints > 0 ? "+" : "") + deltaPercentagePoints.toFixed(2) + " pp"}
                  </strong>
                  <small>D − B 救援服务率差</small>
                </div>
              );
            })}
          </div>
        </section>
      )}

    </PageTransition>
  );
}

function TraceStep({ time, title, detail, tone }: { time: string; title: string; detail: string; tone: string }) {
  return (
    <div className={"trace-step " + tone}>
      <span className="trace-mark" aria-hidden="true" />
      <time>{time}</time>
      <div><b>{title}</b><p>{detail}</p></div>
    </div>
  );
}

export function CommandPage() {
  const { replay, benchmark, selectedRun, currentFrame, loading, error } = useReplay();
  if (loading || error || !replay || !benchmark || !selectedRun || !currentFrame) return <DataState />;

  const healthy = currentFrame.stations.filter((station) => station.healthy).length;
  const connectedUsers = currentFrame.users.filter((user) => user.connected);
  const rescueUsers = currentFrame.users.filter((user) => user.group === "rescue");
  const rescueConnected = rescueUsers.filter((user) => user.connected).length;
  const normalConnected = connectedUsers.filter((user) => user.group === "normal").length;
  const drone = currentFrame.drone;
  const environmentEvents = replay.environment_events.filter((event) => event.source === "configured_event_schedule").length;

  return (
    <PageTransition className="workspace-page command-page">
      <header className="page-heading command-heading" data-enter>
        <div><h1>城市网络态势</h1><p>故障、终端连接与无人机中继，按仿真时钟逐帧复盘。</p></div>
        <div className="heading-tools"><StrategyPicker /><OfflineNotice compact /></div>
      </header>

      <section className="signal-ribbon" aria-label="当前网络指标">
        <MetricCell label="地面站在线" value={healthy + " / " + currentFrame.stations.length} note={healthy === currentFrame.stations.length ? "未记录站点故障" : currentFrame.stations.length - healthy + " 座故障"} alert={healthy < currentFrame.stations.length} />
        <MetricCell label="用户连接" value={connectedUsers.length + " / " + currentFrame.users.length} note={normalConnected + " 普通 · " + rescueConnected + " 救援"} />
        <MetricCell label="重点救援服务" value={rescueConnected + " / " + rescueUsers.length} note="当前采样时刻" alert={rescueConnected < rescueUsers.length} />
        <MetricCell label="空中中继" value={drone.active ? "工作中" : "待命"} note={drone.battery_wh.toFixed(1) + " Wh · 回传" + (drone.backhaul_available ? "可用" : "中断")} />
      </section>

      <div className="command-layout">
        <section className="twin-panel" data-reveal>
          <div className="panel-heading">
            <div><span className="panel-kicker">LIVE REPLAY FRAME</span><h2>应急通信拓扑</h2></div>
            <div className="panel-live-meta"><span className="status-led" /> T+{formatTime(currentFrame.time_s)} <i /> 采样间隔 {replay.time_step_s}s</div>
          </div>
          <CityTwinScene frame={currentFrame} className="command-scene" />
          <ReplayControls />
          <div className="scene-source-note">种子 {replay.seed} · 节点、用户坐标、链路与无人机状态来自当前仿真帧。地图仅为抽象平面。</div>
        </section>

        <aside className="command-side">
          <section className="event-panel" data-reveal>
            <div className="panel-heading compact-heading">
              <div><span className="panel-kicker">FAULT TIMELINE</span><h2>故障与调度事件</h2></div>
              <span className="event-count">{environmentEvents} 环境事件</span>
            </div>
            <EventTimeline maxItems={12} />
          </section>
          <section className="terminals-panel" data-reveal>
            <div className="panel-heading compact-heading">
              <div><span className="panel-kicker">RESCUE USERS</span><h2>救援终端</h2></div>
              <span className="event-count">{rescueConnected} / {rescueUsers.length} 在线</span>
            </div>
            <div className="terminal-list">
              {rescueUsers.map((user) => (
                <div className={"terminal-row " + (user.connected ? "connected" : "lost")} key={user.id}>
                  <span className="terminal-signal" />
                  <b>{user.id.toUpperCase()}</b>
                  <span>{user.connected ? user.path_kind === "drone_relay" ? "空中中继" : "直连" : user.covered ? "容量阻塞" : "无覆盖"}</span>
                  <small>{user.latency_ms === null ? "未采样" : user.latency_ms.toFixed(1) + " ms"}</small>
                </div>
              ))}
            </div>
          </section>
          <section className="command-benchmark" data-reveal>
            <span>配对基准</span><b>{benchmark.reproducibility.seed_count} seeds</b>
            <p>固定配置与随机种子，恢复时间和连接率按完整实验统计。</p>
            <Link to="/lab">打开实验室 <Icon name="arrow" /></Link>
          </section>
        </aside>
      </div>
    </PageTransition>
  );
}

function MetricCell({ label, value, note, alert = false }: { label: string; value: string; note: string; alert?: boolean }) {
  return (
    <div className="signal-cell">
      <span>{label}</span>
      <b className={alert ? "value-alert" : ""}>{value}</b>
      <small>{note}</small>
    </div>
  );
}

export function DecisionPage() {
  const { replay, selectedRun, currentFrame, selectedStrategy, selectedTime, loading, error, setSelectedTime } = useReplay();
  if (loading || error || !replay || !selectedRun || !currentFrame) return <DataState />;

  const decision = currentFrame.decision;
  const diagnosis = currentFrame.diagnosis;
  const config = replay.configuration.dynamic;
  const decisionMade = decision.decision_made === true;
  const destination = Array.isArray(decision.destination_km) ? decision.destination_km as number[] : null;
  const reasons = Array.isArray(decision.infeasible_reasons) ? decision.infeasible_reasons.map(String) : [];
  const recentDecisions = selectedRun.event_log
    .filter((event) => event.event_type === "optimizer_decision" && event.time_s <= selectedTime)
    .slice(-5)
    .reverse();

  return (
    <PageTransition className="workspace-page decision-page">
      <header className="page-heading" data-enter>
        <div><h1>智能自愈决策</h1><p>查看所选仿真时刻的真实诊断、约束筛选与调度输出。</p></div>
        <div className="heading-tools"><StrategyPicker /><OfflineNotice compact /></div>
      </header>

      <section className="decision-summary" data-reveal>
        <div className="decision-method">
          <span className="decision-method-symbol"><Icon name="route" /></span>
          <div>
            <strong>{selectedStrategy === "C_rolling_horizon_mpc" ? "滚动时域候选搜索" : strategyLabel(selectedStrategy)}</strong>
            <p>{selectedStrategy === "C_rolling_horizon_mpc" ? "确定性 beam search · 不是训练所得的机器学习模型" : selectedStrategy === "B_phase1_static_grid" ? "第一阶段规则网格策略 · 单次静态部署搜索" : "无恢复基线 · 不调度无人机"}</p>
          </div>
        </div>
        <div className="decision-summary-value"><span>决策均值</span><b><StatValue value={selectedRun.metrics.algorithm_decision_mean_ms} unit="ms" digits={2} /></b></div>
        <div className="decision-summary-value"><span>完整运行重规划</span><b><StatValue value={selectedRun.metrics.replan_count} unit="次" digits={0} /></b></div>
        <div className="decision-summary-value"><span>不可行决策</span><b><StatValue value={selectedRun.metrics.infeasible_decision_count} unit="次" digits={0} /></b></div>
      </section>

      <div className="decision-layout">
        <div className="decision-main-column">
          <section className="decision-current-panel" data-reveal>
            <div className="panel-heading">
              <div><span className="panel-kicker">SELECTED FRAME · T+{formatTime(selectedTime)}</span><h2>{decisionMade ? "本时刻调度输出" : "当前控制状态"}</h2></div>
              <span className={"decision-status " + (decision.deploy === true ? "active" : "idle")}>{decision.deploy === true ? "中继部署" : "未部署"}</span>
            </div>
            <div className="decision-action-grid">
              <div className="action-primary">
                <span>动作与原因</span>
                <strong>{decisionTitle(String(decision.reason ?? "未知"))}</strong>
                <p>{decisionExplanation(String(decision.reason ?? "未知"), String(decision.trigger ?? ""))}</p>
              </div>
              <div className="action-target"><span>目标坐标</span><strong>{destination ? destination[0].toFixed(3) + " / " + destination[1].toFixed(3) : "暂无"}</strong><small>km · 城市平面位置</small></div>
              <div className="action-target"><span>目标函数得分</span><strong>{typeof decision.objective_score === "number" ? decision.objective_score.toFixed(4) : "暂无"}</strong><small>{decisionMade ? "当前步搜索输出" : "沿用现有计划"}</small></div>
              <div className="action-target"><span>本步算法计算</span><strong>{decisionMade ? <StatValue value={Number(decision.decision_time_ms ?? 0)} unit="ms" digits={2} /> : "未重规划"}</strong><small>计算耗时，不是恢复耗时</small></div>
            </div>
            {reasons.length > 0 && (
              <div className="infeasible-block"><b>当前不可行原因</b><div>{reasons.map((reason) => <span key={reason}>{reasonLabel(reason)}</span>)}</div></div>
            )}
          </section>

          <section className="diagnosis-panel" data-reveal>
            <div className="panel-heading compact-heading"><div><span className="panel-kicker">NETWORK DIAGNOSIS</span><h2>网络状态诊断</h2></div><span className="event-count">由当前仿真帧计算</span></div>
            <div className="diagnosis-grid">
              <DiagnosisCell label="故障基站" values={diagnosis.failed_station_ids} empty="无故障站" />
              <DiagnosisCell label="失联用户" values={diagnosis.disconnected_user_ids} empty="全部连通" />
              <DiagnosisCell label="失联救援用户" values={diagnosis.disconnected_rescue_ids} empty="重点用户已连接" critical />
              <DiagnosisCell label="拥塞资源" values={diagnosis.congested_resource_ids} empty="未达到拥塞阈值" />
            </div>
            <div className="diagnosis-foot"><span>无人机回传</span><b className={diagnosis.drone_backhaul_available ? "value-good" : "value-alert"}>{diagnosis.drone_backhaul_available ? "可用" : "暂时中断"}</b><span>当前业务倍率</span><b>{currentFrame.traffic_multiplier.toFixed(2)}×</b><span>无人机电量</span><b>{currentFrame.drone.battery_wh.toFixed(1)} Wh</b></div>
          </section>

          <section className="decision-history-panel" data-reveal>
            <div className="panel-heading compact-heading"><div><span className="panel-kicker">DECISION TRACE</span><h2>最近调度记录</h2></div><span className="event-count">seed {replay.seed}</span></div>
            <div className="decision-records">
              {recentDecisions.map((event, index) => (
                <button type="button" className="decision-record" key={String(event.time_s) + "-" + index} onClick={() => setSelectedTime(event.time_s)}>
                  <span>{formatTime(event.time_s)}</span><b>{decisionTitle(String(event.reason ?? "未知"))}</b><small>{String(event.trigger ?? "")}</small><Icon name="chevron" />
                </button>
              ))}
              {recentDecisions.length === 0 && <div className="empty-inline">当前时刻之前没有新的调度记录。</div>}
            </div>
          </section>
        </div>

        <aside className="decision-side-column">
          <section className="decision-scene-panel" data-reveal>
            <div className="panel-heading compact-heading"><div><span className="panel-kicker">NETWORK FRAME</span><h2>当前网络平面</h2></div><span className="event-count">T+{formatTime(currentFrame.time_s)}</span></div>
            <CityTwinScene frame={currentFrame} className="decision-scene" labels={false} />
          </section>
          <section className="constraints-panel" data-reveal>
            <div className="panel-heading compact-heading"><div><span className="panel-kicker">FEASIBILITY BOUNDARY</span><h2>规划约束</h2></div></div>
            <div className="constraint-row"><span>预测时域</span><b>{config.prediction_horizon_steps} 步</b></div>
            <div className="constraint-row"><span>Beam width</span><b>{config.beam_width}</b></div>
            <div className="constraint-row"><span>单步最大位移</span><b>{(Number(replay.configuration.base.drone.speed_km_per_s) * replay.time_step_s).toFixed(3)} km</b></div>
            <div className="constraint-row"><span>电量保护储备</span><b>{config.reserve_wh} Wh</b></div>
            <div className="constraint-row"><span>当前剩余电量</span><b>{currentFrame.drone.battery_wh.toFixed(1)} Wh</b></div>
            <div className="constraint-row"><span>不可行规划次数</span><b>{selectedRun.metrics.infeasible_decision_count}</b></div>
            <p className="constraint-note">候选动作受距离、容量、回传、飞行速度与续航约束。这里展示已有仿真记录，不触发实时无人机控制。</p>
          </section>
        </aside>
      </div>
      <div className="decision-playback"><ReplayControls compact /></div>
    </PageTransition>
  );
}

function DiagnosisCell({ label, values, empty, critical = false }: { label: string; values: string[]; empty: string; critical?: boolean }) {
  return (
    <div className={"diagnosis-cell " + (critical && values.length ? "critical" : "")}>
      <span>{label}<b>{values.length}</b></span>
      <div>{values.length ? values.slice(0, 5).map((value) => <i key={value}>{value}</i>) : <small>{empty}</small>}{values.length > 5 && <small>+{values.length - 5}</small>}</div>
    </div>
  );
}

export function LabPage() {
  const { benchmark, phase5Benchmark, phase5Error, loading, error } = useReplay();
  const [view, setView] = useState<"phase2" | "phase5">("phase5");
  const [scenario, setScenario] = useState<Phase5ScenarioId>("severe_persistent_faults");
  if (loading || error || !benchmark) return <DataState title="实验结果暂不可用" />;

  const showingPhase5 = view === "phase5" && phase5Benchmark !== null;
  const scenarioResult = showingPhase5 ? phase5Benchmark.scenarios[scenario] : null;

  return (
    <PageTransition className="workspace-page lab-page">
      <header className="page-heading lab-heading" data-enter>
        <div><h1>算法性能实验室</h1><p>保留历史基线，并逐场景检视多灾种留出验证。</p></div>
        <div className="lab-heading-side">
          <div className="experiment-stamp"><b>{showingPhase5 ? "80" : benchmark.reproducibility.seed_count}</b><span>{showingPhase5 ? "留出策略运行" : "固定随机种子"}</span><small>{showingPhase5 ? "4 场景 × 20 种子" : benchmark.reproducibility.seeds[0] + "–" + benchmark.reproducibility.seeds[benchmark.reproducibility.seeds.length - 1]}</small></div>
          <OfflineNotice compact />
        </div>
      </header>

      <div className="lab-switcher" role="tablist" aria-label="选择实验数据集">
        <button type="button" role="tab" aria-selected={showingPhase5} className={showingPhase5 ? "active" : ""} onClick={() => setView("phase5")}>Phase 5 · 多灾种留出验证</button>
        <button type="button" role="tab" aria-selected={!showingPhase5} className={!showingPhase5 ? "active" : ""} onClick={() => setView("phase2")}>Phase 2 · 20 种子历史基线</button>
      </div>

      {showingPhase5 && scenarioResult && phase5Benchmark ? (
        <Phase5Lab
          benchmark={phase5Benchmark}
          scenario={scenario}
          setScenario={setScenario}
          result={scenarioResult}
        />
      ) : view === "phase5" ? (
        <section className="unavailable-experiment" role="status">
          <div><span className="data-state-symbol">!</span><h2>第五阶段验证数据不可用</h2><p>{phase5Error ?? "FastAPI 尚未提供 Phase 5 汇总结果；不会用演示数据填补。"}</p></div>
          <button type="button" className="text-button" onClick={() => setView("phase2")}>查看历史基线</button>
        </section>
      ) : (
        <Phase2Lab benchmark={benchmark} />
      )}
    </PageTransition>
  );
}

function Phase2Lab({ benchmark }: { benchmark: NonNullable<ReturnType<typeof useReplay>["benchmark"]> }) {
  const aggregate = benchmark.aggregate;
  const order = benchmark.strategy_order.length ? benchmark.strategy_order : [...STRATEGIES];
  const labels = order.map((id) => STRATEGY_ABBR[id]);
  const connection = order.map((id) => percentValue(aggregate[id].metrics.user_connection_success_rate.mean));
  const rescue = order.map((id) => percentValue(aggregate[id].metrics.rescue_user_service_success_rate.mean));
  const recovery = order.map((id) => aggregate[id].network_recovery.recovered_only_time_s.mean);
  const latencyMean = order.map((id) => aggregate[id].latency_conditioned_on_success.pooled_average_ms);
  const latencyP95 = order.map((id) => aggregate[id].latency_conditioned_on_success.pooled_p95_ms);
  const energy = order.map((id) => aggregate[id].metrics.drone_energy_consumed_wh.mean);
  const compute = order.map((id) => aggregate[id].metrics.algorithm_decision_total_ms.mean);

  const percentOption: EChartsOption = {
    ...baseChart,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (value) => Number(value).toFixed(2) + "%" },
    legend: { ...baseChart.legend as object, data: ["用户连接", "救援服务"] },
    xAxis: { type: "category", data: labels, axisTick: { show: false } },
    yAxis: { type: "value", min: 0, max: 100, axisLabel: { fontSize: 13, formatter: "{value}%" }, splitLine: { lineStyle: { color: "#ffffff12" } } },
    series: [
      { name: "用户连接", type: "bar", data: connection, itemStyle: { color: "#ee6845", borderRadius: [2, 2, 0, 0] }, barMaxWidth: 30 },
      { name: "救援服务", type: "bar", data: rescue, itemStyle: { color: "#f1bf7e", borderRadius: [2, 2, 0, 0] }, barMaxWidth: 30 },
    ],
  };
  const recoveryOption: EChartsOption = {
    ...singleSeriesChart,
    tooltip: { trigger: "axis", valueFormatter: (value) => value === null ? "未恢复" : Number(value).toFixed(0) + " s" },
    xAxis: { type: "category", data: labels, axisTick: { show: false } },
    yAxis: { type: "value", name: "秒", axisLabel: { fontSize: 13, formatter: "{value}s" }, splitLine: { lineStyle: { color: "#ffffff12" } } },
    series: [{ name: "已恢复运行平均耗时", type: "bar", data: recovery, itemStyle: { color: "#d78d62" }, barMaxWidth: 44 }],
  };
  const latencyOption: EChartsOption = {
    ...baseChart,
    tooltip: { trigger: "axis", valueFormatter: (value) => Number(value).toFixed(2) + " ms" },
    legend: { ...baseChart.legend as object, data: ["平均时延", "P95 时延"] },
    xAxis: { type: "category", data: labels, axisTick: { show: false } },
    yAxis: { type: "value", name: "ms", axisLabel: { fontSize: 13, formatter: "{value}ms" }, splitLine: { lineStyle: { color: "#ffffff12" } } },
    series: [
      { name: "平均时延", type: "line", data: latencyMean, symbol: "circle", symbolSize: 7, lineStyle: { color: "#ee6845", width: 2 }, itemStyle: { color: "#ee6845" } },
      { name: "P95 时延", type: "line", data: latencyP95, symbol: "circle", symbolSize: 7, lineStyle: { color: "#f1bf7e", width: 2 }, itemStyle: { color: "#f1bf7e" } },
    ],
  };
  const energyOption: EChartsOption = {
    ...singleSeriesChart,
    tooltip: { trigger: "axis", valueFormatter: (value) => Number(value).toFixed(2) + " Wh" },
    xAxis: { type: "category", data: labels, axisTick: { show: false } },
    yAxis: { type: "value", name: "Wh", axisLabel: { fontSize: 13 }, splitLine: { lineStyle: { color: "#ffffff12" } } },
    series: [{ name: "无人机能耗", type: "bar", data: energy, itemStyle: { color: "#ba7059" }, barMaxWidth: 44 }],
  };
  const computeOption: EChartsOption = {
    ...singleSeriesChart,
    tooltip: { trigger: "axis", valueFormatter: (value) => Number(value).toFixed(1) + " ms / 次运行" },
    xAxis: { type: "category", data: labels, axisTick: { show: false } },
    yAxis: { type: "value", name: "ms", axisLabel: { fontSize: 13 }, splitLine: { lineStyle: { color: "#ffffff12" } } },
    series: [{ name: "算法决策总耗时", type: "bar", data: compute, itemStyle: { color: "#936f62" }, barMaxWidth: 44 }],
  };

  return (
    <>
      <div className="lab-source-banner" data-reveal>
        <span className="source-led" />
        <span>历史来源</span><code>results/phase2_20_seed_results.json</code>
        <span>20 个固定种子 · 配对世界轨迹 · 汇总自已保存的 JSON</span>
        <button type="button" className="text-button" onClick={() => navigator.clipboard?.writeText(benchmark.reproducibility.effective_config_sha256)}>复制配置哈希 <Icon name="layers" /></button>
      </div>

      <section className="chart-grid" data-reveal>
        <ChartPanel title="连接与重点服务" subtitle="跨种子均值 · %" option={percentOption} wide />
        <ChartPanel title="网络恢复时间" subtitle="只统计达到恢复条件的运行" option={recoveryOption} />
        <ChartPanel title="条件时延" subtitle="各策略成功连接用户时刻样本 · ms" option={latencyOption} wide />
        <ChartPanel title="无人机能耗" subtitle="每次完整运行 · Wh" option={energyOption} />
        <ChartPanel title="算法决策耗时" subtitle="每次完整运行累计 · ms" option={computeOption} />
      </section>

      <section className="results-table-panel" data-reveal>
        <div className="panel-heading">
          <div><h2>三组策略汇总</h2></div>
          <div className="table-heading-meta">
            <span>连接指标：跨种子均值 ± 样本标准差</span>
            <span className="table-scroll-hint phase2-table-hint">横向滚动查看全部指标</span>
          </div>
        </div>
        <div className="table-scroll" role="region" tabIndex={0} aria-label="三组策略指标汇总表，可横向滚动查看全部列">
          <table className="results-table">
            <thead><tr><th scope="col">策略</th><th scope="col">连接率</th><th scope="col">救援服务率</th><th scope="col">恢复成功</th><th scope="col">恢复耗时</th><th scope="col">平均时延</th><th scope="col">P95 时延</th><th scope="col">无人机能耗</th><th scope="col">计算耗时</th></tr></thead>
            <tbody>{order.map((id, index) => <Phase2ResultRow key={id} id={id} index={index} summary={aggregate[id]} total={benchmark.reproducibility.seed_count} />)}</tbody>
          </table>
        </div>
        <div className="results-method-note">
          <p>平均 / P95 时延按各策略成功连接的用户与时刻分别统计，样本集合不同，只作条件描述。恢复时间只对已恢复运行求均值，未恢复数量单独列出。</p>
          <p>算法计算耗时与网络恢复秒数分开。历史结果中滚动优化没有在所有指标上超过静态策略。</p>
        </div>
      </section>
      <div className="lab-disclaimer"><OfflineNotice compact /><span>抽象研究仿真 · 非无线设备实测 · 不代表真实 6G 性能</span></div>
    </>
  );
}

function Phase5Lab({
  benchmark,
  scenario,
  setScenario,
  result,
}: {
  benchmark: NonNullable<ReturnType<typeof useReplay>["phase5Benchmark"]>;
  scenario: Phase5ScenarioId;
  setScenario: (value: Phase5ScenarioId) => void;
  result: NonNullable<NonNullable<ReturnType<typeof useReplay>["phase5Benchmark"]>["scenarios"][Phase5ScenarioId]>;
}) {
  const order = benchmark.strategy_order;
  const summary = result.aggregate;
  const rescueRates = order.map((id) => percentValue(summary[id].metrics.rescue_user_service_success_rate.mean));
  const sustainedRates = order.map((id) => summary[id].sustained_network_recovery_30s.success_rate * 100);
  const chartOption: EChartsOption = {
    ...baseChart,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (value) => Number(value).toFixed(2) + "%" },
    legend: { ...baseChart.legend as object, data: ["救援服务率", "持续恢复率"] },
    xAxis: { type: "category", data: order.map((id) => PHASE5_ABBR[id]), axisTick: { show: false } },
    yAxis: { type: "value", min: 0, max: 100, axisLabel: { fontSize: 13, formatter: "{value}%" }, splitLine: { lineStyle: { color: "#ffffff12" } } },
    series: [
      { name: "救援服务率", type: "bar", data: rescueRates, itemStyle: { color: "#ee6845" }, barMaxWidth: 38 },
      { name: "持续恢复率", type: "bar", data: sustainedRates, itemStyle: { color: "#f1bf7e" }, barMaxWidth: 38 },
    ],
  };
  const paired = result.paired_differences.D_minus_B_phase1_static_grid?.rescue_user_service_success_rate;
  const pairInterval = paired?.mean_ci95_t;
  const pairedText = paired && paired.mean !== null
    ? (paired.mean > 0 ? "+" : "") + (paired.mean * 100).toFixed(2) + " pp"
      + (pairInterval ? " [" + (pairInterval[0] * 100).toFixed(2) + ", " + (pairInterval[1] * 100).toFixed(2) + "]" : "")
    : "不可计算";

  return (
    <>
      <div className="phase5-source-banner" data-reveal>
        <div><span className="source-led" /><b>冻结验证数据</b><span>results/{result.raw_seed_results}</span></div>
        <div><span>{result.validation_seed_count} 个留出种子</span><button type="button" className="text-button" onClick={() => navigator.clipboard?.writeText(result.effective_config_sha256)}>复制配置哈希 <Icon name="layers" /></button></div>
      </div>

      <div className="scenario-selector" data-reveal>
        <div><h2>{SCENARIO_LABEL[scenario]}</h2><p>每类 20 个固定留出种子；置信区间反映模拟种子波动，不代表真实网络总体。</p></div>
        <label><span>切换场景</span><select value={scenario} onChange={(event) => setScenario(event.target.value as Phase5ScenarioId)}>{PHASE5_SCENARIOS.map((id) => <option value={id} key={id}>{SCENARIO_LABEL[id]}</option>)}</select></label>
        <div className="paired-callout"><span>D − B 救援服务率差</span><strong>{pairedText}</strong><small>同种子配对差 · 百分点</small></div>
      </div>

      <section className="chart-grid phase5-chart-grid" data-reveal>
        <ChartPanel title="救援服务与持续恢复" subtitle="跨留出种子均值 · %" option={chartOption} wide />
        <section className="scenario-facts">
          <div><span>验证种子数</span><b>{result.validation_seed_count}</b></div>
          <div><span>策略运行数</span><b>{result.validation_seed_count * order.length}</b></div>
          <div><span>配置 SHA-256</span><code>{result.effective_config_sha256.slice(0, 16)}…</code></div>
          <p>{scenarioExplanation(scenario)}</p>
        </section>
      </section>

      <section className="results-table-panel phase5-results-panel" data-reveal>
        <div className="panel-heading">
          <div><h2>策略结果与成本</h2></div>
          <div className="table-heading-meta">
            <span>均值及 95% 区间 · 失败运行保留</span>
            <span className="table-scroll-hint phase5-table-hint">横向滚动查看全部指标</span>
          </div>
        </div>
        <div className="table-scroll" role="region" tabIndex={0} aria-label="多灾害策略结果与成本表，可横向滚动查看全部列">
          <table className="results-table phase5-table">
            <thead><tr><th scope="col">策略</th><th scope="col">救援服务率</th><th scope="col">首次全恢复</th><th scope="col">持续 30 秒</th><th scope="col">恢复时间</th><th scope="col">时延 / P95</th><th scope="col">救援服务</th><th scope="col">能耗</th><th scope="col">Wh / 用户小时</th><th scope="col">控制器耗时</th></tr></thead>
            <tbody>{order.map((id) => <Phase5ResultRow key={id} id={id} summary={summary[id]} total={result.validation_seed_count} />)}</tbody>
          </table>
        </div>
        <div className="results-method-note">
          <p>服务率按救援用户-时间步统计；首次恢复要求同一观测时刻所有救援用户均连接，持续恢复要求连续 30 秒。未恢复运行记作失败，另列恢复成功数与失败数。</p>
          <p>时延仅统计成功连接的用户时刻，策略间样本集合不同。无人机救援服务以实际 drone_relay 用户小时计，单位能耗是 Wh / 救援用户小时；控制器耗时是整次仿真的 wall-clock 累计。</p>
        </div>
      </section>
      <div className="lab-disclaimer"><OfflineNotice compact /><span>{benchmark.model_scope} · 结果来自抽象仿真，不是无线设备实测。</span></div>
    </>
  );
}

function Phase2ResultRow({ id, index, summary, total }: { id: StrategyId; index: number; summary: StrategyAggregate; total: number }) {
  const connection = summary.metrics.user_connection_success_rate;
  const rescue = summary.metrics.rescue_user_service_success_rate;
  const recoveryTime = summary.network_recovery.recovered_only_time_s.mean;
  const recovery = summary.network_recovery;
  const latency = summary.latency_conditioned_on_success;
  const energy = summary.metrics.drone_energy_consumed_wh.mean;
  const compute = summary.metrics.algorithm_decision_total_ms.mean;
  return (
    <tr>
      <td><span className={"strategy-code strategy-" + index}>{STRATEGY_ABBR[id]}</span><span>{strategyLabel(id).slice(4)}</span></td>
      <td><b>{formatPercent(connection.mean)}</b><small> ± {formatPercent(connection.sample_sd === undefined ? null : connection.sample_sd)}</small></td>
      <td><b>{formatPercent(rescue.mean)}</b><small> ± {formatPercent(rescue.sample_sd === undefined ? null : rescue.sample_sd)}</small></td>
      <td><b>{recovery.recovered_runs} / {total}</b><small>{recovery.unrecovered_runs} 未恢复</small></td>
      <td><b>{recoveryTime === null ? "未恢复" : recoveryTime.toFixed(0) + " s"}</b><small>仅已恢复运行</small></td>
      <td><b>{latency.pooled_average_ms?.toFixed(3) ?? "无样本"}{latency.pooled_average_ms === null ? "" : " ms"}</b><small>成功用户时刻样本</small></td>
      <td><b>{latency.pooled_p95_ms?.toFixed(3) ?? "无样本"}{latency.pooled_p95_ms === null ? "" : " ms"}</b><small>{latency.pooled_successful_user_time_samples.toLocaleString("zh-CN")} 个样本</small></td>
      <td><b>{formatMean(energy)} Wh</b><small>跨种子均值</small></td>
      <td><b>{formatMean(compute)} ms</b><small>墙钟 / 次运行</small></td>
    </tr>
  );
}

function Phase5ResultRow({ id, summary, total }: { id: Phase5StrategyId; summary: Phase5StrategyAggregate; total: number }) {
  const metrics = summary.metrics;
  const rescue = metrics.rescue_user_service_success_rate;
  const latency = summary.latency_conditioned_on_success;
  const serviceHours = metrics.drone_rescue_user_seconds?.mean;
  const serviceText = serviceHours === null || serviceHours === undefined ? "—" : (serviceHours / 3600).toFixed(3) + " h";
  const energy = metrics.drone_energy_consumed_wh?.mean;
  const energyRatio = metrics.drone_energy_wh_per_rescue_user_hour?.mean;
  const controller = metrics.controller_observe_total_ms?.mean;
  const recovery = summary.network_recovery;
  const sustained = summary.sustained_network_recovery_30s;
  return (
    <tr>
      <td><span className={"strategy-code strategy-" + id.slice(0, 1).toLowerCase()}>{PHASE5_ABBR[id]}</span><span>{phase5StrategyLabel(id)}</span></td>
      <td><b>{formatPercent(rescue.mean)}</b><small>{formatEstimateInterval(rescue, true)}</small></td>
      <td><b>{recovery.recovered_runs} / {total}</b><small>{recovery.unrecovered_runs} 未恢复</small></td>
      <td><b>{sustained.recovered_runs} / {total}</b><small>{sustained.unrecovered_runs} 未持续</small></td>
      <td><b>{formatMean(recovery.recovered_only_time_s.mean)} s</b><small>仅成功运行</small></td>
      <td><b>{latency.pooled_average_ms?.toFixed(2) ?? "无样本"} / {latency.pooled_p95_ms?.toFixed(2) ?? "无样本"}</b><small>ms · n={latency.pooled_successful_user_time_samples.toLocaleString("zh-CN")}</small></td>
      <td><b>{serviceText}</b><small>无人机中继救援用户小时</small></td>
      <td><b>{formatMean(energy)} Wh</b><small>全程能耗</small></td>
      <td><b>{formatMean(energyRatio)}</b><small>Wh / 用户小时</small></td>
      <td><b>{formatMean(controller)} ms</b><small>控制器累计墙钟时间</small></td>
    </tr>
  );
}

function ChartPanel({ title, subtitle, option, wide = false }: { title: string; subtitle: string; option: EChartsOption; wide?: boolean }) {
  return (
    <section className={"chart-panel " + (wide ? "wide" : "")}>
      <div className="panel-heading compact-heading"><div><h2>{title}</h2><p>{subtitle}</p></div></div>
      <Suspense fallback={<div className="chart-loading" role="status">正在读取图表…</div>}>
        <EChartsView option={option} height={300} label={title + "，" + subtitle} />
      </Suspense>
    </section>
  );
}

const baseChart: EChartsOption = {
  backgroundColor: "transparent",
  textStyle: { color: "#dfcbc4", fontFamily: "Schibsted Grotesk, Microsoft YaHei, sans-serif", fontSize: 13 },
  grid: { top: 48, right: 20, bottom: 34, left: 58, containLabel: true },
  legend: { top: 8, left: 58, textStyle: { color: "#dfcbc4", fontSize: 13 }, itemWidth: 12, itemHeight: 8 },
  xAxis: { axisLine: { lineStyle: { color: "#ffffff36" } }, axisLabel: { color: "#e0d4cf", fontSize: 13 }, splitLine: { show: false } },
};

const singleSeriesChart: EChartsOption = {
  ...baseChart,
  legend: { show: false },
  grid: { top: 32, right: 20, bottom: 34, left: 58, containLabel: true },
};

function formatMean(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : (value * 100).toFixed(2) + "%";
}

function percentValue(value: number | null | undefined): number | null {
  return value === null || value === undefined ? null : value * 100;
}

function formatEstimateInterval(value: Phase5Estimate, percentage = false): string {
  if (value.mean === null || value.mean === undefined) return "无样本";
  if (!value.mean_ci95_t) return "n=" + (value.n ?? "—");
  const factor = percentage ? 100 : 1;
  const suffix = percentage ? "%" : "";
  return "[" + (value.mean_ci95_t[0] * factor).toFixed(2) + ", " + (value.mean_ci95_t[1] * factor).toFixed(2) + suffix + "] · n=" + (value.n ?? "—");
}

function phase5StrategyLabel(id: Phase5StrategyId): string {
  const labels: Record<Phase5StrategyId, string> = {
    A_no_recovery: "无恢复",
    B_phase1_static_grid: "静态网格",
    Bprime_static_grid_shared_safety: "统一约束 B′",
    C_rolling_horizon_mpc: "滚动优化",
    D_lexicographic_rescue_priority: "救援优先优化",
  };
  return labels[id];
}

function scenarioExplanation(id: Phase5ScenarioId): string {
  const explanations: Record<Phase5ScenarioId, string> = {
    severe_persistent_faults: "多个基站持续故障，场景不安排预设维修；无人机只有在保留健康地面站作为回传锚点时才能提供端到端中继。",
    dynamic_failures: "运行中注入新的基站、回传故障与恢复事件；地面维修是显式定时事件，不属于算法自主修复。",
    high_mobility_rescue: "救援终端按带种子的轨迹移动；位置与服务需求变化会影响策略可达性。",
    high_load_backhaul_limit: "救援业务突增且回传容量受限；容量约束与负载事件按冻结配置执行。",
  };
  return explanations[id];
}

function decisionTitle(reason: string): string {
  const labels: Record<string, string> = {
    rolling_horizon_action_selected: "选择滚动时域候选动作",
    phase1_grid_target_selected: "选择静态网格中继目标",
    baseline_no_deployment: "保持无恢复基线",
    no_healthy_base_station: "等待可用地面基站",
    drone_backhaul_temporarily_unavailable: "回传中断，暂停中继",
    grid_search_found_no_target: "网格搜索未找到目标",
    target_has_no_backhaul: "候选目标缺少回传",
    battery_budget_cannot_reach_target_and_keep_return_reserve: "电量无法满足返航储备",
  };
  return labels[reason] ?? reason.replaceAll("_", " ");
}

function decisionExplanation(reason: string, trigger: string): string {
  if (reason === "rolling_horizon_action_selected") return "按当前状态和约束完成有限时域搜索。触发方式：" + (trigger || "网络状态变化") + "。执行后继续依据仿真帧重新观测。";
  if (reason === "phase1_grid_target_selected") return "静态网格规则策略在启动时搜索一次目标，之后不因新状态重新选择。";
  if (reason === "baseline_no_deployment") return "A 组不调度无人机，网络状态由地面站及链路事件决定。";
  if (reason === "no_healthy_base_station") return "没有健康地面站可建立无人机回传链路，当前候选动作不可行。";
  if (reason === "drone_backhaul_temporarily_unavailable") return "无人机回传处于中断状态，策略暂停使用空中中继。";
  return "仿真引擎记录的动作原因。触发方式：" + (trigger || "无");
}

function reasonLabel(reason: string): string {
  return decisionTitle(reason);
}

