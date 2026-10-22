import { useEffect, useState } from "react";
import type { ResearchArtifactEnvelope } from "./research-model";

type Row = Record<string, unknown>;
type EvidenceBlock = { artifact_path: string; artifact_sha256: string; artifact: Row };

function record(value: unknown): Row { return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {}; }
function rows(value: unknown): Row[] { return Array.isArray(value) ? value.map(record) : []; }
function text(value: unknown, fallback = "未记录"): string { return typeof value === "string" && value.length ? value : fallback; }
function number(value: unknown, digits = 0): string { return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN", { maximumFractionDigits: digits }) : "—"; }
function asEvidence(value: unknown): EvidenceBlock { return record(value) as unknown as EvidenceBlock; }
function joined(value: unknown): string { return Array.isArray(value) ? value.filter((item) => typeof item === "string").join("、") : text(value); }

export function Phase17ResearchSection({ envelope }: { envelope: ResearchArtifactEnvelope }) {
  const supporting = record(envelope.supporting_artifacts);
  const summary = envelope.artifact;
  const adapterEvidence = asEvidence(supporting.adapter_status);
  const loopEvidence = asEvidence(supporting.closed_loop_run);
  const commandEvidence = asEvidence(supporting.command_audit);
  const faultEvidence = asEvidence(supporting.fault_injection_results);
  const replayEvidence = asEvidence(supporting.offline_replay_validation);
  const inventoryEvidence = asEvidence(supporting.environment_inventory);
  const adapterArtifact = record(adapterEvidence.artifact);
  const loop = record(loopEvidence.artifact);
  const replay = record(replayEvidence.artifact);
  const commandAudit = record(commandEvidence.artifact);
  const faultPayload = record(faultEvidence.artifact);
  const inventory = record(inventoryEvidence.artifact);
  const health = record(adapterArtifact.last_health_check);
  const healthResult = record(health.result);
  const adapterList = rows(adapterArtifact.adapters);
  const faults = rows(faultPayload.faults);
  const timeline = rows(loop.timeline);
  const frames = rows(replay.mapped_frames);
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [faultIndex, setFaultIndex] = useState(0);
  const frame = frames[Math.min(frameIndex, Math.max(0, frames.length - 1))] ?? {};
  const selectedFault = faults[faultIndex] ?? {};
  const stationRows = rows(frame.stations);
  const linkRows = rows(frame.links);
  const userGroups = record(frame.users);
  const userRows = rows(userGroups.items ?? userGroups.nodes ?? frame.user_nodes);
  const drone = record(frame.drone);
  const connectedUsers = userRows.filter((item) => item.connected === true || item.connected_via || item.served_by).length;
  const faultSummary = {
    passed: number(faultPayload.passed_count),
    total: number(faultPayload.injection_count),
    failed: number(faultPayload.failed_count),
  };
  const isPlaying = playing && frameIndex < frames.length - 1;

  useEffect(() => {
    if (!isPlaying || frames.length < 2) return;
    const timer = window.setInterval(() => {
      setFrameIndex((index) => {
        return index >= frames.length - 1 ? index : index + 1;
      });
    }, 650);
    return () => window.clearInterval(timer);
  }, [isPlaying, frames.length]);

  const modes = record(adapterArtifact.mode_availability);
  const software = record(summary.software_closed_loop);
  const softwareResult = record(software.summary);
  const offline = record(summary.offline_replay);
  const physicalCount = number(adapterArtifact.physical_adapter_count);
  const integrity = record(record(supporting.integrity_audit).artifact);
  const frameTime = frame.simulation_time_s;

  return <div className="phase17-workbench" data-testid="phase17-workbench">
    <section className="phase17-hard-stop" role="note" aria-label="真实硬件测试状态">
      <span className="phase17-stop-mark" aria-hidden="true">!</span>
      <div><strong>当前仅完成软件闭环与记录回放验证。真实硬件在环测试尚未完成。</strong><p>真实硬件输出保持关闭；没有实测无线电、飞行控制或基站控制结果。</p></div>
      <span className="phase17-safety-chip">OUTPUT DISABLED</span>
    </section>

    <section className="phase17-overview" aria-label="阶段验证结果">
      <div className="phase17-overview-copy"><span className="panel-kicker">HIL READINESS / SOFTWARE EVIDENCE</span><h2>先验证安全闭环，<br />再接入真实设备。</h2><p>版本化遥测契约、离线离散回放、内存测试执行器和失效关闭安全门。本页所有记录均由保存的验证产物驱动。</p></div>
      <div className="phase17-mode-grid">
        <article><span>软件闭环</span><b data-tone={summary.software_closed_loop_status === "PASS" ? "ok" : "warning"}>{text(summary.software_closed_loop_status)}</b><small>同种子可复现：{software.same_seed_deterministic_match === true ? "是" : "否"}</small></article>
        <article><span>离线回放</span><b data-tone={summary.offline_replay_status === "PASS" ? "ok" : "warning"}>{text(summary.offline_replay_status)}</b><small>{number(offline.frame_count)} 帧 · 插值 {number(offline.interpolation_count)} 次</small></article>
        <article><span>硬件在环</span><b data-tone="warning">未执行</b><small>无已核验硬件或驱动</small></article>
        <article><span>已核验物理适配器</span><b>{physicalCount}</b><small>软件执行器与回放不计入</small></article>
      </div>
    </section>

    <section className="phase17-evidence-strip" aria-label="运行边界与来源">
      <div><span>运行模式</span><b>{text(summary.current_mode)}</b><small>{text(summary.current_mode_source)}</small></div>
      <div><span>设备盘点</span><b>{text(record(inventory.equipment_scan).status)}</b><small>{text(record(inventory.equipment_scan).method, "盘点方式未记录")}</small></div>
      <div><span>最近软件健康检查</span><b>{text(healthResult.status)}</b><small>{text(health.recorded_at)} · 非实时设备遥测</small></div>
      <div><span>安全完整性</span><b data-tone={integrity.status === "PASS" ? "ok" : "warning"}>{text(integrity.status)}</b><small>受保护历史文件 {number(summary.protected_file_count)} 项</small></div>
      <div><span>状态时间域</span><b>仿真 / 回放</b><small>跨墙钟延迟未同步，按不可比较处理</small></div>
    </section>

    <section className="phase17-adapter-section" aria-labelledby="phase17-adapters-title">
      <div className="phase17-section-head"><div><span className="panel-kicker">VERSIONED DEVICE CONTRACTS</span><h3 id="phase17-adapters-title">设备接入能力清单</h3><p>接口存在不代表驱动可用；只有具备已验证输出通道的适配器才会被标记为物理接入。</p></div><code>schema {text(adapterArtifact.schema_version)}</code></div>
      <div className="phase17-adapter-list">{adapterList.map((item) => <article key={text(item.adapter_id)}><div><b>{text(item.adapter_id)}</b><span>{text(item.device_type)}</span></div><i data-tone={item.status === "IMPLEMENTED_AND_TESTED" || item.status === "SIMULATED" || item.status === "REPLAY_ONLY" ? "ok" : "warning"}>{text(item.status)}</i><p>{text(item.implementation)}</p></article>)}</div>
      <div className="phase17-mode-availability">{Object.entries(modes).map(([mode, status]) => <span key={mode}><b>{mode}</b><i>{text(status)}</i></span>)}</div>
    </section>

    <section className="phase17-replay" aria-labelledby="phase17-replay-title">
      <div className="phase17-section-head"><div><span className="panel-kicker">RECORDED SIMULATION / DISCRETE FRAME WALK</span><h3 id="phase17-replay-title">离线网络状态回放</h3><p>按已保存仿真帧逐帧前进，不对中间状态插值。该回放不接收实时设备遥测。</p></div><a href="/api/demo/phase6/dynamic_failures" target="_blank" rel="noreferrer">打开原始回放记录 ↗</a></div>
      <div className="phase17-replay-meta"><span>场景 <b>{text(replay.scenario_id)}</b></span><span>策略 <b>{text(replay.strategy_id)}</b></span><span>来源 SHA-256 <code>{text(replay.source_sha256)}</code></span><span>帧映射校验 <b>{text(replay.frame_mapping_hashes_sha256).slice(0, 16)}…</b></span><span>数据可信度 <b>{text(frame.quality)} · 非实测</b></span><span>遥测新鲜度 <b>不适用 · 已保存回放</b></span></div>
      {frames.length > 0 ? <>
        <div className="phase17-replay-state" data-testid="phase17-replay-state" aria-live="polite">
          <div className="phase17-replay-clock"><span>模拟时间</span><b>{number(frameTime, 1)} s</b><small>帧 {frameIndex + 1} / {frames.length}</small></div>
          <div><span>健康基站</span><b>{stationRows.filter((item) => item.healthy === true).length} / {stationRows.length}</b><small>{stationRows.filter((item) => item.healthy !== true).map((item) => text(item.id)).join(" · ") || "无故障节点"}</small></div>
          <div><span>通信链路</span><b>{linkRows.length}</b><small>仅统计此保存帧所记录的链路</small></div>
          <div><span>无人机位置</span><b>{Array.isArray(drone.position_km) ? drone.position_km.map((value) => number(value, 2)).join(" / ") : "—"} km</b><small>{text(drone.id, "回放未记录")} · {number(drone.battery_wh)} Wh · 回传{drone.backhaul_available === true ? "可用" : "中断"}</small></div>
          <div><span>用户连接</span><b>{connectedUsers || number(userGroups.connected)} / {number(userGroups.total ?? userRows.length)}</b><small>全体用户 · 来自原始仿真快照</small></div>
          <div><span>救援用户</span><b>{number(userGroups.rescue_connected)} / {number(userGroups.rescue_total)}</b><small>按救援组标记统计</small></div>
        </div>
        <div className="phase17-replay-controls">
          <button type="button" onClick={() => { setPlaying(false); setFrameIndex(0); }}>从头</button>
          <button type="button" onClick={() => setFrameIndex((index) => Math.max(0, index - 1))} disabled={frameIndex === 0}>上一帧</button>
          <button type="button" className="phase17-play-button" onClick={() => { if (isPlaying) setPlaying(false); else { if (frameIndex >= frames.length - 1) setFrameIndex(0); setPlaying(true); } }} aria-label={isPlaying ? "暂停回放" : "继续回放"}>{isPlaying ? "暂停回放" : "继续回放"}</button>
          <button type="button" onClick={() => setFrameIndex((index) => Math.min(frames.length - 1, index + 1))} disabled={frameIndex >= frames.length - 1}>单步前进</button>
          <input aria-label="已保存的离散回放帧" type="range" min={0} max={frames.length - 1} value={frameIndex} onChange={(event) => { setPlaying(false); setFrameIndex(Number(event.target.value)); }} />
          <code>{number(frameTime, 1)} s</code>
        </div>
        <details className="phase17-link-detail"><summary>查看当前帧链路明细（{linkRows.length} 条）</summary><div>{linkRows.slice(0, 18).map((link, index) => <span key={`${text(link.source_id)}-${text(link.target_id)}-${index}`}><b>{text(link.kind)}</b>{text(link.source_id)} → {text(link.target_id)}</span>)}</div></details>
      </> : <p className="phase17-no-data" role="status">回放帧未随该接口返回；不会生成示例轨迹。</p>}
    </section>

    <section className="phase17-closed-loop" aria-labelledby="phase17-loop-title">
      <div className="phase17-section-head"><div><span className="panel-kicker">SYNTHETIC ACCEPTANCE FIXTURE / SEED {number(software.seed)}</span><h3 id="phase17-loop-title">软件闭环命令与反馈</h3><p>固定测试植物产生合成遥测；动作结果只有在回执状态与设备状态反馈一致时才计为成功。</p></div><span className="phase17-receipt-count">{number(softwareResult.feedback_matches)} / {number(softwareResult.commands_requested)} 匹配回执</span></div>
      <div className="phase17-loop-summary"><span><b>{number(softwareResult.first_rescue_recovery_step)} s</b><i>测试植物首个救援连接恢复步</i></span><span><b>{number(softwareResult.final_rescue_connected)} / {number(softwareResult.final_rescue_total)}</b><i>最终合成救援用户连接</i></span><span><b>{number(softwareResult.final_battery_wh)} Wh</b><i>测试植物剩余电量</i></span><span><b>{text(software.same_seed_deterministic_match ? "一致" : "不一致")}</b><i>同种子输出哈希复核</i></span></div>
      <div className="phase17-table-scroll" role="region" tabIndex={0} aria-label="软件闭环离散时间线，可横向滚动"><table className="research-table phase17-table"><thead><tr><th>仿真步 / 时间</th><th>基站 / 回传</th><th>救援连接</th><th>遥测校验</th><th>决策</th><th>命令回执</th></tr></thead><tbody>{timeline.map((item) => { const state = record(item.observed_state); const telemetry = record(item.telemetry); const decision = record(item.decision); const command = text(item.command_id, "无动作"); return <tr key={number(item.simulation_step)}><th>{number(item.simulation_step)} / {number(item.simulation_time_s)} s</th><td>{state.station_healthy ? "健康" : "故障"} · {state.backhaul_available ? "回传可用" : "回传中断"}</td><td>{number(state.rescue_connected)} / {number(state.rescue_total)}</td><td>{telemetry.trusted_for_control ? "可信" : `阻断：${rows(telemetry.reasons).join("、") || text(telemetry.reasons)}`}</td><td>{text(decision.action)} · {text(decision.reason)}</td><td>{command === "无动作" ? command : `命令 ${command}`}</td></tr>; })}</tbody></table></div>
      <p className="phase17-synthetic-note">以上恢复时间和电量仅属于内存合成测试植物，不是无人机飞行、网络性能或实测无线结果。</p>
    </section>

    <section className="phase17-faults" aria-labelledby="phase17-fault-title">
      <div className="phase17-section-head"><div><span className="panel-kicker">DETERMINISTIC FAILURE INJECTION</span><h3 id="phase17-fault-title">失效与安全闭环测试</h3><p>测试用例针对契约校验、安全门或内存执行器运行；通过只表示测试预期被满足。</p></div><div className="phase17-fault-score" data-tone={faultSummary.failed === "0" ? "ok" : "warning"}><b>{faultSummary.passed} / {faultSummary.total}</b><span>通过 · {faultSummary.failed} 失败</span></div></div>
      <div className="phase17-fault-browser"><label><span>故障注入案例</span><select aria-label="选择故障注入案例" value={faultIndex} onChange={(event) => setFaultIndex(Number(event.target.value))}>{faults.map((item, index) => <option value={index} key={`${text(item.fault_type)}-${index}`}>用例 {number(item.test_case_index)} · {text(item.fault_type)}</option>)}</select></label><div className="phase17-fault-result"><span data-tone={selectedFault.passed === true ? "ok" : "warning"}>{selectedFault.passed === true ? "预期结果匹配" : "未通过 / 未记录"}</span><div><small>预期</small><b>{text(selectedFault.expected_result)}</b></div><div><small>实际</small><b>{text(selectedFault.actual_result)}</b></div><p>同步用例次序不表示仿真时间。{rows(selectedFault.observed_simulation_events).length > 0 ? ` 实际离散事件：${rows(selectedFault.observed_simulation_events).map((event) => `t=${number(event.simulation_time_s)}s ${text(event.event_type)}`).join("；")}。` : ""} {joined(selectedFault.detail)}</p></div></div>
      <div className="phase17-command-audit"><span className="panel-kicker">COMMAND AUDIT / COMMAND ≠ FEEDBACK</span><b>{number(rows(commandAudit.commands).length)} 条保存命令 · 模式 {text(commandAudit.live_device === false ? "非实时" : "无法确认")}</b><p>超时不记为成功：{commandAudit.timeout_is_not_success === true ? "已验证" : "未验证"}；回执必须匹配状态反馈：{commandAudit.command_success_requires_matching_feedback === true ? "是" : "否"}。</p><details><summary>展开命令、安全判定与设备回执</summary>{rows(commandAudit.commands).map((entry) => { const cmd = record(entry.command); const safety = record(entry.safety); const receipt = record(entry.receipt); return <pre key={text(cmd.command_id)}>{JSON.stringify({ command: cmd, safety, receipt }, null, 2)}</pre>; })}</details></div>
    </section>

    <section className="phase17-prerequisites" aria-label="真实硬件在环测试前置条件"><div><span className="panel-kicker">BEFORE PHYSICAL HIL</span><h3>真实设备验证仍有明确前置条件</h3></div><ul><li>经确认的无线测量仪器、无人机遥测或基站状态硬件及其驱动。</li><li>端到端设备身份、版本化协议、单位、校时和测量不确定度证据。</li><li>授权的频谱、飞行范围、操作人急停和返航安全程序。</li><li>硬件输出适配器独立代码审查、台架演练和风险验收。</li></ul></section>
  </div>;
}
