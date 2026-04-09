import { createRoot, type Root } from 'react-dom/client';
import { act, type ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Sidebar from './Sidebar';
import HudBar from './HudBar';
import LiveClock from './LiveClock';

const wsHarness = vi.hoisted(() => {
  type ConnectionState = 'connecting' | 'open' | 'closed';
  const listeners = new Set<(state: ConnectionState) => void>();
  let state: ConnectionState = 'closed';

  return {
    get state() {
      return state;
    },
    set state(next: ConnectionState) {
      state = next;
    },
    listeners,
    emit(next: ConnectionState) {
      state = next;
      for (const listener of listeners) {
        listener(next);
      }
    },
    reset() {
      state = 'closed';
      listeners.clear();
    },
  };
});

const missionListHarness = vi.hoisted(() => ({
  missions: [] as Array<{
    mission_id: string;
    status: string;
    cost_usd: number;
    done_tasks: number;
    total_tasks: number;
  }>,
}));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

afterEach(() => {
  document.body.innerHTML = '';
  localStorage.clear();
  wsHarness.reset();
  vi.useRealTimers();
});

vi.mock('../lib/ws', () => ({
  wsClient: {
    get connectionState() {
      return wsHarness.state;
    },
    onConnectionState(handler: (state: 'connecting' | 'open' | 'closed') => void) {
      wsHarness.listeners.add(handler);
      handler(wsHarness.state);
    },
    offConnectionState(handler: (state: 'connecting' | 'open' | 'closed') => void) {
      wsHarness.listeners.delete(handler);
    },
  },
}));

vi.mock('../hooks/useMissionList', () => ({
  useMissionList: () => ({
    missions: missionListHarness.missions,
    loading: false,
    error: null,
  }),
}));

function renderToContainer(element: ReactElement): { root: Root; container: HTMLDivElement } {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(element);
  });

  return { root, container };
}

describe('app shell components', () => {
  it('LiveClock renders a tabular HH:MM:SS clock and updates over time', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2024, 0, 1, 12, 34, 56));

    const { root, container } = renderToContainer(<LiveClock />);

    const initialTime = container.textContent ?? '';
    expect(initialTime).toMatch(/^\d{2}:\d{2}:\d{2}$/);

    act(() => {
      vi.setSystemTime(new Date(2024, 0, 1, 12, 34, 57));
      vi.advanceTimersByTime(1000);
    });

    expect(container.textContent).toMatch(/^\d{2}:\d{2}:\d{2}$/);
    expect(container.textContent).not.toBe(initialTime);

    act(() => {
      root.unmount();
    });

    vi.useRealTimers();
  });

  it('HudBar summarizes mission activity and shows ws state', () => {
    missionListHarness.missions = [
      {
        mission_id: 'm1',
        status: 'active',
        cost_usd: 1.25,
        done_tasks: 1,
        total_tasks: 2,
      },
      {
        mission_id: 'm2',
        status: 'complete',
        cost_usd: 2.5,
        done_tasks: 2,
        total_tasks: 2,
      },
      {
        mission_id: 'm3',
        status: 'failed',
        cost_usd: 3,
        done_tasks: 0,
        total_tasks: 1,
      },
    ];
    wsHarness.state = 'open';

    const { container, root } = renderToContainer(<HudBar />);

    expect(container.textContent).toContain('AGENTFORCE');
    expect(container.textContent).toContain('1 ACTIVE');
    expect(container.textContent).toContain('1 TASKS');
    expect(container.textContent).toContain('$6.75 TODAY');
    expect(container.querySelector('[aria-hidden="true"]')?.className).toContain('bg-green');

    act(() => {
      root.unmount();
    });
  });

  it('Sidebar persists collapsed state and renders four nav items', () => {
    localStorage.setItem('sidebar-collapsed', '1');
    wsHarness.state = 'open';

    const { container, root } = renderToContainer(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>,
    );

    expect(container.textContent).not.toContain('Mission Control');
    expect(container.textContent).not.toContain('Plan Mode');
    expect(container.querySelectorAll('a').length).toBe(4);
    expect(container.textContent).not.toContain('v0.0.0');

    const button = container.querySelector('button');
    expect(button).not.toBeNull();

    act(() => {
      button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(localStorage.getItem('sidebar-collapsed')).toBe('0');
    expect(container.textContent).toContain('Mission Control');
    expect(container.textContent).toContain('v0.0.0');

    act(() => {
      root.unmount();
    });
  });
});
