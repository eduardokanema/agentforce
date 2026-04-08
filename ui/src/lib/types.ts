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
  review_score: number;
  human_intervention_needed: boolean;
  last_updated: string;
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
  event_log?: EventLogEntry[];
  completed_at?: string | null;
  caps_hit?: Record<string, string>;
  working_dir?: string;
  worker_agent?: string;
  worker_model?: string;
  daemon_pid?: number | null;
  daemon_started_at?: string | null;
}

export type MissionSummaryStatus = 'active' | 'complete' | 'failed' | 'needs_human';

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
