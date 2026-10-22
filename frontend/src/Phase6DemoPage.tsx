import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { CityTwinScene, Icon, OfflineNotice, PageTransition } from "./components";
import { formatTime } from "./presentation";
import {
  PHASE5_SCENARIOS,
  PHASE5_STRATEGIES,
  type Phase5ScenarioId,
  type Phase5StrategyId,
} from "./types";
import type { ReplayEvent, StateSnapshot } from "./types";
import type { Phase6DemoArtifact, Phase6DemoIndex } from "./phase6-demo-types";
import { useCurrentPageData } from "./useCurrentPageData";
import { useReplayHotkeys } from "./useReplayHotkeys";

const SCENARIO_LABEL: Record<Phase5ScenarioId, string> = {
  severe_persistent_faults: "严重持续故障",
  dynamic_failures: "动态故障",
  high_mobility_rescue: "高移动救援",
  high_load_backhaul_limit: "高负载 / 回传受限",
};

const STRATEGY_ABBR: Record<Phase5StrategyId, string> = {
  A_no_recovery: "A",
  B_phase1_static_grid: "B",
  Bprime_static_grid_shared_safety: "B′",
  C_rolling_horizon_mpc: "C",
  D_lexicographic_rescue_priority: "D",
};

const STRATEGY_LABEL: Record<Phase5StrategyId, string> = {
  A_no_recovery: "无恢复",
  B_phase1_static_grid: "静态网格",
  Bprime_static_grid_shared_safety: "统一约束 B′",
  C_rolling_horizon_mpc: "滚动时域优化",
  D_lexicographic_rescue_priority: "救援优先优化",
};

const SCENARIO_NOTE: Record<Phase5ScenarioId, string> = {
  severe_persistent_faults: "两座地面站持续故障，不安排维修事件；一座健康站保留为无人机回传锚点。",
  dynamic_failures: "运行中发生站点与回传故障，随后按配置时间恢复；滚动策略在这些变化中可能落后静态基线。",
  high_mobility_rescue: "救援用户沿固定种子的随机轨迹移动，位置变化由离散仿真帧记录。",
  high_load_backhaul_limit: "救援需求上升且回传容量受限，连接和时延受容量模型约束。",
};

const EVENT_LABEL: Record<string, string> = {
  initial_station_fault_state: "仿真起始基站故障状态",
  station_failure: "基站故障",
  station_recovery: "基站恢复",
  backhaul_failure: "无人机回传中断",
  backhaul_recovery: "无人机回传恢复",
  backhaul_capacity_change: "回传容量变化",
  traffic_change: "业务负载变化",
  user_mobility_change: "移动强度变化",
  optimizer_decision: "调度决策",
  network_recovery: "救援服务首次全恢复",
  drone_state_update: "无人机状态更新",
};

const SUMMARY_EVENT_TYPES = new Set([
  "initial_station_fault_state", "station_failure", "station_recovery", "backhaul_failure",
  "backhaul_recovery", "backhaul_capacity_change", "traffic_change", "user_mobility_change", "network_recovery",
]);

async function fetchJson<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `接口返回 ${response.status}：${url}`);
  }
  return response.json() as Promise<T>;
}

