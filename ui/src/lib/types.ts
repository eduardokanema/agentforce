export const TASK_STATUSES = [
  'pending',
  'spec_writing',
  'tests_written',
  'in_progress',
  'completed',
  'reviewing',
  'review_approved',
  'review_rejected',
  'needs_human',
  'retry',
  'failed',
  'blocked',
] as const;

export type TaskStatus = (typeof TASK_STATUSES)[number];

export interface TDDSpec {
  test_file?: string | null;
  test_command?: string | null;
  tests_must_pass: boolean;
  coverage_threshold?: number | null;
}

export interface TaskSpec {
  id: string;
  title: string;
  description: string;
  acceptance_criteria: string[];
  tdd?: TDDSpec | null;
  dependencies: string[];
  working_dir?: string | null;
  max_retries: number;
  output_artifacts: string[];
}

export interface Caps {
  max_tokens_per_task: number;
  max_retries_global: number;
  max_retries_per_task: number;
  max_wall_time_minutes: number;
  max_human_interventions: number;
  max_cost_usd?: number | null;
  max_concurrent_workers: number;
}

export interface MissionSpec {
  name: string;
  goal: string;
  definition_of_done: string[];
  tasks: TaskSpec[];
  caps: Caps;
  working_dir?: string | null;
  project_memory_file?: string | null;
}

export interface TaskState {
  task_id: string;
  status: TaskStatus;
  retries: number;
  retry_count?: number;
  review_score: number;
  human_intervention_needed: boolean;
  last_updated: string;
  tokens_in?: number;
  tokens_out?: number;
  cost_usd?: number;
  spec_summary?: string;
  worker_output?: string;
  review_feedback?: string;
  blocking_issues?: string[];
  human_intervention_message?: string;
  error_message?: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface EventLogEntry {
  timestamp: string;
  event_type: string;
  task_id?: string | null;
  details: string;
}

export interface MissionState {
  mission_id: string;
  spec: MissionSpec;
  task_states: Record<string, TaskState>;
  started_at: string;
  total_retries: number;
  total_human_interventions: number;
  total_tokens_used: number;
  estimated_cost_usd: number;
  tokens_in?: number;
  tokens_out?: number;
  cost_usd?: number;
  event_log?: EventLogEntry[];
  completed_at?: string | null;
  caps_hit?: Record<string, string>;
  working_dir?: string;
  worker_agent?: string;
  worker_model?: string;
  daemon_pid?: number | null;
  daemon_started_at?: string | null;
}

export interface TelemetryMissionByCost {
  mission_id: string;
  name: string;
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
  duration: string;
  retries: number;
}

export interface TelemetryTaskByCost {
  mission_id: string;
  task_id: string;
  task: string;
  mission: string;
  model: string;
  cost_usd: number;
  retries: number;
}

export interface TelemetryCostPoint {
  mission_name: string;
  cumulative_cost: number;
}

export interface TelemetryData {
  total_missions: number;
  total_tasks: number;
  total_cost_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
  missions_by_cost: TelemetryMissionByCost[];
  tasks_by_cost: TelemetryTaskByCost[];
  retry_distribution: Record<string, number>;
  cost_over_time: TelemetryCostPoint[];
}

export type MissionSummaryStatus = 'active' | 'in_progress' | 'complete' | 'completed' | 'review_approved' | 'failed' | 'needs_human';

export interface MissionSummary {
  mission_id: string;
  name: string;
  status: MissionSummaryStatus;
  done_tasks: number;
  total_tasks: number;
  pct: number;
  duration: string;
  worker_agent: string;
  worker_model: string;
  started_at: string;
  cost_usd: number;
  retries?: number;
  tokens_in?: number;
  tokens_out?: number;
  workspace?: string;
  models?: string[];
  active_task_title?: string;
}

export interface Connector {
  name: string;
  display_name: string;
  active: boolean;
  last_configured?: string;
  token_last4?: string;
}

export interface ProviderModel {
  id: string;
  name: string;
  cost_per_1k_input: number;
  cost_per_1k_output: number;
  latency_label: string;
}

export interface Provider {
  id: string;
  display_name: string;
  description?: string;
  type?: 'api' | 'cli';
  binary?: string;
  requires_key?: boolean;
  active: boolean;
  is_default?: boolean;
  last_configured?: string | null;
  enabled_models: string[] | null;
  default_model?: string | null;
  all_models: ProviderModel[];
}

export interface FilesystemEntry {
  name: string;
  path: string;
  is_dir: boolean;
}

export interface FilesystemListing {
  path: string;
  entries: FilesystemEntry[];
  parent: string | null;
}

export interface DefaultCaps {
  max_concurrent_workers: number;
  max_retries_per_task: number;
  max_wall_time_minutes: number;
  max_cost_usd: number;
}

export interface AppConfig {
  filesystem: {
    allowed_base_paths: string[];
  };
  default_caps: DefaultCaps;
}

export interface Model {
  id: string;
  name: string;
  provider: string;
  cost_per_1k_input: number;
  cost_per_1k_output: number;
  latency_label: string;
}

export interface AgentInfo {
  id: string;
  display_name: string;
  binary: string;
  available: boolean;
  is_default: boolean;
  model: string | null;
}

export interface TaskAttempt {
  attempt_number: number;
  output: string;
  review?: string | null;
  score?: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  cost_usd?: number | null;
}

type Assert<T extends true> = T;
type IsAssignable<From, To> = [From] extends [To] ? true : false;

type SerializedTaskState = {
  task_id: string;
  status: TaskStatus;
  retries: number;
  review_score: number;
  human_intervention_needed: boolean;
  last_updated: string;
};

type SerializedMissionState = {
  mission_id: string;
  spec: MissionSpec;
  task_states: Record<string, TaskState>;
  started_at: string;
  total_retries: number;
  total_human_interventions: number;
  total_tokens_used: number;
  estimated_cost_usd: number;
};

type _taskStateMatchesSerializedShape = Assert<IsAssignable<SerializedTaskState, TaskState>>;
type _missionStateMatchesSerializedShape = Assert<IsAssignable<SerializedMissionState, MissionState>>;
