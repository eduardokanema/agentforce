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

export type DraftKind = 'simple_plan' | 'black_hole';

export interface MissionDraft {
  id: string;
  revision: number;
  status: string;
  draft_kind?: DraftKind;
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
  planning_follow_ups?: PlanningFollowUp[];
  repair_status?: string;
  repair_questions?: PreflightQuestion[];
  repair_answers?: Record<string, PreflightAnswer>;
  repair_issues?: RepairIssue[];
  repair_context?: RepairContext | null;
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
  retry_count?: number;
  retries?: number;
  max_retries?: number;
  human_intervention_needed?: boolean;
  human_intervention_message?: string;
  human_intervention_kind?: string;
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

export interface BlackHoleLoopLimits {
  max_loops: number;
  max_no_progress: number;
  function_line_limit?: number | null;
}

export interface BlackHoleGatePolicy {
  require_test_delta?: boolean;
  public_surface_policy?: string;
}

export interface BlackHoleConfig {
  mode: 'black_hole';
  objective: string;
  analyzer: string;
  scope?: string;
  global_acceptance?: string[];
  loop_limits: BlackHoleLoopLimits;
  gate_policy?: BlackHoleGatePolicy;
  docs_manifest_path?: string | null;
  notes?: string;
  profile_snapshot?: {
    planning_profiles?: PlanningProfileSet | null;
    execution_defaults?: ExecutionConfig | null;
  } | null;
}

export interface BlackHoleCampaign {
  id: string;
  draft_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  current_loop: number;
  max_loops: number;
  max_no_progress: number;
  no_progress_count: number;
  active_child_mission_id?: string | null;
  active_plan_run_id?: string | null;
  last_metric?: Record<string, unknown>;
  last_delta?: number;
  stop_reason?: string;
  config_snapshot?: Record<string, unknown>;
  tokens_in?: number;
  tokens_out?: number;
  cost_usd?: number;
}

export interface BlackHoleLoop {
  campaign_id: string;
  loop_no: number;
  status: string;
  created_at: string;
  completed_at?: string | null;
  candidate_id?: string;
  candidate_summary?: string;
  candidate_payload?: Record<string, unknown>;
  metric_before?: Record<string, unknown>;
  metric_after?: Record<string, unknown>;
  normalized_delta?: number;
  plan_run_id?: string | null;
  plan_version_id?: string | null;
  mission_id?: string | null;
  review_summary?: string;
  gate_reason?: string;
  tokens_in?: number;
  tokens_out?: number;
  cost_usd?: number;
}

export interface BlackHoleCampaignState {
  draft_id: string;
  draft_kind?: DraftKind;
  config?: BlackHoleConfig | null;
  campaign?: BlackHoleCampaign | null;
  loops: BlackHoleLoop[];
}

export interface PreflightQuestion {
  id: string;
  prompt: string;
  options: string[];
  reason?: string;
  allow_custom?: boolean;
  issue_ids?: string[];
  preview?: {
    before_text?: string;
    proposed_text?: string;
    why_required?: string;
  } | null;
}

export interface PreflightAnswer {
  selected_option?: string;
  custom_answer?: string;
}

export interface PlanningFollowUp {
  id: string;
  source: string;
  mode: string;
  status: string;
  prompt: string;
  reason?: string;
  question_id?: string;
  origin_run_id?: string;
  origin_version_id?: string;
  selected_option?: string;
  custom_answer?: string;
  generated_task_ids: string[];
  target_task_ids: string[];
}

export interface RepairIssue {
  issue_id: string;
  source: string;
  blocking: boolean;
  kind: string;
  task_id?: string | null;
  original_text?: string;
  reason?: string;
}

export interface RepairContext {
  repair_round?: number;
  max_rounds?: number;
  mode?: string | null;
  loop_no?: number | null;
  source_run_id?: string | null;
  source_version_id?: string | null;
  gate_reason?: string;
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
  draft_kind?: DraftKind;
  created_at: string;
  updated_at: string;
}

export interface MissionSummary {
  mission_id: string;
  name: string;
  status: MissionSummaryStatus;
  draft_kind?: DraftKind;
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
  provider_id?: string;
  supported_thinking?: string[];
  enabled_thinking?: string[];
  active?: boolean;
  enabled?: boolean;
  selectable?: boolean;
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

export interface LabsConfig {
  black_hole_enabled: boolean;
  [key: string]: unknown;
}

export const DEFAULT_LABS_CONFIG: LabsConfig = {
  black_hole_enabled: false,
};

export type ProjectMode = 'standard' | 'optimize';

export type ProjectStatus =
  | 'planning'
  | 'ready'
  | 'running'
  | 'blocked'
  | 'completed'
  | 'archived'
  | 'idle';

export type ProjectStage =
  | 'setup'
  | 'planning'
  | 'ready_to_launch'
  | 'executing'
  | 'blocked'
  | 'completed'
  | 'archived';

export type ProjectSection = 'overview' | 'plan' | 'mission' | 'history' | 'settings';

export type EvidenceStatus = 'ok' | 'warning' | 'error' | 'pending';

export interface ProjectEvidenceItem {
  kind: string;
  label: string;
  status: EvidenceStatus;
  summary: string;
  source_type?: string | null;
  source_id?: string | null;
  updated_at?: string | null;
}

export interface ProjectEvidenceSummary {
  status: EvidenceStatus;
  contract_summary?: string | null;
  verifier_summary?: string | null;
  artifact_summary?: string | null;
  stream_summary?: string | null;
  items: ProjectEvidenceItem[];
}

export interface ProjectCycleView {
  cycle_id: string;
  title: string;
  status: ProjectStatus;
  draft_id?: string | null;
  mission_id?: string | null;
  latest_plan_run_id?: string | null;
  latest_plan_version_id?: string | null;
  predecessor_cycle_id?: string | null;
  successor_cycle_id?: string | null;
  blocker?: string | null;
  next_action?: string | null;
  created_at: string;
  updated_at: string;
  evidence?: ProjectEvidenceSummary | null;
}

export interface ProjectSummaryView {
  project_id: string;
  name: string;
  repo_root: string;
  primary_working_directory?: string | null;
  workspace_count: number;
  goal?: string | null;
  planned_task_count: number;
  current_stage: ProjectStage;
  current_plan_id?: string | null;
  current_mission_id?: string | null;
  next_action_label?: string | null;
  mode: ProjectMode;
  status: ProjectStatus;
  active_cycle_id?: string | null;
  blocker?: string | null;
  next_action?: string | null;
  active_mission_id?: string | null;
  archived_at?: string | null;
  has_activity: boolean;
  updated_at: string;
  active_plan_count?: number;
  running_plan_count?: number;
  blocked_node_count?: number;
  related_project_ids?: string[];
}

export interface ProjectContextView {
  repo_root: string;
  primary_working_directory?: string | null;
  working_directories: string[];
  goal?: string | null;
  definition_of_done: string[];
  planned_task_count: number;
  task_titles: string[];
  mission_count: number;
}

export interface ProjectHarnessView {
  summary: ProjectSummaryView;
  context: ProjectContextView;
  cycles: ProjectCycleView[];
  active_cycle_id?: string | null;
  active_cycle?: ProjectCycleView | null;
  evidence: ProjectEvidenceSummary;
  docs_status: {
    implemented: string[];
    planned: string[];
  };
  policy_summary: {
    mode: ProjectMode;
    derived: boolean;
    optimize_available: boolean;
  };
  lifecycle: {
    archived: boolean;
    archived_at?: string | null;
    can_archive: boolean;
    can_unarchive: boolean;
    can_delete: boolean;
    can_edit: boolean;
    has_activity: boolean;
  };
  project?: ProjectRecordView;
  plans?: ProjectPlanSummaryView[];
  selected_plan_id?: string | null;
  selected_plan?: ProjectPlanDetailView | null;
  scheduler?: ProjectSchedulerState | null;
  history?: ProjectHistoryView | null;
}

export type ProjectGraphNodeRuntimeStatus =
  | 'draft'
  | 'ready'
  | 'queued'
  | 'running'
  | 'reviewing'
  | 'blocked'
  | 'completed'
  | 'failed';

export interface ProjectRecordView {
  project_id: string;
  name: string;
  repo_root: string;
  description?: string | null;
  related_project_ids: string[];
  settings: {
    working_directories?: string[];
    scheduler_overrides?: Record<string, number>;
    [key: string]: unknown;
  };
  archived_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectPlanNodeRuntimeView {
  status: ProjectGraphNodeRuntimeStatus;
  reason?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  scheduler_priority?: number | null;
}

export interface ProjectPlanNodeView {
  node_id: string;
  title: string;
  description: string;
  dependencies: string[];
  subtasks: string[];
  touch_scope: string[];
  outputs: string[];
  owner_project_id: string;
  merged_project_scope: string[];
  evidence: string[];
  working_directory?: string | null;
  runtime: ProjectPlanNodeRuntimeView;
}

export interface ProjectPlanVersionView {
  version_id: string;
  plan_id: string;
  project_id: string;
  name: string;
  objective: string;
  nodes: ProjectPlanNodeView[];
  merged_project_scope: string[];
  changelog: string[];
  planner_debug: Record<string, unknown>;
  launched_mission_run_id?: string | null;
  created_at: string;
}

export interface ProjectMissionNodeStateView {
  node_id: string;
  status: ProjectGraphNodeRuntimeStatus;
  reason?: string | null;
  task_id?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ProjectMissionRunView {
  mission_run_id: string;
  plan_id: string;
  plan_version_id: string;
  project_id: string;
  mission_id?: string | null;
  status: ProjectGraphNodeRuntimeStatus | string;
  node_states: ProjectMissionNodeStateView[];
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at: string;
}

export interface ProjectPlanSummaryView {
  plan_id: string;
  project_id: string;
  name: string;
  objective: string;
  status: ProjectStatus | 'draft';
  quick_task: boolean;
  node_count: number;
  selected_version_id?: string | null;
  active_mission_run_id?: string | null;
  mission_id?: string | null;
  merged_project_scope: string[];
  planner_debug: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  supersedes_plan_id?: string | null;
}

export interface ProjectPlanGraphView {
  plan_id: string;
  nodes: ProjectPlanNodeView[];
  selected_version_id?: string | null;
  active_mission_run_id?: string | null;
}

export interface ProjectPlanHistoryView {
  versions: ProjectPlanVersionView[];
  mission_runs: ProjectMissionRunView[];
  planner: Record<string, unknown>;
}

export interface ProjectPlanDetailView extends ProjectPlanSummaryView {
  graph: ProjectPlanGraphView;
  history: ProjectPlanHistoryView;
}

export interface ProjectSchedulerItemView {
  plan_id: string;
  plan_name: string;
  node_id: string;
  title: string;
  status: ProjectGraphNodeRuntimeStatus | string;
  scheduler_priority: number;
  owning_project_id: string;
  merged_project_scope: string[];
  conflict_reason?: string | null;
}

export interface ProjectSchedulerPlanView {
  plan_id: string;
  name: string;
  status: ProjectStatus | 'draft';
  ready_count: number;
  blocked_count: number;
  running_count: number;
  selected_version_id?: string | null;
  active_mission_run_id?: string | null;
  merged_project_scope: string[];
  updated_at: string;
}

export interface ProjectSchedulerState {
  project_id: string;
  updated_at: string;
  queue: ProjectSchedulerItemView[];
  blocked: ProjectSchedulerItemView[];
  running: ProjectSchedulerItemView[];
  plans: ProjectSchedulerPlanView[];
}

export interface ProjectHistoryView {
  plan_versions: ProjectPlanVersionView[];
  mission_runs: ProjectMissionRunView[];
}

export const PROJECTS_ROUTE = '/projects';
export const PLAN_ROUTE = '/plan';
export const MISSIONS_ROUTE = '/missions';
export const BLACK_HOLE_ROUTE = '/black-hole';

export function projectRoute(id: string): string {
  return projectOverviewRoute(id);
}

export function projectSectionRoute(id: string, section: ProjectSection): string {
  return `${PROJECTS_ROUTE}/${id}/${section}`;
}

export function projectOverviewRoute(id: string): string {
  return projectSectionRoute(id, 'overview');
}

export function projectPlanRoute(id: string): string {
  return projectSectionRoute(id, 'plan');
}

export function projectMissionRoute(id: string): string {
  return projectSectionRoute(id, 'mission');
}

export function projectHistoryRoute(id: string): string {
  return projectSectionRoute(id, 'history');
}

export function projectSettingsRoute(id: string): string {
  return projectSectionRoute(id, 'settings');
}

export function planDraftRoute(id: string): string {
  return `${PLAN_ROUTE}/${id}`;
}

export function blackHoleDraftRoute(id: string): string {
  return `${BLACK_HOLE_ROUTE}/${id}`;
}

export function isBlackHoleEnabled(labs: LabsConfig | null | undefined): boolean {
  return labs?.black_hole_enabled === true;
}

export interface AppConfig {
  filesystem: {
    allowed_base_paths: string[];
    default_start_path: string;
  };
  default_caps: DefaultCaps;
  labs: LabsConfig;
}

export interface Model {
  id: string;
  label?: string;
  name: string;
  provider: string;
  provider_id?: string;
  agent?: string;
  model?: string;
  model_id?: string;
  thinking?: string;
  supported_thinking?: string[];
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
