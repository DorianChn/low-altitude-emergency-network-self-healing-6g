import type { ResearchArtifactEnvelope, ResearchPhaseId } from "./research-model";

type JsonRecord = Record<string, unknown>;

interface Phase18ResearchSectionProps {
  envelope: ResearchArtifactEnvelope;
  onOpenPhase: (phase: ResearchPhaseId) => void;
}

function record(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
}

function rows(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.filter((item): item is JsonRecord => item !== null && typeof item === "object" && !Array.isArray(item)) : [];
}

function valueText(value: unknown, fallback = "未记录"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function valueNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function statusTone(status: unknown): "ok" | "warning" | "muted" {
  if (status === "PASS") return "ok";
  if (status === "PARTIAL" || status === "FAIL" || status === "PASS_WITH_WARNING" || status === "CONDITIONAL") return "warning";
  return "muted";
}

function statusLabel(status: unknown): string {
  const labels: Record<string, string> = {
    PASS: "已核验",
    PARTIAL: "部分完成",
    NOT_IMPLEMENTED: "未实现",
    NOT_TESTED: "未测试",
    NOT_ASSESSABLE: "无法判定",
    CONDITIONAL: "有条件可交付",
    PASS_WITH_WARNING: "通过（提示）",
    NOT_READY: "未就绪",
    FAIL: "失败",
  };
  return typeof status === "string" ? labels[status] ?? status : "未记录";
}

export function Phase18ResearchSection({ envelope, onOpenPhase }: Phase18ResearchSectionProps) {
  const summary = record(envelope.artifact);
  const supporting = record(envelope.supporting_artifacts);
  const audit = record(record(supporting.integrity_audit).artifact);
  const history = record(audit.protected_history);
  const workspace = record(audit.workspace);
  const rawCountAudit = record(audit.raw_experiment_count_audit);
  const release = record(record(supporting.release_manifest).artifact);
  const phases = rows(summary.phase_statuses);
  const findings = rows(summary.research_findings);
  const gates = rows(summary.delivery_gates);
  const tests = rows(summary.test_matrix);
  const releaseItems = rows(release.items);
  const allChecks = rows(rawCountAudit.checks);
  const protectedCount = valueNumber(history.protected_file_count);
  const protectedMatched = valueNumber(history.matched_file_count);
  const sourceDrift = valueNumber(history.phase5_source_snapshot_drift_count);
  const overall = record(summary.competition_readiness);
  const auditStatus = valueText(summary.status, "PARTIAL");
  const archiveCount = valueNumber(release.file_count, releaseItems.length);

  return (
    <div className="phase18-workbench" data-testid="phase18-workbench">
      <section className="phase18-lead" aria-labelledby="phase18-title">
        <div className="phase18-lead-copy">
          <span className="panel-kicker">FINAL AUDIT / RELEASE CANDIDATE</span>
          <h2 id="phase18-title">用证据决定<br />哪些可以交付</h2>
          <p>{valueText(summary.executive_summary, "各阶段的代码、实验和验证状态按来源分别核对。")}</p>
        </div>
        <div className="phase18-verdict" data-tone={statusTone(overall.status ?? auditStatus)}>
          <span>竞赛材料准备度</span>
          <strong>{statusLabel(overall.status ?? auditStatus)}</strong>
          <small>{valueText(overall.label, "本地发布候选 · 审核前状态")}</small>
        </div>
      </section>

      <section className="phase18-ledger" aria-label="最终审计计数">
        <article><span>受保护历史文件</span><b data-tone={protectedMatched === protectedCount && protectedCount > 0 ? "ok" : "warning"}>{protectedMatched} / {protectedCount}</b><small>SHA-256 匹配</small></article>
        <article><span>原始实验结构核对</span><b data-tone={valueText(rawCountAudit.status) === "PASS" ? "ok" : "warning"}>{allChecks.filter((item) => item.matches === true).length} / {allChecks.length}</b><small>运行数、种子组、轨迹数</small></article>
        <article><span>Phase 5 源码快照差异</span><b data-tone={sourceDrift > 0 ? "warning" : "ok"}>{sourceDrift}</b><small>冻结数据与源码版本分开核验</small></article>
        <article><span>发布清单文件</span><b>{archiveCount}</b><small>本地 RC 文件记录</small></article>
      </section>

      <section className="phase18-status-section" aria-labelledby="phase18-status-title">
        <div className="phase18-section-title"><div><span className="panel-kicker">STAGE STATUS / EVIDENCE SCOPE</span><h3 id="phase18-status-title">项目阶段记录</h3></div><p>“已核验”指对应文件或测试按所列范围通过，不表示真实网络验证。</p></div>
        <div className="phase18-stage-list">
          {phases.map((phase) => {
            const id = valueText(phase.id, "") as ResearchPhaseId;
            const canOpen = ["phase5", "phase8", "phase9", "phase10", "phase11", "phase14", "phase15", "phase16", "phase17", "phase18"].includes(id);
            const content = <>
              <span className="phase18-stage-index">{valueText(phase.label, id)}</span>
              <strong>{valueText(phase.title, "阶段证据")}</strong>
              <span className="phase18-stage-state" data-tone={statusTone(phase.status)}>{statusLabel(phase.status)}</span>
              <small>{valueText(phase.note)}</small>
            </>;
            return canOpen ? <button className="phase18-stage-row" type="button" key={id} onClick={() => onOpenPhase(id)} aria-label={`打开${valueText(phase.title, id)}证据`}>
              {content}<span className="phase18-stage-open" aria-hidden="true">↗</span>
            </button> : <article className="phase18-stage-row" key={id}>{content}</article>;
          })}
        </div>
      </section>

      <section className="phase18-findings-section" aria-labelledby="phase18-findings-title">
        <div className="phase18-section-title"><div><span className="panel-kicker">RESULTS / INCLUDING NEGATIVE EVIDENCE</span><h3 id="phase18-findings-title">实验结果没有一个全场景赢家</h3></div><p>数值来自冻结汇总；不同模型版本、场景和策略集合不合并成一组统计。</p></div>
        {findings.length ? <div className="phase18-findings-list">{findings.map((finding, index) => <article key={`${valueText(finding.id, "finding")}-${index}`}>
          <span>{String(index + 1).padStart(2, "0")}</span>
          <div><h4>{valueText(finding.title)}</h4><p>{valueText(finding.result)}</p>
            <small>{valueText(finding.sample_definition)} · 来源 <code>{valueText(finding.evidence_path)}</code></small>
          </div>
          <strong data-tone={statusTone(finding.status)}>{valueText(finding.status_label, statusLabel(finding.status))}</strong>
        </article>)}</div> : <p className="phase18-empty" role="status">没有可核验的结果摘要；请检查原始证据文件，不会补入示例结论。</p>}
      </section>

      <section className="phase18-gates-section" aria-labelledby="phase18-gates-title">
        <div className="phase18-section-title"><div><span className="panel-kicker">OPEN GATES / DO NOT OVERCLAIM</span><h3 id="phase18-gates-title">交付边界与未完成项</h3></div></div>
        <div className="phase18-gates-list">{gates.map((gate, index) => <article key={`${valueText(gate.id, "gate")}-${index}`} data-tone={statusTone(gate.status)}>
          <span className="phase18-gate-status">{statusLabel(gate.status)}</span><div><strong>{valueText(gate.title)}</strong><p>{valueText(gate.detail)}</p>{typeof gate.evidence_path === "string" && <code>{gate.evidence_path}</code>}</div>
        </article>)}</div>
      </section>

      <section className="phase18-system-section" aria-label="发布候选与工作区状态">
        <div className="phase18-system-block"><span className="panel-kicker">LOCAL RELEASE CANDIDATE</span><h3>{valueText(release.version, "6g-rescue-phase18-rc1")}</h3><p>{valueText(release.release_note, "仅为本地候选名称，不代表 Git tag 或正式发布。")}</p><div className="phase18-system-meta"><span>分支 <b>{valueText(workspace.branch)}</b></span><span>HEAD <code>{valueText(workspace.head).slice(0, 12)}</code></span><span>本阶段提交 <b>{workspace.phase18_commit_created === true ? "已创建" : "未创建"}</b></span><span>远程推送 <b>{workspace.remote_push_performed === true ? "已执行" : "未执行"}</b></span></div></div>
        <div className="phase18-system-block"><span className="panel-kicker">RELEASE MANIFEST</span><h3>{archiveCount} 项文件摘要</h3><p>清单列出相对路径、字节数、SHA-256、来源阶段、纳入状态与冻结标记。清单自身不包含自己的哈希。</p><div className="phase18-manifest-digest"><code>{valueText(record(supporting.release_manifest).artifact_sha256)}</code><span>manifest SHA-256</span></div></div>
      </section>

      <details className="phase18-test-details"><summary>展开最终测试矩阵（{tests.length} 项）</summary><div className="phase18-test-list">{tests.map((test, index) => <div key={`${valueText(test.id, "test")}-${index}`}><span>{valueText(test.name)}</span><b data-tone={statusTone(test.status)}>{valueText(test.result, statusLabel(test.status))}</b><small>{valueText(test.evidence_path)}</small></div>)}</div></details>
      <p className="phase18-scope-note">本项目是面向 6G 研究的抽象仿真与软件验证平台。页面中的模型性能、公开数据拟合与合成软件闭环不构成真实 6G 网络测试、目标设备校准、HIL 测试或 ITU-R / 3GPP 符合性证明。</p>
    </div>
  );
}
