import type {
  AppConfig,
  BlackHoleCampaignState,
  BlackHoleConfig,
  Connector,
  DaemonStatus,
  DefaultCaps,
  DraftSummary,
  FilesystemListing,
  LabsConfig,
  Model,
  MissionDraft,
  PreflightAnswer,
  ProjectHarnessView,
  ProjectPlanDetailView,
  ProjectSchedulerState,
  ProjectSummaryView,
  MissionState,
  MissionSummary,
  Provider,
  TaskAttempt,
  TaskSpec,
  TaskState,
  TelemetryData,
  ExecutionProfile,
} from './types';
import { DEFAULT_LABS_CONFIG as DEFAULT_LABS } from './types';

export const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status} ${response.statusText}`);
  }

  return (await response.json()) as T;
}

async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status} ${response.statusText}`);
  }
}

function withLegacyExecutionFields<T extends {
  worker_profile?: ExecutionProfile | null;
  reviewer_profile?: ExecutionProfile | null;
  worker_agent?: string | null;
  worker_model?: string | null;
  worker_thinking?: string | null;
  reviewer_agent?: string | null;
  reviewer_model?: string | null;
  reviewer_thinking?: string | null;
}>(payload: T): T {
  const next = { ...payload };
  if (next.worker_profile) {
    next.worker_agent ??= next.worker_profile.agent ?? null;
    next.worker_model ??= next.worker_profile.model ?? null;
    next.worker_thinking ??= next.worker_profile.thinking ?? null;
  }
  if (next.reviewer_profile) {
    next.reviewer_agent ??= next.reviewer_profile.agent ?? null;
    next.reviewer_model ??= next.reviewer_profile.model ?? null;
    next.reviewer_thinking ??= next.reviewer_profile.thinking ?? null;
  }
  return next;
}

