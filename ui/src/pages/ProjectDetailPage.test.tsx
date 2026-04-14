import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  archiveProject: vi.fn(),
  deleteProject: vi.fn(),
  getProject: vi.fn(),
  getPlanDraft: vi.fn(),
  getMission: vi.fn(),
  unarchiveProject: vi.fn(),
  updateProject: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  archiveProject: api.archiveProject,
  deleteProject: api.deleteProject,
  getProject: api.getProject,
  getPlanDraft: api.getPlanDraft,
  getMission: api.getMission,
  unarchiveProject: api.unarchiveProject,
  updateProject: api.updateProject,
}));

const toastHarness = vi.hoisted(() => ({
  addToast: vi.fn(),
}));

vi.mock('../hooks/useToast', () => ({
  useToast: () => toastHarness,
}));

import ProjectDetailPage from './ProjectDetailPage';

function renderPage(initialEntry = '/projects/proj-1/overview'): HTMLDivElement {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/projects/:id/:section" element={<ProjectDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
  });

  return container;
}

function flushPromises(): Promise<void> {
  return act(async () => {
    await Promise.resolve();
  });
}

describe('ProjectDetailPage', () => {
  beforeEach(() => {
    api.archiveProject.mockReset();
    api.deleteProject.mockReset();
    api.getProject.mockReset();
    api.getPlanDraft.mockReset();
    api.getMission.mockReset();
    api.unarchiveProject.mockReset();
    api.updateProject.mockReset();
    toastHarness.addToast.mockReset();
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('renders the selected project harness details', async () => {
    api.getPlanDraft.mockResolvedValue({
      id: 'draft-1',
      revision: 1,
      status: 'draft',
      draft_kind: 'simple_plan',
      draft_spec: {
        name: 'AgentForce',
        goal: 'Goal',
        definition_of_done: [],
        tasks: [
          { id: 'task-1', title: 'Task One', description: 'Desc', acceptance_criteria: [], dependencies: [], max_retries: 3, output_artifacts: [] },
        ],
        caps: {
          max_tokens_per_task: 1000,
          max_retries_global: 3,
          max_retries_per_task: 3,
          max_wall_time_minutes: 30,
          max_human_interventions: 1,
          max_concurrent_workers: 1,
        },
      },
      turns: [],
      validation: {},
      activity_log: [],
      approved_models: [],
      workspace_paths: ['/tmp/agentforce'],
      companion_profile: {},
      draft_notes: [],
      preflight_status: 'not_needed',
      preflight_questions: [],
      preflight_answers: {},
      plan_runs: [{
        id: 'run-1',
        draft_id: 'draft-1',
        base_revision: 1,
        head_revision_seen: 1,
        status: 'running',
        trigger_kind: 'manual',
        trigger_message: 'go',
        created_at: '2026-04-14T10:00:00Z',
        current_step: 'resolver',
        steps: [],
      }],
      plan_versions: [],
      planning_follow_ups: [],
      repair_questions: [],
      repair_answers: {},
      repair_issues: [],
    });
    api.getMission.mockResolvedValue({
      mission_id: 'mission-1',
      spec: {
        name: 'AgentForce',
        goal: 'Goal',
        definition_of_done: [],
        tasks: [
          { id: 'task-1', title: 'Task One', description: 'Desc', acceptance_criteria: [], dependencies: [], max_retries: 3, output_artifacts: [] },
        ],
        caps: {
          max_tokens_per_task: 1000,
          max_retries_global: 3,
          max_retries_per_task: 3,
          max_wall_time_minutes: 30,
          max_human_interventions: 1,
          max_concurrent_workers: 1,
        },
      },
      task_states: {
        'task-1': {
          task_id: 'task-1',
          status: 'in_progress',
          retries: 0,
          review_score: 0,
          human_intervention_needed: false,
          last_updated: '2026-04-14T10:00:00Z',
        },
      },
      started_at: '2026-04-14T10:00:00Z',
      total_retries: 2,
      total_human_interventions: 0,
      total_tokens_used: 100,
      estimated_cost_usd: 0.1,
    });
    api.getProject.mockResolvedValue({
      summary: {
        project_id: 'proj-1',
        name: 'AgentForce',
        repo_root: '/tmp/agentforce',
        primary_working_directory: '/tmp/agentforce/apps/core',
        workspace_count: 2,
        goal: 'Goal',
        planned_task_count: 1,
        current_stage: 'executing',
        current_plan_id: 'draft-1',
        current_mission_id: 'mission-1',
        next_action_label: 'Ship the update',
        mode: 'standard',
        status: 'running',
        active_cycle_id: 'cycle-1',
        blocker: 'None',
        next_action: 'Ship the update',
        active_mission_id: 'mission-1',
        archived_at: null,
        has_activity: true,
        updated_at: '2026-04-14T10:00:00Z',
      },
      context: {
        repo_root: '/tmp/agentforce',
        primary_working_directory: '/tmp/agentforce/apps/core',
        working_directories: ['/tmp/agentforce/apps/core', '/tmp/agentforce/tests'],
        goal: 'Goal',
        definition_of_done: ['Done means shipped'],
        planned_task_count: 1,
        task_titles: ['Task One'],
        mission_count: 1,
      },
      cycles: [
        {
          cycle_id: 'cycle-1',
          title: 'Initial cycle',
          status: 'running',
          draft_id: 'draft-1',
          mission_id: 'mission-1',
          latest_plan_run_id: 'run-1',
          latest_plan_version_id: 'version-1',
          predecessor_cycle_id: null,
          successor_cycle_id: null,
          blocker: 'None',
          next_action: 'Ship the update',
          created_at: '2026-04-14T09:00:00Z',
          updated_at: '2026-04-14T10:00:00Z',
          evidence: {
            status: 'pending',
            contract_summary: 'Awaiting review',
            verifier_summary: null,
            artifact_summary: null,
            stream_summary: null,
            items: [],
          },
        },
      ],
      active_cycle_id: 'cycle-1',
      active_cycle: null,
      evidence: {
        status: 'pending',
        contract_summary: 'Awaiting review',
        verifier_summary: null,
        artifact_summary: null,
        stream_summary: null,
        items: [],
      },
      docs_status: {
        implemented: ['README.md'],
        planned: ['ui shell'],
      },
      policy_summary: {
        mode: 'standard',
        derived: true,
        optimize_available: false,
      },
      lifecycle: {
        archived: false,
        archived_at: null,
        can_archive: true,
        can_unarchive: false,
        can_delete: false,
        can_edit: true,
        has_activity: true,
      },
    });

    const container = renderPage();
    await flushPromises();
    await flushPromises();

    expect(api.getProject).toHaveBeenCalledWith('proj-1');
    expect(api.getPlanDraft).toHaveBeenCalledWith('draft-1');
    expect(api.getMission).toHaveBeenCalledWith('mission-1');
    expect(container.textContent).toContain('AgentForce');
    expect(container.textContent).toContain('/tmp/agentforce');
    expect(container.textContent).toContain('Back to Projects');
    expect(container.textContent).toContain('Project Context');
    expect(container.textContent).toContain('Now');
    expect(container.textContent).toContain('Next');
    expect(container.textContent).toContain('Evidence');
    expect(container.textContent).toContain('Plan');
    expect(container.textContent).toContain('Mission');
    expect(container.textContent).toContain('History');
    expect(container.textContent).toContain('/tmp/agentforce/apps/core');
    expect(container.textContent).toContain('Done means shipped');
    expect(container.textContent).toContain('Plan status');
    expect(container.textContent).toContain('Running');
    expect(container.textContent).toContain('Resolver');
    expect(container.textContent).toContain('Mission progress');
    expect(container.textContent).toContain('0/1 tasks approved');
    expect(container.textContent).toContain('Task One');
    expect(container.textContent).not.toContain('Initial cycle');
    expect(container.textContent).toContain('README.md');
    expect(container.textContent).toContain('ui shell');
    expect(container.querySelector('a[href="/projects/proj-1/plan"]')).toBeTruthy();
    expect(container.querySelector('a[href="/projects/proj-1/mission"]')).toBeTruthy();
    expect(container.querySelector('a[href="/projects"]')).toBeTruthy();
  });
});
