import { createRoot } from 'react-dom/client';
import { act } from 'react-dom/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MissionState } from '../lib/types';

const wsHarness = vi.hoisted(() => {
  const stateHandlers = new Set<(event: { type: 'mission_state'; mission_id: string; state: MissionState }) => void>();
  const costHandlers = new Set<(event: {
    type: 'mission_cost_update';
    mission_id: string;
    tokens_in: number;
    tokens_out: number;
    cost_usd: number;
  }) => void>();
  const taskCostHandlers = new Set<(event: {
    type: 'task_cost_update';
    mission_id: string;
    task_id: string;
    tokens_in: number;
    tokens_out: number;
    cost_usd: number;
  }) => void>();
  const subscribe = vi.fn();

  return {
    stateHandlers,
    costHandlers,
    taskCostHandlers,
    subscribe,
    emit(event: { type: 'mission_state'; mission_id: string; state: MissionState }) {
      for (const handler of stateHandlers) {
        handler(event);
      }
    },
    emitCost(event: {
      type: 'mission_cost_update';
      mission_id: string;
      tokens_in: number;
      tokens_out: number;
      cost_usd: number;
    }) {
      for (const handler of costHandlers) {
        handler(event);
      }
    },
    emitTaskCost(event: {
      type: 'task_cost_update';
      mission_id: string;
      task_id: string;
      tokens_in: number;
      tokens_out: number;
      cost_usd: number;
    }) {
      for (const handler of taskCostHandlers) {
        handler(event);
      }
    },
    reset() {
      stateHandlers.clear();
      costHandlers.clear();
      taskCostHandlers.clear();
      subscribe.mockClear();
    },
  };
});

const mission: MissionState = {
  mission_id: 'mission-123',
  spec: {
    name: 'Mission Alpha',
    goal: 'Exercise websocket updates',
    definition_of_done: [],
    tasks: [],
    caps: {
      max_tokens_per_task: 1000,
      max_retries_global: 5,
      max_retries_per_task: 3,
      max_wall_time_minutes: 60,
      max_human_interventions: 2,
      max_concurrent_workers: 1,
    },
  },
  task_states: {
    'task-1': {
      task_id: 'task-1',
      status: 'pending',
      retries: 0,
      review_score: 0,
      human_intervention_needed: false,
      last_updated: '2024-01-01T00:00:00Z',
    },
  },
  started_at: '2024-01-01T00:00:00Z',
  total_retries: 0,
  total_human_interventions: 0,
  total_tokens_used: 0,
  estimated_cost_usd: 0,
  event_log: [],
  completed_at: null,
  caps_hit: {},
  working_dir: '/tmp',
  worker_agent: 'opencode',
  worker_model: 'gpt-5',
};

const updatedMission: MissionState = {
  ...mission,
  spec: { ...mission.spec, name: 'Mission Beta' },
};

vi.mock('../lib/api', () => ({
  getMission: vi.fn(async () => mission),
}));

vi.mock('../lib/ws', () => ({
  wsClient: {
    subscribe: wsHarness.subscribe,
    on(type: string, handler: (event: { type: 'mission_state'; mission_id: string; state: MissionState }) => void) {
      if (type === 'mission_state') {
        wsHarness.stateHandlers.add(handler);
      } else if (type === 'mission_cost_update') {
        wsHarness.costHandlers.add(handler as never);
      } else if (type === 'task_cost_update') {
        wsHarness.taskCostHandlers.add(handler as never);
      }
    },
    off(type: string, handler: (event: { type: 'mission_state'; mission_id: string; state: MissionState }) => void) {
      if (type === 'mission_state') {
        wsHarness.stateHandlers.delete(handler);
      } else if (type === 'mission_cost_update') {
        wsHarness.costHandlers.delete(handler as never);
      } else if (type === 'task_cost_update') {
        wsHarness.taskCostHandlers.delete(handler as never);
      }
    },
  },
}));

import { useMission } from './useMission';

function TestHarness({ missionId }: { missionId: string }) {
  const { mission, loading, error } = useMission(missionId);

  return (
    <div data-testid="state">
      {loading
        ? 'loading'
        : error ?? [
            mission?.spec.name ?? 'empty',
            mission?.tokens_in ?? 0,
            mission?.tokens_out ?? 0,
            mission?.cost_usd ?? 0,
            mission?.task_states['task-1']?.tokens_in ?? 0,
            mission?.task_states['task-1']?.tokens_out ?? 0,
            mission?.task_states['task-1']?.cost_usd ?? 0,
          ].join(' ')}
    </div>
  );
}

describe('useMission', () => {
  afterEach(() => {
    wsHarness.reset();
    document.body.innerHTML = '';
  });

  it('replaces mission state when a mission_state websocket event arrives', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(<TestHarness missionId="mission-123" />);
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(container.textContent).toContain('Mission Alpha');

    act(() => {
      wsHarness.emit({ type: 'mission_state', mission_id: 'mission-123', state: updatedMission });
    });

    expect(container.textContent).toContain('Mission Beta');

    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('updates live mission and task cost fields from websocket events', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(<TestHarness missionId="mission-123" />);
    });

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      wsHarness.emitCost({
        type: 'mission_cost_update',
        mission_id: 'mission-123',
        tokens_in: 42,
        tokens_out: 7,
        cost_usd: 1.25,
      });
    });

    act(() => {
      wsHarness.emitTaskCost({
        type: 'task_cost_update',
        mission_id: 'mission-123',
        task_id: 'task-1',
        tokens_in: 11,
        tokens_out: 3,
        cost_usd: 0.5,
      });
    });

    expect(container.textContent).toContain('1.25');
    expect(container.textContent).toContain('42');
    expect(container.textContent).toContain('11');
    expect(container.textContent).toContain('3');

    act(() => {
      root.unmount();
    });
    container.remove();
  });
});
