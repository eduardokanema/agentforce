import { act, type ReactElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MissionState } from '../lib/types';

let missionForHook: MissionState;
let streamForHook: { lines: string[]; done: boolean };

const apiHarness = vi.hoisted(() => ({
  stopTask: vi.fn(async () => undefined),
  retryTask: vi.fn(async () => undefined),
  injectPrompt: vi.fn(async () => undefined),
  resolveHumanBlock: vi.fn(async () => undefined),
  markTaskFailed: vi.fn(async () => undefined),
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

vi.mock('../hooks/useTaskStream', () => ({
  useTaskStream: () => streamForHook,
}));

vi.mock('../lib/api', () => ({
  stopTask: apiHarness.stopTask,
  retryTask: apiHarness.retryTask,
  injectPrompt: apiHarness.injectPrompt,
  resolveHumanBlock: apiHarness.resolveHumanBlock,
  markTaskFailed: apiHarness.markTaskFailed,
}));

vi.mock('../hooks/useToast', () => ({
  useToast: () => toastHarness,
}));

vi.mock('../components/Terminal', () => ({
  default: function TerminalMock({ lines, done }: { lines: string[]; done: boolean }) {
    return (
      <div data-terminal-mock="true">
        <div>{lines.join('\n')}</div>
        <div>{done ? 'done' : 'active'}</div>
      </div>
    );
  },
}));

vi.mock('../components/ReviewPanel', () => ({
  default: function ReviewPanelMock(props: {
    feedback: string;
    score: number;
    criteriaResults?: Record<string, string>;
    blockingIssues?: string[];
    suggestions?: string[];
  }) {
    return <pre data-review-panel>{JSON.stringify(props)}</pre>;
  },
}));

vi.mock('../components/RetryHistory', () => ({
  default: function RetryHistoryMock({ currentRetryCount }: { currentRetryCount: number }) {
    return <div data-retry-history>{currentRetryCount}</div>;
  },
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
      status: 'in_progress',
      retries: 2,
      retry_count: 2,
      review_score: 6,
      human_intervention_needed: true,
      last_updated: '2024-01-01T00:00:00Z',
      tokens_in: 111,
      tokens_out: 222,
      cost_usd: 1.23,
      worker_output: 'booting worker\nready',
      review_feedback:
        '{"feedback":"Needs another pass.","score":6,"criteriaResults":{"coverage":"met"},"blockingIssues":["Waiting on API contract"],"suggestions":["Add a test for the retry flow."]}',
      blocking_issues: ['Missing fixture coverage'],
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

function renderToContainer(element: ReactElement): { root: Root; container: HTMLDivElement } {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(element);
  });

  return { root, container };
}

describe('TaskDetailPage', () => {
  afterEach(() => {
    apiHarness.stopTask.mockClear();
    apiHarness.retryTask.mockClear();
    apiHarness.injectPrompt.mockClear();
    apiHarness.resolveHumanBlock.mockClear();
    apiHarness.markTaskFailed.mockClear();
    toastHarness.addToast.mockClear();
    document.body.innerHTML = '';
  });

  it('renders task controls, token meter, review panel props, retry history, and inject panel', () => {
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
    expect(markup).toContain('↓ 111 in');
    expect(markup).toContain('↑ 222 out');
    expect(markup).toContain('$1.2300');
    expect(markup).toContain('Stop');
    expect(markup).toContain('Retry');
    expect(markup).toContain('Mark Failed');
    expect(markup).toContain('Resolve Block');
    expect(markup).toContain('Send Instruction to Agent');
    expect(markup).toContain('data-review-panel');
    expect(markup).toContain('Needs another pass.');
    expect(markup).toContain('Waiting on API contract');
    expect(markup).toContain('Add a test for the retry flow.');
    expect(markup).toContain('data-retry-history');
    expect(markup).toContain('2');
    expect(markup).toContain('booting worker');
    expect(markup).toContain('queued follow-up');
    expect(markup).toContain('(stream complete)');
  });

  it('hides the review, retry history, and inject panel when the task has no extras', () => {
    missionForHook = {
      ...mockMission,
      task_states: {
      'task-1': {
          ...mockMission.task_states['task-1'],
          status: 'blocked',
          retry_count: 0,
          retries: 0,
          review_score: 0,
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

    expect(markup).not.toContain('data-review-panel');
    expect(markup).not.toContain('data-retry-history');
    expect(markup).not.toContain('Send Instruction to Agent');
  });

  it('confirms before invoking task actions and sends instructions from the panel', async () => {
    missionForHook = mockMission;
    streamForHook = { lines: ['booting worker'], done: false };

    const { container, root } = renderToContainer(
      <MemoryRouter initialEntries={['/mission/mission-123/task/task-1']}>
        <Routes>
          <Route path="/mission/:mission_id/task/:task_id" element={<TaskDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const buttons = Array.from(container.querySelectorAll('button'));
    const stopButton = buttons.find((button) => button.textContent === 'Stop');
    const retryButton = buttons.find((button) => button.textContent === 'Retry');
    const markFailedButton = buttons.find((button) => button.textContent === 'Mark Failed');
    const resolveButton = buttons.find((button) => button.textContent === 'Resolve Block');
    expect(stopButton).toBeDefined();
    expect(retryButton).toBeDefined();
    expect(markFailedButton).toBeDefined();
    expect(resolveButton).toBeDefined();
    expect(stopButton?.disabled).toBe(false);
    expect(retryButton?.disabled).toBe(true);
    expect(markFailedButton?.disabled).toBe(true);
    expect(resolveButton?.disabled).toBe(true);

    const injectPanel = container.querySelector('details.sec');
    expect(injectPanel).not.toBeNull();

    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    expect(textarea).not.toBeNull();

    await act(async () => {
      Simulate.change(textarea, { target: { value: 'Please re-check the output' } } as any);
    });

    const sendButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Send Instruction'),
    );
    expect(sendButton?.disabled).toBe(false);

    await act(async () => {
      sendButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(apiHarness.injectPrompt).toHaveBeenCalledWith(
      'mission-123',
      'task-1',
      'Please re-check the output',
    );
    expect(toastHarness.addToast).toHaveBeenCalledWith('Instruction delivered', 'success');

    await act(async () => {
      stopButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.textContent).toContain('Stop task "Investigate stream"?');
    const stopConfirm = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === 'Stop Task',
    ) as HTMLButtonElement;
    await act(async () => {
      stopConfirm.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(apiHarness.stopTask).toHaveBeenCalledWith('mission-123', 'task-1');
    expect(toastHarness.addToast).toHaveBeenCalledWith('Task stopped', 'success');

    act(() => {
      root.unmount();
    });
  });

  it('enables retry and resolve actions when the task needs human intervention', async () => {
    missionForHook = {
      ...mockMission,
      task_states: {
        'task-1': {
          ...mockMission.task_states['task-1'],
          status: 'needs_human',
          retry_count: 1,
          retries: 1,
        },
      },
    };
    streamForHook = { lines: ['waiting on human'], done: true };

    const { container, root } = renderToContainer(
      <MemoryRouter initialEntries={['/mission/mission-123/task/task-1']}>
        <Routes>
          <Route path="/mission/:mission_id/task/:task_id" element={<TaskDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const buttons = Array.from(container.querySelectorAll('button'));
    const retryButton = buttons.find((button) => button.textContent === 'Retry');
    const markFailedButton = buttons.find((button) => button.textContent === 'Mark Failed');
    const resolveButton = buttons.find((button) => button.textContent === 'Resolve Block');

    expect(retryButton?.disabled).toBe(false);
    expect(markFailedButton?.disabled).toBe(false);
    expect(resolveButton?.disabled).toBe(false);

    await act(async () => {
      retryButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.textContent).toContain('Retry task "Investigate stream"?');
    const retryConfirm = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === 'Retry Task',
    ) as HTMLButtonElement;
    await act(async () => {
      retryConfirm.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(apiHarness.retryTask).toHaveBeenCalledWith('mission-123', 'task-1');
    expect(toastHarness.addToast).toHaveBeenCalledWith('Task retry queued', 'success');

    await act(async () => {
      markFailedButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.textContent).toContain('Mark task "Investigate stream" as failed?');
    const markFailedDialog = container.querySelector('[role="dialog"]') as HTMLElement;
    expect(markFailedDialog).toBeTruthy();
    const markFailedConfirm = Array.from(markFailedDialog.querySelectorAll('button'))[1] as HTMLButtonElement;
    await act(async () => {
      markFailedConfirm.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(apiHarness.markTaskFailed).toHaveBeenCalledWith('mission-123', 'task-1');
    expect(toastHarness.addToast).toHaveBeenCalledWith('Task marked as failed', 'success');

    await act(async () => {
      resolveButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.textContent).toContain('Resolve human block for task "Investigate stream"?');
    const resolveDialog = container.querySelector('[role="dialog"]') as HTMLElement;
    const resolveConfirm = Array.from(resolveDialog.querySelectorAll('button'))[1] as HTMLButtonElement;
    await act(async () => {
      resolveConfirm.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(apiHarness.resolveHumanBlock).toHaveBeenCalledWith(
      'mission-123',
      'task-1',
      'Human guidance applied.',
    );
    expect(toastHarness.addToast).toHaveBeenCalledWith('Human block resolved', 'success');

    act(() => {
      root.unmount();
    });
  });
});
