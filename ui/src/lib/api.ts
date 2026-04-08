import type { MissionState, MissionSummary, TaskSpec, TaskState } from './types';

export const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: {
      Accept: 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status} ${response.statusText}`);
  }

  return (await response.json()) as T;
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
