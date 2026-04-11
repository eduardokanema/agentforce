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

export interface ExecutionProfile {
  agent?: string | null;
  model?: string | null;
  thinking?: string | null;
}

export interface PlanningProfileSet {
  planner?: ExecutionProfile | null;
  critic_technical?: ExecutionProfile | null;
  critic_practical?: ExecutionProfile | null;
  resolver?: ExecutionProfile | null;
}

export interface ExecutionConfig {
  worker?: ExecutionProfile | null;
  reviewer?: ExecutionProfile | null;
}

export interface ExecutionMetadata {
  defaults: ExecutionConfig;
  mixed_roles: Array<'worker' | 'reviewer'>;
  task_overrides: {
    worker: number;
    reviewer: number;
  };
  tasks?: Record<string, ExecutionConfig>;
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
  execution?: ExecutionConfig | null;
}

export interface Caps {
  max_tokens_per_task: number;
  max_retries_global: number;
  max_retries_per_task: number;
  max_wall_time_minutes: number;
  max_human_interventions: number;
  max_cost_usd?: number | null;
  max_concurrent_workers: number;
  review?: string;
}

export interface MissionSpec {
  name: string;
  goal: string;
  definition_of_done: string[];
  tasks: TaskSpec[];
  caps: Caps;
  execution_defaults?: ExecutionConfig | null;
  working_dir?: string | null;
  project_memory_file?: string | null;
}

export interface DraftTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface MissionDraft {
  id: string;
  revision: number;
  status: string;
  draft_spec: MissionSpec;
  turns: DraftTurn[];
  validation: Record<string, unknown>;
  activity_log: unknown[];
  approved_models: string[];
  workspace_paths: string[];
  companion_profile: Record<string, unknown>;
  draft_notes: Record<string, unknown>[];
  plan_runs?: PlanRun[];
  plan_versions?: PlanVersion[];
  planning_summary?: PlanningSummary | null;
  preflight_status?: string;
  preflight_questions?: PreflightQuestion[];
  preflight_answers?: Record<string, PreflightAnswer>;
}

export interface PlanStep {
  name: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  message?: string;
  summary?: string;
  tokens_in?: number;
  tokens_out?: number;
  cost_usd?: number;
  metadata?: Record<string, unknown>;
}

export interface PlanRun {
  id: string;
  draft_id: string;
  base_revision: number;
  head_revision_seen: number;
  status: string;
  trigger_kind: string;
  trigger_message: string;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  stale?: boolean;
  current_step?: string | null;
  steps: PlanStep[];
  result_version_id?: string | null;
  promoted_version_id?: string | null;
  launched_mission_id?: string | null;
  error_message?: string;
  changelog?: string[];
  tokens_in?: number;
  tokens_out?: number;
  cost_usd?: number;
}

export interface PlanVersion {
  id: string;
  draft_id: string;
  source_run_id: string;
  revision_base: number;
  created_at: string;
  draft_spec_snapshot: MissionSpec;
  changelog: string[];
  validation: Record<string, unknown>;
  launched_mission_id?: string | null;
}

export interface PlanningSummary {
  latest_plan_version_id?: string;
  changelog?: string[];
  validation?: Record<string, unknown>;
}

export interface PreflightQuestion {
  id: string;
  prompt: string;
  options: string[];
  reason?: string;
  allow_custom?: boolean;
}

export interface PreflightAnswer {
  selected_option?: string;
  custom_answer?: string;
}

export interface MissionPlanningSummary {
  draft_id: string;
  source_run_id: string;
  source_version_id: string;
  planning_cost_usd: number;
  planning_tokens_in: number;
  planning_tokens_out: number;
  changelog: string[];
  created_at: string;
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
  human_intervention_kind?: string;
  human_intervention_options?: HumanInterventionOption[];
  human_intervention_context?: HumanInterventionContext;
  error_message?: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface HumanInterventionOption {
  id: string;
  label: string;
  description?: string;
  effect?: string;
}

export interface HumanInterventionContext {
  type?: string;
  summary?: string;
  risk?: string;
  proposed_action?: string;
  targets?: string[];
  action_key?: string;
  [key: string]: unknown;
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
  active_wall_time_seconds?: number;
  event_log?: EventLogEntry[];
  completed_at?: string | null;
  finished_at?: string | null;
  caps_hit?: Record<string, string>;
  execution_defaults?: ExecutionConfig | null;
  execution?: ExecutionMetadata | null;
  destructive_action_allow_rules?: Record<string, HumanInterventionContext>;
  working_dir?: string;
  worker_agent?: string;
  worker_model?: string;
  daemon_pid?: number | null;
  daemon_started_at?: string | null;
  source_plan_version_id?: string | null;
  source_plan_run_id?: string | null;
  source_draft_id?: string | null;
  planning?: MissionPlanningSummary | null;
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

export type MissionSummaryStatus = 'active' | 'in_progress' | 'complete' | 'completed' | 'review_approved' | 'failed' | 'needs_human' | 'draft' | 'finished';

export interface DraftSummary {
  id: string;
  name: string;
  goal: string;
  status: 'draft';
  created_at: string;
  updated_at: string;
}

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
  execution?: ExecutionMetadata | null;
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
  provider_id?: string;
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

export interface DaemonJobInfo {
  job_id: string;
  job_type: 'mission' | 'plan_run';
  mission_id?: string;
  state: 'queued' | 'running';
  enqueued_at?: string;
}

export interface DaemonStatus {
  running: boolean;
  queue: DaemonJobInfo[];
  active: DaemonJobInfo[];
  last_heartbeat: string | null;
}
