import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_LABS_CONFIG, MISSIONS_ROUTE, isBlackHoleEnabled, type LabsConfig } from './lib/types';

const api = vi.hoisted(() => ({
  getConfig: vi.fn(),
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
  api.selectLabsConfig.mockImplementation((config) => config?.labs ?? DEFAULT_LABS_CONFIG);
});

vi.mock('./lib/api', () => ({
  getConfig: api.getConfig,
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

vi.mock('./pages/MissionDetailPage', () => ({
  default: function MissionDetailPage() {
    return <div data-testid="page">Mission detail page</div>;
  },
}));

vi.mock('./pages/TaskDetailPage', () => ({
  default: function TaskDetailPage() {
    return <div data-testid="page">Task detail page</div>;
  },
}));

vi.mock('./pages/PlanModePage', () => ({
  default: function PlanModePage({ labs }: { labs: LabsConfig }) {
    return <div data-testid="page">Plan mode page {String(isBlackHoleEnabled(labs))}</div>;
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
  it('renders the shell and the plan route', async () => {
    const { root, container } = renderAt('/plan');
    await flushPromises();

    expect(api.getConfig).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[data-testid="sidebar"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="hudbar"]')).toBeTruthy();
    expect(container.textContent).toContain('Plan mode page true');

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

    expect(window.location.pathname).toBe(MISSIONS_ROUTE);
    expect(container.textContent).toContain('Missions page false');
    expect(container.textContent).not.toContain('Black hole page');

    act(() => {
      root.unmount();
    });
  });

  it('renders the mission route', async () => {
    const { root, container } = renderAt('/mission/mission-123');
    await flushPromises();

    expect(container.textContent).toContain('Mission detail page');

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
