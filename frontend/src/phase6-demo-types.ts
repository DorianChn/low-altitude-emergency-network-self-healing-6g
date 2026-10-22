import type {
  Phase5ScenarioId,
  Phase5StrategyAggregate,
  Phase5StrategyId,
  ReplayArtifact,
  ReplayEvent,
  StateSnapshot,
} from "./types";

export interface Phase6DemoScenarioIndex {
  label: string;
  artifact: string;
  seed: number;
  validation_seed_count: number;
  strategy_count_in_full_validation: number;
  duration_s: number;
  time_step_s: number;
  world_trace_sha256: string;
  effective_config_sha256: string;
  source_validation_file: string;
}

export interface Phase6DemoIndex {
  schema_version: string;
  mode: "precomputed_offline_replay";
  live_stream: false;
  model_scope: string;
  source_phase: "phase5_frozen_validation";
  frozen_manifest_sha256: string;
  scenario_order: Phase5ScenarioId[];
  seed_selection_rule: string;
  scenarios: Record<Phase5ScenarioId, Phase6DemoScenarioIndex>;
}

export interface Phase6DemoRun {
  strategy_id: Phase5StrategyId;
  strategy_name: string;
  metrics: Record<string, number | string | null>;
  event_log: ReplayEvent[];
  state_snapshots: StateSnapshot[];
}

export interface Phase6DemoValidation {
  scenario_id: Phase5ScenarioId;
  validation_seed: number;
  validation_seed_count: number;
  strategy_run_count_in_full_validation: number;
  seed_selection_rule: string;
  frozen_manifest_sha256: string;
  source_validation_file: string;
  source_validation_file_sha256: string;
  source_seed_record_sha256: string;
  world_trace_sha256: string;
  effective_config_sha256: string;
  frame_capture: string;
  reconciliation: Record<string, boolean>;
}

export interface Phase6DemoArtifact {
  schema_version: string;
  model_scope: string;
  mode: "precomputed_offline_replay";
  live_stream: false;
  scenario_id: Phase5ScenarioId;
  scenario_label: string;
  seed: number;
  world_trace_sha256: string;
  time_step_s: number;
  duration_s: number;
  configuration: ReplayArtifact["configuration"];
  environment_events: ReplayEvent[];
  strategies: Record<Phase5StrategyId, Phase6DemoRun>;
  validation: Phase6DemoValidation;
  strategy_aggregates: Record<Phase5StrategyId, Phase5StrategyAggregate>;
}