function stringOrFallback(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function stringArrayOrEmpty(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function objectRecordOrEmpty(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

export function selectLabsConfig(config: Pick<AppConfig, 'labs'> | null | undefined): LabsConfig {
  const labs = config?.labs;
  const normalizedLabs: Record<string, unknown> = labs && typeof labs === 'object' && !Array.isArray(labs)
    ? { ...labs }
    : {};
  return {
    ...DEFAULT_LABS,
    ...normalizedLabs,
    black_hole_enabled: normalizedLabs.black_hole_enabled === true,
  };
}

export const BLACK_HOLE_UI_SURFACES = {
  routePaths: ['/black-hole', '/black-hole/:id'],
  apiEndpoints: [
    'POST /api/plan/drafts',
    'GET /api/plan/drafts/{draft_id}/black-hole',
    'POST /api/plan/drafts/{draft_id}/black-hole',
    'POST /api/plan/drafts/{draft_id}/black-hole/pause',
    'POST /api/plan/drafts/{draft_id}/black-hole/resume',
    'POST /api/plan/drafts/{draft_id}/black-hole/stop',
    'POST /api/plan/drafts/{draft_id}/black-hole/repair',
  ],
} as const;

function normalizeTaskSpec(task: unknown, index: number): TaskSpec | null {
  if (!task || typeof task !== 'object' || Array.isArray(task)) {
    return null;
  }
  const candidate = task as Record<string, unknown>;
  return {
    id: stringOrFallback(candidate.id, `task-${index + 1}`),
    title: stringOrFallback(candidate.title, ''),
    description: stringOrFallback(candidate.description, ''),
    acceptance_criteria: stringArrayOrEmpty(candidate.acceptance_criteria),
    tdd: candidate.tdd && typeof candidate.tdd === 'object' && !Array.isArray(candidate.tdd)
      ? (candidate.tdd as TaskSpec['tdd'])
      : null,
    dependencies: stringArrayOrEmpty(candidate.dependencies),
    working_dir: typeof candidate.working_dir === 'string' ? candidate.working_dir : null,
    max_retries: typeof candidate.max_retries === 'number' ? candidate.max_retries : 3,
    output_artifacts: stringArrayOrEmpty(candidate.output_artifacts),
    execution: candidate.execution && typeof candidate.execution === 'object' && !Array.isArray(candidate.execution)
      ? (candidate.execution as TaskSpec['execution'])
      : null,
  };
}

function normalizeDraftSpec(payload: MissionDraft): MissionDraft['draft_spec'] {
  const draftSpec = objectRecordOrEmpty(payload.draft_spec);
  const caps = objectRecordOrEmpty(draftSpec.caps);
  const normalizedTasks = Array.isArray(draftSpec.tasks)
    ? draftSpec.tasks.map(normalizeTaskSpec).filter((task): task is TaskSpec => task !== null)
    : [];

  return {
    name: stringOrFallback(draftSpec.name, stringOrFallback((payload as unknown as Record<string, unknown>).name)),
    goal: stringOrFallback(draftSpec.goal, stringOrFallback((payload as unknown as Record<string, unknown>).goal)),
    definition_of_done: stringArrayOrEmpty(draftSpec.definition_of_done),
    tasks: normalizedTasks,
    caps: {
      max_tokens_per_task: typeof caps.max_tokens_per_task === 'number' ? caps.max_tokens_per_task : 100000,
      max_retries_global: typeof caps.max_retries_global === 'number' ? caps.max_retries_global : 3,
      max_retries_per_task: typeof caps.max_retries_per_task === 'number' ? caps.max_retries_per_task : 3,
      max_wall_time_minutes: typeof caps.max_wall_time_minutes === 'number' ? caps.max_wall_time_minutes : 120,
      max_human_interventions: typeof caps.max_human_interventions === 'number' ? caps.max_human_interventions : 2,
      max_cost_usd: typeof caps.max_cost_usd === 'number' ? caps.max_cost_usd : null,
      max_concurrent_workers: typeof caps.max_concurrent_workers === 'number' ? caps.max_concurrent_workers : 3,
      review: typeof caps.review === 'string' ? caps.review : undefined,
    },
    execution_defaults:
      draftSpec.execution_defaults && typeof draftSpec.execution_defaults === 'object' && !Array.isArray(draftSpec.execution_defaults)
        ? (draftSpec.execution_defaults as MissionDraft['draft_spec']['execution_defaults'])
        : null,
    working_dir: typeof draftSpec.working_dir === 'string' ? draftSpec.working_dir : null,
    project_memory_file: typeof draftSpec.project_memory_file === 'string' ? draftSpec.project_memory_file : null,
  };
}

function normalizePlanDraft(payload: MissionDraft): MissionDraft {
  const preflightAnswers = objectRecordOrEmpty(payload.preflight_answers) as Record<string, PreflightAnswer>;
  const repairAnswers = objectRecordOrEmpty(payload.repair_answers) as Record<string, PreflightAnswer>;
  const planningFollowUps = Array.isArray(payload.planning_follow_ups)
    ? payload.planning_follow_ups.filter((item): item is NonNullable<MissionDraft["planning_follow_ups"]>[number] =>
      Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  return {
    ...payload,
    draft_spec: normalizeDraftSpec(payload),
    turns: Array.isArray(payload.turns) ? payload.turns : [],
    validation: objectRecordOrEmpty(payload.validation),
    activity_log: Array.isArray(payload.activity_log) ? payload.activity_log : [],
    approved_models: stringArrayOrEmpty(payload.approved_models),
    workspace_paths: stringArrayOrEmpty(payload.workspace_paths),
    companion_profile: objectRecordOrEmpty(payload.companion_profile),
    draft_notes: Array.isArray(payload.draft_notes)
      ? payload.draft_notes.filter((note): note is Record<string, unknown> => Boolean(note) && typeof note === 'object' && !Array.isArray(note))
      : [],
    plan_runs: Array.isArray(payload.plan_runs) ? payload.plan_runs : [],
    plan_versions: Array.isArray(payload.plan_versions) ? payload.plan_versions : [],
    preflight_questions: Array.isArray(payload.preflight_questions) ? payload.preflight_questions : [],
    preflight_answers: preflightAnswers,
    planning_follow_ups: planningFollowUps,
    repair_questions: Array.isArray(payload.repair_questions) ? payload.repair_questions : [],
    repair_answers: repairAnswers,
    repair_issues: Array.isArray(payload.repair_issues) ? payload.repair_issues : [],
  };
}

export function getMissions(): Promise<MissionSummary[]> {
  return requestJson<MissionSummary[]>('/api/missions');
}

export function getProjects(options?: { includeArchived?: boolean }): Promise<ProjectSummaryView[]> {
  const query = options?.includeArchived ? '?include_archived=1' : '';
  return requestJson<ProjectSummaryView[]>(`/api/projects${query}`);
}

export function getProject(id: string, options?: { planId?: string | null }): Promise<ProjectHarnessView> {
  const query = options?.planId ? `?plan_id=${encodeURIComponent(options.planId)}` : '';
  return requestJson<ProjectHarnessView>(`/api/projects/${encodeURIComponent(id)}${query}`);
}

export function getPlan(id: string): Promise<ProjectPlanDetailView> {
  return requestJson<ProjectPlanDetailView>(`/api/plans/${encodeURIComponent(id)}`);
}

export function getProjectScheduler(id: string): Promise<ProjectSchedulerState> {
  return requestJson<ProjectSchedulerState>(`/api/projects/${encodeURIComponent(id)}/scheduler`);
}

export function lookupProjectByDraft(id: string): Promise<{ project_id: string }> {
  return requestJson<{ project_id: string }>(`/api/project/lookup?draft_id=${encodeURIComponent(id)}`);
}

export function lookupProjectByMission(id: string): Promise<{ project_id: string }> {
  return requestJson<{ project_id: string }>(`/api/project/lookup?mission_id=${encodeURIComponent(id)}`);
}

export function createProject(payload: {
  repo_root: string;
  name?: string;
  goal?: string;
  working_directories?: string[];
}): Promise<ProjectHarnessView> {
  return requestJson<ProjectHarnessView>('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function updateProject(id: string, payload: {
  name?: string;
  goal?: string;
  working_directories?: string[];
}): Promise<ProjectHarnessView> {
  return requestJson<ProjectHarnessView>(`/api/projects/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function archiveProject(id: string): Promise<void> {
  return requestVoid(`/api/project/${encodeURIComponent(id)}/archive`);
}

export function unarchiveProject(id: string): Promise<void> {
  return requestVoid(`/api/project/${encodeURIComponent(id)}/unarchive`);
}

export async function deleteProject(id: string): Promise<void> {
  const response = await fetch(`${BASE_URL}/api/projects/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status} ${response.statusText}`);
  }
}

export function createProjectPlan(projectId: string, payload: {
  name?: string;
  objective: string;
  quick_task?: boolean;
  supersedes_plan_id?: string | null;
}): Promise<ProjectPlanDetailView> {
  return requestJson<ProjectPlanDetailView>(`/api/projects/${encodeURIComponent(projectId)}/plans`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function approveProjectPlan(planId: string): Promise<{
  plan_id: string;
  selected_version_id: string;
}> {
  return requestJson<{
    plan_id: string;
    selected_version_id: string;
  }>(`/api/plans/${encodeURIComponent(planId)}/approve-version`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
}

export function startProjectPlan(planId: string): Promise<{
  mission_run_id: string;
  mission_id: string;
  plan_id: string;
  version_id: string;
  status: string;
}> {
  return requestJson<{
    mission_run_id: string;
    mission_id: string;
    plan_id: string;
    version_id: string;
    status: string;
  }>(`/api/plans/${encodeURIComponent(planId)}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
}

export function readjustProjectPlan(planId: string): Promise<ProjectPlanDetailView> {
  return requestJson<ProjectPlanDetailView>(`/api/plans/${encodeURIComponent(planId)}/readjust`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
}

export function getDrafts(): Promise<DraftSummary[]> {
  return requestJson<DraftSummary[]>('/api/plan/drafts');
}

export function getMission(id: string): Promise<MissionState> {
  return requestJson<MissionState>(`/api/mission/${encodeURIComponent(id)}`);
}

export function getTask(missionId: string, taskId: string): Promise<TaskState & TaskSpec> {
  return requestJson<TaskState & TaskSpec>(
    `/api/mission/${encodeURIComponent(missionId)}/task/${encodeURIComponent(taskId)}`,
  );
}

export function getTaskOutput(missionId: string, taskId: string): Promise<{ lines: string[] }> {
  return requestJson<{ lines: string[] }>(
    `/api/mission/${encodeURIComponent(missionId)}/task/${encodeURIComponent(taskId)}/output`,
  );
}

export function getTaskStreamEvents(
  missionId: string,
  taskId: string,
  afterSeq = 0,
): Promise<{
  events: Array<import('./ws').StreamEventRecord>;
  done: boolean;
  last_seq: number;
}> {
  return requestJson<{
    events: Array<import('./ws').StreamEventRecord>;
    done: boolean;
    last_seq: number;
  }>(
    `/api/mission/${encodeURIComponent(missionId)}/task/${encodeURIComponent(taskId)}/stream_events?after_seq=${afterSeq}`,
  );
}

export function getTaskAttempts(missionId: string, taskId: string): Promise<TaskAttempt[]> {
  return requestJson<TaskAttempt[]>(
    `/api/mission/${encodeURIComponent(missionId)}/task/${encodeURIComponent(taskId)}/attempts`,
  );
}

export function stopMission(id: string): Promise<void> {
  return requestVoid(`/api/mission/${encodeURIComponent(id)}/stop`);
}

export function restartMission(id: string): Promise<void> {
  return requestVoid(`/api/mission/${encodeURIComponent(id)}/restart`);
}

export function troubleshootMission(id: string, prompt: string): Promise<{ task_id: string; status: string }> {
  return requestJson<{ task_id: string; status: string }>(
    `/api/mission/${encodeURIComponent(id)}/troubleshoot`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    },
  );
}

export function finishMission(id: string): Promise<void> {
  return requestVoid(`/api/mission/${encodeURIComponent(id)}/finish`);
}

export function updateMissionDefaultModels(
  id: string,
  models: {
    worker_profile?: ExecutionProfile | null;
    worker_agent?: string | null;
    worker_model?: string | null;
    worker_thinking?: string | null;
    reviewer_profile?: ExecutionProfile | null;
    reviewer_agent?: string | null;
    reviewer_model?: string | null;
    reviewer_thinking?: string | null;
  },
): Promise<{
  worker_agent: string | null;
  worker_model: string | null;
  worker_thinking: string | null;
  reviewer_agent: string | null;
  reviewer_model: string | null;
  reviewer_thinking: string | null;
  pinned_tasks: number;
}> {
  return requestJson<{
    worker_agent: string | null;
    worker_model: string | null;
    worker_thinking: string | null;
    reviewer_agent: string | null;
    reviewer_model: string | null;
    reviewer_thinking: string | null;
    pinned_tasks: number;
  }>(
    `/api/mission/${encodeURIComponent(id)}/default_models`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(withLegacyExecutionFields(models)),
    },
  );
}

export function archiveMission(id: string): Promise<void> {
  return requestVoid(`/api/mission/${encodeURIComponent(id)}/archive`);
}

export function unarchiveMission(id: string): Promise<void> {
  return requestVoid(`/api/mission/${encodeURIComponent(id)}/unarchive`);
}

export function deleteMission(id: string): Promise<void> {
  return requestVoid(`/api/mission/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function stopTask(missionId: string, taskId: string): Promise<void> {
  return requestVoid(`/api/mission/${encodeURIComponent(missionId)}/task/${encodeURIComponent(taskId)}/stop`);
}

export function retryTask(missionId: string, taskId: string): Promise<void> {
  return requestVoid(`/api/mission/${encodeURIComponent(missionId)}/task/${encodeURIComponent(taskId)}/retry`);
}

export function injectPrompt(missionId: string, taskId: string, message: string): Promise<void> {
  return requestVoid(`/api/mission/${encodeURIComponent(missionId)}/task/${encodeURIComponent(taskId)}/inject`, {
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message }),
  });
}

export function resolveHumanBlock(
  missionId: string,
  taskId: string,
  resolution: string | { message?: string; choice_id?: string },
): Promise<void> {
  const body = typeof resolution === 'string' ? { message: resolution } : resolution;
  return requestVoid(`/api/mission/${encodeURIComponent(missionId)}/task/${encodeURIComponent(taskId)}/resolve`, {
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
}

export function changeTaskModel(
  missionId: string,
  taskId: string,
  modelOrModels: string | {
    worker_profile?: ExecutionProfile | null;
    worker_agent?: string | null;
    worker_model?: string | null;
    worker_thinking?: string | null;
    reviewer_profile?: ExecutionProfile | null;
    reviewer_agent?: string | null;
    reviewer_model?: string | null;
    reviewer_thinking?: string | null;
  },
): Promise<{
  worker_agent: string | null;
  worker_model: string | null;
  worker_thinking: string | null;
  reviewer_agent: string | null;
  reviewer_model: string | null;
  reviewer_thinking: string | null;
  retried: boolean;
}> {
  const body = typeof modelOrModels === 'string' ? { worker_model: modelOrModels } : modelOrModels;
  return requestJson<{
    worker_agent: string | null;
    worker_model: string | null;
    worker_thinking: string | null;
    reviewer_agent: string | null;
    reviewer_model: string | null;
    reviewer_thinking: string | null;
    retried: boolean;
  }>(
    `/api/mission/${encodeURIComponent(missionId)}/task/${encodeURIComponent(taskId)}/change_model`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(withLegacyExecutionFields(body)),
    },
  );
}

export function markTaskFailed(missionId: string, taskId: string): Promise<void> {
  return requestVoid(`/api/mission/${encodeURIComponent(missionId)}/task/${encodeURIComponent(taskId)}/resolve`, {
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ failed: true }),
  });
}

export function getConnectors(): Promise<Connector[]> {
  return requestJson<Connector[]>('/api/connectors');
}

export function configureConnector(name: string, token: string): Promise<void> {
  return requestVoid(`/api/connectors/${encodeURIComponent(name)}/configure`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ token }),
  });
}

export function testConnector(name: string): Promise<{ ok: boolean; error?: string }> {
  return requestJson<{ ok: boolean; error?: string }>(`/api/connectors/${encodeURIComponent(name)}/test`, {
    method: 'POST',
  });
}

export function deleteConnector(name: string): Promise<void> {
  return requestVoid(`/api/connectors/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export function getTelemetry(): Promise<TelemetryData> {
  return requestJson<TelemetryData>('/api/telemetry');
}

export function getModels(): Promise<Model[]> {
  return requestJson<Model[]>('/api/models');
}

export function createMission(yaml: string): Promise<{ id: string }> {
  return requestJson<{ id: string }>('/api/missions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ yaml }),
  });
}

export function createPlanDraft(payload: {
  prompt: string;
  approved_models?: string[];
  workspace_paths: string[];
  companion_profile: Record<string, unknown>;
  validation?: Record<string, unknown>;
  auto_start?: boolean;
}): Promise<{ id: string; revision: number; plan_run_id?: string; requires_preflight?: boolean }> {
  return requestJson<{ id: string; revision: number; plan_run_id?: string; requires_preflight?: boolean }>('/api/plan/drafts', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
}

export function getPlanDraft(id: string): Promise<MissionDraft> {
  return requestJson<MissionDraft>(`/api/plan/drafts/${encodeURIComponent(id)}`).then(normalizePlanDraft);
}

export function getBlackHoleCampaign(id: string): Promise<BlackHoleCampaignState> {
  return requestJson<BlackHoleCampaignState>(`/api/plan/drafts/${encodeURIComponent(id)}/black-hole`);
}

export function createBlackHoleCampaign(
  id: string,
  expectedRevision: number,
  config: BlackHoleConfig,
): Promise<{ draft_id: string; campaign_id: string; status: string; revision: number }> {
  return requestJson<{ draft_id: string; campaign_id: string; status: string; revision: number }>(
    `/api/plan/drafts/${encodeURIComponent(id)}/black-hole`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_revision: expectedRevision, config }),
    },
  );
}

export function pauseBlackHoleCampaign(
  id: string,
): Promise<{ draft_id: string; campaign_id: string; status: string }> {
  return requestJson<{ draft_id: string; campaign_id: string; status: string }>(
    `/api/plan/drafts/${encodeURIComponent(id)}/black-hole/pause`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  );
}

export function resumeBlackHoleCampaign(
  id: string,
  config?: BlackHoleConfig,
): Promise<{ draft_id: string; campaign_id: string; status: string }> {
  return requestJson<{ draft_id: string; campaign_id: string; status: string }>(
    `/api/plan/drafts/${encodeURIComponent(id)}/black-hole/resume`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config ? { config } : {}),
    },
  );
}

