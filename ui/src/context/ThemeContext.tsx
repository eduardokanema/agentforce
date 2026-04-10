import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

export type ThemeMode = 'dark' | 'light' | 'system';

interface ThemeContextValue {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  cycleTheme: () => void;
  effectiveTheme: 'dark' | 'light';
}

const ThemeContext = createContext<ThemeContextValue | null>(null);
export { ThemeContext };

const STORAGE_KEY = 'agentforce-theme';
const DARK_MEDIA = '(prefers-color-scheme: dark)';
const CYCLE: ThemeMode[] = ['dark', 'light', 'system'];

function resolveEffective(mode: ThemeMode): 'dark' | 'light' {
  if (mode !== 'system') return mode;
  return window.matchMedia(DARK_MEDIA).matches ? 'dark' : 'light';
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return (stored === 'dark' || stored === 'light' || stored === 'system') ? stored : 'system';
  });

  const [effectiveTheme, setEffectiveTheme] = useState<'dark' | 'light'>(() => resolveEffective(mode));

  // Apply data-theme to root element
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', effectiveTheme);
  }, [effectiveTheme]);

  // Subscribe to OS preference changes when in system mode
  useEffect(() => {
    if (mode !== 'system') return;

    const mql = window.matchMedia(DARK_MEDIA);
    const handler = (e: { matches: boolean }) => {
      setEffectiveTheme(e.matches ? 'dark' : 'light');
    };

    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, [mode]);

  const setMode = useCallback((next: ThemeMode) => {
    localStorage.setItem(STORAGE_KEY, next);
    setModeState(next);
    setEffectiveTheme(resolveEffective(next));
  }, []);

  const cycleTheme = useCallback(() => {
    const idx = CYCLE.indexOf(mode);
    setMode(CYCLE[(idx + 1) % CYCLE.length]);
  }, [mode, setMode]);

  const value = useMemo(() => ({ mode, setMode, cycleTheme, effectiveTheme }), [mode, setMode, cycleTheme, effectiveTheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider');
  return ctx;
}