export function Phase6DemoPage() {
  const { register, clear } = useCurrentPageData();
  const [index, setIndex] = useState<Phase6DemoIndex | null>(null);
  const [artifact, setArtifact] = useState<Phase6DemoArtifact | null>(null);
  const [scenario, setScenario] = useState<Phase5ScenarioId>("severe_persistent_faults");
  const [strategy, setStrategy] = useState<Phase5StrategyId>("C_rolling_horizon_mpc");
  const [selectedEvent, setSelectedEvent] = useState<ReplayEvent | null>(null);
  const [showAllEvents, setShowAllEvents] = useState(false);
  const [selectedTime, setSelectedTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [loadingIndex, setLoadingIndex] = useState(true);
  const [loadingReplay, setLoadingReplay] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => () => clear("phase6-demo"), [clear]);
  useEffect(() => {
    register("phase6-demo", {
      sourceId: artifact?.scenario_id ?? scenario,
      sourceLabel: "Phase 5 冻结验证回放",
      mode: "single-seed",
      status: error ? "error" : artifact ? "ready" : "loading",
      seed: artifact?.seed ?? null,
      scenarioId: scenario,
      scenarioLabel: SCENARIO_LABEL[scenario],
      strategyId: strategy,
      error,
    });
  }, [artifact, error, register, scenario, strategy]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    fetchJson<Phase6DemoIndex>("/api/demo/phase6", controller.signal)
      .then((value) => {
        if (value.mode !== "precomputed_offline_replay" || value.live_stream !== false) {
          throw new Error("演示接口未声明为离线预计算回放");
        }
        setIndex(value);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof Error ? cause.message : "无法读取演示场景索引");
      })
      .finally(() => { if (active) setLoadingIndex(false); });
    return () => { active = false; controller.abort(); };
    // retryKey intentionally refreshes the index after an API or artifact error.
  }, [retryKey]);

  useEffect(() => {
    if (!index) return;
    const controller = new AbortController();
    let active = true;
    fetchJson<Phase6DemoArtifact>(`/api/demo/phase6/${scenario}`, controller.signal)
      .then((value) => {
        if (value.scenario_id !== scenario || value.mode !== "precomputed_offline_replay" || value.live_stream !== false) {
          throw new Error("回放文件与所选场景不匹配");
        }
        if (value.validation.frozen_manifest_sha256 !== index.frozen_manifest_sha256) {
          throw new Error("回放文件与第五阶段冻结清单不匹配");
        }
        if (PHASE5_STRATEGIES.some((id) => !value.strategies[id]?.state_snapshots.length)) {
          throw new Error("回放文件缺少策略状态帧");
        }
        setArtifact(value);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof Error ? cause.message : "无法读取所选场景回放");
      })
      .finally(() => { if (active) setLoadingReplay(false); });
    return () => { active = false; controller.abort(); };
  }, [index, retryKey, scenario]);

  const run = artifact?.strategies[strategy] ?? null;
  const frameIndex = artifact
    ? Math.min(Math.round(selectedTime / artifact.time_step_s), Math.max(0, (run?.state_snapshots.length ?? 1) - 1))
    : 0;
  const frame = run?.state_snapshots[frameIndex] ?? null;
  const priorFrame = run?.state_snapshots[frameIndex - 1] ?? null;
  const adjacentPriorFrame = priorFrame && frame && frame.time_s - priorFrame.time_s === artifact?.time_step_s ? priorFrame : null;
  const rescueUsers = frame?.users.filter((user) => user.group === "rescue") ?? [];
  const connected = frame?.users.filter((user) => user.connected).length ?? 0;
  const rescueConnected = rescueUsers.filter((user) => user.connected).length;
  const liveEvents = useMemo(() => {
    if (!artifact || !run) return [];
    const initialFrame = artifact.strategies.A_no_recovery.state_snapshots[0];
    const failedAtStart = initialFrame?.stations.filter((station) => !station.healthy).map((station) => station.id) ?? [];
    const initialFaultState: ReplayEvent[] = failedAtStart.length
      ? [{ time_s: 0, event_type: "initial_station_fault_state", target_id: failedAtStart.join(", ") }]
      : [];
    return [
      ...initialFaultState,
      ...artifact.environment_events,
      ...run.event_log,
    ]
      .sort((a, b) => a.time_s - b.time_s || a.event_type.localeCompare(b.event_type));
  }, [artifact, run]);
  const visibleEvents = useMemo(
    () => showAllEvents ? liveEvents : liveEvents.filter((event) => SUMMARY_EVENT_TYPES.has(event.event_type)),
    [liveEvents, showAllEvents],
  );
  const nearbyEvents = useMemo(() => {
    if (!visibleEvents.length) return [];
    const at = visibleEvents.findIndex((event) => event.time_s >= selectedTime);
    const start = Math.max(0, Math.min(at < 0 ? visibleEvents.length - 7 : at - 3, visibleEvents.length - 7));
    return visibleEvents.slice(start, start + 7);
  }, [visibleEvents, selectedTime]);

  useEffect(() => {
    if (!playing || !artifact || selectedTime >= artifact.duration_s) return;
    const nextTime = Math.min(artifact.duration_s, selectedTime + artifact.time_step_s);
    const timer = window.setTimeout(() => {
      setSelectedTime(nextTime);
      if (nextTime >= artifact.duration_s) setPlaying(false);
    }, 1000 / playbackRate);
    return () => window.clearTimeout(timer);
  }, [artifact, playbackRate, playing, selectedTime]);

  const handleTimeChange = useCallback((value: number) => {
    if (!artifact) return;
    setPlaying(false);
    setSelectedEvent(null);
    const clamped = Math.max(0, Math.min(artifact.duration_s, value));
    setSelectedTime(Math.round(clamped / artifact.time_step_s) * artifact.time_step_s);
  }, [artifact]);

  const stepReplay = useCallback((direction: -1 | 1) => {
    if (!artifact) return;
    handleTimeChange(selectedTime + direction * artifact.time_step_s);
  }, [artifact, handleTimeChange, selectedTime]);
  const toggleReplay = useCallback(() => {
    if (!artifact) return;
    if (selectedTime >= artifact.duration_s) setSelectedTime(0);
    setPlaying((value) => !value || selectedTime >= artifact.duration_s);
  }, [artifact, selectedTime]);
  const pauseReplay = useCallback(() => setPlaying(false), []);
  useReplayHotkeys({ enabled: Boolean(artifact && !error), togglePlayback: toggleReplay, step: stepReplay, pause: pauseReplay });

  if (loadingIndex || (loadingReplay && !artifact)) {
    return (
      <PageTransition className="phase6-demo-page">
        <div className="phase6-load-state" role="status"><span className="status-led" />正在读取冻结验证场景与仿真帧…</div>
      </PageTransition>
    );
  }

  if (error || !index || !artifact || !run || !frame) {
    return (
      <PageTransition className="phase6-demo-page">
        <section className="phase6-error-state" role="alert">
          <span className="data-state-symbol">!</span>
          <h1>现场演示数据不可用</h1>
          <p>{error ?? "没有可读取的预生成场景回放。"}</p>
          <button type="button" onClick={() => {
            setLoadingIndex(true);
            setLoadingReplay(true);
            setArtifact(null);
            setIndex(null);
            setError(null);
            setRetryKey((value) => value + 1);
          }}>重新读取数据</button>
        </section>
      </PageTransition>
    );
  }

  const currentDecision = frame.decision;
  const reason = typeof currentDecision.reason === "string" ? currentDecision.reason : "未记录调度说明";
  const infeasibleReasons = Array.isArray(currentDecision.infeasible_reasons)
    ? currentDecision.infeasible_reasons.map(String)
    : [];
  const destination = Array.isArray(currentDecision.destination_km)
    ? currentDecision.destination_km.map(Number)
    : null;
  const healthyStations = frame.stations.filter((station) => station.healthy).length;
  const progress = artifact.duration_s ? selectedTime / artifact.duration_s : 0;
  const eventTimes = [...new Set(liveEvents.map((event) => event.time_s))].sort((a, b) => a - b);
  const hasPreviousEvent = eventTimes.some((time) => time < selectedTime);
  const hasNextEvent = eventTimes.some((time) => time > selectedTime);

  return (
    <PageTransition className="phase6-demo-page">
      <header className="page-heading phase6-page-heading">
        <div>
          <span className="page-index">FIELD DEMONSTRATION / PHASE 06</span>
          <h1>灾害网络自愈<br className="phase6-mobile-break" />演示台</h1>
          <p>用固定验证种子回放故障、失联、调度与恢复；策略统计对应该场景全部 {artifact.validation.validation_seed_count} 个留出种子。</p>
        </div>
        <OfflineNotice compact />
      </header>

      <details className="phase6-quick-guide">
        <summary>首次使用：三步看懂这次回放</summary>
        <ol><li>先选灾害场景，再用时间轴或方向键观察故障与恢复。</li><li>点选策略按钮，对照同一 seed 的状态变化；表格汇总该场景全部留出种子。</li><li>事件前后差值只描述相邻保存帧，不代表单个事件造成的因果效果。</li></ol>
      </details>

      <section className="phase6-provenance" aria-label="回放来源">
        <div><span className="source-led" /><b>Phase 5 冻结验证回放</b><span>{artifact.validation.source_validation_file}</span></div>
        <div>
          <span>场景验证 {artifact.validation.validation_seed_count} seeds</span>
          <span>对应 {artifact.validation.strategy_run_count_in_full_validation} 次策略运行</span>
          <span className="phase6-seed-label">本次轨迹 seed {artifact.seed}</span>
        </div>
      </section>

      <section className="phase6-scene-picker" aria-label="灾害场景">
        <div><span className="panel-kicker">SELECT A RECORDED SCENARIO</span><h2>{SCENARIO_LABEL[scenario]}</h2><p>{SCENARIO_NOTE[scenario]}</p></div>
        <label><span>切换场景</span>
          <select value={scenario} onChange={(event) => {
            setScenario(event.target.value as Phase5ScenarioId);
            setSelectedEvent(null);
            setArtifact(null);
            setLoadingReplay(true);
            setPlaying(false);
            setSelectedTime(0);
            setError(null);
          }} aria-label="切换灾害场景" disabled={loadingReplay}>
            {PHASE5_SCENARIOS.map((id) => <option value={id} key={id}>{SCENARIO_LABEL[id]}</option>)}
          </select>
        </label>
        <div className="phase6-clock-stamp"><span>SIM CLOCK</span><b>T+{formatTime(selectedTime)}</b><small>10 秒离散采样</small></div>
      </section>

      <section className="phase6-metric-strip" aria-label="当前仿真帧指标">
        <LiveMetric label="地面基站" value={`${healthyStations} / ${frame.stations.length}`} note={`${frame.stations.length - healthyStations} 座故障`} alert={healthyStations < frame.stations.length} />
        <LiveMetric label="当前用户连接" value={`${connected} / ${frame.users.length}`} note="当前采样时刻" />
        <LiveMetric label="救援用户服务" value={`${rescueConnected} / ${rescueUsers.length}`} note="当前采样时刻" alert={rescueConnected < rescueUsers.length} />
        <LiveMetric label="无人机中继" value={frame.drone.active ? "工作中" : "待命"} note={`${frame.drone.battery_wh.toFixed(1)} Wh · 回传${frame.drone.backhaul_available ? "可用" : "中断"}`} alert={!frame.drone.backhaul_available} />
      </section>

      <div className="phase6-strategy-switch" role="group" aria-label="选择回放策略">
        <span className="panel-kicker">STRATEGY / 同一留出世界轨迹</span>
        <div>{PHASE5_STRATEGIES.map((id) => (
          <button
            key={id}
            type="button"
            className={`phase6-strategy-button ${strategy === id ? "selected" : ""}`}
            onClick={() => { setStrategy(id); setSelectedEvent(null); }}
            aria-pressed={strategy === id}
            data-testid={`strategy-${id}`}
          >
            <b>{STRATEGY_ABBR[id]}</b><span>{STRATEGY_LABEL[id]}</span>
          </button>
        ))}</div>
      </div>

      <section className="phase6-replay-layout" aria-label="数字孪生回放与决策">
        <section className="phase6-twin-panel">
          <div className="panel-heading">
            <div><span className="panel-kicker">DISCRETE NETWORK STATE</span><h2>城市通信拓扑</h2></div>
            <span className="panel-live-meta" data-testid="current-replay-frame"><span className="status-led" /> {STRATEGY_ABBR[strategy]} / T+{formatTime(frame.time_s)}</span>
          </div>
          <CityTwinScene
            frame={frame}
            replaySeed={artifact.seed}
            worldWidthKm={artifact.configuration.base.city_width_km}
            worldHeightKm={artifact.configuration.base.city_height_km}
            className="phase6-scene"
          />
          <div className="phase6-controls" aria-label="仿真时间轴控制">
            <div className="phase6-range-heading"><b>{formatTime(selectedTime)}</b><span>/ {formatTime(artifact.duration_s)}</span><small data-testid="current-replay-seed">seed {artifact.seed} · {new Set(liveEvents.map((event) => event.time_s)).size} 个事件时刻</small></div>
            <input
              type="range"
              min={0}
              max={artifact.duration_s}
              step={artifact.time_step_s}
              value={selectedTime}
              onChange={(event) => handleTimeChange(Number(event.target.value))}
              aria-label="灾害网络回放时间"
              data-testid="replay-slider"
              style={{ "--range-progress": `${progress * 100}%` } as CSSProperties}
            />
            <div className="phase6-playback-actions">
              <button type="button" className="icon-button subtle" aria-label="上一个关键事件" disabled={!hasPreviousEvent} onClick={() => jumpEvent(-1, liveEvents, selectedTime, handleTimeChange)}><Icon name="back" /></button>
              <button type="button" className="play-button" aria-label={playing ? "暂停回放" : "继续回放"} onClick={() => {
                if (selectedTime >= artifact.duration_s) setSelectedTime(0);
                setPlaying((value) => !value);
              }}>
                <Icon name={playing ? "pause" : "play"} /><span>{playing ? "暂停" : "继续"}</span>
              </button>
              <button type="button" className="icon-button subtle" aria-label="下一个关键事件" disabled={!hasNextEvent} onClick={() => jumpEvent(1, liveEvents, selectedTime, handleTimeChange)}><Icon name="next" /></button>
              <label><span>回放速度</span><select value={playbackRate} onChange={(event) => setPlaybackRate(Number(event.target.value))} aria-label="回放速度"><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select></label>
            </div>
          </div>
          <p className="phase6-map-note">站点、用户坐标、链路、无人机位置和电量均来自逐步仿真重放帧；显示为二维抽象城区，不代表实景测绘。</p>
        </section>

        <aside className="phase6-inspector">
          <section className="phase6-decision-panel">
            <div className="panel-heading compact-heading"><div><span className="panel-kicker">DECISION / CURRENT TICK</span><h2>调度记录</h2></div><span className="event-count">{run.event_log.filter((event) => event.event_type === "optimizer_decision" && event.time_s <= selectedTime).length} 次已记录决策</span></div>
            <div className="phase6-decision-state">
              <span className={currentDecision.deploy === true ? "decision-lamp active" : "decision-lamp"} />
              <div><b>{decisionLabel(reason)}</b><small>{currentDecision.deploy === true ? "中继部署许可" : "当前未部署"}</small></div>
            </div>
            <dl className="phase6-decision-facts">
              <div><dt>诊断失联用户</dt><dd>{frame.diagnosis.disconnected_user_ids.length}</dd></div>
              <div><dt>失联救援用户</dt><dd>{frame.diagnosis.disconnected_rescue_ids.length}</dd></div>
              <div><dt>回传链路</dt><dd>{frame.diagnosis.drone_backhaul_available ? "可用" : "不可用"}</dd></div>
              <div><dt>规划目标</dt><dd>{destination ? `${destination[0].toFixed(2)}, ${destination[1].toFixed(2)} km` : "未生成"}</dd></div>
            </dl>
            {infeasibleReasons.length > 0 && <div className="phase6-infeasible"><b>不可行 / 暂停原因</b>{infeasibleReasons.map((item, i) => <span key={`${item}-${i}`}>{decisionLabel(item)}</span>)}</div>}
          </section>

          <section className="phase6-events-panel">
            <div className="panel-heading compact-heading"><div><span className="panel-kicker">EVENT TRACE</span><h2>故障与恢复时间轴</h2></div><button type="button" className="text-button" aria-pressed={showAllEvents} onClick={() => setShowAllEvents((value) => !value)}>{showAllEvents ? "仅看关键事件" : "查看全部事件"}</button></div>
            <p className="phase6-events-caption">显示 {nearbyEvents.length} / {visibleEvents.length} 条{showAllEvents ? "全部记录" : "关键事件"}（共 {liveEvents.length} 条）。同一时刻的多条记录会分别保留。</p>
            <div className="phase6-event-list">
              {nearbyEvents.map((event, i) => (
                <button type="button" className={`phase6-event-row ${selectedEvent === event || (!selectedEvent && event.time_s === selectedTime) ? "selected" : ""}`} key={`${event.time_s}-${event.event_type}-${i}`} onClick={() => { handleTimeChange(event.time_s); setSelectedEvent(event); }}>
                  <span className={`phase6-event-mark ${event.event_type.includes("failure") || event.event_type.includes("fault") ? "alert" : event.event_type === "network_recovery" ? "healthy" : ""}`} />
                  <time>T+{formatTime(event.time_s)}</time>
                  <span><b>{EVENT_LABEL[event.event_type] ?? "未识别记录"}</b><small>{event.target_id ? String(event.target_id) : event.reason ? String(event.reason) : "记录于冻结场景轨迹"}</small></span>
                </button>
              ))}
              {!nearbyEvents.length && <p className="phase6-empty-events">当前场景尚无可显示事件。</p>}
            </div>
            {selectedEvent && <EventEvidence event={selectedEvent} before={adjacentPriorFrame} after={frame} timeStep={artifact.time_step_s} />}
          </section>

          <section className="phase6-rescue-panel">
            <div className="panel-heading compact-heading"><div><span className="panel-kicker">RESCUE ENDPOINTS</span><h2>救援用户状态</h2></div><span className="event-count">{rescueConnected} / {rescueUsers.length} 在线</span></div>
            <div className="phase6-rescue-list">
              {rescueUsers.map((user) => <div className={`phase6-rescue-row ${user.connected ? "connected" : "lost"}`} key={user.id}>
                <span className="terminal-signal" /><b>{user.id.toUpperCase()}</b>
                <span>{user.connected ? user.path_kind === "drone_relay" ? "空中中继" : "地面直连" : user.covered ? "容量受限" : "无覆盖"}</span>
                <small>{user.latency_ms === null ? "—" : `${user.latency_ms.toFixed(1)} ms`}</small>
              </div>)}
            </div>
          </section>
        </aside>
      </section>

      <section className="phase6-comparison-panel" aria-labelledby="phase6-comparison-title">
        <div className="panel-heading"><div><span className="panel-kicker">HELD-OUT RESULTS / ALL {artifact.validation.validation_seed_count} SEEDS</span><h2 id="phase6-comparison-title">策略结果对照</h2></div><span className="event-count">同场景配置 · 同种子集合 · 5 种策略</span></div>
        <p className="phase6-table-scroll-hint">窄屏可在表格区域内横向滚动查看其余指标。</p>
        <div className="phase6-table-scroll" role="region" tabIndex={0} aria-label="五种策略的留出验证结果，可横向滚动">
          <table className="phase6-results-table">
            <thead><tr><th scope="col">策略</th><th scope="col">救援服务率</th><th scope="col">首次全恢复</th><th scope="col">持续 30 秒</th><th scope="col">恢复时间</th><th scope="col">平均 / P95 时延</th><th scope="col">无人机能耗</th><th scope="col">控制器耗时</th></tr></thead>
            <tbody>{PHASE5_STRATEGIES.map((id) => {
              const summary = artifact.strategy_aggregates[id];
              const rescueMetric = summary.metrics.rescue_user_service_success_rate;
              const meanLatency = summary.latency_conditioned_on_success.pooled_average_ms;
              const p95Latency = summary.latency_conditioned_on_success.pooled_p95_ms;
              const latencyN = summary.latency_conditioned_on_success.pooled_successful_user_time_samples;
              const energy = summary.metrics.drone_energy_consumed_wh?.mean;
              const compute = summary.metrics.controller_observe_total_ms?.mean;
              const recovery = summary.network_recovery;
              const sustained = summary.sustained_network_recovery_30s;
              const recoveryRuns = recovery.recovered_runs + recovery.unrecovered_runs;
              const sustainedRuns = sustained.recovered_runs + sustained.unrecovered_runs;
              return <tr key={id} className={strategy === id ? "selected" : ""}>
                <th scope="row"><span className={`strategy-code strategy-${id.slice(0, 1).toLowerCase()}`}>{STRATEGY_ABBR[id]}</span>{STRATEGY_LABEL[id]}</th>
                <td><b>{formatPercent(rescueMetric?.mean)}</b><small>95% CI {formatInterval(rescueMetric?.mean_ci95_t, true)}</small></td>
                <td><b>{recovery.recovered_runs} / {recoveryRuns}</b><small>{recovery.unrecovered_runs} 未恢复</small></td>
                <td><b>{sustained.recovered_runs} / {sustainedRuns}</b><small>{sustained.unrecovered_runs} 未持续</small></td>
                <td><b>{formatNumber(recovery.recovered_only_time_s.mean)} s</b><small>仅已恢复运行</small></td>
                <td><b>{formatNumber(meanLatency)} / {formatNumber(p95Latency)} ms</b><small>成功用户时刻 n={latencyN.toLocaleString("zh-CN")}</small></td>
                <td><b>{formatNumber(energy)} Wh</b><small>每种子均值</small></td>
                <td><b>{formatNumber(compute)} ms</b><small>每次完整运行累计</small></td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        <div className="phase6-stat-note">
          <p>表中服务率、能耗和控制器耗时按 {artifact.validation.validation_seed_count} 个冻结留出种子汇总；本次地图是按冻结规则选出的单条轨迹（seed {artifact.seed}）。恢复时间只对成功运行求均值，未恢复运行不进入该均值但仍计入右侧分母。</p>
          <p>平均时延与 P95 将成功用户时刻样本合并后计算，样本集合可能因策略而不同；n 是样本数，不是种子数。空值显示为“—”。C/D 是确定性搜索优化器，不是训练过的机器学习模型；它们不保证所有场景优于 B。</p>
          <details className="phase6-metric-guide"><summary>指标与分母说明</summary><dl><div><dt>救援服务率</dt><dd>按逐个留出种子计算，再对种子均值汇总；95% CI 是种子层 t 区间。</dd></div><div><dt>首次全恢复 / 持续 30 秒</dt><dd>分母是已记录的总运行数；未恢复计入未恢复数量。恢复耗时均值只对成功恢复的运行计算。</dd></div><div><dt>平均时延 / P95</dt><dd>仅使用成功连接的用户时刻；显示汇总样本池的均值与第 95 百分位，不是“每种子 P95 的均值”。</dd></div><div><dt>能耗 / 控制器耗时</dt><dd>展示跨种子均值；耗时为每次完整策略运行累计的控制器计算时间，不是网页渲染时间。</dd></div></dl></details>
        </div>
      </section>

      <section className="phase6-mapping" aria-labelledby="phase6-mapping-title">
        <div className="phase6-mapping-heading"><div><span className="panel-kicker">RESEARCH SCOPE / IMT-2030</span><h2 id="phase6-mapping-title">能力映射与边界</h2></div><a href="https://www.itu.int/rec/R-REC-M.2160-0-202311-I/en" target="_blank" rel="noreferrer">ITU-R M.2160-0 官方框架 <Icon name="arrow" /></a></div>
        <div className="phase6-mapping-grid">
          <MappingItem title="韧性与自愈" status="仿真近似" detail="基站 / 回传故障、诊断与策略恢复均由离散模型驱动；不接真实无线接入或设备控制。" />
          <MappingItem title="AI 与通信" status="确定性优化" detail="C/D 执行滚动候选搜索与词典序搜索；未训练模型，也没有分布式学习或空口 AI。" />
          <MappingItem title="数字孪生" status="离线回放" detail="二维城市拓扑来自固定种子逐步仿真；不是传感器同步的实时物理世界镜像。" />
          <MappingItem title="能效、时延、覆盖" status="抽象指标" detail="报告模型内的 Wh、ms、连接与覆盖；不是 ITU 空口性能指标或 M.2160 目标验证。" />
        </div>
        <p className="phase6-boundary-note">没有健康地面回传站时，单架无人机不能自行建立端到端通信。本平台是面向 6G 的抽象研究仿真，不是真实 6G 网络测试。</p>
      </section>
      <section className="phase6-fleet-boundary" role="note">
        <div><span className="panel-kicker">REPLAY COVERAGE</span><b>当前回放为单无人机逐帧记录</b><p>Phase 10/11 已有多无人机统计汇总，但没有可由回放 API 核验的逐帧机队坐标与链路状态；本页不会生成替代轨迹。</p></div>
        <Link to="/research">查看多无人机实验汇总</Link>
      </section>
    </PageTransition>
  );
}

function LiveMetric({ label, value, note, alert = false }: { label: string; value: string; note: string; alert?: boolean }) {
  return <div className="phase6-live-metric"><span>{label}</span><b className={alert ? "value-alert" : ""}>{value}</b><small>{note}</small></div>;
}

function MappingItem({ title, status, detail }: { title: string; status: string; detail: string }) {
  return <article className="phase6-mapping-item"><span>{status}</span><h3>{title}</h3><p>{detail}</p></article>;
}

function EventEvidence({ event, before, after, timeStep }: { event: ReplayEvent; before: StateSnapshot | null; after: StateSnapshot | null; timeStep: number }) {
  const fields: Array<[string, unknown]> = [
    ["影响对象", event.target_id ?? event.station_id ?? event.user_id ?? event.resource_id],
    ["记录原因", event.reason ?? event.cause ?? event.trigger],
    ["回传 / 链路", event.link_id ?? event.backhaul_available],
    ["动作目标", event.destination_km ?? event.target_km],
    ["事件来源", event.source],
    ["安全过滤", event.infeasible_reasons ?? event.safety_reason],
  ];
  const presentFields = fields.filter((item) => item[1] !== undefined && item[1] !== null);
  const beforeStats = before ? frameSummary(before) : null;
  const afterStats = after && after.time_s === event.time_s ? frameSummary(after) : null;

  return <section className="phase6-event-evidence" role="region" aria-label="选中事件详情">
    <div className="phase6-event-evidence-head"><b>{EVENT_LABEL[event.event_type] ?? "未识别记录"}</b><time>T+{formatTime(event.time_s)}</time></div>
    {presentFields.length ? <dl>{presentFields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{eventValue(value)}</dd></div>)}</dl> : <p>该事件记录未包含结构化影响对象或原因字段。</p>}
    {beforeStats && afterStats ? <div className="phase6-event-change">
      <span>相邻保存帧 · T+{formatTime(before?.time_s ?? 0)} → T+{formatTime(after?.time_s ?? 0)}</span>
      <p>基站健康 {beforeStats.healthyStations}/{beforeStats.stationCount} → {afterStats.healthyStations}/{afterStats.stationCount}；用户连接 {beforeStats.connectedUsers}/{beforeStats.userCount} → {afterStats.connectedUsers}/{afterStats.userCount}；救援在线 {beforeStats.connectedRescue}/{beforeStats.rescueCount} → {afterStats.connectedRescue}/{afterStats.rescueCount}。</p>
      <small>这里只描述相邻离散帧中同时观察到的变化，不据此推断单个事件的因果效应。采样间隔 {timeStep}s。</small>
    </div> : <p className="phase6-event-no-delta">没有同时存在的相邻记录帧，因此不生成前后差值。</p>}
    {!EVENT_LABEL[event.event_type] && <details><summary>查看原始记录</summary><pre>{JSON.stringify(event, null, 2)}</pre></details>}
  </section>;
}

function frameSummary(frame: StateSnapshot) {
  const rescueUsers = frame.users.filter((user) => user.group === "rescue");
  return {
    healthyStations: frame.stations.filter((station) => station.healthy).length,
    stationCount: frame.stations.length,
    connectedUsers: frame.users.filter((user) => user.connected).length,
    userCount: frame.users.length,
    connectedRescue: rescueUsers.filter((user) => user.connected).length,
    rescueCount: rescueUsers.length,
  };
}

function eventValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => typeof item === "string" || typeof item === "number" ? String(item) : "").filter(Boolean).join("、") || "已记录";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return "已记录";
}

