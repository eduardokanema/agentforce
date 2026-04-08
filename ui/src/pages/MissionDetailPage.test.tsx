import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { MissionState } from '../lib/types';

let missionForHook: MissionState;

vi.mock('../hooks/useMission', () => ({
  useMission: () => ({
    mission: missionForHook,
    loading: false,
    error: null,
  }),
}));

import MissionDetailPage from './MissionDetailPage';

const mockMission: MissionState = {
  mission_id: 'mission-123',
  spec: {
    name: 'Mission Alpha',
    goal: 'Validate the mission detail page',
    definition_of_done: ['All acceptance criteria pass'],
    tasks: [
      { id: 'task-1', title: 'First task', description: 'First', acceptance_criteria: [], dependencies: [], max_retries: 3, output_artifacts: [] },
      { id: 'task-2', title: 'Second task', description: 'Second', acceptance_criteria: [], dependencies: [], max_retries: 3, output_artifacts: [] },
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
};

missionForHook = mockMission;

describe('MissionDetailPage', () => {
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
    expect(markup).toContain('Tasks Completed');
    expect(markup).toContain('Duration');
    expect(markup).toContain('Total Retries');
    expect(markup).toContain('Avg Review Score');
    expect(markup).toContain('Human Interventions');
    expect(markup).toContain('Worker Agent');
    expect(markup).toContain('/mission/mission-123/task/task-1');
    expect(markup).toContain('Event Log');
    expect(markup).not.toContain('event-0');
    expect(markup).toContain('event-54');
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

    expect(markup).toContain('Tasks Completed');
    expect(markup).toContain('1 / 2');
    expect(markup).toContain('text-blue bg-blue-bg border-blue/20">active</span>');
  });
});
