import { act, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider, useTheme } from './ThemeContext';

// Minimal harness that exposes theme state via data attributes
function ThemeHarness({ onMount }: { onMount?: (ctx: ReturnType<typeof useTheme>) => void }) {
  const ctx = useTheme();
  useEffect(() => {
    onMount?.(ctx);
  }, [ctx, onMount]);
  return (
    <div
      data-mode={ctx.mode}
      data-effective={ctx.effectiveTheme}
      data-testid="harness"
    />
  );
}

let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  localStorage.clear();

  // Default matchMedia mock — prefers light
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false, // prefers-color-scheme: dark → false = light
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
});

afterEach(() => {
  document.body.innerHTML = '';
  document.documentElement.removeAttribute('data-theme');
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('ThemeProvider', () => {
  it('sets data-theme on mount (system → light when matchMedia.matches=false)', async () => {
    await act(async () => {
      createRoot(container).render(
        <ThemeProvider>
          <ThemeHarness />
        </ThemeProvider>,
      );
    });

    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('setMode("dark") updates data-theme and writes to localStorage', async () => {
    let captured: ReturnType<typeof useTheme> | undefined;

    await act(async () => {
      createRoot(container).render(
        <ThemeProvider>
          <ThemeHarness onMount={(ctx) => { captured = ctx; }} />
        </ThemeProvider>,
      );
    });

    await act(async () => {
      captured!.setMode('dark');
    });

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(localStorage.getItem('agentforce-theme')).toBe('dark');
  });

  it('reads initial mode from localStorage', async () => {
    localStorage.setItem('agentforce-theme', 'light');

    await act(async () => {
      createRoot(container).render(
        <ThemeProvider>
          <ThemeHarness />
        </ThemeProvider>,
      );
    });

    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    const harness = container.querySelector('[data-testid="harness"]');
    expect(harness?.getAttribute('data-mode')).toBe('light');
  });

  it('subscribes to matchMedia change event when mode is "system"', async () => {
    let changeListener: ((e: { matches: boolean }) => void) | undefined;
    const addEventListenerMock = vi.fn((_event: string, cb: (e: { matches: boolean }) => void) => {
      changeListener = cb;
    });
    const removeEventListenerMock = vi.fn();

    window.matchMedia = vi.fn().mockReturnValue({
      matches: true, // dark preferred
      media: '(prefers-color-scheme: dark)',
      addEventListener: addEventListenerMock,
      removeEventListener: removeEventListenerMock,
    });

    await act(async () => {
      createRoot(container).render(
        <ThemeProvider>
          <ThemeHarness />
        </ThemeProvider>,
      );
    });

    // Initial: system → dark (matches=true)
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(addEventListenerMock).toHaveBeenCalledWith('change', expect.any(Function));

    // Simulate OS switching to light
    await act(async () => {
      changeListener!({ matches: false });
    });

    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('useTheme throws when used outside ThemeProvider', () => {
    function Naked() {
      useTheme();
      return null;
    }

    expect(() => {
      const r = createRoot(document.createElement('div'));
      act(() => { r.render(<Naked />); });
    }).toThrow();
  });
});
