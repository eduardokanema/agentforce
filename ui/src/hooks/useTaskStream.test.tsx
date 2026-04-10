import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TaskState, TaskSpec } from '../lib/types';

const wsHarness = vi.hoisted(() => {
  const handlers = new Map<string, Set<(event: any) => void>>();
  const subscribe = vi.fn();

  return {
    handlers,
    subscribe,
    emit(event: any) {
      const listeners = handlers.get(event.type);
      if (!listeners) {
        return;
      }

      for (const listener of listeners) {
        listener(event);
      }
    },
    reset() {
      handlers.clear();
      subscribe.mockClear();
    },
  };
});

const task: TaskState & TaskSpec = {
  task_id: 'task-1',
  status: 'in_progress',
  retries: 1,
  review_score: 0,
  human_intervention_needed: false,
  last_updated: '2024-01-01T00:00:00Z',
  worker_output: 'booting worker\r\nready',
  id: 'task-1',
  title: 'Investigate stream',
  description: 'Investigate live terminal stream handling',
  acceptance_criteria: [],
  dependencies: [],
  max_retries: 3,
  output_artifacts: [],
};

vi.mock('../lib/api', () => ({
  getTask: vi.fn(async () => task),
  getTaskOutput: vi.fn(async () => ({ lines: ['booting worker', 'ready'] })),
}));

vi.mock('../lib/ws', () => ({
  wsClient: {
    subscribe: wsHarness.subscribe,
    on(type: string, handler: (event: any) => void) {
      const listeners = wsHarness.handlers.get(type) ?? new Set();
      listeners.add(handler);
      wsHarness.handlers.set(type, listeners);
    },
    off(type: string, handler: (event: any) => void) {
      const listeners = wsHarness.handlers.get(type);
      if (!listeners) {
        return;
      }

      listeners.delete(handler);
    },
  },
}));

import { useTaskStream } from './useTaskStream';
import { getTaskOutput } from '../lib/api';

function TestHarness({ missionId, taskId }: { missionId: string; taskId: string }) {
  const { lines, done } = useTaskStream(missionId, taskId);

  return (
    <div>
      <div data-testid="lines">{lines.join('|')}</div>
      <div data-testid="done">{done ? 'done' : 'live'}</div>
    </div>
  );
}

describe('useTaskStream', () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    wsHarness.reset();
    document.body.innerHTML = '';
  });

  afterAll(() => {
    delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
  });

  it('prefills worker_output, appends live lines, and handles task_stream_done', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(<TestHarness missionId="mission-123" taskId="task-1" />);
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(container.querySelector('[data-testid="lines"]')?.textContent).toBe('booting worker|ready');
    expect(container.querySelector('[data-testid="done"]')?.textContent).toBe('live');

    act(() => {
      wsHarness.emit({
        type: 'task_stream_line',
        mission_id: 'mission-123',
        task_id: 'task-1',
        line: 'queued follow-up',
        seq: 3,
      });
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(container.querySelector('[data-testid="lines"]')?.textContent).toBe('booting worker|ready|queued follow-up');

    act(() => {
      wsHarness.emit({
        type: 'task_stream_done',
        mission_id: 'mission-123',
        task_id: 'task-1',
      });
    });

    expect(container.querySelector('[data-testid="done"]')?.textContent).toBe('done');

    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('keeps live lines that arrive before the initial worker_output fetch resolves', async () => {
    const outputResolver: { current: ((value: { lines: string[] }) => void) | null } = {
      current: null,
    };
    const pendingOutput = new Promise<{ lines: string[] }>((resolve) => {
      outputResolver.current = resolve;
    });

    vi.mocked(getTaskOutput).mockImplementationOnce(async () => pendingOutput);

    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(<TestHarness missionId="mission-123" taskId="task-1" />);
    });

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      wsHarness.emit({
        type: 'task_stream_line',
        mission_id: 'mission-123',
        task_id: 'task-1',
        line: 'early live line',
        seq: 1,
      });
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(container.querySelector('[data-testid="lines"]')?.textContent).toBe('early live line');

    if (outputResolver.current) {
      outputResolver.current({ lines: ['booting worker', 'ready'] });
    }

    await act(async () => {
      await Promise.resolve();
    });

    expect(container.querySelector('[data-testid="lines"]')?.textContent).toBe('booting worker|ready|early live line');

    act(() => {
      root.unmount();
    });
    container.remove();
  });
});