export function stopBlackHoleCampaign(
  id: string,
): Promise<{ draft_id: string; campaign_id: string; status: string }> {
  return requestJson<{ draft_id: string; campaign_id: string; status: string }>(
    `/api/plan/drafts/${encodeURIComponent(id)}/black-hole/stop`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  );
}

export function submitPlanDraftRepair(
  id: string,
  expectedRevision: number,
  answers: Record<string, PreflightAnswer>,
  context?: {
    loop_no?: number | null;
    repair_round?: number | null;
    source_version_id?: string | null;
  },
): Promise<{ draft_id: string; revision: number; status: string; plan_run_id?: string; campaign_id?: string }> {
  return requestJson<{ draft_id: string; revision: number; status: string; plan_run_id?: string; campaign_id?: string }>(
    `/api/plan/drafts/${encodeURIComponent(id)}/repair`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: expectedRevision,
        answers,
        ...(context ?? {}),
      }),
    },
  );
}

export function submitBlackHoleDraftRepair(
  id: string,
  expectedRevision: number,
  answers: Record<string, PreflightAnswer>,
  context?: {
    loop_no?: number | null;
    repair_round?: number | null;
    source_version_id?: string | null;
  },
): Promise<{ draft_id: string; revision: number; status: string; plan_run_id?: string; campaign_id?: string }> {
  return requestJson<{ draft_id: string; revision: number; status: string; plan_run_id?: string; campaign_id?: string }>(
    `/api/plan/drafts/${encodeURIComponent(id)}/black-hole/repair`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: expectedRevision,
        answers,
        ...(context ?? {}),
      }),
    },
  );
}

