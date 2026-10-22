export type ResearchPhaseId = "phase5" | "phase8" | "phase9" | "phase10" | "phase11" | "phase14" | "phase15" | "phase16" | "phase17" | "phase18";
export type HistoricalResearchPhaseId = Exclude<ResearchPhaseId, "phase14" | "phase15" | "phase16" | "phase17" | "phase18">;
export type ResearchSceneId =
  | "severe_persistent_faults"
  | "dynamic_failures"
  | "high_mobility_rescue"
  | "high_load_backhaul_limit";

type JsonRecord = Record<string, unknown>;

export interface ResearchArtifactEnvelope {
  schema_version: string;
  dataset_id: ResearchPhaseId;
  artifact_path: string;
  artifact_sha256: string;
  experiment_role: string;
  model_scope: string;
  artifact: JsonRecord;
  supporting_artifacts?: Record<string, {
    artifact_path: string;
    artifact_sha256: string;
    artifact: JsonRecord;
  }>;
}

export interface ResearchEstimate {
  mean: number | null;
  sampleSd: number | null;
  ci95: [number, number] | null;
  n: number | null;
}

export interface ResearchRecovery {
  successes: number | null;
  total: number | null;
  failures: number | null;
  successfulMeanSeconds: number | null;
  allRunCensorMeanSeconds: number | null;
}

export interface ResearchStrategy {
  id: string;
  label: string;
  category: string;
  module: string;
  observation: string;
  trigger: string;
  constraints: string;
  rescueService: ResearchEstimate;
  connection: ResearchEstimate;
  firstRecovery: ResearchRecovery;
  sustainedRecovery: ResearchRecovery;
  energyWh: ResearchEstimate;
  energyPerRescueHour: ResearchEstimate;
  conditionalMeanLatencyMs: number | null;
  conditionalP95LatencyMs: number | null;
  latencySamples: number | null;
  computeTotalMs: ResearchEstimate;
  computeLabel: string;
}

export interface ResearchPairDifference {
  available: boolean;
  selectedId: string;
  baselineId: string;
  n: number | null;
  meanDifference: number | null;
  ci95: [number, number] | null;
  adjustedP: number | null;
  rawP: number | null;
  effectSize: number | null;
  note: string;
}

export interface ResearchDataset {
  phase: HistoricalResearchPhaseId;
  phaseLabel: string;
  scenarioId: ResearchSceneId;
  scenarioLabel: string;
  experimentRole: string;
  sourcePath: string;
  sourceSha256: string;
  seedCount: number;
  runCount: number | null;
  strategyCount: number;
  statisticalMethod: string;
  metricDefinition: string;
  latencyDefinition: string;
  compareNote: string;
  strategies: ResearchStrategy[];
  pairDifference: ResearchPairDifference;
  multiUavReplayAvailable: false;
}

export const RESEARCH_PHASES: Array<{ id: ResearchPhaseId; label: string }> = [
  { id: "phase5", label: "Phase 5 · 多灾种验证" },
  { id: "phase8", label: "Phase 8 · 机制复验" },
  { id: "phase9", label: "Phase 9 · 事件驱动" },
  { id: "phase10", label: "Phase 10 · 多机协同" },
  { id: "phase11", label: "Phase 11 · 基线扩展" },
  { id: "phase14", label: "Phase 14 · 链路模型" },
  { id: "phase15", label: "Phase 15 · 测量校准" },
  { id: "phase16", label: "Phase 16 · 实测准备" },
  { id: "phase17", label: "Phase 17 · HIL 安全闭环" },
  { id: "phase18", label: "Phase 18 · 最终证据审计" },
];

export const RESEARCH_SCENES: Array<{ id: ResearchSceneId; label: string }> = [
  { id: "severe_persistent_faults", label: "严重持续故障" },
  { id: "dynamic_failures", label: "动态故障" },
  { id: "high_mobility_rescue", label: "高移动救援" },
  { id: "high_load_backhaul_limit", label: "高负载 / 回传受限" },
];

