import { useEffect, useState } from 'react';
import { getMissions } from '../lib/api';
import { wsClient, type MissionListEvent, type MissionListUpdateEvent } from '../lib/ws';
import type { MissionSummary } from '../lib/types';

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

  useEffect(() => {
    let active = true;
    setLoading(true);

    void getMissions()
      .then((initialMissions) => {
        if (!active) {
          return;
        }

        setMissions(initialMissions);
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

    wsClient.on('mission_list', handler);
    wsClient.on('mission_list_update', handler);

    return () => {
      active = false;
      wsClient.off('mission_list', handler);
      wsClient.off('mission_list_update', handler);
    };
  }, [refreshIndex]);

  return { missions, loading, error, refresh: () => setRefreshIndex((current) => current + 1) };
}