export function patchPlanDraftSpec(
  id: string,
  expectedRevision: number,
  draftSpec: MissionDraft['draft_spec'],
  validation?: MissionDraft['validation'],
): Promise<{ id: string; revision: number }> {
  return fetch(`${BASE_URL}/api/plan/drafts/${encodeURIComponent(id)}/spec`, {
    method: 'PATCH',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      expected_revision: expectedRevision,
      draft_spec: draftSpec,
      validation,
    }),
  }).then(async (response) => {
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const message = typeof payload?.error === 'string'
        ? payload.error
        : `Request failed with status ${response.status} ${response.statusText}`;
      throw Object.assign(new Error(message), {
        status: response.status,
        payload,
      });
    }
    return payload as { id: string; revision: number };
  });
}

export function importPlanDraftYaml(
  id: string,
  expectedRevision: number,
  yaml: string,
): Promise<{ id: string; revision: number; draft_spec: MissionDraft['draft_spec'] }> {
  return fetch(`${BASE_URL}/api/plan/drafts/${encodeURIComponent(id)}/import-yaml`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      expected_revision: expectedRevision,
      yaml,
    }),
  }).then(async (response) => {
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const message = typeof payload?.error === 'string'
        ? payload.error
        : `Request failed with status ${response.status} ${response.statusText}`;
      throw Object.assign(new Error(message), {
        status: response.status,
        payload,
      });
    }
    return payload as { id: string; revision: number; draft_spec: MissionDraft['draft_spec'] };
  });
}

