import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  approveProjectPlan: vi.fn(),
  createProjectPlan: vi.fn(),
  getProject: vi.fn(),
  readjustProjectPlan: vi.fn(),
  startProjectPlan: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  approveProjectPlan: api.approveProjectPlan,
  createProjectPlan: api.createProjectPlan,
  getProject: api.getProject,
  readjustProjectPlan: api.readjustProjectPlan,
  startProjectPlan: api.startProjectPlan,
}));

const toastHarness = vi.hoisted(() => ({
  addToast: vi.fn(),
}));

vi.mock('../hooks/useToast', () => ({
  useToast: () => toastHarness,
}));

import ProjectPlanPage from './ProjectPlanPage';

function renderPage(initialEntry = '/projects/proj-1/plan?plan=plan-1'): HTMLDivElement {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/projects/:id/plan" element={<ProjectPlanPage />} />
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

describe('ProjectPlanPage', () => {
  beforeEach(() => {
    api.approveProjectPlan.mockReset();
    api.createProjectPlan.mockReset();
    api.getProject.mockReset();
    api.readjustProjectPlan.mockReset();
    api.startProjectPlan.mockReset();
    toastHarness.addToast.mockReset();
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('renders the graph workspace, node drawer, and debug panel from the selected plan', async () => {
    api.getProject.mockResolvedValue({
      summary: {
        project_id: 'proj-1',
        name: 'AgentForce',
        repo_root: '/tmp/agentforce',
        primary_working_directory: '/tmp/agentforce/apps/core',
        workspace_count: 2,
        goal: 'Goal',
        planned_task_count: 2,
        current_stage: 'executing',
        current_plan_id: 'plan-1',
        current_mission_id: 'mission-1',
        next_action_label: 'Open workspace',
        mode: 'standard',
        status: 'running',
        active_cycle_id: 'plan-1',
        blocker: null,
        next_action: 'Open workspace',
        active_mission_id: 'mission-1',
        archived_at: null,
        has_activity: true,
        updated_at: '2026-04-14T10:00:00Z',
        active_plan_count: 2,
        running_plan_count: 1,
        blocked_node_count: 1,
      },
      context: {
        repo_root: '/tmp/agentforce',
        primary_working_directory: '/tmp/agentforce/apps/core',
        working_directories: ['/tmp/agentforce/apps/core', '/tmp/agentforce/tests'],
        goal: 'Goal',
        definition_of_done: [],
        planned_task_count: 2,
        task_titles: [],
        mission_count: 1,
      },
      plans: [
        {
          plan_id: 'plan-1',
          project_id: 'proj-1',
          name: 'Workspace redesign',
          objective: 'Replace the old shell.',
          status: 'running',
          quick_task: false,
          node_count: 2,
          selected_version_id: 'version-1',
          active_mission_run_id: 'run-1',
          mission_id: 'mission-1',
          merged_project_scope: ['proj-1'],
          planner_debug: { provider: 'deterministic' },
          created_at: '2026-04-14T09:00:00Z',
          updated_at: '2026-04-14T10:00:00Z',
          supersedes_plan_id: null,
        },
      ],
      selected_plan_id: 'plan-1',
      selected_plan: {
        plan_id: 'plan-1',
        project_id: 'proj-1',
        name: 'Workspace redesign',
        objective: 'Replace the old shell.',
        status: 'running',
        quick_task: false,
        node_count: 2,
        selected_version_id: 'version-1',
        active_mission_run_id: 'run-1',
        mission_id: 'mission-1',
        merged_project_scope: ['proj-1'],
        planner_debug: { provider: 'deterministic' },
        created_at: '2026-04-14T09:00:00Z',
        updated_at: '2026-04-14T10:00:00Z',
        supersedes_plan_id: null,
        graph: {
          plan_id: 'plan-1',
          selected_version_id: 'version-1',
          active_mission_run_id: 'run-1',
          nodes: [
            {
              node_id: 'node-1',
              title: 'Draft DAG page',
              description: 'Build the graph-first workspace.',
              dependencies: [],
              subtasks: ['Render nodes'],
              touch_scope: ['ui/src/pages/ProjectPlanPage.tsx'],
              outputs: ['ui/dist/workspace.html'],
              owner_project_id: 'proj-1',
              merged_project_scope: ['proj-1'],
              evidence: [],
              working_directory: '/tmp/agentforce/apps/core',
              runtime: { status: 'running', reason: null },
            },
            {
              node_id: 'node-2',
              title: 'Hide planner internals',
              description: 'Move debug details out of the main surface.',
              dependencies: ['node-1'],
              subtasks: ['Build debug panel'],
              touch_scope: ['ui/src/pages/ProjectDetailPage.tsx'],
              outputs: [],
              owner_project_id: 'proj-1',
              merged_project_scope: ['proj-1'],
              evidence: [],
              working_directory: '/tmp/agentforce/apps/core',
              runtime: { status: 'ready', reason: null },
            },
          ],
        },
        history: {
          versions: [],
          mission_runs: [
            {
              mission_run_id: 'run-1',
              plan_id: 'plan-1',
              plan_version_id: 'version-1',
              project_id: 'proj-1',
              mission_id: 'mission-1',
              status: 'running',
              node_states: [],
              created_at: '2026-04-14T09:30:00Z',
              started_at: '2026-04-14T09:31:00Z',
              completed_at: null,
              updated_at: '2026-04-14T10:00:00Z',
            },
          ],
          planner: { provider: 'deterministic' },
        },
      },
      scheduler: {
        project_id: 'proj-1',
        updated_at: '2026-04-14T10:00:00Z',
        queue: [],
        blocked: [],
        running: [],
        plans: [],
      },
      history: { plan_versions: [], mission_runs: [] },
      cycles: [],
      active_cycle_id: null,
      active_cycle: null,
      evidence: { status: 'pending', items: [] },
      docs_status: { implemented: [], planned: [] },
      policy_summary: { mode: 'standard', derived: false, optimize_available: false },
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

    expect(api.getProject).toHaveBeenCalledWith('proj-1', { planId: 'plan-1' });
    expect(container.textContent).toContain('Plan workspace');
    expect(container.textContent).toContain('Workspace redesign');
    expect(container.textContent).toContain('Draft DAG page');
    expect(container.textContent).toContain('Node drawer');
    expect(container.textContent).toContain('History / Debug');
    expect(container.textContent).toContain('Re-approve version');
    expect(container.textContent).toContain('Start mission overlay');
  });
});
