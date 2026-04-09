import { createRoot, type Root } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { act, type ReactElement } from 'react';
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TASK_STATUSES, type TaskStatus } from '../lib/types';
import StatusBadge from './StatusBadge';
import MissionProgressBar from './MissionProgressBar';
import EventLogTable from './EventLogTable';
import ConnectionBanner from './ConnectionBanner';

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

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

afterAll(() => {
  delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
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

const STATUS_EXPECTATIONS: Record<TaskStatus, { text: string; bg: string }> = {
  pending: { text: 'text-dim', bg: 'bg-surface' },
  spec_writing: { text: 'text-blue', bg: 'bg-blue-bg' },
  tests_written: { text: 'text-blue', bg: 'bg-blue-bg' },
  in_progress: { text: 'text-blue', bg: 'bg-blue-bg' },
  completed: { text: 'text-teal', bg: 'bg-teal/10' },
  reviewing: { text: 'text-blue', bg: 'bg-blue-bg' },
  review_approved: { text: 'text-green', bg: 'bg-green-bg' },
  review_rejected: { text: 'text-amber', bg: 'bg-amber-bg' },
  needs_human: { text: 'text-amber', bg: 'bg-amber-bg' },
  retry: { text: 'text-dim', bg: 'bg-surface' },
  failed: { text: 'text-red', bg: 'bg-red-bg' },
  blocked: { text: 'text-amber', bg: 'bg-amber-bg' },
};

function renderToContainer(element: ReactElement): { root: Root; container: HTMLDivElement } {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(element);
  });

  return { root, container };
}

describe('shared UI components', () => {
  let originalScrollIntoView: unknown;

  beforeEach(() => {
    wsHarness.reset();
    originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => {
    wsHarness.reset();
    document.body.innerHTML = '';

    if (originalScrollIntoView) {
      Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
        configurable: true,
        writable: true,
        value: originalScrollIntoView,
      });
    } else {
      delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  it('StatusBadge renders the expected classes for every TaskStatus', () => {
    for (const status of TASK_STATUSES) {
      const markup = renderToStaticMarkup(<StatusBadge status={status} />);
      const expected = STATUS_EXPECTATIONS[status];

      expect(markup).toContain(expected.text);
      expect(markup).toContain(expected.bg);
    }
  });

  it('MissionProgressBar uses a width transition that matches the server timing', () => {
    const markup = renderToStaticMarkup(<MissionProgressBar pct={37} />);

    expect(markup).toContain('h-[3px]');
    expect(markup).toContain('w-[var(--pct)]');
    expect(markup).toContain('transition-[width]');
    expect(markup).toContain('duration-[400ms]');
    expect(markup).toContain('[transition-timing-function:ease]');
  });

  it('EventLogTable truncates details and formats timestamps as local time only', () => {
    const longDetails = 'x'.repeat(200);
    const markup = renderToStaticMarkup(
      <EventLogTable
        entries={[
          {
            timestamp: '2024-01-01T12:34:56Z',
            event_type: 'review_approved',
            task_id: 'task-1',
            details: longDetails,
          },
        ]}
      />,
    );

    expect(markup).toContain('truncate');
    expect(markup).toContain('max-w-[420px]');
    expect(markup).toContain(longDetails.slice(0, 140));
    expect(markup).not.toContain(longDetails.slice(0, 141));
    expect(markup.toLowerCase()).toMatch(/title="0?1\/0?1\/2024, 8:34:56 [ap]m"/);
  });

  it('ConnectionBanner reflects wsClient connection state changes', () => {
    wsHarness.state = 'open';
    const { root, container } = renderToContainer(<ConnectionBanner />);

    expect(container.textContent).toContain('Connected');
    expect(container.querySelector('[aria-hidden="true"]')?.className).toContain('bg-green');

    act(() => {
      wsHarness.emit('closed');
    });

    expect(container.textContent).toContain('Reconnecting');
    expect(container.querySelector('[aria-hidden="true"]')?.className).toContain('bg-amber');

    act(() => {
      root.unmount();
    });
    container.remove();
  });
});
