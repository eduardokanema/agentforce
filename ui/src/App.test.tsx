import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_LABS_CONFIG, PROJECTS_ROUTE, isBlackHoleEnabled, type LabsConfig } from './lib/types';

const api = vi.hoisted(() => ({
  getConfig: vi.fn(),
  lookupProjectByDraft: vi.fn(),
  lookupProjectByMission: vi.fn(),
  selectLabsConfig: vi.fn(),
}));

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
  api.getConfig.mockResolvedValue({ labs: { ...DEFAULT_LABS_CONFIG, black_hole_enabled: true } });
  api.lookupProjectByDraft.mockResolvedValue({ project_id: 'proj-1' });
  api.lookupProjectByMission.mockResolvedValue({ project_id: 'proj-1' });
  api.selectLabsConfig.mockImplementation((config) => config?.labs ?? DEFAULT_LABS_CONFIG);
});

vi.mock('./lib/api', () => ({
  getConfig: api.getConfig,
  lookupProjectByDraft: api.lookupProjectByDraft,
  lookupProjectByMission: api.lookupProjectByMission,
  selectLabsConfig: api.selectLabsConfig,
}));

vi.mock('./components/Sidebar', () => ({
  default: function Sidebar({ labs }: { labs: LabsConfig }) {
    return <div data-testid="sidebar">Sidebar {String(isBlackHoleEnabled(labs))}</div>;
  },
}));

vi.mock('./components/HudBar', () => ({
  default: function HudBar() {
    return <div data-testid="hudbar">HudBar</div>;
  },
}));

vi.mock('./pages/MissionsPage', () => ({
  default: function MissionsPage({ labs }: { labs: LabsConfig }) {
    return <div data-testid="page">Missions page {String(isBlackHoleEnabled(labs))}</div>;
  },
}));

vi.mock('./pages/ProjectsPage', () => ({
  default: function ProjectsPage() {
    return <div data-testid="page">Projects page</div>;
  },
}));

vi.mock('./pages/ProjectDetailPage', () => ({
  default: function ProjectDetailPage() {
    return <div data-testid="page">Project detail page</div>;
  },
}));

vi.mock('./pages/TaskDetailPage', () => ({
  default: function TaskDetailPage() {
    return <div data-testid="page">Task detail page</div>;
  },
}));

vi.mock('./pages/ProjectPlanPage', () => ({
  default: function ProjectPlanPage({ labs }: { labs: LabsConfig }) {
    return <div data-testid="page">Project plan page {String(isBlackHoleEnabled(labs))}</div>;
  },
}));

vi.mock('./pages/ProjectMissionPage', () => ({
  default: function ProjectMissionPage() {
    return <div data-testid="page">Project mission page</div>;
  },
}));

vi.mock('./pages/PlanRedirectPage', () => ({
  default: function PlanRedirectPage() {
    return <div data-testid="page">Plan redirect page</div>;
  },
}));

vi.mock('./pages/MissionRedirectPage', () => ({
  default: function MissionRedirectPage() {
    return <div data-testid="page">Mission redirect page</div>;
  },
}));

vi.mock('./pages/BlackHoleModePage', () => ({
  default: function BlackHoleModePage({ labs }: { labs: LabsConfig }) {
    return <div data-testid="page">Black hole page {String(isBlackHoleEnabled(labs))}</div>;
  },
}));

vi.mock('./pages/ConnectorsPage', () => ({
  default: function ConnectorsPage() {
    return <div data-testid="page">Connectors page</div>;
  },
}));

vi.mock('./pages/TelemetryPage', () => ({
  default: function TelemetryPage() {
    return <div data-testid="page">Telemetry page</div>;
  },
}));

import App from './App';

function renderAt(pathname: string): { root: Root; container: HTMLDivElement } {
  window.history.pushState({}, '', pathname);
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(<App />);
  });

  return { root, container };
}

function flushPromises(): Promise<void> {
  return act(async () => {
    await Promise.resolve();
  });
}

afterEach(() => {
  document.body.innerHTML = '';
  window.history.pushState({}, '', '/');
  vi.clearAllMocks();
});

describe('App routes', () => {
  it('redirects the landing route to Projects', async () => {
    const { root, container } = renderAt('/');
    await flushPromises();

    expect(window.location.pathname).toBe('/projects');
    expect(container.textContent).toContain('Projects page');

    act(() => {
      root.unmount();
    });
  });

  it('renders the shell and the plan route', async () => {
    const { root, container } = renderAt('/plan');
    await flushPromises();

    expect(api.getConfig).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[data-testid="sidebar"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="hudbar"]')).toBeTruthy();
    expect(container.textContent).toContain('Plan redirect page');

    act(() => {
      root.unmount();
    });
  });

  it('renders the mission control route', async () => {
    const { root, container } = renderAt('/missions');
    await flushPromises();

    expect(container.textContent).toContain('Missions page true');

    act(() => {
      root.unmount();
    });
  });

  it('renders the black-hole route when Labs enables it', async () => {
    const { root, container } = renderAt('/black-hole');
    await flushPromises();

    expect(container.textContent).toContain('Black hole page true');

    act(() => {
      root.unmount();
    });
  });

  it('redirects the black-hole route when Labs disables it', async () => {
    api.getConfig.mockResolvedValue({ labs: DEFAULT_LABS_CONFIG });
    api.selectLabsConfig.mockImplementation(() => DEFAULT_LABS_CONFIG);

    const { root, container } = renderAt('/black-hole');
    await flushPromises();

    expect(window.location.pathname).toBe(PROJECTS_ROUTE);
    expect(container.textContent).toContain('Projects page');
    expect(container.textContent).not.toContain('Black hole page');

    act(() => {
      root.unmount();
    });
  });

  it('renders the project routes', async () => {
    const projects = renderAt('/projects');
    await flushPromises();
    expect(projects.container.textContent).toContain('Projects page');
    act(() => {
      projects.root.unmount();
    });

    const projectDetail = renderAt('/projects/proj-1/overview');
    await flushPromises();
    expect(projectDetail.container.textContent).toContain('Project detail page');
    act(() => {
      projectDetail.root.unmount();
    });

    const projectPlan = renderAt('/projects/proj-1/plan');
    await flushPromises();
    expect(projectPlan.container.textContent).toContain('Project plan page true');
    act(() => {
      projectPlan.root.unmount();
    });

    const projectMission = renderAt('/projects/proj-1/mission');
    await flushPromises();
    expect(projectMission.container.textContent).toContain('Project mission page');
    act(() => {
      projectMission.root.unmount();
    });
  });

  it('renders the mission route', async () => {
    const { root, container } = renderAt('/mission/mission-123');
    await flushPromises();

    expect(container.textContent).toContain('Mission redirect page');

    act(() => {
      root.unmount();
    });
  });

  it('renders the connectors and telemetry routes', async () => {
    const connectors = renderAt('/models');
    await flushPromises();
    expect(connectors.container.textContent).toContain('Connectors page');
    act(() => {
      connectors.root.unmount();
    });

    const telemetry = renderAt('/telemetry');
    await flushPromises();
    expect(telemetry.container.textContent).toContain('Telemetry page');
    act(() => {
      telemetry.root.unmount();
    });
  });
});
