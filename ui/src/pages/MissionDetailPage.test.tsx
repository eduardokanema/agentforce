import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MissionState } from '../lib/types';

let missionForHook: MissionState;
const apiHarness = vi.hoisted(() => ({
  stopMission: vi.fn(async () => undefined),
  restartMission: vi.fn(async () => undefined),
  createReadjustedDraft: vi.fn(async () => ({ id: 'draft-321', revision: 1 })),
}));
const toastHarness = vi.hoisted(() => ({
  addToast: vi.fn(),
  removeToast: vi.fn(),
  toasts: [],
}));

vi.mock('../hooks/useMission', () => ({
  useMission: () => ({
    mission: missionForHook,
    loading: false,
    error: null,
  }),
}));

vi.mock('../lib/api', () => ({
  stopMission: apiHarness.stopMission,
  restartMission: apiHarness.restartMission,
  createReadjustedDraft: apiHarness.createReadjustedDraft,
}));

vi.mock('../hooks/useToast', () => ({
  useToast: () => toastHarness,
}));

import MissionDetailPage, { filterEventLogEntries } from './MissionDetailPage';

const mockMission: MissionState = {
  mission_id: 'mission-123',
  spec: {
    name: 'Mission Alpha',
    goal: 'Validate the mission detail page',
    definition_of_done: ['All acceptance criteria pass'],
    tasks: [
      { id: 'task-1', title: 'First task', description: 'First', acceptance_criteria: [], dependencies: [], max_retries: 3, output_artifacts: [] },
      { id: 'task-2', title: 'Second task', description: 'Second', acceptance_criteria: [], dependencies: ['task-1'], max_retries: 3, output_artifacts: [] },
    ],
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
      status: 'review_approved',
      retries: 1,
      review_score: 8,
      human_intervention_needed: false,
      last_updated: '2024-01-01T00:00:00Z',
    },
    'task-2': {
      task_id: 'task-2',
      status: 'in_progress',
      retries: 0,
      review_score: 0,
      human_intervention_needed: false,
      last_updated: '2024-01-01T00:00:00Z',
    },
  },
  started_at: '2024-01-01T00:00:00Z',
  tokens_in: 100,
  tokens_out: 23,
  cost_usd: 0.5,
  total_retries: 1,
  total_human_interventions: 0,
  total_tokens_used: 100,
  estimated_cost_usd: 0.5,
  event_log: Array.from({ length: 55 }, (_, index) => ({
    timestamp: `2024-01-01T00:00:${String(index).padStart(2, '0')}Z`,
    event_type: index % 2 === 0 ? 'task_started' : 'task_completed',
    task_id: index % 2 === 0 ? 'task-2' : 'task-1',
    details: `event-${index}`,
  })),
  completed_at: null,
  caps_hit: {},
  working_dir: '/tmp/work',
  worker_agent: 'opencode',
  worker_model: 'gpt-5',
  execution: {
    defaults: {
      worker: { agent: 'codex', model: 'gpt-5', thinking: 'medium' },
      reviewer: { agent: 'codex', model: 'gpt-5-mini', thinking: 'low' },
    },
    mixed_roles: ['worker', 'reviewer'],
    task_overrides: { worker: 1, reviewer: 1 },
  },
};

missionForHook = mockMission;