export async function sendPlanDraftMessage(
  id: string,
  content: string,
): Promise<{ draft_id: string; revision: number; status: string; plan_run_id?: string }> {
  return requestJson<{ draft_id: string; revision: number; status: string; plan_run_id?: string }>(
    `/api/plan/drafts/${encodeURIComponent(id)}/messages`,
    {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ content }),
    },
  );
}

export function submitPlanDraftPreflight(
  id: string,
  answers: Record<string, PreflightAnswer>,
  skip = false,
): Promise<{ draft_id: string; revision: number; plan_run_id?: string; status: string }> {
  return requestJson<{ draft_id: string; revision: number; plan_run_id?: string; status: string }>(
    `/api/plan/drafts/${encodeURIComponent(id)}/preflight`,
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ answers, skip }),
    },
  );
}

export function retryPlanRun(runId: string): Promise<{
  draft_id: string;
  plan_run_id: string;
  status: string;
}> {
  return requestJson<{
    draft_id: string;
    plan_run_id: string;
    status: string;
  }>(`/api/plan/runs/${encodeURIComponent(runId)}/retry`, { method: 'POST' });
}

export function startPlanDraft(id: string): Promise<{ mission_id: string; draft_id: string; status: string }> {
  return requestJson<{ mission_id: string; draft_id: string; status: string }>(
    `/api/plan/drafts/${encodeURIComponent(id)}/start`,
    { method: 'POST' },
  );
}

