import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  archiveProject: vi.fn(),
  deleteProject: vi.fn(),
  getProject: vi.fn(),
  unarchiveProject: vi.fn(),
  updateProject: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  archiveProject: api.archiveProject,
  deleteProject: api.deleteProject,
  getProject: api.getProject,
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
    api.unarchiveProject.mockReset();
    api.updateProject.mockReset();
    toastHarness.addToast.mockReset();
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('renders the project-first home surface with portfolio and scheduler data', async () => {
    api.getProject.mockResolvedValue({
      project: {
        project_id: 'proj-1',
        name: 'AgentForce',
        repo_root: '/tmp/agentforce',
        description: 'Keep the redesign inside one project container.',
        related_project_ids: ['proj-2'],
        settings: {
          working_directories: ['/tmp/agentforce/apps/core', '/tmp/agentforce/tests'],
        },
        archived_at: null,
        created_at: '2026-04-14T09:00:00Z',
        updated_at: '2026-04-14T10:00:00Z',
      },
      summary: {
        project_id: 'proj-1',
        name: 'AgentForce',
        repo_root: '/tmp/agentforce',
        primary_working_directory: '/tmp/agentforce/apps/core',
        workspace_count: 2,
        goal: 'Keep the redesign inside one project container.',
        planned_task_count: 4,
        current_stage: 'executing',
        current_plan_id: 'plan-1',
        current_mission_id: 'mission-1',
        next_action_label: 'Open workspace',
        mode: 'standard',
        status: 'running',
        active_cycle_id: 'plan-1',
        blocker: 'Touch scope conflict',
        next_action: 'Open workspace',
        active_mission_id: 'mission-1',
        archived_at: null,
        has_activity: true,
        updated_at: '2026-04-14T10:00:00Z',
        active_plan_count: 3,
        running_plan_count: 2,
        blocked_node_count: 1,
      },
      context: {
        repo_root: '/tmp/agentforce',
        primary_working_directory: '/tmp/agentforce/apps/core',
        working_directories: ['/tmp/agentforce/apps/core', '/tmp/agentforce/tests'],
        goal: 'Keep the redesign inside one project container.',
        definition_of_done: [],
        planned_task_count: 4,
        task_titles: ['Graph workspace'],
        mission_count: 1,
      },
      plans: [
        {
          plan_id: 'plan-1',
          project_id: 'proj-1',
          name: 'Workspace redesign',
          objective: 'Replace the dense shell with a DAG workspace.',
          status: 'running',
          quick_task: false,
          node_count: 4,
          selected_version_id: 'version-1',
          active_mission_run_id: 'run-1',
          mission_id: 'mission-1',
          merged_project_scope: ['proj-1', 'proj-2'],
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
        objective: 'Replace the dense shell with a DAG workspace.',
        status: 'running',
        quick_task: false,
        node_count: 4,
        selected_version_id: 'version-1',
        active_mission_run_id: 'run-1',
        mission_id: 'mission-1',
        merged_project_scope: ['proj-1', 'proj-2'],
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
              title: 'Graph workspace',
              description: 'Build the DAG workspace.',
              dependencies: [],
              subtasks: ['Render graph'],
              touch_scope: ['ui/src/pages/ProjectPlanPage.tsx'],
              outputs: [],
              owner_project_id: 'proj-1',
              merged_project_scope: ['proj-1'],
              evidence: [],
              working_directory: '/tmp/agentforce/apps/core',
              runtime: { status: 'running' },
            },
          ],
        },
        history: {
          versions: [
            {
              version_id: 'version-1',
              plan_id: 'plan-1',
              project_id: 'proj-1',
              name: 'Workspace redesign',
              objective: 'Replace the dense shell with a DAG workspace.',
              nodes: [],
              merged_project_scope: ['proj-1'],
              changelog: ['Approved from current graph with 4 node(s).'],
              planner_debug: { provider: 'deterministic' },
              launched_mission_run_id: 'run-1',
              created_at: '2026-04-14T09:30:00Z',
            },
          ],
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
        queue: [
          {
            plan_id: 'plan-1',
            plan_name: 'Workspace redesign',
            node_id: 'node-2',
            title: 'History / Debug surface',
            status: 'ready',
            scheduler_priority: 120,
            owning_project_id: 'proj-1',
            merged_project_scope: ['proj-1'],
          },
        ],
        blocked: [
          {
            plan_id: 'plan-2',
            plan_name: 'Cross-project follow-up',
            node_id: 'node-3',
            title: 'Shared auth touchpoint',
            status: 'blocked',
            scheduler_priority: 0,
            conflict_reason: 'Touch scope conflict with active node node-1',
            owning_project_id: 'proj-2',
            merged_project_scope: ['proj-1', 'proj-2'],
          },
        ],
        running: [
          {
            plan_id: 'plan-1',
            plan_name: 'Workspace redesign',
            node_id: 'node-1',
            title: 'Graph workspace',
            status: 'running',
            scheduler_priority: 130,
            owning_project_id: 'proj-1',
            merged_project_scope: ['proj-1'],
          },
        ],
        plans: [],
      },
      history: {
        plan_versions: [],
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
      },
      cycles: [],
      active_cycle_id: 'plan-1',
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

    expect(api.getProject).toHaveBeenCalledWith('proj-1');
    expect(container.textContent).toContain('Project Home');
    expect(container.textContent).toContain('Plan Portfolio');
    expect(container.textContent).toContain('Current Blockers');
    expect(container.textContent).toContain('Selected Plan');
    expect(container.textContent).toContain('Workspace redesign');
    expect(container.textContent).toContain('3');
    expect(container.textContent).toContain('Touch scope conflict with active node node-1');
    expect(container.querySelector('a[href="/projects/proj-1/plan?plan=plan-1"]')).toBeTruthy();
    expect(container.querySelector('a[href="/projects"]')).toBeTruthy();
  });
});
