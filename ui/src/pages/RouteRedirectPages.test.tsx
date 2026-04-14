import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  lookupProjectByDraft: vi.fn(),
  lookupProjectByMission: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  lookupProjectByDraft: api.lookupProjectByDraft,
  lookupProjectByMission: api.lookupProjectByMission,
}));

import MissionRedirectPage from './MissionRedirectPage';
import PlanRedirectPage from './PlanRedirectPage';

function flushPromises(): Promise<void> {
  return act(async () => {
    await Promise.resolve();
  });
}

describe('legacy redirect pages', () => {
  beforeEach(() => {
    api.lookupProjectByDraft.mockReset();
    api.lookupProjectByMission.mockReset();
    window.localStorage.clear();
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('redirects a legacy draft route into the owning project plan', async () => {
    api.lookupProjectByDraft.mockResolvedValue({ project_id: 'proj-1' });
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(
        <MemoryRouter initialEntries={['/plan/draft-1']}>
          <Routes>
            <Route path="/plan/:id" element={<PlanRedirectPage />} />
            <Route path="/projects/:id/plan" element={<div>Project plan target</div>} />
          </Routes>
        </MemoryRouter>,
      );
    });

    await flushPromises();
    await flushPromises();

    expect(api.lookupProjectByDraft).toHaveBeenCalledWith('draft-1');
    expect(container.textContent).toContain('Project plan target');

    act(() => {
      root.unmount();
    });
  });

  it('redirects /plan to the last active project plan when available', async () => {
    window.localStorage.setItem('agentforce-last-project-id', 'proj-last');
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(
        <MemoryRouter initialEntries={['/plan']}>
          <Routes>
            <Route path="/plan" element={<PlanRedirectPage />} />
            <Route path="/projects/:id/plan" element={<div>Last project plan</div>} />
          </Routes>
        </MemoryRouter>,
      );
    });

    await flushPromises();
    await flushPromises();

    expect(container.textContent).toContain('Last project plan');

    act(() => {
      root.unmount();
    });
  });

  it('redirects a legacy mission route into the owning project mission', async () => {
    api.lookupProjectByMission.mockResolvedValue({ project_id: 'proj-2' });
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(
        <MemoryRouter initialEntries={['/mission/mission-1']}>
          <Routes>
            <Route path="/mission/:id" element={<MissionRedirectPage />} />
            <Route path="/projects/:id/mission" element={<div>Project mission target</div>} />
          </Routes>
        </MemoryRouter>,
      );
    });

    await flushPromises();
    await flushPromises();

    expect(api.lookupProjectByMission).toHaveBeenCalledWith('mission-1');
    expect(container.textContent).toContain('Project mission target');

    act(() => {
      root.unmount();
    });
  });
});
