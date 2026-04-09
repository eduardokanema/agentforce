import { act, type ReactElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./Terminal', () => ({
  default: function TerminalMock({ lines }: { lines: string[] }) {
    return <div data-terminal-mock>{lines.join('|')}</div>;
  },
}));

import RetryHistory from './RetryHistory';

function render(element: ReactElement): { root: ReturnType<typeof createRoot>; container: HTMLDivElement } {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(element);
  });

  return { root, container };
}

describe('RetryHistory', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('shows first-attempt messaging when there is no history', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([{ attempt_number: 1, output: 'only attempt', review: null, score: 0 }]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { container, root } = render(
      <RetryHistory missionId="mission-1" taskId="task-1" currentRetryCount={0} />,
    );

    expect(container.textContent).toContain('First attempt — no history');

    act(() => {
      root.unmount();
    });
  });

  it('renders attempts as tabs and defaults to the latest attempt', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify([
          { attempt_number: 1, output: 'first line\nsecond line', review: 'Initial pass', score: 4 },
          {
            attempt_number: 2,
            output: 'final output',
            review: 'Looks much better after the retry. '.repeat(8),
            score: 8,
          },
        ]),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { container, root } = render(
      <RetryHistory missionId="mission-1" taskId="task-1" currentRetryCount={2} />,
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(fetchMock).toHaveBeenCalledWith('/api/mission/mission-1/task/task-1/attempts', {
      headers: { Accept: 'application/json' },
    });
    expect(container.textContent).toContain('Attempt 1');
    expect(container.textContent).toContain('Attempt 2');
    expect(container.textContent).toContain('final output');
    expect(container.textContent).toContain('8/10');
    expect(container.textContent).toContain('Looks much better after the retry');

    const tabs = Array.from(container.querySelectorAll('button')).filter((button) =>
      button.textContent?.startsWith('Attempt'),
    );
    expect(tabs[1]?.className).toContain('bg-cyan-bg');
    expect(tabs[1]?.className).toContain('text-cyan');

    await act(async () => {
      tabs[0]?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(container.textContent).toContain('first line|second line');

    act(() => {
      root.unmount();
    });
  });

  it('falls back to no-history messaging when the fetch fails', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('boom'));
    vi.stubGlobal('fetch', fetchMock);

    const { container, root } = render(
      <RetryHistory missionId="mission-1" taskId="task-1" currentRetryCount={3} />,
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(container.textContent).toContain('First attempt — no history');

    act(() => {
      root.unmount();
    });
  });
});
