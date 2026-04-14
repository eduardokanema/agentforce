import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  archiveProject,
  configureConnector,
  createProject,
  deleteConnector,
  deleteProject,
  getProject,
  getProjects,
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
  unarchiveProject,
  updateProject,
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

  it('fetches project summaries and a project harness detail', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify([{
          project_id: 'proj-1',
          name: 'AgentForce',
          repo_root: '/tmp/agentforce',
          primary_working_directory: '/tmp/agentforce/apps/core',
          workspace_count: 2,
          goal: 'Make planning clearer',
          planned_task_count: 3,
          mode: 'standard',
          status: 'planning',
          active_cycle_id: 'cycle-1',
          blocker: null,
          next_action: 'Review plan',
          active_mission_id: null,
          updated_at: '2026-04-14T10:00:00Z',
        }]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({
          summary: {
            project_id: 'proj-1',
            name: 'AgentForce',
            repo_root: '/tmp/agentforce',
            primary_working_directory: '/tmp/agentforce/apps/core',
            workspace_count: 2,
            goal: 'Make planning clearer',
            planned_task_count: 3,
            mode: 'standard',
            status: 'planning',
            active_cycle_id: 'cycle-1',
            blocker: null,
            next_action: 'Review plan',
            active_mission_id: null,
            updated_at: '2026-04-14T10:00:00Z',
          },
          context: {
            repo_root: '/tmp/agentforce',
            primary_working_directory: '/tmp/agentforce/apps/core',
            working_directories: ['/tmp/agentforce/apps/core', '/tmp/agentforce/tests'],
            goal: 'Make planning clearer',
            definition_of_done: ['Plan is clear'],
            planned_task_count: 3,
            task_titles: ['Task one', 'Task two'],
            mission_count: 0,
          },
          cycles: [{
            cycle_id: 'cycle-1',
            title: 'Initial plan',
            status: 'planning',
            draft_id: 'draft-1',
            mission_id: null,
            latest_plan_run_id: 'run-1',
            latest_plan_version_id: 'version-1',
            predecessor_cycle_id: null,
            successor_cycle_id: null,
            blocker: null,
            next_action: 'Launch mission',
            created_at: '2026-04-14T09:00:00Z',
            updated_at: '2026-04-14T10:00:00Z',
            evidence: {
              status: 'pending',
              contract_summary: 'Draft validation pending',
              verifier_summary: null,
              artifact_summary: null,
              stream_summary: null,
              items: [],
            },
          }],
          active_cycle_id: 'cycle-1',
          active_cycle: {
            cycle_id: 'cycle-1',
            title: 'Initial plan',
            status: 'planning',
            draft_id: 'draft-1',
            mission_id: null,
            latest_plan_run_id: 'run-1',
            latest_plan_version_id: 'version-1',
            predecessor_cycle_id: null,
            successor_cycle_id: null,
            blocker: null,
            next_action: 'Launch mission',
            created_at: '2026-04-14T09:00:00Z',
            updated_at: '2026-04-14T10:00:00Z',
            evidence: {
              status: 'pending',
              contract_summary: 'Draft validation pending',
              verifier_summary: null,
              artifact_summary: null,
              stream_summary: null,
              items: [],
            },
          },
          evidence: {
            status: 'pending',
            contract_summary: 'Draft validation pending',
            verifier_summary: null,
            artifact_summary: null,
            stream_summary: null,
            items: [],
          },
          docs_status: {
            implemented: ['docs tree'],
            planned: ['backend routes'],
          },
          policy_summary: {
            mode: 'standard',
            derived: true,
            optimize_available: false,
          },
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    await getProjects();
    await getProject('proj-1');

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/projects', {
      headers: { Accept: 'application/json' },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/project/proj-1', {
      headers: { Accept: 'application/json' },
    });
  });

  it('creates, updates, archives, unarchives, and deletes projects', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ summary: { project_id: 'proj-1' } }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ summary: { project_id: 'proj-1' } }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await createProject({
      repo_root: '/tmp/agentforce',
      name: 'AgentForce',
      goal: 'Clarify planning',
      working_directories: ['/tmp/agentforce/apps/core'],
    });
    await updateProject('proj-1', {
      name: 'AgentForce Updated',
      goal: 'Updated goal',
      working_directories: ['/tmp/agentforce/tests'],
    });
    await archiveProject('proj-1');
    await unarchiveProject('proj-1');
    await deleteProject('proj-1');

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/projects', {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({
        repo_root: '/tmp/agentforce',
        name: 'AgentForce',
        goal: 'Clarify planning',
        working_directories: ['/tmp/agentforce/apps/core'],
      }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/project/proj-1', {
      method: 'PATCH',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: 'AgentForce Updated',
        goal: 'Updated goal',
        working_directories: ['/tmp/agentforce/tests'],
      }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/project/proj-1/archive', {
      method: 'POST',
      headers: { Accept: 'application/json' },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(4, '/api/project/proj-1/unarchive', {
      method: 'POST',
      headers: { Accept: 'application/json' },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(5, '/api/project/proj-1', {
      method: 'DELETE',
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
