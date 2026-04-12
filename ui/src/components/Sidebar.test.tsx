import { createRoot, type Root } from 'react-dom/client';
import { act, type ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from './Toast';
import { ThemeProvider } from '../context/ThemeContext';
import { DEFAULT_LABS_CONFIG } from '../lib/types';
import Sidebar from './Sidebar';

const ENABLED_LABS = { ...DEFAULT_LABS_CONFIG, black_hole_enabled: true };

const wsHarness = vi.hoisted(() => {
  type ConnectionState = 'connecting' | 'open' | 'closed';
  const listeners = new Set<(state: ConnectionState) => void>();
  let state: ConnectionState = 'closed';

  return {
    get state() {
      return state;
    },
    set state(next: ConnectionState) {
      state = next;
    },
    listeners,
    emit(next: ConnectionState) {
      state = next;
      for (const listener of listeners) {
        listener(next);
      }
    },
    reset() {
      state = 'closed';
      listeners.clear();
    },
  };
});

// jsdom does not implement matchMedia — provide a minimal stub.
const matchMediaListeners = new Set<() => void>();
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (_query: string) => ({
    matches: false,
    addEventListener: (_: string, fn: () => void) => matchMediaListeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => matchMediaListeners.delete(fn),
  }),
});

vi.mock('../lib/ws', () => ({
  wsClient: {
    get connectionState() {
      return wsHarness.state;
    },
    onConnectionState(handler: (state: 'connecting' | 'open' | 'closed') => void) {
      wsHarness.listeners.add(handler);
      handler(wsHarness.state);
    },
    offConnectionState(handler: (state: 'connecting' | 'open' | 'closed') => void) {
      wsHarness.listeners.delete(handler);
    },
  },
}));

const api = vi.hoisted(() => ({
  selectLabsConfig: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  selectLabsConfig: api.selectLabsConfig,
}));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  // Default to 'dark' so theme cycle tests start from a known state.
  localStorage.setItem('agentforce-theme', 'dark');
  api.selectLabsConfig.mockImplementation((config) => config?.labs ?? DEFAULT_LABS_CONFIG);
});

afterEach(() => {
  document.body.innerHTML = '';
  localStorage.clear();
  wsHarness.reset();
});

function renderToContainer(element: ReactElement): { root: Root; container: HTMLDivElement } {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <ToastProvider>
        <ThemeProvider>{element}</ThemeProvider>
      </ToastProvider>,
    );
  });

  return { root, container };
}

function getThemeButton(container: HTMLElement): HTMLButtonElement | null {
  return container.querySelector('[data-testid="theme-toggle"]');
}

describe('Sidebar', () => {
  it('persists collapsed state and renders the full nav', () => {
    localStorage.setItem('sidebar-collapsed', '1');
    wsHarness.state = 'open';

    const { container, root } = renderToContainer(
      <MemoryRouter>
        <Sidebar labs={ENABLED_LABS} />
      </MemoryRouter>,
    );

    expect(container.textContent).not.toContain('Mission Control');
    expect(container.querySelectorAll('a').length).toBe(7);

    const button = container.querySelector('button');
    act(() => {
      button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(localStorage.getItem('sidebar-collapsed')).toBe('0');
    expect(container.textContent).toContain('Mission Control');

    act(() => { root.unmount(); });
  });

  it('hides the Black Hole nav item when Labs disables it', () => {
    const { container, root } = renderToContainer(
      <MemoryRouter>
        <Sidebar labs={DEFAULT_LABS_CONFIG} />
      </MemoryRouter>,
    );

    expect(container.querySelectorAll('a').length).toBe(6);
    expect(container.querySelector('a[href="/black-hole"]')).toBeNull();

    act(() => { root.unmount(); });
  });

  describe('theme toggle', () => {
    it('renders a theme toggle button', () => {
      const { container, root } = renderToContainer(
        <MemoryRouter>
          <Sidebar labs={ENABLED_LABS} />
        </MemoryRouter>,
      );

      expect(getThemeButton(container)).not.toBeNull();

      act(() => { root.unmount(); });
    });

    it('cycles dark → light → system → dark on three clicks', () => {
      const { container, root } = renderToContainer(
        <MemoryRouter>
          <Sidebar labs={ENABLED_LABS} />
        </MemoryRouter>,
      );

      const btn = getThemeButton(container)!;

      expect(btn.getAttribute('data-mode')).toBe('dark');

      act(() => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
      expect(btn.getAttribute('data-mode')).toBe('light');

      act(() => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
      expect(btn.getAttribute('data-mode')).toBe('system');

      act(() => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
      expect(btn.getAttribute('data-mode')).toBe('dark');

      act(() => { root.unmount(); });
    });

    it('persists theme mode to localStorage', () => {
      const { container, root } = renderToContainer(
        <MemoryRouter>
          <Sidebar labs={ENABLED_LABS} />
        </MemoryRouter>,
      );

      const btn = getThemeButton(container)!;

      act(() => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
      expect(localStorage.getItem('agentforce-theme')).toBe('light');

      act(() => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
      expect(localStorage.getItem('agentforce-theme')).toBe('system');

      act(() => { root.unmount(); });
    });

    it('restores mode from localStorage on mount', () => {
      localStorage.setItem('agentforce-theme', 'system');

      const { container, root } = renderToContainer(
        <MemoryRouter>
          <Sidebar labs={ENABLED_LABS} />
        </MemoryRouter>,
      );

      const btn = getThemeButton(container)!;
      expect(btn.getAttribute('data-mode')).toBe('system');

      act(() => { root.unmount(); });
    });

    it('shows label when expanded and only icon when collapsed', () => {
      const { container, root } = renderToContainer(
        <MemoryRouter>
          <Sidebar labs={ENABLED_LABS} />
        </MemoryRouter>,
      );

      const btn = getThemeButton(container)!;
      expect(btn.textContent).toMatch(/Dark/);

      const collapseBtn = container.querySelector('button:not([data-testid="theme-toggle"])')!;
      act(() => { collapseBtn.dispatchEvent(new MouseEvent('click', { bubbles: true })); });

      expect(btn.textContent).not.toMatch(/Dark/);
      expect(btn.textContent?.trim().length).toBeGreaterThan(0);

      act(() => { root.unmount(); });
    });
  });
});
