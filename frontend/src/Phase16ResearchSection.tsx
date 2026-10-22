/* Hallmark · component-scope: no macrostructure · pre-emit critique: P4 H4 E4 S5 R5 V4 */
import type { ResearchArtifactEnvelope } from "./research-model";

type Row = Record<string, unknown>;
type Supporting = NonNullable<ResearchArtifactEnvelope["supporting_artifacts"]>;

function object(value: unknown): Row {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = "未记录"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function hash(value: unknown): string {
  return typeof value === "string" && value.length >= 16 ? value.slice(0, 16) + "…" : "未记录";
}

const SOURCE_LABELS: Record<string, string> = {
  tx_power: "发射功率",
  rx_power: "接收功率",
  tx_antenna_gain: "发射天线增益",
  rx_antenna_gain: "接收天线增益",
  feedline_loss: "电缆与馈线损耗",
  frequency: "载频配置",
  bandwidth: "带宽配置",
  distance: "收发距离与定位",
  antenna_height: "天线高度",
  antenna_attitude: "天线姿态与指向",
  temperature_gain_drift: "温度与增益漂移",
  repeatability: "重复性",
  between_batch: "批次间差异",
  environmental_variation: "遮挡、多径与环境波动",
  model_residual: "模型残差",
  parameter_estimation: "参数估计不确定度",
};

const CATEGORY_LABELS: Record<string, string> = {
  instrument: "仪器测量",
  systematic: "系统误差",
  configuration: "配置误差",
  geometry: "几何测量",
  repeatability: "重复性 / 批次",
  natural_variability: "自然波动",
  model_residual: "模型残差",
  parameter_estimation: "参数估计",
};

const ADAPTER_LABELS: Record<string, string> = {
  offline_file_import: "CSV / JSON 文件导入",
  radio_instrument_driver: "真实射频仪器驱动",
  future_instrument_adapter_contract: "未来仪器接入接口",
};

const ADAPTER_STATUS_LABELS: Record<string, string> = {
  IMPLEMENTED_AND_TESTED: "已实现并测试",
  INTERFACE_ONLY: "仅接口约定",
  UNAVAILABLE: "不可用",
};

const SCENARIO_LABELS: Record<string, string> = {
  open_line_of_sight: "开阔视距",
  urban_street: "城市街道",
  building_obstructed: "建筑遮挡",
};

const PURPOSE_LABELS: Record<string, string> = {
  "reference propagation and repeatability": "建立参考传播条件并检查重复性",
  "street canyon and route variability": "评估街谷传播与路线间差异",
  "obstruction loss and link margin changes": "评估建筑遮挡损耗及链路裕量变化",
};

const SOURCE_LABELS_EN: Record<string, string> = {
  "position error": "定位误差",
  "antenna alignment": "天线对准",
  "temperature drift": "温度漂移",
  multipath: "多径",
  "time variation": "时间变化",
  "route repeatability": "路线重复性",
  "position sync": "定位同步",
  "building geometry": "建筑几何",
  orientation: "天线朝向",
  "environmental variation": "环境变化",
};

const METADATA_LABELS: Record<string, string> = {
  device_model: "设备型号",
  calibration_status: "校准状态",
};

const CHECKLIST_LABELS: Record<string, string> = {
  "Authorized, type-appropriate transmitter or shielded-lab source": "经核验的合规发射机或屏蔽实验室信号源",
  "Calibrated receiver/test instrument with certificate": "带有效校准证书的接收机或测试仪",
  "Antenna patterns and calibrated feedline-loss records": "天线方向图和馈线损耗记录",
  "Positioning and time synchronization evidence": "定位与时间同步误差证据",
  "Site/frequency authorization for any emission": "发射地点与频率使用批准",
  "UAV and actual site flight/airspace approval if airborne": "无人机及实际地点的飞行/空域批准",
  "Privacy-reviewed, session-grouped storage location": "完成隐私审查并按会话分组的存储位置",
};

const PLAN_STATUS_LABELS: Record<string, string> = {
  PLANNED_NOT_EXECUTED: "仅完成计划 · 尚未执行",
};

const PLAN_DESIGN_LABELS: Record<string, string> = {
  "complete route/session/batch": "完整路线、会话或测量批次",
  "Keep entire routes and measurement batches in exactly one of development, validation, or final holdout. Never split adjacent samples across partitions.": "整条路线和完整测量批次只进入开发、验证或最终留出中的一个集合；相邻样本不得拆分到不同集合。",
  "Recalculate after the pilot using observed between-route variance and a predeclared precision/power target; five routes are a planning floor, not a statistical guarantee.": "先导测量后按路线间方差和预先声明的精度/功效目标重算样本量；5 条路线只是工作量下限，不代表统计保证。",
};

export function Phase16ResearchSection({ envelope }: { envelope: ResearchArtifactEnvelope }) {
  const main = envelope.artifact;
  const support: Supporting = envelope.supporting_artifacts ?? {};
  const inventory = object(support.environment_inventory?.artifact);
  const importAudit = object(support.measurement_import?.artifact);
  const budget = object(support.uncertainty_budget?.artifact);
  const state = object(support.calibration_state?.artifact);
  const integrity = object(support.integrity_audit?.artifact);
  const dataset = object(inventory.available_measurement_data);
  const device = object(inventory.equipment_scan);
  const plan = object(main.measurement_plan);
  const design = object(plan.design);
  const provisionalCells = object(design.provisional_cells);
  const planFrequencyHz = count(plan.target_frequency_hz);
  const planFrequency = planFrequencyHz === null ? "未记录" : `${(planFrequencyHz / 1e9).toFixed(1)} GHz`;
  const transmissionAuthorized = plan.transmission_authorized === true;
  const flightAuthorized = plan.uav_flight_authorized === true;
  const sources = array(budget.sources).map(object);
  const scenarios = array(plan.scenarios).map(object);
  const checklist = array(main.equipment_readiness_checklist).map(object);
  const adapters = array(main.measurement_adapters).map(object);
  const transitions = array(state.state_transitions).map(object);
  const missingMetadata = array(importAudit.missing_device_metadata).filter((item): item is string => typeof item === "string");
  const metadataRequired = array(importAudit.required_device_metadata_fields).length;
  const metadataComplete = Math.max(0, metadataRequired - missingMetadata.length);
  const protectedCount = array(integrity.protected_hashes).length;
  const rawSourceCount = array(integrity.raw_dataset_files).length;
  const knownUncertaintyCount = sources.filter((source) => count(source.standard_uncertainty) !== null).length;
  const deviceCount = array(device.matched_devices).length;
  const importStatus = text(importAudit.import_status);
  const readiness = text(main.status);
  const stateStatus = text(state.status);
  const importSha = text(importAudit.source_sha256, "未记录");
  const importCleanCount = count(importAudit.record_count_after_cleaning);
  const importBeforeCount = count(importAudit.record_count_before_cleaning);
  const rejectCount = count(importAudit.rejected_record_count);
  const duplicateCount = count(importAudit.duplicate_record_count);
  const auditPass = text(integrity.status);

  return (
    <div className="phase16-readiness" data-testid="phase16-readiness">
      <section className="phase16-alert" role="note" aria-label="设备校准声明">
        <strong>真实设备校准尚未完成；当前工具用于测量准备、数据审计和校准验收。</strong>
        <p>没有目标设备实测、完整测量不确定度及预先冻结的验收标准，因此当前状态保持未校准。</p>
      </section>

      <section className="phase16-overview" aria-label="当前准备状态">
        <div className="phase16-overview-copy">
          <h2>先把证据链备齐</h2>
          <p>本地扫描、数据导入、误差预算和验收门槛分开记录。公开测量数据不会被视作项目设备的校准记录。</p>
        </div>
        <div className="phase16-status-line">
          <span className="phase16-status-mark" data-tone="warning" />
          <div><b>{readiness === "NOT_READY_FOR_FIELD_MEASUREMENT" ? "尚不具备外场测量条件" : readiness}</b><span>目标设备校准：{stateStatus}</span></div>
        </div>
      </section>

      <section className="phase16-evidence-band" aria-label="已核验数据">
        <article>
          <span>设备扫描</span><b>{device.status === "COMPLETED" && deviceCount === 0 ? "未发现已枚举的测量仪器" : `${deviceCount} 个匹配设备`}</b>
          <p>{text(device.status)} · 串口 {count(device.serial_port_count) ?? "未检测"} 个。按设备名称筛查，不含序列号；不代表其他目录或未枚举设备不存在。</p>
        </article>
        <article>
          <span>公开测量数据</span><b>{count(dataset.record_count)?.toLocaleString("zh-CN") ?? "—"} 条 · {count(dataset.source_file_count) ?? "—"} 个源文件</b>
          <p>{text(dataset.dataset_id)} · {count(dataset.carrier_frequency_hz) === null ? "频率未记录" : `${(Number(dataset.carrier_frequency_hz) / 1e9).toFixed(1)} GHz`}。CIR 为测量数据，路径损耗为发布者派生标签。</p>
        </article>
        <article>
          <span>设备元数据完整度</span><b>{metadataComplete} / {metadataRequired} 项</b>
          <p>{missingMetadata.length ? `缺少：${missingMetadata.map((field) => METADATA_LABELS[field] ?? field).join("、")}` : "导入元数据字段完整"}。该值针对公开数据导入，不代表项目设备档案完整。</p>
        </article>
        <article>
          <span>历史结果完整性</span><b>{auditPass} · {protectedCount} 项受保护文件</b>
          <p>Phase 15 原始数据源 {rawSourceCount} 个；冻结输入和来源哈希已核对。Phase 14/15 历史数值未重算覆盖。</p>
        </article>
      </section>

      <section className="phase16-import-section" aria-labelledby="phase16-import-title">
        <div className="phase16-section-heading">
          <div><h3 id="phase16-import-title">导入审计</h3><p>原始文件只读，清洗副本与审计记录另存。</p></div>
          <span className="phase16-pill" data-tone={importStatus === "PASS" ? "ok" : "warning"}>{importStatus}</span>
        </div>
        <div className="phase16-import-grid">
          <p><b>{importBeforeCount?.toLocaleString("zh-CN") ?? "—"}</b><span>导入记录</span></p>
          <p><b>{importCleanCount?.toLocaleString("zh-CN") ?? "—"}</b><span>有效记录</span></p>
          <p><b>{rejectCount ?? "—"}</b><span>拒绝记录</span></p>
          <p><b>{duplicateCount ?? "—"}</b><span>重复记录</span></p>
        </div>
        <div className="phase16-source-hash"><span>原始文件 SHA-256</span><code>{importSha}</code><span>读取后哈希未变：{importAudit.source_hash_unchanged_after_read === true ? "是" : "无法确认"}</span></div>
        <div className="phase16-adapters" aria-label="采集适配器状态">
          {adapters.map((adapter, index) => {
            const status = text(adapter.status);
            const tone = status === "IMPLEMENTED_AND_TESTED" ? "ok" : status === "UNAVAILABLE" ? "off" : "pending";
            return <span key={text(adapter.id, String(index))}><b>{ADAPTER_LABELS[text(adapter.id)] ?? text(adapter.id)}</b><i data-tone={tone}>{ADAPTER_STATUS_LABELS[status] ?? status}</i></span>;
          })}
        </div>
      </section>

      <section className="phase16-uncertainty-section" aria-labelledby="phase16-uncertainty-title">
        <div className="phase16-section-heading">
          <div><h3 id="phase16-uncertainty-title">测量不确定度预算</h3><p>清单分开记录仪器误差、系统误差、自然波动、模型残差和参数估计。</p></div>
          <span className="phase16-budget-count">已有标准不确定度数值 {knownUncertaintyCount} / {sources.length}</span>
        </div>
        <div className="phase16-budget-warning">合成标准不确定度：<b>{count(budget.combined_standard_uncertainty_db) === null ? "不可计算" : `${Number(budget.combined_standard_uncertainty_db).toFixed(3)} dB`}</b>。缺失项保持未知，不按 0 参与；扩展不确定度和覆盖概率均未给出。</div>
        <div className="phase16-table-scroll" role="region" tabIndex={0} aria-label="测量不确定度来源表，可横向滚动">
          <table className="research-table phase16-budget-table">
            <thead><tr><th scope="col">来源</th><th scope="col">类别</th><th scope="col">单位</th><th scope="col">标准不确定度</th><th scope="col">当前证据</th></tr></thead>
            <tbody>{sources.map((source, index) => {
              const id = text(source.id, String(index));
              const value = count(source.standard_uncertainty);
              return <tr key={id}><th scope="row">{SOURCE_LABELS[id] ?? text(source.quantity, id)}</th><td>{CATEGORY_LABELS[text(source.category)] ?? text(source.category)}</td><td>{text(source.unit)}</td><td>{value === null ? "未知" : `${value} ${text(source.unit)}`}</td><td>{value === null ? "无目标设备误差证据" : text(source.evidence)}</td></tr>;
            })}</tbody>
          </table>
        </div>
        <p className="phase16-coverage-note">自然波动与仪器不确定度不是同一类量；模型残差也不能替代测量仪器的校准误差。扩展不确定度使用明确给定的覆盖因子 U = k·u₍c₎，不会仅凭 k 自动标成 95%。</p>
      </section>

      <section className="phase16-plan-section" aria-labelledby="phase16-plan-title">
        <div className="phase16-section-heading">
          <div><h3 id="phase16-plan-title">城市空地链路测量计划</h3><p>{planFrequency} 附近仅作为目标研究频段；当前计划状态：{PLAN_STATUS_LABELS[text(plan.status)] ?? text(plan.status)}。没有执行发射、接收或无人机飞行。</p></div>
          <span className="phase16-pill" data-tone={transmissionAuthorized && flightAuthorized ? "ok" : "warning"}>{transmissionAuthorized ? "频谱授权已记录" : "频谱授权未核验"} · {flightAuthorized ? "飞行已记录" : "飞行未核验"}</span>
        </div>
        <div className="phase16-scenario-list">
          {scenarios.map((scenario) => <article key={text(scenario.id)}><h4>{SCENARIO_LABELS[text(scenario.id)] ?? text(scenario.id).replaceAll("_", " ")}</h4><p>{PURPOSE_LABELS[text(scenario.purpose)] ?? text(scenario.purpose)}</p><span>{array(scenario.primary_sources).map((item) => SOURCE_LABELS_EN[String(item)] ?? String(item)).join(" · ") || array(scenario.conditions).map(String).join(" · ")}</span><i className="phase16-measurement-state">{main.field_measurement_executed === true ? "已有测量记录" : "计划场景 · 尚未测量"}</i></article>)}
        </div>
        <div className="phase16-plan-method">
          <p><b>划分单位</b><span>{PLAN_DESIGN_LABELS[text(design.independent_unit)] ?? text(design.independent_unit, "未记录")}；{PLAN_DESIGN_LABELS[text(design.split_rule)] ?? text(design.split_rule, "未记录数据划分规则")}</span></p>
          <p><b>规划下限</b><span>每格 {count(provisionalCells.independent_routes_per_cell) ?? "未设定"} 条独立路线、每路线 {count(provisionalCells.repeat_passes_per_route) ?? "未设定"} 次重复。{PLAN_DESIGN_LABELS[text(design.sample_size_rule)] ?? text(design.sample_size_rule, "尚无样本量规则")}</span></p>
          <p><b>无线频率</b><span>{transmissionAuthorized ? "计划中存在授权证据引用；实际发射前仍需核对设备和现场范围。" : `未发现本项目授权。不得把该计划理解为允许在 ${planFrequency} 发射。`}</span></p>
          <p><b>无人机飞行</b><span>{flightAuthorized ? "计划中存在飞行批准引用；仍需核对具体机型、地点与任务。" : "实际机型、空域、地点、任务与飞行计划需另行核验批准。"}</span></p>
        </div>
      </section>

      <section className="phase16-gates-section" aria-labelledby="phase16-gates-title">
        <div className="phase16-section-heading"><div><h3 id="phase16-gates-title">开始现场采集前的缺口</h3><p>各项由现有证据生成，前端没有手工切换校准状态的入口。</p></div></div>
        <ul className="phase16-gates-list">{checklist.map((item, index) => <li key={`${text(item.item)}-${index}`}><span data-tone={text(item.status) === "TEMPLATE_READY" ? "ok" : "warning"}>{text(item.status)}</span><p>{CHECKLIST_LABELS[text(item.item)] ?? text(item.item)}</p></li>)}</ul>
      </section>

      <section className="phase16-state-history" aria-labelledby="phase16-history-title">
        <div className="phase16-section-heading"><div><h3 id="phase16-history-title">校准验收状态变更</h3><p>状态由证据和冻结判据计算，不接受页面手动指定。</p></div></div>
        {transitions.length === 0
          ? <p className="phase16-empty">当前状态未发生转换；最近保存状态为 {stateStatus}。</p>
          : <ol>{transitions.map((transition, index) => <li key={`${text(transition.timestamp_utc)}-${index}`}><time>{text(transition.timestamp_utc)}</time><b>{text(transition.from, "初始")} → {text(transition.to)}</b><p>{text(transition.reason)}</p><code>模型 {text(transition.model_version)} · 输入 SHA {hash(Object.values(object(transition.input_hashes))[0])}</code></li>)}</ol>}
      </section>

      <footer className="phase16-boundary-note">
        <b>模型边界</b>
        <p>当前基站 / 无人机链路参数仍是 Phase 14 工程假设。Phase 15 的 3.6 GHz 公开非城市路径损耗候选不进入正式仿真，也不能当作 3.5 GHz 城市设备校准。此平台是测量准备和抽象研究工具，不是真实 6G 网络测试。</p>
        <span>清洗副本 SHA-256 {hash(importAudit.cleaned_output_sha256)} · 来源审计 SHA-256 {hash(support.measurement_import?.artifact_sha256)}</span>
      </footer>
    </div>
  );
}