describe('MissionDetailPage', () => {
  afterEach(() => {
    apiHarness.stopMission.mockClear();
    apiHarness.restartMission.mockClear();
    apiHarness.createReadjustedDraft.mockClear();
    toastHarness.addToast.mockClear();
    document.body.innerHTML = '';
  });

  it('renders the mission detail layout from useMission', () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/mission/mission-123']}>
        <Routes>
          <Route path="/mission/:id" element={<MissionDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(markup).toContain('Missions');
    expect(markup).toContain('Mission Alpha');
    expect(markup).toContain('text-title');
    expect(markup).toContain('↓ 100 in');
    expect(markup).toContain('↑ 23 out');
    expect(markup).toContain('$0.5000');
    expect(markup).toContain('Workspace path');
    expect(markup).toContain('worker codex · gpt-5 · medium');
    expect(markup).toContain('reviewer codex · gpt-5-mini · low');
    expect(markup).toContain('mixed worker, reviewer');
    expect(markup).toContain('Mission Control');
    expect(markup).toContain('/mission/mission-123/task/task-1');
    expect(markup).toContain('Event Log');
    expect(markup).not.toContain('event-0');
    expect(markup).toContain('event-54');
  });

  it('renders task cards and dependency chips instead of a table', () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/mission/mission-123']}>
        <Routes>
          <Route path="/mission/:id" element={<MissionDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(markup).toContain('grid grid-cols-1');
    expect(markup).toContain('needs #01');
  });

  it('shows only the first five running tasks with the shimmer class', () => {
    missionForHook = {
      ...mockMission,
      spec: {
        ...mockMission.spec,
        tasks: Array.from({ length: 7 }, (_, index) => ({
          id: `task-${index + 1}`,
          title: `Task ${index + 1}`,
          description: `Task ${index + 1}`,
          acceptance_criteria: [],
          dependencies: index > 0 ? [`task-${index}`] : [],
          max_retries: 3,
          output_artifacts: [],
        })),
      },
      task_states: Object.fromEntries(
        Array.from({ length: 7 }, (_, index) => {
          const taskId = `task-${index + 1}`;
          return [
            taskId,
            {
              task_id: taskId,
              status: 'in_progress',
              retries: 0,
              review_score: 0,
              human_intervention_needed: false,
              last_updated: '2024-01-01T00:00:00Z',
            },
          ];
        }),
      ),
    };

    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/mission/mission-123']}>
        <Routes>
          <Route path="/mission/:id" element={<MissionDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect((markup.match(/animate-\[scan-line_2s_linear_infinite\]/g) ?? []).length).toBe(5);
  });

  it('confirms before stopping or restarting the mission', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/mission/mission-123']}>
          <Routes>
            <Route path="/mission/:id" element={<MissionDetailPage />} />
          </Routes>
        </MemoryRouter>,
      );
    });

    const buttons = Array.from(container.querySelectorAll('button'));
    expect(buttons).toHaveLength(3);

    await act(async () => {
      buttons[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.textContent).toContain('Stop mission "Mission Alpha"?');
    const stopDialog = container.querySelector('[role="dialog"]') as HTMLElement;
    const stopConfirm = Array.from(stopDialog.querySelectorAll('button'))[1] as HTMLButtonElement;
    expect(stopConfirm).toBeTruthy();

    await act(async () => {
      stopConfirm.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(apiHarness.stopMission).toHaveBeenCalledWith('mission-123');
    expect(toastHarness.addToast).toHaveBeenCalledWith('Mission stopped', 'success');

    await act(async () => {
      buttons[2].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.textContent).toContain('Restart mission "Mission Alpha"?');
    const restartDialog = container.querySelector('[role="dialog"]') as HTMLElement;
    const restartConfirm = Array.from(restartDialog.querySelectorAll('button'))[1] as HTMLButtonElement;

    await act(async () => {
      restartConfirm.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(apiHarness.restartMission).toHaveBeenCalledWith('mission-123');
    expect(toastHarness.addToast).toHaveBeenCalledWith('Mission restarted', 'success');

    act(() => {
      root.unmount();
    });
  });

  it('offers a visible Readjust Trajectory action that returns to seeded planning', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/mission/mission-123']}>
          <Routes>
            <Route path="/mission/:id" element={<MissionDetailPage />} />
            <Route path="/plan" element={<div data-testid="plan-route">Plan Route</div>} />
          </Routes>
        </MemoryRouter>,
      );
    });

    const readjustButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Readjust Trajectory'),
    ) as HTMLButtonElement | undefined;

    expect(readjustButton).toBeTruthy();

    await act(async () => {
      readjustButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(apiHarness.createReadjustedDraft).toHaveBeenCalledWith('mission-123');
    expect(container.querySelector('[data-testid="plan-route"]')).toBeTruthy();

    act(() => {
      root.unmount();
    });
  });

  it('filters event log entries by event type substring', () => {
    const filtered = filterEventLogEntries(mockMission.event_log ?? [], 'completed');

    expect(filtered.length).toBeGreaterThan(0);
    expect(filtered.every((entry) => entry.event_type.includes('completed'))).toBe(true);
    expect(filtered.some((entry) => entry.event_type.includes('started'))).toBe(false);
  });

  it('counts only review-approved tasks as completed', () => {
    missionForHook = {
      ...mockMission,
      task_states: {
        'task-1': mockMission.task_states['task-1'],
        'task-2': {
          ...mockMission.task_states['task-2'],
          status: 'completed',
        },
      },
    };

    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/mission/mission-123']}>
        <Routes>
          <Route path="/mission/:id" element={<MissionDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(markup).toContain('text-blue bg-blue-bg border-blue/20">active</span>');
  });
});
