import { createRoot, type Root } from 'react-dom/client';
import { act, type ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
});

vi.mock('./components/Sidebar', () => ({
  default: function Sidebar() {
    return <div data-testid="sidebar">Sidebar</div>;
  },
}));

vi.mock('./components/HudBar', () => ({
  default: function HudBar() {
    return <div data-testid="hudbar">HudBar</div>;
  },
}));

vi.mock('./pages/MissionsPage', () => ({
  default: function MissionsPage() {
    return <div data-testid="page">Missions page</div>;
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
  default: function PlanModePage() {
    return <div data-testid="page">Plan mode page</div>;
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

afterEach(() => {
  document.body.innerHTML = '';
  window.history.pushState({}, '', '/');
});

describe('App routes', () => {
  it('renders the shell and the plan route', () => {
    const { root, container } = renderAt('/plan');

    expect(container.querySelector('[data-testid="sidebar"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="hudbar"]')).toBeTruthy();
    expect(container.textContent).toContain('Plan mode page');

    act(() => {
      root.unmount();
    });
  });

  it('renders the mission route', () => {
    const { root, container } = renderAt('/mission/mission-123');

    expect(container.textContent).toContain('Mission detail page');

    act(() => {
      root.unmount();
    });
  });

  it('renders the connectors and telemetry routes', () => {
    const connectors = renderAt('/models');
    expect(connectors.container.textContent).toContain('Connectors page');
    act(() => {
      connectors.root.unmount();
    });

    const telemetry = renderAt('/telemetry');
    expect(telemetry.container.textContent).toContain('Telemetry page');
    act(() => {
      telemetry.root.unmount();
    });
  });
});
