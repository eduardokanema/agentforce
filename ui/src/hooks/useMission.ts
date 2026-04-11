import { useEffect, useState } from 'react';
import { getMission } from '../lib/api';
import {
  type MissionEventLoggedEvent,
  wsClient,
  type MissionCostUpdateEvent,
  type MissionStateEvent,
  type MissionTaskUpdateEvent,
  type TaskAttemptStartEvent,
  type TaskCostUpdateEvent,
} from '../lib/ws';
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

    const handleMissionState = (event: MissionStateEvent): void => {
      if (!active || event.mission_id !== missionId) {
        return;
      }

      setMission(event.state);
    };

    const handleMissionCostUpdate = (event: MissionCostUpdateEvent): void => {
      if (!active || event.mission_id !== missionId) {
        return;
      }

      setMission((currentMission) => {
        if (!currentMission) {
          return currentMission;
        }

        return {
          ...currentMission,
          tokens_in: event.tokens_in,
          tokens_out: event.tokens_out,
          cost_usd: event.cost_usd,
        };
      });
    };

    const handleMissionTaskUpdate = (event: MissionTaskUpdateEvent): void => {
      if (!active || event.mission_id !== missionId) {
        return;
      }

      setMission((currentMission) => {
        if (!currentMission) {
          return currentMission;
        }

        return {
          ...currentMission,
          task_states: {
            ...currentMission.task_states,
            [event.task_id]: {
              ...currentMission.task_states[event.task_id],
              ...event.task,
            },
          },
        };
      });
    };

    const handleTaskAttemptStart = (event: TaskAttemptStartEvent): void => {
      if (!active || event.mission_id !== missionId) {
        return;
      }

      setMission((currentMission) => {
        if (!currentMission) {
          return currentMission;
        }

        const currentTask = currentMission.task_states[event.task_id];
        if (!currentTask) {
          return currentMission;
        }

        return {
          ...currentMission,
          task_states: {
            ...currentMission.task_states,
            [event.task_id]: {
              ...currentTask,
              status: 'in_progress',
              worker_output: '',
              review_feedback: undefined,
              error_message: undefined,
              review_score: 0,
              human_intervention_needed: false,
              human_intervention_message: undefined,
              human_intervention_kind: undefined,
              human_intervention_options: undefined,
              human_intervention_context: undefined,
              spec_summary: undefined,
              completed_at: undefined,
            },
          },
        };
      });
    };

    const handleMissionEventLogged = (event: MissionEventLoggedEvent): void => {
      if (!active || event.mission_id !== missionId) {
        return;
      }

      setMission((currentMission) => {
        if (!currentMission) {
          return currentMission;
        }

        return {
          ...currentMission,
          event_log: [...(currentMission.event_log ?? []), event.entry].slice(-200),
        };
      });
    };

    const handleTaskCostUpdate = (event: TaskCostUpdateEvent): void => {
      if (!active || event.mission_id !== missionId) {
        return;
      }

      setMission((currentMission) => {
        if (!currentMission) {
          return currentMission;
        }

        const taskState = currentMission.task_states[event.task_id];
        if (!taskState) {
          return currentMission;
        }

        return {
          ...currentMission,
          task_states: {
            ...currentMission.task_states,
            [event.task_id]: {
              ...taskState,
              tokens_in: event.tokens_in,
              tokens_out: event.tokens_out,
              cost_usd: event.cost_usd,
            },
          },
        };
      });
    };

    wsClient.subscribe(missionId);
    wsClient.on('mission_state', handleMissionState);
    wsClient.on('mission_task_update', handleMissionTaskUpdate);
    wsClient.on('task_attempt_start', handleTaskAttemptStart);
    wsClient.on('mission_event_logged', handleMissionEventLogged);
    wsClient.on('mission_cost_update', handleMissionCostUpdate);
    wsClient.on('task_cost_update', handleTaskCostUpdate);

    return () => {
      active = false;
      wsClient.off('mission_state', handleMissionState);
      wsClient.off('mission_task_update', handleMissionTaskUpdate);
      wsClient.off('task_attempt_start', handleTaskAttemptStart);
      wsClient.off('mission_event_logged', handleMissionEventLogged);
      wsClient.off('mission_cost_update', handleMissionCostUpdate);
      wsClient.off('task_cost_update', handleTaskCostUpdate);
    };
  }, [missionId]);

  return { mission, loading, error };
}
