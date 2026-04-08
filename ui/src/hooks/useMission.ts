import { useEffect, useState } from 'react';
import { getMission } from '../lib/api';
import { wsClient, type MissionStateEvent } from '../lib/ws';
import type { MissionState } from '../lib/types';

export function useMission(missionId: string): {
  mission: MissionState | null;
  loading: boolean;
  error: string | null;
} {
  const [mission, setMission] = useState<MissionState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    setLoading(true);
    setError(null);

    void getMission(missionId)
      .then((initialMission) => {
        if (!active) {
          return;
        }

        setMission(initialMission);
      })
      .catch((err: unknown) => {
        if (!active) {
          return;
        }

        setError(err instanceof Error ? err.message : 'Failed to load mission');
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    const handler = (event: MissionStateEvent): void => {
      if (!active || event.mission_id !== missionId) {
        return;
      }

      setMission(event.state);
    };

    wsClient.subscribe(missionId);
    wsClient.on('mission_state', handler);

    return () => {
      active = false;
      wsClient.off('mission_state', handler);
    };
  }, [missionId]);

  return { mission, loading, error };
}
