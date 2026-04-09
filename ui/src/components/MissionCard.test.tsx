import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MissionSummary } from '../lib/types';

const useElapsedTimeMock = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useElapsedTime', () => ({
  useElapsedTime: useElapsedTimeMock,
}));

import MissionCard from './MissionCard';

function renderCard(mission: MissionSummary, onStop = vi.fn(), onRestart = vi.fn()): {
  container: HTMLDivElement;
  onStop: ReturnType<typeof vi.fn>;
  onRestart: ReturnType<typeof vi.fn>;
} {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <MemoryRouter>
        <MissionCard mission={mission} onStop={onStop} onRestart={onRestart} />
      </MemoryRouter>,
    );
  });

  return { container, onStop, onRestart };
}

describe('MissionCard', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useElapsedTimeMock.mockReset();
    useElapsedTimeMock.mockReturnValue('45s');
    vi.setSystemTime(new Date('2026-04-08T00:01:00Z'));
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  it('renders the expected chrome and accent bar for an active mission', () => {
    const mission: MissionSummary = {
      mission_id: 'mission-123',
      name: 'Backfill pipeline',
      status: 'active',
      done_tasks: 3,
      total_tasks: 5,
      pct: 60,
      duration: '1h 20m',
      worker_agent: 'worker-a',
      worker_model: 'gpt-5.4',
      started_at: '2026-04-08T00:00:00Z',
      cost_usd: 1.23,
      retries: 2,
      workspace: '/Users/rent/Projects/agentforce',
      models: ['gpt-5.4', 'gpt-4.1'],
      active_task_title: 'Coordinate the long-running backfill process and report progress',
    } as MissionSummary & { retries?: number; active_task_title?: string };

    const { container } = renderCard(mission);

    expect(container.innerHTML).toContain('hover:shadow-[0_0_0_1px_theme(colors.border-lit),0_4px_24px_theme(colors.glow-cyan)]');
    expect(container.innerHTML).toContain('bg-cyan');
    expect(container.textContent).toContain('Backfill pipeline');
    expect(container.textContent).toContain('45s');
    expect(container.textContent).toContain('3/5 tasks');
    expect(container.textContent).toContain('2 retries');
    expect(container.textContent).toContain('$1.2300');
    expect(container.textContent).toContain('Coordinate the long-running backfill pr');
    expect(container.textContent).toContain('/Users/rent/Projects/agentforce');
    expect(container.textContent).toContain('gpt-4.1');
    expect(container.textContent).toContain('ago');
    expect(container.innerHTML).toContain('opacity-0');
    expect(container.innerHTML).toContain('group-hover:opacity-100');
  });

  it('confirms before invoking stop and restart handlers', async () => {
    const mission: MissionSummary = {
      mission_id: 'mission-123',
      name: 'Backfill pipeline',
      status: 'active',
      done_tasks: 3,
      total_tasks: 5,
      pct: 60,
      duration: '1h 20m',
      worker_agent: 'worker-a',
      worker_model: 'gpt-5.4',
      started_at: '2026-04-08T00:00:00Z',
      cost_usd: 1.23,
    };
    const onStop = vi.fn();
    const onRestart = vi.fn();
    const { container } = renderCard(mission, onStop, onRestart);
    const buttons = Array.from(container.querySelectorAll('button'));

    await act(async () => {
      buttons[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.textContent).toContain('Stop mission "Backfill pipeline"?');
    const confirmButtons = Array.from(container.querySelectorAll('button')).filter(
      (button) => button.textContent === 'Stop Mission',
    );
    expect(confirmButtons).toHaveLength(1);

    await act(async () => {
      confirmButtons[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onStop).toHaveBeenCalledTimes(1);

    await act(async () => {
      buttons[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.textContent).toContain('Restart mission "Backfill pipeline"?');
    const restartConfirm = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === 'Restart Mission',
    ) as HTMLButtonElement;

    await act(async () => {
      restartConfirm.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onRestart).toHaveBeenCalledTimes(1);
  });

  it('shows the green accent state for approved missions', () => {
    const mission: MissionSummary = {
      mission_id: 'mission-456',
      name: 'Patch review',
      status: 'complete',
      done_tasks: 5,
      total_tasks: 5,
      pct: 100,
      duration: '2h 00m',
      worker_agent: 'worker-b',
      worker_model: 'gpt-5.4',
      started_at: '2026-04-07T22:00:00Z',
      cost_usd: 9.87,
    };

    const { container } = renderCard(mission);

    expect(container.innerHTML).toContain('bg-green');
  });
});
