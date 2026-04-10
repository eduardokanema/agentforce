import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  configureConnector,
  deleteConnector,
  getConnectors,
  getTaskAttempts,
  injectPrompt,
  markTaskFailed,
  resolveHumanBlock,
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
});