function jumpEvent(direction: -1 | 1, events: Array<{ time_s: number }>, current: number, setTime: (time: number) => void) {
  const times = [...new Set(events.map((event) => event.time_s))].sort((a, b) => a - b);
  const next = direction > 0 ? times.find((time) => time > current) : [...times].reverse().find((time) => time < current);
  if (next !== undefined) setTime(next);
}

function decisionLabel(reason: string): string {
  const labels: Record<string, string> = {
    baseline_no_deployment: "基线策略不部署无人机",
    phase1_grid_target_selected: "静态网格选择中继目标",
    static_grid_target_selected_with_shared_safety: "静态网格目标通过共享安全约束",
    rolling_horizon_action_selected: "滚动时域选择下一动作",
    lexicographic_rescue_action_selected: "词典序目标选择救援动作",
    no_healthy_base_station: "无健康基站可提供回传",
    drone_backhaul_temporarily_unavailable: "无人机回传暂时中断",
    target_has_no_backhaul: "候选目标没有可用回传",
    grid_search_found_no_target: "网格搜索没有可行目标",
    full_target_sortie_energy_would_violate_reserve: "完整航程将低于电量储备",
    return_energy_reserve_would_be_violated: "返航电量储备约束不满足",
  };
  return labels[reason] ?? reason.replaceAll("_", " ");
}

function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(2)}%`;
}

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function formatInterval(value: [number, number] | null | undefined, percentage = false): string {
  if (!value) return "—";
  const multiplier = percentage ? 100 : 1;
  return `[${(value[0] * multiplier).toFixed(2)}, ${(value[1] * multiplier).toFixed(2)}${percentage ? "%" : ""}]`;
}
