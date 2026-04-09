import type {
  Connector,
  Model,
  MissionState,
  MissionSummary,
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
