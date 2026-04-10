import type {
  AppConfig,
  Connector,
  DefaultCaps,
  FilesystemListing,
  Model,
  MissionDraft,
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

export function resolveHumanBlock(missionId: string, taskId: string, message: string): Promise<void> {
  return requestVoid(`/api/mission/${encodeURIComponent(missionId)}/task/${encodeURIComponent(taskId)}/resolve`, {
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message }),
  });
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
}): Promise<{ id: string; revision: number }> {
  return requestJson<{ id: string; revision: number }>('/api/plan/drafts', {
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

export function patchPlanDraftSpec(
  id: string,
  expectedRevision: number,
  draftSpec: MissionDraft['draft_spec'],
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
): Promise<Response> {
  const response = await fetch(`${BASE_URL}/api/plan/drafts/${encodeURIComponent(id)}/messages`, {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ content }),
  });

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status} ${response.statusText}`);
  }

  return response;
}

export function startPlanDraft(id: string): Promise<{ mission_id: string; draft_id: string; status: string }> {
  return requestJson<{ mission_id: string; draft_id: string; status: string }>(
    `/api/plan/drafts/${encodeURIComponent(id)}/start`,
    { method: 'POST' },
  );
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
