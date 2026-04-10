import { useEffect, useState } from 'react';
import { NavLink, useInRouterContext } from 'react-router-dom';
import { wsClient } from '../lib/ws';
import { useTheme, type ThemeMode } from '../context/ThemeContext';

type WsConnectionState = 'connecting' | 'open' | 'closed';

const NAV_ITEMS = [
  { label: 'Mission Control', icon: '⌘', to: '/' },
  { label: 'Plan Mode', icon: '◈', to: '/plan' },
  { label: 'Ground Control', icon: '⊛', to: '/ground-control' },
  { label: 'Models', icon: '⬡', to: '/models' },
  { label: 'Telemetry', icon: '◎', to: '/telemetry' },
  { label: 'Settings', icon: '⚙', to: '/settings' },
] as const;

const APP_VERSION = 'v0.0.0';

const THEME_ICONS: Record<ThemeMode, string> = { dark: '☽', light: '☀', system: '⊙' };
const THEME_LABELS: Record<ThemeMode, string> = { dark: 'Dark', light: 'Light', system: 'System' };

function readCollapsedState(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }

  return window.localStorage.getItem('sidebar-collapsed') === '1';
}

function connectionDotClassName(state: WsConnectionState): string {
  if (state === 'open') {
    return 'w-2 h-2 rounded-full bg-green animate-[pulse-glow_2s_ease-in-out_infinite]';
  }

  return 'w-2 h-2 rounded-full bg-amber';
}

function SidebarNavLink({
  item,
  collapsed,
}: {
  item: (typeof NAV_ITEMS)[number];
  collapsed: boolean;
}): JSX.Element {
  const inRouter = useInRouterContext();
  const baseClassName = [
    'flex min-h-10 items-center px-3 py-2 text-[12px] transition-all duration-200',
    collapsed ? 'justify-center px-0' : 'justify-start gap-3',
  ].join(' ');

  if (!inRouter) {
    return (
      <a
        href={item.to}
        className={[baseClassName, 'text-dim hover:bg-card hover:text-text'].join(' ')}
        title={item.label}
      >
        <span aria-hidden="true" className="text-[13px] leading-none">
          {item.icon}
        </span>
        {!collapsed ? <span className="truncate">{item.label}</span> : null}
      </a>
    );
  }

  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) => [
        baseClassName,
        isActive
          ? 'bg-cyan-bg/30 text-cyan shadow-[inset_0_0_12px_rgba(34,211,238,0.1)]'
          : 'text-dim hover:bg-card hover:text-text',
      ].join(' ')}
      title={item.label}
    >
      <span aria-hidden="true" className="text-[13px] leading-none">
        {item.icon}
      </span>
      {!collapsed ? <span className="truncate font-medium">{item.label}</span> : null}
    </NavLink>
  );
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(readCollapsedState);
  const [connectionState, setConnectionState] = useState<WsConnectionState>(() => wsClient.connectionState);
  const { mode, cycleTheme } = useTheme();

  useEffect(() => {
    window.localStorage.setItem('sidebar-collapsed', collapsed ? '1' : '0');
  }, [collapsed]);

  useEffect(() => {
    const handler = (state: WsConnectionState): void => {
      setConnectionState(state);
    };

    wsClient.onConnectionState(handler);
    return () => {
      wsClient.offConnectionState(handler);
    };
  }, []);

  return (
    <aside
      className={[
        'shrink-0 border-r border-border bg-surface/95 backdrop-blur-sm transition-all duration-200',
        collapsed ? 'w-14' : 'w-48',
      ].join(' ')}
    >
      <div className="sticky top-10 flex h-[calc(100vh-2.5rem)] flex-col overflow-hidden">
        <div className="flex items-center justify-between gap-2 border-b border-border px-2 py-2">
          <button
            type="button"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="inline-flex h-8 w-8 items-center justify-center rounded border border-border text-dim transition-colors hover:bg-card hover:text-text"
            onClick={() => setCollapsed((value) => !value)}
          >
            {collapsed ? '→' : '←'}
          </button>
        </div>

        <nav className="flex-1 space-y-1 px-2 py-3">
          {NAV_ITEMS.map((item) => (
            <SidebarNavLink key={item.to} item={item} collapsed={collapsed} />
          ))}
        </nav>

        <div className="border-t border-border px-2 py-2 space-y-1">
          <button
            type="button"
            data-testid="theme-toggle"
            data-mode={mode}
            aria-label={`Theme: ${THEME_LABELS[mode]}`}
            onClick={cycleTheme}
            className={[
              'flex min-h-10 w-full items-center px-3 py-2 text-[12px] text-dim transition-colors hover:bg-card hover:text-text',
              collapsed ? 'justify-center px-0' : 'justify-start gap-3',
            ].join(' ')}
          >
            <span aria-hidden="true" className="text-[13px] leading-none">{THEME_ICONS[mode]}</span>
            {!collapsed ? <span className="truncate">{THEME_LABELS[mode]}</span> : null}
          </button>
          <div className="flex items-center gap-2 px-3 py-1">
            <span aria-hidden="true" className={connectionDotClassName(connectionState)} />
            {!collapsed ? <span className="text-[10px] text-muted">{APP_VERSION}</span> : null}
          </div>
        </div>
      </div>
    </aside>
  );
}