const PHASE_LABELS: Record<HistoricalResearchPhaseId, string> = {
  phase5: "Phase 5 · 多灾种留出验证",
  phase8: "Phase 8 · 独立机制复验",
  phase9: "Phase 9 · 修复版确认实验",
  phase10: "Phase 10 · 多无人机确认实验",
  phase11: "Phase 11 · 算法基线确认实验",
};

const SOURCE_PATHS: Record<HistoricalResearchPhaseId, string> = {
  phase5: "results/phase5_validation_summary.json",
  phase8: "results/phase8_replication_summary.json",
  phase9: "results/phase9_corrected_confirmation_summary.json",
  phase10: "results/phase10_confirmation_summary.json",
  phase11: "results/phase11_confirmation_summary.json",
};

const SCENE_LABELS: Record<ResearchSceneId, string> = {
  severe_persistent_faults: "严重持续故障",
  dynamic_failures: "动态故障",
  high_mobility_rescue: "高移动救援",
  high_load_backhaul_limit: "高负载 / 回传受限",
};

const STRATEGY_NAMES: Record<string, string> = {
  A_no_recovery: "A · 无恢复措施",
  B_phase1_static_grid: "B · 静态网格",
  Bprime_static_grid_shared_safety: "B′ · 统一约束静态网格",
  C_rolling_horizon_mpc: "C · 滚动时域优化",
  D_lexicographic_rescue_priority: "D · 救援优先优化",
  E_event_driven_rescue_recovery: "E · 事件驱动恢复",
  Bprime_static_grid_shared_safety_uav1: "B′ · 单无人机静态网格",
  F_independent_greedy_uav2: "F · 双机独立贪心",
  G_centralized_coordination_uav2: "G · 双机集中协同",
  H_marginal_rescue_greedy_uav2: "H · 双机边际覆盖贪心",
  I_constrained_user_assignment_uav2: "I · 双机约束分配",
  J_budgeted_joint_beam_uav2: "J · 双机限额联合搜索",
  F_independent_greedy_uav3: "F · 三机独立贪心",
  G_centralized_coordination_uav3: "G · 三机集中协同",
  H_marginal_rescue_greedy_uav3: "H · 三机边际覆盖贪心",
  I_constrained_user_assignment_uav3: "I · 三机约束分配",
  J_budgeted_joint_beam_uav3: "J · 三机限额联合搜索",
};

