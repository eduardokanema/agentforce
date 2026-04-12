import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  configureConnector,
  deleteConnector,
  getPlanDraft,
  getConnectors,
  getTaskAttempts,
  injectPrompt,
  markTaskFailed,
  resolveHumanBlock,
  retryPlanRun,
  retryTask,
  stopTask,
  testConnector,
} from './api';

describe('connectors API client', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('fetches connectors with a GET request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([{ name: 'github', display_name: 'GitHub', active: true }]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await getConnectors();

    expect(fetchMock).toHaveBeenCalledWith('/api/connectors', {
      headers: { Accept: 'application/json' },
    });
  });

  it('configures a connector with POST body token and tests it with POST', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }));
    vi.stubGlobal('fetch', fetchMock);

    await configureConnector('github', 'secret-token');
    await testConnector('github');

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/connectors/github/configure', {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: 'secret-token' }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/connectors/github/test', {
      method: 'POST',
      headers: { Accept: 'application/json' },
    });
  });

  it('removes a connector with DELETE', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await deleteConnector('github');

    expect(fetchMock).toHaveBeenCalledWith('/api/connectors/github', {
      method: 'DELETE',
      headers: { Accept: 'application/json' },
    });
  });

  it('fetches task attempts and posts task control actions', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify([{ attempt_number: 1, output: 'first', score: 0 }]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await getTaskAttempts('mission-1', 'task-1');
    await stopTask('mission-1', 'task-1');
    await retryTask('mission-1', 'task-1');
    await injectPrompt('mission-1', 'task-1', 'please check');
    await resolveHumanBlock('mission-1', 'task-1', 'resolved');
    await resolveHumanBlock('mission-1', 'task-1', { choice_id: 'always_allow', message: 'ok' });
    await markTaskFailed('mission-1', 'task-1');

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/mission/mission-1/task/task-1/attempts',
      { headers: { Accept: 'application/json' } },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/mission/mission-1/task/task-1/stop',
      { method: 'POST', headers: { Accept: 'application/json' } },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/mission/mission-1/task/task-1/retry',
      { method: 'POST', headers: { Accept: 'application/json' } },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      '/api/mission/mission-1/task/task-1/inject',
      {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'please check' }),
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      '/api/mission/mission-1/task/task-1/resolve',
      {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'resolved' }),
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      '/api/mission/mission-1/task/task-1/resolve',
      {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ choice_id: 'always_allow', message: 'ok' }),
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      7,
      '/api/mission/mission-1/task/task-1/resolve',
      {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ failed: true }),
      },
    );
  });

  it('posts plan run retries to the retry endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ draft_id: 'draft-1', plan_run_id: 'run-2', status: 'queued' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await retryPlanRun('run-1');

    expect(fetchMock).toHaveBeenCalledWith('/api/plan/runs/run-1/retry', {
      method: 'POST',
      headers: { Accept: 'application/json' },
    });
  });

  it('normalizes legacy draft payloads with top-level name and empty draft_spec', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        id: 'add391ae-5f8a-43f5-87b5-2240d6ff544c',
        revision: 4,
        status: 'draft',
        name: 'Introduce A New Lab Session In',
        goal: 'Introduce a new Lab session in settings.',
        draft_spec: {},
        turns: [],
        validation: {},
        activity_log: [],
        approved_models: [],
        workspace_paths: ['/Users/eduardo/Projects/hermes/data/projects/agentforce'],
        companion_profile: {},
        draft_notes: [],
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const draft = await getPlanDraft('add391ae-5f8a-43f5-87b5-2240d6ff544c');

    expect(draft.draft_spec.name).toBe('Introduce A New Lab Session In');
    expect(draft.draft_spec.goal).toBe('Introduce a new Lab session in settings.');
    expect(draft.draft_spec.tasks).toEqual([]);
    expect(draft.draft_spec.definition_of_done).toEqual([]);
    expect(draft.draft_spec.caps.max_retries_per_task).toBe(3);
  });
});
