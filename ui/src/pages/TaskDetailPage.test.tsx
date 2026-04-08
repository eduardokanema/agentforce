import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { MissionState } from '../lib/types';

let missionForHook: MissionState;
let streamForHook: { lines: string[]; done: boolean };

vi.mock('../hooks/useMission', () => ({
  useMission: () => ({
    mission: missionForHook,
    loading: false,
    error: null,
  }),
}));

vi.mock('../hooks/useTaskStream', () => ({
  useTaskStream: () => streamForHook,
}));

import TaskDetailPage from './TaskDetailPage';

const mockMission: MissionState = {
  mission_id: 'mission-123',
  spec: {
    name: 'Mission Alpha',
    goal: 'Validate the task detail page',
    definition_of_done: ['All acceptance criteria pass'],
    tasks: [
      {
        id: 'task-1',
        title: 'Investigate stream',
        description: 'Investigate live terminal stream handling',
        acceptance_criteria: ['Stream renders lines'],
        dependencies: [],
        max_retries: 3,
        output_artifacts: [],
      },
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
      status: 'blocked',
      retries: 2,
      review_score: 6,
      human_intervention_needed: true,
      last_updated: '2024-01-01T00:00:00Z',
      worker_output: 'booting worker\nready',
      review_feedback: 'Needs another pass.',
      blocking_issues: ['Waiting on API contract', 'Missing fixture coverage'],
      human_intervention_message: 'Please approve the API schema before continuing.',
      error_message: 'Worker crashed while parsing input.',
    },
  },
  started_at: '2024-01-01T00:00:00Z',
  total_retries: 2,
  total_human_interventions: 1,
  total_tokens_used: 100,
  estimated_cost_usd: 0.5,
  event_log: [],
  completed_at: null,
  caps_hit: {},
  working_dir: '/tmp/work',
  worker_agent: 'opencode',
  worker_model: 'gpt-5',
};

describe('TaskDetailPage', () => {
  it('renders the task detail layout from useMission and useTaskStream', () => {
    missionForHook = mockMission;
    streamForHook = {
      lines: ['booting worker', 'ready', 'queued follow-up'],
      done: true,
    };

    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/mission/mission-123/task/task-1']}>
        <Routes>
          <Route path="/mission/:mission_id/task/:task_id" element={<TaskDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(markup).toContain('Missions');
    expect(markup).toContain('Mission Alpha');
    expect(markup).toContain('Investigate stream');
    expect(markup).toContain('Status');
    expect(markup).toContain('Review Score');
    expect(markup).toContain('Retries');
    expect(markup).toContain('Duration');
    expect(markup).toContain('booting worker');
    expect(markup).toContain('queued follow-up');
    expect(markup).toContain('(stream complete)');
    expect(markup).toContain('Needs another pass.');
    expect(markup).toContain('Waiting on API contract');
    expect(markup).toContain('Please approve the API schema before continuing.');
    expect(markup).toContain('Worker crashed while parsing input.');
  });

  it('omits conditional panels when the task has no extra review data', () => {
    missionForHook = {
      ...mockMission,
      task_states: {
        'task-1': {
          ...mockMission.task_states['task-1'],
          review_feedback: '',
          blocking_issues: [],
          human_intervention_message: '',
          error_message: '',
        },
      },
    };
    streamForHook = { lines: [], done: false };

    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/mission/mission-123/task/task-1']}>
        <Routes>
          <Route path="/mission/:mission_id/task/:task_id" element={<TaskDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(markup).not.toContain('Review Feedback');
    expect(markup).not.toContain('Blocking Issues');
    expect(markup).not.toContain('Human Intervention');
    expect(markup).not.toContain('Error');
  });
});
