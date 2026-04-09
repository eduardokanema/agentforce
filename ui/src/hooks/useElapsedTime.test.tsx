import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useElapsedTime } from './useElapsedTime';

function Harness({ startedAt }: { startedAt: string | null | undefined }) {
  const elapsed = useElapsedTime(startedAt);
  return <div>{elapsed}</div>;
}

describe('useElapsedTime', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  it('formats elapsed time and refreshes every five seconds', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-08T01:00:00Z'));

    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(<Harness startedAt="2026-04-08T00:58:55Z" />);
    });

    expect(container.textContent).toBe('1m');

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(container.textContent).toBe('1m');

    act(() => {
      root.unmount();
    });
  });

  it('returns a dash when the timestamp is missing', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(<Harness startedAt={undefined} />);
    });

    expect(container.textContent).toBe('—');

    act(() => {
      root.unmount();
    });
  });
});
