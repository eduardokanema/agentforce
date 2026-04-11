import type {
  AppConfig,
  BlackHoleCampaignState,
  BlackHoleConfig,
  Connector,
  DaemonStatus,
  DefaultCaps,
  DraftSummary,
  FilesystemListing,
  Model,
  MissionDraft,
  PreflightAnswer,
  MissionState,
  MissionSummary,
  Provider,
  TaskAttempt,
  TaskSpec,
  TaskState,
  TelemetryData,
} from './types';

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

export function getMissions(): Promise<MissionSummary[]> {
  return requestJson<MissionSummary[]>('/api/missions');
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
    worker_agent?: string | null;
    worker_model?: string | null;
    worker_thinking?: string | null;
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
      body: JSON.stringify(models),
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
    worker_agent?: string | null;
    worker_model?: string | null;
    worker_thinking?: string | null;
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
      body: JSON.stringify(body),
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
  approved_models: string[];
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
  return requestJson<MissionDraft>(`/api/plan/drafts/${encodeURIComponent(id)}`);
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
): Promise<{ draft_id: string; plan_run_id: string; status: string }> {
  return requestJson<{ draft_id: string; plan_run_id: string; status: string }>(
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
): Promise<{ draft_id: string; revision: number; plan_run_id: string; status: string }> {
  return requestJson<{ draft_id: string; revision: number; plan_run_id: string; status: string }>(
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
  defaultModel?: string,
): Promise<void> {
  return requestVoid(`/api/providers/${encodeURIComponent(id)}/models`, {
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled_models: enabledModels, default_model: defaultModel }),
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

export function updateDefaultCaps(caps: DefaultCaps): Promise<{ default_caps: DefaultCaps }> {
  return requestJson<{ default_caps: DefaultCaps }>('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ default_caps: caps }),
  });
}

export function getFilesystemListing(path: string): Promise<FilesystemListing> {
  return requestJson<FilesystemListing>(`/api/filesystem?path=${encodeURIComponent(path)}`);
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
