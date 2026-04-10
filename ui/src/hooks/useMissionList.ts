import { useEffect, useState, useCallback } from 'react';
import { getMissions, getDrafts } from '../lib/api';
import { wsClient, type MissionListEvent, type MissionListUpdateEvent } from '../lib/ws';
import type { MissionSummary, DraftSummary } from '../lib/types';
import { useInterval } from './useInterval';

function mapDraftToSummary(draft: DraftSummary): MissionSummary {
  return {
    mission_id: draft.id,
    name: draft.name,
    status: 'draft',
    done_tasks: 0,
    total_tasks: 0,
    pct: 0,
    duration: '0s',
    worker_agent: '',
    worker_model: '',
    started_at: draft.created_at,
    cost_usd: 0,
  };
}

function mergeMissionSummaries(
  current: MissionSummary[],
  incoming: MissionSummary[],
): MissionSummary[] {
  const indexById = new Map(current.map((mission, index) => [mission.mission_id, index] as const));
  const next = current.slice();

  for (const mission of incoming) {
    const index = indexById.get(mission.mission_id);
    if (index === undefined) {
      next.push(mission);
      continue;
    }

    next[index] = mission;
  }

  return next;
}

export function useMissionList(): {
  missions: MissionSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
} {
  const [missions, setMissions] = useState<MissionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);

  const refresh = useCallback(() => {
    setRefreshIndex((current) => current + 1);
  }, []);

  // Poll every 15 seconds as a fallback to ensure list is fresh
  useInterval(refresh, 15000);

  useEffect(() => {
    let active = true;
    setLoading(true);

    Promise.all([getMissions(), getDrafts()])
      .then(([fetchedMissions, fetchedDrafts]) => {
        if (!active) {
          return;
        }

        const mappedDrafts = fetchedDrafts.map(mapDraftToSummary);
        
        // Merge them, giving precedence to missions if there's an ID collision
        // (which happens when a draft transitions to a mission)
        const merged = mergeMissionSummaries(mappedDrafts, fetchedMissions);
        
        setMissions(merged);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active) {
          return;
        }

        setError(err instanceof Error ? err.message : 'Failed to load missions');
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    const handler = (event: MissionListEvent | MissionListUpdateEvent): void => {
      if (!active) {
        return;
      }

      setMissions((current) => mergeMissionSummaries(current, event.missions));
    };

    const draftUpdatedHandler = (): void => {
      if (!active) {
        return;
      }
      refresh();
    };

    wsClient.on('mission_list', handler);
    wsClient.on('mission_list_update', handler);
    wsClient.on('draft_updated', draftUpdatedHandler);

    return () => {
      active = false;
      wsClient.off('mission_list', handler);
      wsClient.off('mission_list_update', handler);
      wsClient.off('draft_updated', draftUpdatedHandler);
    };
  }, [refreshIndex, refresh]);

  return { missions, loading, error, refresh };
}
