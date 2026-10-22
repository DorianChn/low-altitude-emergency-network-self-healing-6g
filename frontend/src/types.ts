export const STRATEGIES = [
  "A_no_recovery",
  "B_phase1_static_grid",
  "C_rolling_horizon_mpc",
] as const;

export type StrategyId = (typeof STRATEGIES)[number];

export interface ReplayEvent {
  time_s: number;
  event_type: string;
  [key: string]: unknown;
}

export interface UserState {
  id: string;
  group: "normal" | "rescue";
  priority: number;
  x_km: number;
  y_km: number;
  demand_mbps: number;
  covered: boolean;
  connected: boolean;
  path_kind: string | null;
  serving_station_id: string | null;
  latency_ms: number | null;
}

export interface StationState {
  id: string;
  x_km: number;
  y_km: number;
  healthy: boolean;
  capacity_mbps: number;
  coverage_radius_km: number;
}

export interface DroneState {
  id: string;
  x_km: number;
  y_km: number;
  active: boolean;
  battery_wh: number;
  capacity_mbps: number;
  access_radius_km: number;
  backhaul_radius_km: number;
  backhaul_available: boolean;
}

export interface StateSnapshot {
  time_s: number;
  traffic_multiplier: number;
  stations: StationState[];
  drone: DroneState;
  users: UserState[];
  links: Array<{ source_id: string; target_id: string; kind: string; user_id: string }>;
  resource_utilization: Record<string, number>;
  decision: ReplayEvent;
  diagnosis: {
    failed_station_ids: string[];
    disconnected_user_ids: string[];
    uncovered_user_ids: string[];
    capacity_blocked_user_ids: string[];
    disconnected_rescue_ids: string[];
    congested_resource_ids: string[];
    drone_backhaul_available: boolean;
  };
}

export interface ReplayMetrics {
  network_coverage_rate: number | null;
  user_connection_success_rate: number | null;
  rescue_user_service_success_rate: number | null;
  network_recovery_time_s: number | null;
  average_latency_ms: number | null;
  p95_latency_ms: number | null;
  latency_sample_count: number;
  drone_energy_consumed_wh: number;
  drone_battery_remaining_wh: number;
  drone_battery_minimum_wh: number;
  algorithm_decision_count: number;
  algorithm_decision_total_ms: number;
  algorithm_decision_mean_ms: number;
  algorithm_decision_p95_ms: number | null;
  replan_count: number;
  infeasible_decision_count: number;
  infeasible_decision_reasons: Record<string, number>;
  evaluation_ticks: number;
  user_count: number;
  rescue_user_count: number;
  [key: string]: number | string | null | Record<string, number>;
}

export interface ReplayRun {
  strategy_id: StrategyId;
  strategy_name: string;
  metrics: ReplayMetrics;
  event_log: ReplayEvent[];
  state_snapshots: StateSnapshot[];
}

export interface ReplayArtifact {
  schema_version: string;
  model_scope: string;
  mode: "precomputed_offline_replay";
  live_stream: false;
  seed: number;
  world_trace_sha256: string;
  time_step_s: number;
  duration_s: number;
  configuration: {
    base: {
      city_width_km: number;
      city_height_km: number;
      normal_user_count: number;
      rescue_user_count: number;
      drone: Record<string, number | string>;
      stations: Array<Record<string, number | string | boolean>>;
    };
    dynamic: {
      events: ReplayEvent[];
      mobility_axis_max_km_per_tick: number;
      battery_capacity_wh: number;
      initial_battery_wh: number;
      reserve_wh: number;
      movement_wh_per_km: number;
      hover_power_w: number;
      relay_power_w: number;
      decision_interval_s: number;
      prediction_horizon_steps: number;
      beam_width: number;
      congestion_threshold: number;
      rescue_service_weight: number;
      connection_weight: number;
      recovery_bonus: number;
      latency_penalty_weight: number;
      energy_penalty_weight: number;
      rescue_progress_weight: number;
    };
  };
  environment_events: ReplayEvent[];
  strategies: Record<StrategyId, ReplayRun>;
}

export interface MetricSummary {
  mean: number | null;
  sample_sd?: number | null;
  n?: number;
}

export interface StrategyAggregate {
  metrics: Record<string, MetricSummary>;
  network_recovery: {
    recovered_runs: number;
    unrecovered_runs: number;
    success_rate: number;
    recovered_only_time_s: MetricSummary;
  };
  latency_conditioned_on_success: {
    pooled_average_ms: number | null;
    pooled_p95_ms: number | null;
    pooled_successful_user_time_samples: number;
  };
}

export interface BenchmarkArtifact {
  model_scope: string;
  strategy_order: StrategyId[];
  reproducibility: {
    seed_count: number;
    seeds: number[];
    effective_config_sha256: string;
    paired_world_traces: boolean;
  };
  statistical_notes: string[];
  aggregate: Record<StrategyId, StrategyAggregate>;
}

export interface ApiHealth {
  status: string;
  mode: string;
  live_stream: false;
  model_scope: string;
  phase2_benchmark_available: boolean;
  seed_2026_replay_available: boolean;
  phase5_validation_available?: boolean;
}

export const PHASE5_SCENARIOS = [
  "severe_persistent_faults",
  "dynamic_failures",
  "high_mobility_rescue",
  "high_load_backhaul_limit",
] as const;

export type Phase5ScenarioId = (typeof PHASE5_SCENARIOS)[number];

export const PHASE5_STRATEGIES = [
  "A_no_recovery",
  "B_phase1_static_grid",
  "Bprime_static_grid_shared_safety",
  "C_rolling_horizon_mpc",
  "D_lexicographic_rescue_priority",
] as const;

export type Phase5StrategyId = (typeof PHASE5_STRATEGIES)[number];

export interface Phase5Estimate {
  mean: number | null;
  median?: number | null;
  sample_sd?: number | null;
  mean_ci95_t?: [number, number] | null;
  n?: number;
  min?: number | null;
  max?: number | null;
  ci95_wilson?: [number, number] | null;
}

export interface Phase5RecoverySummary {
  recovered_only_time_s: Phase5Estimate;
  recovery_or_censoring_time_s?: Phase5Estimate;
  recovered_runs: number;
  unrecovered_runs: number;
  success_rate: number;
}

export interface Phase5StrategyAggregate {
  seed_count: number;
  metrics: Record<string, Phase5Estimate>;
  network_recovery: Phase5RecoverySummary;
  sustained_network_recovery_30s: Phase5RecoverySummary;
  latency_conditioned_on_success: {
    pooled_average_ms: number | null;
    pooled_p95_ms: number | null;
    pooled_successful_user_time_samples: number;
  };
}

export interface Phase5ScenarioSummary {
  aggregate: Record<Phase5StrategyId, Phase5StrategyAggregate>;
  effective_config_sha256: string;
  paired_differences: Record<string, Record<string, Phase5Estimate>>;
  raw_seed_results: string;
  validation_seed_count: number;
  validation_seeds: number[];
}

export interface Phase5BenchmarkArtifact {
  schema_version: string;
  phase: string;
  model_scope: string;
  strategy_order: Phase5StrategyId[];
  frozen_manifest_sha256: string;
  statistical_scope: string;
  scenarios: Record<Phase5ScenarioId, Phase5ScenarioSummary>;
}