const STRATEGY_DETAILS: Record<string, Omit<ResearchStrategy, "id" | "label" | "rescueService" | "connection" | "firstRecovery" | "sustainedRecovery" | "energyWh" | "energyPerRescueHour" | "conditionalMeanLatencyMs" | "conditionalP95LatencyMs" | "latencySamples" | "computeTotalMs">> = {
  A_no_recovery: { category: "固定基线", module: "src/lowalt6g/policies.py", observation: "不执行恢复调度。", trigger: "无动作触发。", constraints: "由共享仿真执行层决定地面网络可服务范围。", computeLabel: "控制器观测累计 · ms / 运行" },
  B_phase1_static_grid: { category: "规则型", module: "src/lowalt6g/policies.py", observation: "当前用户位置、基站与链路状态。", trigger: "固定周期执行网格候选选址。", constraints: "覆盖、容量、健康回传、飞行速度与电池储备。", computeLabel: "控制器观测累计 · ms / 运行" },
  Bprime_static_grid_shared_safety: { category: "规则型", module: "src/lowalt6g/policies.py + src/lowalt6g/energy_budget.py", observation: "当前网络与统一电量预算。", trigger: "固定周期执行网格候选选址。", constraints: "共享出动能耗预算、返航储备、覆盖、容量与回传。", computeLabel: "控制器观测累计 · ms / 运行" },
  C_rolling_horizon_mpc: { category: "确定性滚动优化", module: "src/lowalt6g/optimizer.py", observation: "控制器可见的当前网络状态与配置预测时域。", trigger: "周期或状态变化后有限候选重规划。", constraints: "链路、共享容量、速度、电池储备、返航与计算预算。", computeLabel: "优化决策累计 · ms / 运行" },
  D_lexicographic_rescue_priority: { category: "确定性词典序优化", module: "src/lowalt6g/optimizer.py + src/lowalt6g/phase8_d_optimizer.py", observation: "当前网络状态、救援需求及安全预算。", trigger: "周期或状态变化后按优先级比较可行候选。", constraints: "救援优先级、回传、容量、飞行和电池储备。", computeLabel: "优化决策累计 · ms / 运行" },
  E_event_driven_rescue_recovery: { category: "事件驱动确定性优化", module: "src/lowalt6g/phase9_strategy_e.py", observation: "故障、回传、救援连接、容量及电量变化。", trigger: "关键观测事件触发，带去重和冷却。", constraints: "可用回传、接入/回传距离、容量、速度、返航预算和电池储备。", computeLabel: "策略决策累计 · ms / 运行" },
  Bprime_static_grid_shared_safety_uav1: { category: "规则型", module: "src/lowalt6g/policies.py + src/lowalt6g/energy_budget.py", observation: "单机当前网络与安全预算。", trigger: "固定周期网格选址。", constraints: "统一安全执行层与返航储备。", computeLabel: "协调计算累计 · ms / 运行" },
  F_independent_greedy_uav2: { category: "独立贪心", module: "src/lowalt6g/multi_uav.py", observation: "单机局部可观察状态；资源由共享引擎统一分配。", trigger: "各机独立选择任务和目标。", constraints: "共享基站容量、机载容量、回传和飞行安全。", computeLabel: "协调计算累计 · ms / 运行" },
  G_centralized_coordination_uav2: { category: "集中式确定性搜索", module: "src/lowalt6g/multi_uav.py", observation: "协调器可见的机队、用户、链路与容量状态。", trigger: "统一生成候选并联合比较。", constraints: "共享资源、路径可行性、间距、速度、电量和返航。", computeLabel: "协调计算累计 · ms / 运行" },
  H_marginal_rescue_greedy_uav2: { category: "边际覆盖贪心", module: "src/lowalt6g/phase11_algorithms.py", observation: "当前未服务救援需求和可行候选位置。", trigger: "逐机选取新增救援覆盖最大的可行位置。", constraints: "已分配用户去重、共享容量、回传与安全预算。", computeLabel: "协调计算累计 · ms / 运行" },
  I_constrained_user_assignment_uav2: { category: "约束用户分配", module: "src/lowalt6g/phase11_algorithms.py", observation: "当前用户与可行中继资源关系。", trigger: "在已有机位下集中分配用户/容量。", constraints: "用户唯一分配、共享基站和无人机容量、链路可行性。", computeLabel: "协调计算累计 · ms / 运行" },
  J_budgeted_joint_beam_uav2: { category: "限额联合搜索", module: "src/lowalt6g/phase11_algorithms.py", observation: "当前机队候选位置和共享网络状态。", trigger: "在固定搜索预算内执行有限联合规划。", constraints: "候选与计算预算、机队共享容量、飞行、电量和返航。", computeLabel: "协调计算累计 · ms / 运行" },
  F_independent_greedy_uav3: { category: "独立贪心", module: "src/lowalt6g/multi_uav.py", observation: "单机局部可观察状态；资源由共享引擎统一分配。", trigger: "各机独立选择任务和目标。", constraints: "共享基站容量、机载容量、回传和飞行安全。", computeLabel: "协调计算累计 · ms / 运行" },
  G_centralized_coordination_uav3: { category: "集中式确定性搜索", module: "src/lowalt6g/multi_uav.py", observation: "协调器可见的机队、用户、链路与容量状态。", trigger: "统一生成候选并联合比较。", constraints: "共享资源、路径可行性、间距、速度、电量和返航。", computeLabel: "协调计算累计 · ms / 运行" },
  H_marginal_rescue_greedy_uav3: { category: "边际覆盖贪心", module: "src/lowalt6g/phase11_algorithms.py", observation: "当前未服务救援需求和可行候选位置。", trigger: "逐机选取新增救援覆盖最大的可行位置。", constraints: "已分配用户去重、共享容量、回传与安全预算。", computeLabel: "协调计算累计 · ms / 运行" },
  I_constrained_user_assignment_uav3: { category: "约束用户分配", module: "src/lowalt6g/phase11_algorithms.py", observation: "当前用户与可行中继资源关系。", trigger: "在已有机位下集中分配用户/容量。", constraints: "用户唯一分配、共享基站和无人机容量、链路可行性。", computeLabel: "协调计算累计 · ms / 运行" },
  J_budgeted_joint_beam_uav3: { category: "限额联合搜索", module: "src/lowalt6g/phase11_algorithms.py", observation: "当前机队候选位置和共享网络状态。", trigger: "在固定搜索预算内执行有限联合规划。", constraints: "候选与计算预算、机队共享容量、飞行、电量和返航。", computeLabel: "协调计算累计 · ms / 运行" },
};

