import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getTelemetryMock = vi.hoisted(() => vi.fn());

vi.mock('../lib/api', () => ({
  getTelemetry: getTelemetryMock,
}));

import TelemetryPage from './TelemetryPage';

const telemetry = {
  total_missions: 3,
  total_tasks: 9,
  total_cost_usd: 12.3456,
  total_tokens_in: 1200,
  total_tokens_out: 800,
  missions_by_cost: [
    {
      mission_id: 'mission-1',
      name: 'Alpha Mission',
      cost_usd: 6.1111,
      tokens_in: 500,
      tokens_out: 300,
      duration: '1h 20m',
      retries: 4,
    },
    {
      mission_id: 'mission-2',
      name: 'Beta Mission',
      cost_usd: 4.4444,
      tokens_in: 400,
      tokens_out: 250,
      duration: '50m 10s',
      retries: 1,
    },
    {
      mission_id: 'mission-3',
      name: 'Gamma Mission',
      cost_usd: 1.7901,
      tokens_in: 300,
      tokens_out: 250,
      duration: '15m 02s',
      retries: 0,
    },
  ],
  tasks_by_cost: [
    {
      mission_id: 'mission-1',
      task_id: 'task-1',
      task: 'Gather data',
      mission: 'Alpha Mission',
      model: 'gpt-5.4',
      cost_usd: 3.5555,
      retries: 2,
    },
    {
      mission_id: 'mission-2',
      task_id: 'task-2',
      task: 'Write tests',
      mission: 'Beta Mission',
      model: 'gpt-4.1',
      cost_usd: 2.2222,
      retries: 1,
    },
    {
      mission_id: 'mission-3',
      task_id: 'task-3',
      task: 'Review output',
      mission: 'Gamma Mission',
      model: 'gpt-4.1-mini',
      cost_usd: 1.1111,
      retries: 0,
    },
  ],
  retry_distribution: { '0': 4, '1': 2, '2+': 1 },
  cost_over_time: [
    { mission_name: 'Alpha Mission', cumulative_cost: 6.1111 },
    { mission_name: 'Beta Mission', cumulative_cost: 10.5555 },
    { mission_name: 'Gamma Mission', cumulative_cost: 12.3456 },
  ],
};

function renderPage(): { container: HTMLDivElement; root: ReturnType<typeof createRoot> } {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(<TelemetryPage />);
  });

  return { container, root };
}

describe('TelemetryPage', () => {
  let createObjectURLMock: ReturnType<typeof vi.fn>;
  let revokeObjectURLMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-09T01:00:00Z'));
    getTelemetryMock.mockReset();
    getTelemetryMock.mockResolvedValue(telemetry);
    createObjectURLMock = vi.fn(() => 'blob:telemetry');
    revokeObjectURLMock = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: createObjectURLMock,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: revokeObjectURLMock,
    });
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.useRealTimers();
    vi.restoreAllMocks();
    delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
  });

  it('renders telemetry stats, tables, charts, and export/refresh controls', async () => {
    const originalCreateElement = document.createElement.bind(document);
    let createdAnchor: HTMLAnchorElement | null = null;
    const click = vi.fn();

    const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation(((tagName: string, options?: ElementCreationOptions) => {
      const element = originalCreateElement(tagName, options);
      if (tagName === 'a') {
        createdAnchor = element as HTMLAnchorElement;
        Object.defineProperty(element, 'click', {
          configurable: true,
          value: click,
        });
      }
      return element;
    }) as typeof document.createElement);

    const { container, root } = renderPage();

    await act(async () => {
      await Promise.resolve();
    });

    expect(getTelemetryMock).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain('Last updated');
    expect(container.textContent).toContain('Total Missions');
    expect(container.textContent).toContain('Total Tasks');
    expect(container.textContent).toContain('Total Cost');
    expect(container.textContent).toContain('Total Tokens');
    expect(container.textContent).toContain('3');
    expect(container.textContent).toContain('$12.3456');
    expect(container.textContent).toContain('1,200 in / 800 out');
    expect(container.textContent).toContain('Top Missions by Cost');
    expect(container.textContent).toContain('Top Tasks by Cost');
    expect(container.textContent).toContain('Gather data');
    expect(container.textContent).toContain('Alpha Mission');
    expect(container.textContent).toContain('gpt-5.4');

    const bars = Array.from(container.querySelectorAll('svg[data-testid="retry-distribution"] rect[data-bar]'));
    expect(bars).toHaveLength(3);
    expect(bars.map((bar) => Number(bar.getAttribute('height')))).toEqual([100, 50, 25]);

    const polyline = container.querySelector('svg[data-testid="cumulative-cost"] polyline');
    const points = polyline?.getAttribute('points')?.split(' ') ?? [];
    expect(points).toHaveLength(3);
    expect(points[0]?.startsWith('20,')).toBe(true);
    expect(points[2]?.startsWith('280,')).toBe(true);

    const refreshButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('Refresh'));
    expect(refreshButton).toBeTruthy();

    await act(async () => {
      refreshButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(getTelemetryMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      vi.advanceTimersByTime(30000);
    });

    expect(getTelemetryMock).toHaveBeenCalledTimes(3);

    const exportButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('Export'));
    expect(exportButton).toBeTruthy();

    await act(async () => {
      exportButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(createObjectURLMock).toHaveBeenCalledTimes(1);
    const blob = createObjectURLMock.mock.calls[0][0] as Blob;
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe('application/json');
    expect(blob.size).toBeGreaterThan(0);
    expect((createdAnchor as HTMLAnchorElement | null)?.download).toBe('agentforce-telemetry.json');
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:telemetry');

    act(() => {
      root.unmount();
    });

    createElementSpy.mockRestore();
  });

  it('renders empty chart states safely when the API returns zeros', async () => {
    getTelemetryMock.mockResolvedValueOnce({
      total_missions: 0,
      total_tasks: 0,
      total_cost_usd: 0,
      total_tokens_in: 0,
      total_tokens_out: 0,
      missions_by_cost: [],
      tasks_by_cost: [],
      retry_distribution: { '0': 0, '1': 0, '2+': 0 },
      cost_over_time: [],
    });

    const { container, root } = renderPage();

    await act(async () => {
      await Promise.resolve();
    });

    expect(container.textContent).toContain('0');
    expect(container.textContent).toContain('No data yet');

    act(() => {
      root.unmount();
    });
  });
});
