import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MissionSummary } from '../lib/types';

const useMissionListMock = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useMissionList', () => ({
  useMissionList: useMissionListMock,
}));

vi.mock('../components/ConnectionBanner', () => ({
  default: function ConnectionBanner() {
    return <div data-testid="connection-banner">Connection banner</div>;
  },
}));

import MissionsPage from './MissionsPage';

function renderPage(): HTMLDivElement {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <MemoryRouter>
        <MissionsPage />
      </MemoryRouter>,
    );
  });

  return container;
}

describe('MissionsPage', () => {
  beforeEach(() => {
    useMissionListMock.mockReset();
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('renders a loading skeleton while the initial fetch is in flight', () => {
    useMissionListMock.mockReturnValue({ missions: [], loading: true, error: null });

    const container = renderPage();

    expect(container.textContent).toContain('AgentForce Missions');
    expect(container.querySelector('[data-testid="connection-banner"]')).toBeTruthy();
    expect(container.querySelector('.animate-pulse')).toBeTruthy();
    expect(container.textContent).not.toContain('No missions yet');
  });

  it('renders an empty state when no missions are available', () => {
    useMissionListMock.mockReturnValue({ missions: [], loading: false, error: null });

    const container = renderPage();

    expect(container.textContent).toContain('No missions yet');
    expect(container.textContent).toContain('Missions will appear here once they start.');
  });

  it('renders mission cards with all requested fields', () => {
    const missions: MissionSummary[] = [
      {
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
      },
    ];
    useMissionListMock.mockReturnValue({ missions, loading: false, error: null });

    const container = renderPage();

    const link = container.querySelector('a[href="/mission/mission-123"]');

    expect(link?.textContent).toContain('Backfill pipeline');
    expect(container.textContent).toContain('active');
    expect(container.textContent).toContain('3 / 5 tasks');
    expect(container.textContent).toContain('60% complete');
    expect(container.textContent).toContain('1h 20m');
    expect(container.textContent).toContain('worker-a · gpt-5.4');
  });

  it('keeps the page copy limited to the requested mission list surface', () => {
    useMissionListMock.mockReturnValue({ missions: [], loading: false, error: null });

    const container = renderPage();

    expect(container.textContent).not.toContain('Live mission dashboard');
    expect(container.textContent).not.toContain('No refresh required');
  });
});
