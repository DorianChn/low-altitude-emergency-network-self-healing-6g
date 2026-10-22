import type { ResearchArtifactEnvelope } from "./research-model";

type Row = Record<string, unknown>;

function object(value: unknown): Row {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function text(value: unknown, fallback = "—"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function fixed(value: unknown, digits = 2): string {
  const n = number(value);
  return n === null ? "—" : n.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function interval(value: unknown): string {
  if (!Array.isArray(value) || value.length !== 2) return "未保存";
  return `[${fixed(value[0])}, ${fixed(value[1])}]`;
}

function metric(row: Row, key: string, unit = "dB"): string {
  const value = number(row[key]);
  return value === null ? "—" : `${fixed(value)} ${unit}`;
}

export function Phase15ResearchSection({ envelope }: { envelope: ResearchArtifactEnvelope }) {
  const summary = envelope.artifact;
  const support = envelope.supporting_artifacts ?? {};
  const holdout = object(support.holdout_validation?.artifact);
  const audit = object(support.dataset_audit?.artifact);
  const fit = object(summary.candidate_fit);
  const data = object(summary.dataset);
  const uncertainty = object(object(fit.parameter_uncertainty).ci95);
  const comparisons = object(holdout.comparisons);
  const phase14 = object(comparisons.phase14_exact);
  const matched = object(comparisons.frequency_matched_unfitted);
  const candidateMetrics = object(holdout.candidate_metrics);
  const phase14Metrics = object(phase14.baseline_metrics);
  const matchedMetrics = object(matched.baseline_metrics);
  const auditSource = object(audit.source_file_integrity);
  const rowAudit = object(audit.row_audit);
  const missing = object(audit.missing_measurement_metadata_counts);
  const missingUncertainty = number(holdout.measurement_uncertainty_db_missing_count);
  const measurementCount = number(data.cleaned_measurement_count);
  const sourceFileCount = number(data.source_file_count);
  const fitCount = number(fit.training_sample_count);
  const holdoutCount = number(holdout.sample_count);
  const baselineDelta = object(phase14).candidate_minus_baseline_mae_db;
  const decision = text(object(holdout.acceptance).decision, text(summary.holdout_acceptance_decision));
  const groups = object(holdout.per_holdout_group);
  const groupRows = Object.entries(groups);

  return (
    <div className="phase15-evidence" data-testid="phase15-research">
      <header className="radio-validation-head phase15-head">
        <div><span className="panel-kicker">PHASE 15 / PUBLIC MEASUREMENT EVIDENCE</span><h2>有留出结果；项目设备未校准</h2><p>公开空地信道数据完成了分组拟合和独立环境留出评估。结果只适用于数据集本身，不用于城市网络仿真。</p></div>
        <div className="phase15-status-stack"><span className="phase15-status phase15-status-done">公开数据：{text(summary.public_dataset_candidate_status)}</span><span className="phase15-status phase15-status-open">项目设备：{text(summary.project_device_calibration_status)}</span></div>
      </header>

      <section className="phase15-dataset-grid" aria-label="公开测量数据范围">
        <article><span>数据集</span><b>{text(data.title)}</b><p>{measurementCount?.toLocaleString("zh-CN") ?? "—"} 条配对测量记录 · {sourceFileCount ?? "—"} 个原始文件</p></article>
        <article><span>测量范围</span><b>3.60 GHz · 61.44 MHz</b><p>空对地 CIR · UAV 名义高度 10 m / 15 m · 3 类开放环境</p></article>
        <article><span>质量审计</span><b>{text(audit.status)} · {number(rowAudit.rejected_row_count) ?? "—"} 条拒绝</b><p>六个文件分组完整；保留 200 tap CIR 源文件与作者派生路径损耗标签</p></article>
        <article><span>解释边界</span><b>非目标设备校准</b><p>未知发射功率、天线增益、接收灵敏度与逐样本不确定度；无可靠 SINR/RSRP 标签</p></article>
      </section>

      <section className="phase15-model-band" aria-label="拟合参数和独立留出设计">
        <article className="phase15-model-candidate"><span>候选参数 / 仅公开数据域</span><b>ΔPL {fixed(fit.dataset_offset_db)} dB</b><p>训练 {fitCount ?? "—"} 条 · {number(fit.training_group_count) ?? "—"} 个完整文件组 · 拟合 MAE {metric(fit, "training_mae_db")}</p></article>
        <article><span>固定而未拟合</span><b>n = {fixed(fit.path_loss_exponent, 1)}</b><p>沿用 Phase14 UAV 接入假设；训练距离仅覆盖 {fixed(fit.distance_span_decades, 3)} 个十进数量级，不足以同时识别斜率和截距。</p></article>
        <article><span>参数区间 / 整组 Bootstrap</span><b>{interval(uncertainty.dataset_offset_db)} dB</b><p>4 个训练组、4,000 次重采样；未包含源数据未提供的测量不确定度。</p></article>
        <article><span>冻结的独立留出</span><b>{holdoutCount ?? "—"} 条 · 2 个整组</b><p>Over-water 10 m ({number(object(groups["Over-water_10m"]).sample_count) ?? "—"}) 与 15 m ({number(object(groups["Over-water_15m"]).sample_count) ?? "—"})；未用于拟合。</p></article>
      </section>

      <section className="phase15-results-block" aria-labelledby="phase15-error-title">
        <div className="radio-block-heading"><div><span className="panel-kicker">SAME HOLDOUT / PATH-LOSS LABELS</span><h3 id="phase15-error-title">相同 570 条留出样本的误差对照</h3></div><small>更低 MAE 只说明对这两组数据标签的预测误差更低</small></div>
        <div className="phase15-table-scroll" role="region" tabIndex={0} aria-label="校准模型留出误差表，可横向滚动">
          <table className="research-table phase15-table">
            <thead><tr><th scope="col">模型</th><th scope="col">载频 / 指数</th><th scope="col">MAE</th><th scope="col">RMSE</th><th scope="col">平均偏差</th><th scope="col">与候选模型的配对组 MAE 差</th><th scope="col">组 Bootstrap 95% 区间</th></tr></thead>
            <tbody>
              <tr className="phase15-candidate-row"><th scope="row">Phase15 单参数候选</th><td>3.6 GHz / n 固定 2.3</td><td><b>{metric(candidateMetrics, "mae_db")}</b></td><td>{metric(candidateMetrics, "rmse_db")}</td><td>{metric(candidateMetrics, "mean_bias_db")}</td><td>基准</td><td>—</td></tr>
              <tr><th scope="row">Phase14 精确基线</th><td>3.5 GHz / n = 2.3</td><td><b>{metric(phase14Metrics, "mae_db")}</b></td><td>{metric(phase14Metrics, "rmse_db")}</td><td>{metric(phase14Metrics, "mean_bias_db")}</td><td>{fixed(baselineDelta)} dB</td><td>{interval(phase14.paired_mae_difference_ci95_cluster_bootstrap_db)} dB</td></tr>
              <tr><th scope="row">频率匹配未拟合</th><td>3.6 GHz / n = 2.3</td><td><b>{metric(matchedMetrics, "mae_db")}</b></td><td>{metric(matchedMetrics, "rmse_db")}</td><td>{metric(matchedMetrics, "mean_bias_db")}</td><td>{fixed(matched.candidate_minus_baseline_mae_db)} dB</td><td>{interval(matched.paired_mae_difference_ci95_cluster_bootstrap_db)} dB</td></tr>
            </tbody>
          </table>
        </div>
        <div className="phase15-acceptance" role="note"><b>验收判断：{decision}</b><span>按完整测量文件进行配对重采样，但独立留出只有两个组，区间分辨率很低；{missingUncertainty ?? "—"} 条留出样本没有报告测量不确定度。因此不能宣称候选参数通过校准精度判据，也不能把 MAE 差异解释为项目设备精度提升。</span></div>
        <details className="phase15-metric-guide"><summary>如何读整体 MAE 与配对组差</summary><p>表中的候选与基线 MAE 都是按全部 {holdoutCount ?? "—"} 条记录汇总；单独显示的配对差 −5.05 dB 则先分别计算两个留出组的 MAE 差，再对两组等权平均。按全部样本池直接相减为 −5.37 dB。两者回答的问题不同，差异来自组样本量不等；请结合下方逐组误差阅读。只有两个独立组，组 Bootstrap 区间分辨率也有限。</p></details>
        <div className="phase15-group-results" aria-label="各留出组单独误差">
          {groupRows.map(([group, value]) => {
            const row = object(value);
            return <article key={group}><span>{group}</span><b>n={number(row.sample_count) ?? "—"}</b><p>候选 MAE {metric(object(row.candidate), "mae_db")} · Phase14 MAE {metric(object(object(object(row.comparisons).phase14_exact).baseline), "mae_db")}</p></article>;
          })}
        </div>
      </section>

      <section className="phase15-plot-section" aria-labelledby="phase15-plot-title">
        <div className="radio-block-heading"><div><span className="panel-kicker">SAVED PLOTS / REPRODUCIBLE OUTPUT</span><h3 id="phase15-plot-title">预测曲线、残差与偏移估计</h3></div><small>由 results 中已保存的观测、拟合与留出 JSON 生成</small></div>
        <div className="phase15-plots">
          <figure><a href="/api/research/phase15/plots/phase15_fit_and_holdout.svg" target="_blank" rel="noreferrer"><img src="/api/research/phase15/plots/phase15_fit_and_holdout.png" alt="公开空地数据训练点和留出点，以及 Phase14、频率匹配和候选路径损耗预测曲线" loading="lazy" /></a><figcaption>训练与留出观测，以及三个固定预测模型。</figcaption></figure>
          <figure><a href="/api/research/phase15/plots/phase15_holdout_residuals.svg" target="_blank" rel="noreferrer"><img src="/api/research/phase15/plots/phase15_holdout_residuals.png" alt="过水环境留出样本中候选模型和 Phase14 基线的预测路径损耗残差分布" loading="lazy" /></a><figcaption>最终留出两组的样本残差；不是设备级验证。</figcaption></figure>
          <figure><a href="/api/research/phase15/plots/phase15_parameter_uncertainty.svg" target="_blank" rel="noreferrer"><img src="/api/research/phase15/plots/phase15_parameter_uncertainty.png" alt="四个训练环境高度组的路径损耗偏移估计和按组 Bootstrap 区间" loading="lazy" /></a><figcaption>每个训练文件偏移与等组 Bootstrap 区间。</figcaption></figure>
        </div>
      </section>

      <section className="phase15-limit-grid" aria-label="参数缺失和适用限制">
        <article><span>关键字段缺失</span><b>发射 / 天线 / 接收参数各 {number(missing.transmit_power_dbm) ?? "—"} 条</b><p>另缺 {number(missing.measured_sinr_db) ?? "—"} 条 SINR、RSRP、逐样本不确定度、设备型号、LOS、遮挡及天气记录。未进行填补。</p></article>
        <article><span>不可识别参数</span><b>功率链与失效门限</b><p>发射功率、天线增益、接收灵敏度、阴影标准差与城市遮挡损耗不能由当前标签唯一分离。</p></article>
        <article><span>网络仿真使用</span><b>{object(summary.formal_network_simulation).executed === true ? "已运行" : "未运行"}</b><p>{text(object(summary.formal_network_simulation).reason)}</p></article>
      </section>

      <section className="phase15-provenance" aria-label="数据来源与校验信息">
        <div><span>数据集 DOI</span><a href={text(data.source_url)} target="_blank" rel="noreferrer">{text(data.doi)}</a></div>
        <div><span>许可</span><a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a></div>
        <div><span>清洗数据 SHA-256</span><code>{text(data.cleaned_measurement_sha256)}</code></div>
        <div><span>协议 SHA-256</span><code>{text(summary.protocol_sha256)}</code></div>
        <div><span>源码包 SHA-256</span><code>{text(summary.source_bundle_sha256)}</code></div>
        <div><span>原始文件哈希审计</span><b>{number(auditSource.verified_file_count) ?? "—"}/{number(auditSource.manifest_file_count) ?? "—"} 匹配</b></div>
      </section>
    </div>
  );
}