export function discardPlanDraft(id: string): Promise<void> {
  return requestVoid(`/api/plan/drafts/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function createReadjustedDraft(missionId: string): Promise<{ id: string; revision: number }> {
  return requestJson<{ id: string; revision: number }>(`/api/mission/${encodeURIComponent(missionId)}/readjust-trajectory`, {
    method: 'POST',
  });
}

export function getProviders(): Promise<Provider[]> {
  return requestJson<Provider[]>('/api/providers');
}

export function configureProvider(id: string, apiKey: string): Promise<void> {
  return requestVoid(`/api/providers/${encodeURIComponent(id)}/configure`, {
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export function testProvider(id: string): Promise<{ ok: boolean; error?: string }> {
  return requestJson<{ ok: boolean; error?: string }>(
    `/api/providers/${encodeURIComponent(id)}/test`,
    { method: 'POST' },
  );
}

export function updateProviderModels(
  id: string,
  enabledModels: string[],
  enabledThinkingByModel?: Record<string, string[]>,
  defaultModel?: string,
): Promise<void> {
  return requestVoid(`/api/providers/${encodeURIComponent(id)}/models`, {
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      enabled_models: enabledModels,
      enabled_thinking_by_model: enabledThinkingByModel,
      default_model: defaultModel,
    }),
  });
}

export function addOllamaModel(modelId: string): Promise<void> {
  return requestVoid('/api/providers/ollama/models/add', {
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId }),
  });
}

export function deleteProvider(id: string): Promise<void> {
  return requestVoid(`/api/providers/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function refreshProviderModels(id: string): Promise<{ refreshed: boolean; count?: number }> {
  return requestJson<{ refreshed: boolean; count?: number }>(
    `/api/providers/${encodeURIComponent(id)}/refresh`,
    { method: 'POST' },
  );
}

export function deactivateProvider(id: string): Promise<void> {
  return requestVoid(`/api/providers/${encodeURIComponent(id)}/deactivate`, { method: 'POST' });
}

export function activateProvider(id: string): Promise<void> {
  return requestVoid(`/api/providers/${encodeURIComponent(id)}/activate`, { method: 'POST' });
}

export function getDefaultModel(): Promise<{ model: string | null }> {
  return requestJson<{ model: string | null }>('/api/models/default');
}

export function setDefaultModel(model: string | null): Promise<void> {
  return requestVoid('/api/models/default', {
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model }),
  });
}

