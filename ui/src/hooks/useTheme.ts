import { useEffect, useState } from 'react';

export type ThemeMode = 'dark' | 'light' | 'system';

const CYCLE: ThemeMode[] = ['dark', 'light', 'system'];
const STORAGE_KEY = 'agentforce-theme';

function readThemeMode(): ThemeMode {
  if (typeof window === 'undefined') return 'dark';
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'system') return stored;
  return 'dark';
}

export function useTheme(): { mode: ThemeMode; cycleTheme: () => void } {
  const [mode, setMode] = useState<ThemeMode>(readThemeMode);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, mode);
    const root = document.documentElement;

    if (mode !== 'system') {
      root.setAttribute('data-theme', mode);
      return;
    }

    // System mode: apply OS preference and react to real-time changes.
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () => root.setAttribute('data-theme', mq.matches ? 'dark' : 'light');
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [mode]);

  function cycleTheme() {
    setMode((current) => {
      const idx = CYCLE.indexOf(current);
      return CYCLE[(idx + 1) % CYCLE.length];
    });
  }

  return { mode, cycleTheme };
}
