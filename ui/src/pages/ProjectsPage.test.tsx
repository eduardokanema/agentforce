import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  archiveProject: vi.fn(),
  createProject: vi.fn(),
  getProjects: vi.fn(),
  unarchiveProject: vi.fn(),
}));

const toastHarness = vi.hoisted(() => ({
  addToast: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  archiveProject: api.archiveProject,
  createProject: api.createProject,
  getProjects: api.getProjects,
  unarchiveProject: api.unarchiveProject,
}));

vi.mock('../hooks/useToast', () => ({
  useToast: () => toastHarness,
}));

import ProjectsPage from './ProjectsPage';

function renderPage(): HTMLDivElement {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <MemoryRouter>
        <ProjectsPage />
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

describe('ProjectsPage', () => {
  beforeEach(() => {
    api.archiveProject.mockReset();
    api.createProject.mockReset();
    api.getProjects.mockReset();
    api.unarchiveProject.mockReset();
    toastHarness.addToast.mockReset();
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('shows a loading skeleton while projects are fetched', () => {
    api.getProjects.mockReturnValue(new Promise(() => undefined));

    const container = renderPage();

    expect(container.textContent).toContain('Projects');
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(3);
    expect(container.textContent).not.toContain('No projects yet');
  });

  it('renders an empty state when no projects exist', async () => {
    api.getProjects.mockResolvedValue([]);

    const container = renderPage();
    await flushPromises();

    expect(container.textContent).toContain('No projects yet. Create a project to start the brief, spec, tasks, and mission in one place.');
  });

  it('renders an error state and retry action when loading fails', async () => {
    api.getProjects.mockRejectedValue(new Error('boom'));

    const container = renderPage();
    await flushPromises();

    expect(container.querySelector('[role="alert"]')).toBeTruthy();
    expect(container.textContent).toContain('Unable to load projects');
    expect(container.textContent).toContain('boom');
    expect(container.querySelector('button')).toBeTruthy();
  });

  it('renders cards with the requested project fields and detail links', async () => {
    api.getProjects.mockResolvedValue([
      {
        project_id: 'proj-1',
        name: 'AgentForce',
        repo_root: '/tmp/agentforce',
        primary_working_directory: '/tmp/agentforce/apps/core',
        workspace_count: 2,
        goal: 'Make planning clearer before launch',
        planned_task_count: 4,
        current_stage: 'blocked',
        current_plan_id: 'draft-1',
        current_mission_id: 'mission-1',
        next_action_label: 'Investigate pipeline drift',
        mode: 'optimize',
        status: 'blocked',
        blocker: 'Waiting on config',
        next_action: 'Investigate pipeline drift',
        active_cycle_id: 'cycle-1',
        active_mission_id: 'mission-1',
        archived_at: null,
        has_activity: true,
        updated_at: '2026-04-14T10:00:00Z',
      },
    ]);

    const container = renderPage();
    await flushPromises();

    expect(container.textContent).toContain('AgentForce');
    expect(container.textContent).toContain('/tmp/agentforce');
    expect(container.textContent).toContain('/tmp/agentforce/apps/core');
    expect(container.textContent).toContain('Blocked');
    expect(container.textContent).toContain('Waiting on config');
    expect(container.textContent).toContain('Investigate pipeline drift');
    expect(container.textContent).toContain('Make planning clearer before launch');
    expect(container.textContent).toContain('4');
    expect(container.textContent).toContain('2 working directories');
    expect(container.textContent).toContain('Optimize');
    expect(container.textContent).toContain('Updated');
    expect(container.querySelector('a[href="/projects/proj-1/overview"]')).toBeTruthy();
  });
});