export function activateAgent(id: string): Promise<void> {
  return requestVoid(`/api/agents/${encodeURIComponent(id)}/activate`, { method: 'POST' });
}

export function setAgentModel(id: string, model: string | null): Promise<void> {
  return requestVoid(`/api/agents/${encodeURIComponent(id)}/model`, {
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model }),
  });
}

export function getConfig(): Promise<AppConfig> {
  return requestJson<AppConfig>('/api/config');
}

export function updateConfig(config: Partial<AppConfig>): Promise<AppConfig> {
  return requestJson<AppConfig>('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

export function updateDefaultCaps(caps: DefaultCaps): Promise<{ default_caps: DefaultCaps }> {
  return updateConfig({ default_caps: caps }).then((result) => ({ default_caps: result.default_caps }));
}

export function getFilesystemListing(path: string): Promise<FilesystemListing> {
  return requestJson<FilesystemListing>(`/api/filesystem?path=${encodeURIComponent(path)}`);
}

export function createFilesystemFolder(path: string, name: string): Promise<{ path: string }> {
  return requestJson<{ path: string }>('/api/filesystem', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, name }),
  });
}

// ---------------------------------------------------------------------------
// Daemon control
// ---------------------------------------------------------------------------

export function getDaemonStatus(): Promise<DaemonStatus> {
  return requestJson<DaemonStatus>('/api/daemon');
}

export function daemonStop(): Promise<void> {
  return requestVoid('/api/daemon/stop');
}

export function daemonRestart(): Promise<void> {
  return requestVoid('/api/daemon/restart');
}

export function daemonDequeue(jobId: string): Promise<void> {
  return requestVoid('/api/daemon/dequeue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mission_id: jobId }),
  });
}