function record(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
}

function path(value: unknown, ...keys: string[]): unknown {
  let current = value;
  for (const key of keys) current = record(current)[key];
  return current;
}

function numeric(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function estimate(value: unknown): ResearchEstimate {
  const stats = record(value);
  const interval = stats.mean_ci95_t ?? stats.ci95_t;
  const ci95 = Array.isArray(interval) && interval.length === 2
    ? [numeric(interval[0]), numeric(interval[1])] as [number | null, number | null]
    : null;
  const low = ci95?.[0] ?? null;
  const high = ci95?.[1] ?? null;
  return {
    mean: numeric(stats.mean ?? stats.mean_difference),
    sampleSd: numeric(stats.sample_sd ?? stats.sample_sd_difference),
    ci95: low !== null && high !== null ? [low, high] : null,
    n: numeric(stats.n ?? stats.paired_n),
  };
}

function mean(value: unknown): number | null {
  return numeric(record(value).mean);
}

function recovery(
  successes: unknown,
  total: unknown,
  failures: unknown,
  successfulMean: unknown,
  allRunMean: unknown,
): ResearchRecovery {
  return {
    successes: numeric(successes),
    total: numeric(total),
    failures: numeric(failures),
    successfulMeanSeconds: mean(successfulMean),
    allRunCensorMeanSeconds: mean(allRunMean),
  };
}

function getStrategyMap(phase: HistoricalResearchPhaseId, scene: JsonRecord): JsonRecord {
  if (phase === "phase5") return record(path(scene, "aggregate"));
  if (phase === "phase8") return record(path(scene, "all_strategy_and_variant_summaries"));
  if (phase === "phase9") return record(path(scene, "strategy_summaries"));
  return record(path(scene, "policies"));
}

function makeStrategy(phase: HistoricalResearchPhaseId, id: string, rawValue: unknown): ResearchStrategy {
  const item = record(rawValue);
  const metrics = record(item.metrics);
  const latency = record(
    phase === "phase5" ? item.latency_conditioned_on_success
      : phase === "phase8" ? item.latency_conditioned_on_success
        : phase === "phase9" ? item.conditional_latency
          : metrics.conditional_latency_summary,
  );
  let firstRecovery: ResearchRecovery;
  let sustainedRecovery: ResearchRecovery;

  if (phase === "phase5") {
    const first = record(item.network_recovery);
    const sustained = record(item.sustained_network_recovery_30s);
    firstRecovery = recovery(first.recovered_runs, first.recovered_runs === undefined ? null : Number(first.recovered_runs) + Number(first.unrecovered_runs ?? 0), first.unrecovered_runs, first.recovered_only_time_s, first.recovery_or_censoring_time_s);
    sustainedRecovery = recovery(sustained.recovered_runs, sustained.recovered_runs === undefined ? null : Number(sustained.recovered_runs) + Number(sustained.unrecovered_runs ?? 0), sustained.unrecovered_runs, null, null);
  } else if (phase === "phase8") {
    const first = record(item.recovery_time);
    const sustained = record(item.sustained_30s);
    firstRecovery = recovery(first.successes, first.total, first.unrecovered, first.recovered_only_s, metrics.network_recovery_or_censoring_time_s);
    sustainedRecovery = recovery(sustained.successes, sustained.total, sustained.failures, sustained.recovered_only_start_time_s, null);
  } else if (phase === "phase9") {
    const first = record(item.first_full_recovery);
    const sustained = record(item.sustained_30s_recovery);
    firstRecovery = recovery(first.successes, first.total, first.unrecovered, first.successful_run_time_s, first.censored_time_mean_s);
    sustainedRecovery = recovery(sustained.successes, sustained.total, sustained.failures, sustained.successful_run_start_time_s, null);
  } else if (phase === "phase10") {
    const first = record(metrics.first_full_recovery_success);
    const sustained = record(metrics.sustained_30s_recovery_success);
    firstRecovery = recovery(first.success_count, first.total_count, numeric(first.total_count) === null || numeric(first.success_count) === null ? null : Number(first.total_count) - Number(first.success_count), metrics.first_full_recovery_time_s_successful_runs, metrics.first_full_recovery_or_censor_time_s);
    sustainedRecovery = recovery(sustained.success_count, sustained.total_count, numeric(sustained.total_count) === null || numeric(sustained.success_count) === null ? null : Number(sustained.total_count) - Number(sustained.success_count), metrics.sustained_30s_recovery_time_s_successful_runs, null);
  } else {
    const first = record(item.recovery);
    firstRecovery = recovery(first.first_full_successes, first.first_full_total, first.first_full_unrecovered, first.first_full_time_given_success, first.all_run_first_full_or_censor);
    sustainedRecovery = recovery(first.sustained_30s_successes, first.sustained_30s_total, first.sustained_30s_unrecovered, first.sustained_time_given_success, null);
  }

  const energyKey = phase === "phase10" || phase === "phase11" ? "uav_energy_total_wh" : "drone_energy_consumed_wh";
  const computeKey = phase === "phase5" ? "controller_observe_total_ms"
    : phase === "phase10" || phase === "phase11" ? "coordination_compute_total_ms"
      : "algorithm_decision_total_ms";
  const latencyMean = numeric(latency.pooled_average_ms ?? latency.pooled_mean_ms ?? latency.mean_ms ?? latency.mean_of_seed_means_ms ?? mean(metrics.average_latency_ms));
  const latencyP95 = numeric(latency.pooled_p95_ms ?? latency.pooled_p95_ms_nearest_rank ?? latency.p95_ms_nearest_rank ?? latency.mean_of_seed_p95_ms ?? mean(metrics.p95_latency_ms));
  let latencySamples = numeric(latency.pooled_successful_user_time_samples ?? latency.successful_user_time_sample_count ?? latency.pooled_connected_user_time_samples);
  if (phase === "phase10" && latencySamples === null) latencySamples = mean(metrics.latency_sample_count);
  if (phase === "phase11") {
    const sampleCounts = record(item.latency_sample_counts_by_seed);
    const countValues = Object.values(sampleCounts).map(numeric).filter((value): value is number => value !== null);
    if (countValues.length) latencySamples = countValues.reduce((sum, value) => sum + value, 0);
  }
  const detail = STRATEGY_DETAILS[id] ?? {
    category: "确定性机制消融变体",
    module: phase === "phase8" ? "src/lowalt6g/phase8_experiments.py" : "对应阶段实验配置与策略模块",
    observation: "沿用所对照正式策略的可观测状态。",
    trigger: "该变体按对应实验协议仅改变指定机制。",
    constraints: "仿真执行层安全约束保持开启；具体差异见阶段实验配置。",
    computeLabel: phase === "phase5" ? "控制器观测累计 · ms / 运行" : "算法计算累计 · ms / 运行",
  };

  return {
    id,
    label: STRATEGY_NAMES[id] ?? id.replaceAll("_", " "),
    ...detail,
    rescueService: estimate(metrics.rescue_user_service_success_rate),
    connection: estimate(metrics.user_connection_success_rate),
    firstRecovery,
    sustainedRecovery,
    energyWh: estimate(metrics[energyKey]),
    energyPerRescueHour: estimate(metrics.drone_energy_wh_per_rescue_user_hour ?? metrics.energy_wh_per_uav_rescue_user_hour),
    conditionalMeanLatencyMs: latencyMean,
    conditionalP95LatencyMs: latencyP95,
    latencySamples,
    computeTotalMs: estimate(metrics[computeKey]),
  };
}

function pairedDifference(
  phase: HistoricalResearchPhaseId,
  artifact: JsonRecord,
  scene: JsonRecord,
  sceneId: ResearchSceneId,
  selectedId: string,
  baselineId: string,
): ResearchPairDifference {
  const unavailable = (note: string): ResearchPairDifference => ({
    available: false,
    selectedId,
    baselineId,
    n: null,
    meanDifference: null,
    ci95: null,
    adjustedP: null,
    rawP: null,
    effectSize: null,
    note,
  });
  const flip = (entry: JsonRecord, inverted: boolean): ResearchPairDifference => {
    const interval = entry.ci95_t ?? entry.mean_ci95_t;
    const ci = Array.isArray(interval) && interval.length === 2 ? [numeric(interval[0]), numeric(interval[1])] : null;
    const low = ci?.[0] ?? null;
    const high = ci?.[1] ?? null;
    const sign = inverted ? -1 : 1;
    return {
      available: true,
      selectedId,
      baselineId,
      n: numeric(entry.paired_n ?? entry.n ?? entry.paired_seed_count),
      meanDifference: numeric(entry.mean_difference ?? entry.mean) === null ? null : sign * Number(entry.mean_difference ?? entry.mean),
      ci95: low !== null && high !== null ? inverted ? [-high, -low] : [low, high] : null,
      adjustedP: numeric(entry.p_holm_adjusted),
      rawP: numeric(entry.p_exact_two_sided),
      effectSize: numeric(entry.cohen_dz),
      note: "差值方向为所选策略 − 基线；来自已保存的同种子配对统计。",
    };
  };

  if (phase === "phase5") {
    const key = `${selectedId}_minus_${baselineId}`;
    const entry = record(path(scene, "paired_differences", key, "rescue_user_service_success_rate"));
    return Object.keys(entry).length ? flip(entry, false) : unavailable("该阶段未保存所选策略与基线的救援率配对差值。");
  }

  if (phase === "phase8" || phase === "phase9") {
    const tests = Array.isArray(artifact.paired_tests) ? artifact.paired_tests.map(record) : [];
    const entries = tests.filter((entry) => entry.scenario_id === sceneId && entry.metric === "rescue_user_service_success_rate");
    // Phase 9 stores the event-driven policy as the short token "E" in its
    // comparison field; keep the public strategy ID stable in the UI.
    const comparisonToken = (id: string) => phase === "phase9" && id === "E_event_driven_rescue_recovery" ? "E" : id;
    const selectedToken = comparisonToken(selectedId);
    const baselineToken = comparisonToken(baselineId);
    const direct = entries.find((entry) => entry.comparison === `${selectedToken}_minus_${baselineToken}`);
    if (direct) return flip(direct, false);
    const inverse = entries.find((entry) => entry.comparison === `${baselineToken}_minus_${selectedToken}`);
    return inverse ? flip(inverse, true) : unavailable("本阶段没有保存这组策略对照；不会从汇总均值推导配对显著性。");
  }

  const pairMap = record(scene.paired_comparisons);
  for (const item of Object.values(pairMap).map(record)) {
    const left = String(item.left_strategy ?? item.left_policy ?? "");
    const right = String(item.right_strategy ?? item.right_policy ?? "");
    const metrics = record(item.metrics);
    const metric = record(metrics.rescue_user_service_success_rate);
    if (!Object.keys(metric).length) continue;
    if (left === selectedId && right === baselineId) return flip({ ...metric, paired_seed_count: item.paired_seed_count }, false);
    if (left === baselineId && right === selectedId) return flip({ ...metric, paired_seed_count: item.paired_seed_count }, true);
  }
  return unavailable("本阶段没有保存这组策略对照；不会从汇总均值推导配对显著性。");
}

function methodDescription(phase: HistoricalResearchPhaseId, artifact: JsonRecord): string {
  if (phase === "phase5") return "按种子汇总均值及 Student-t 95% 区间；恢复比例使用 Wilson 区间。未恢复运行保留在分母。";
  const source = phase === "phase8" ? record(artifact.multiple_testing)
    : record(artifact.statistical_method ?? artifact.statistics);
  const values = Object.entries(source).filter(([, value]) => typeof value === "string");
  if (values.length) return values.map(([key, value]) => `${key}: ${String(value)}`).join("；");
  return "此阶段方法说明未包含在当前汇总字段中；请参阅对应阶段报告。界面不重算统计量。";
}

export function normalizeResearchArtifact(
  envelope: ResearchArtifactEnvelope,
  phase: HistoricalResearchPhaseId,
  sceneId: ResearchSceneId,
  selectedId?: string,
  baselineId?: string,
): ResearchDataset {
  const artifact = record(envelope.artifact);
  const scene = record(path(artifact, "scenarios", sceneId));
  const strategyMap = getStrategyMap(phase, scene);
  const strategies = Object.entries(strategyMap).map(([id, value]) => makeStrategy(phase, id, value));
  const preferredStrategy = phase === "phase5" || phase === "phase8" ? "D_lexicographic_rescue_priority"
    : phase === "phase9" ? "E_event_driven_rescue_recovery"
      : "G_centralized_coordination_uav3";
  const selected = selectedId && strategies.some((item) => item.id === selectedId)
    ? selectedId
    : strategies.some((item) => item.id === preferredStrategy) ? preferredStrategy : strategies[0]?.id ?? "";
  const suggestedBaseline = phase === "phase10" || phase === "phase11"
    ? "Bprime_static_grid_shared_safety_uav1"
    : phase === "phase9" ? "Bprime_static_grid_shared_safety"
      : "B_phase1_static_grid";
  const baseline = baselineId && strategies.some((item) => item.id === baselineId) ? baselineId : suggestedBaseline;
  const seedCount = numeric(scene.validation_seed_count ?? scene.seed_count ?? artifact.seed_count_total) ?? 0;
  const allSceneSeeds = phase === "phase5"
    ? Object.values(record(artifact.scenarios)).reduce<number>((sum, item) => sum + (numeric(record(item).validation_seed_count) ?? 0), 0)
    : numeric(artifact.seed_count_total) ?? seedCount;
  const strategyRunCount = numeric(artifact.policy_run_count) ?? (allSceneSeeds * strategies.length);
  const paired = pairedDifference(phase, artifact, scene, sceneId, selected, baseline);
  const dataModel = phase === "phase10" || phase === "phase11"
    ? "救援服务率为仿真期间救援用户—采样时刻服务比例；恢复成功数按每场景全部留出种子计。"
    : "救援服务率为仿真期间救援用户—采样时刻服务比例；恢复成功数按每场景全部留出种子计。";
  const latencyDefinition = "时延仅按该策略实际成功连接的用户—时刻样本统计。样本集合可能不同，条件均值和 P95 不能解释为相同用户集合上的配对改善。";
  return {
    phase,
    phaseLabel: PHASE_LABELS[phase],
    scenarioId: sceneId,
    scenarioLabel: SCENE_LABELS[sceneId],
    experimentRole: envelope.experiment_role || String(artifact.experiment_role ?? artifact.phase ?? "冻结实验汇总"),
    sourcePath: envelope.artifact_path || SOURCE_PATHS[phase],
    sourceSha256: envelope.artifact_sha256,
    seedCount,
    runCount: strategyRunCount,
    strategyCount: strategies.length,
    statisticalMethod: methodDescription(phase, artifact),
    metricDefinition: dataModel,
    latencyDefinition,
    compareNote: paired.note,
    strategies,
    pairDifference: paired,
    multiUavReplayAvailable: false,
  };
}

export function isOfficialPhase8Strategy(id: string): boolean {
  return [
    "A_no_recovery",
    "B_phase1_static_grid",
    "Bprime_static_grid_shared_safety",
    "C_rolling_horizon_mpc",
    "D_lexicographic_rescue_priority",
  ].includes(id);
}
