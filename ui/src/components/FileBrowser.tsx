import { useEffect, useState } from 'react';
import { getConfig, getFilesystemListing } from '../lib/api';
import type { FilesystemEntry } from '../lib/types';

interface FileBrowserProps {
  selected: string[];
  onSelect: (paths: string[]) => void;
}

function BreadcrumbNav({
  path,
  allowedRoots,
  onNavigate,
}: {
  path: string;
  allowedRoots: string[];
  onNavigate: (p: string) => void;
}) {
  const segments = path.split('/').filter(Boolean);
  const rootPath = allowedRoots.length > 0 ? allowedRoots[0] : '/';
  const rootSegments = rootPath.split('/').filter(Boolean);

  // Build breadcrumb from rootSegment level
  const crumbs: { label: string; path: string }[] = [];
  let built = '';
  for (let i = 0; i < segments.length; i++) {
    built += '/' + segments[i];
    // Only show segments at/below the root level
    if (i >= rootSegments.length - 1) {
      crumbs.push({ label: segments[i], path: built });
    }
  }

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-0.5 font-mono text-[11px]">
      {crumbs.map((crumb, idx) => {
        const isLast = idx === crumbs.length - 1;
        const isAtRoot = allowedRoots.some((r) => r === crumb.path || r.startsWith(crumb.path + '/'));
        const canNavigate = !isLast && !isAtRoot;
        return (
          <span key={crumb.path} className="flex items-center gap-0.5">
            {idx > 0 && <span className="text-muted">/</span>}
            {canNavigate ? (
              <button
                type="button"
                className="text-cyan transition-colors hover:text-cyan/70"
                onClick={() => onNavigate(crumb.path)}
              >
                {crumb.label}
              </button>
            ) : (
              <span className={isLast ? 'text-text font-semibold' : 'text-dim'}>{crumb.label}</span>
            )}
          </span>
        );
      })}
    </div>
  );
}

export default function FileBrowser({ selected, onSelect }: FileBrowserProps) {
  const [allowedRoots, setAllowedRoots] = useState<string[]>([]);
  const [currentPath, setCurrentPath] = useState('');
  const [entries, setEntries] = useState<FilesystemEntry[]>([]);
  const [parent, setParent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load config on mount
  useEffect(() => {
    let cancelled = false;
    getConfig()
      .then((cfg) => {
        if (cancelled) return;
        const roots = cfg.filesystem.allowed_base_paths;
        setAllowedRoots(roots);
        const startPath = roots.length > 0 ? roots[0] : '';
        navigate(startPath);
      })
      .catch(() => {
        if (!cancelled) navigate('');
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const navigate = (path: string) => {
    setLoading(true);
    setError(null);
    getFilesystemListing(path)
      .then((listing) => {
        setCurrentPath(listing.path);
        setEntries(listing.entries.filter((e) => e.is_dir));
        setParent(listing.parent);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (err.message.includes('403')) {
          setError('Path outside allowed directories');
        } else if (err.message.includes('404')) {
          setError('Directory not found');
        } else {
          setError(err.message);
        }
        setLoading(false);
      });
  };

  const handleSelect = () => {
    if (!currentPath || selected.includes(currentPath)) return;
    onSelect([...selected, currentPath]);
  };

  const handleRemove = (path: string) => {
    onSelect(selected.filter((p) => p !== path));
  };

  const isCurrentSelected = currentPath ? selected.includes(currentPath) : false;

  return (
    <div className="rounded-lg border border-border bg-surface">
      {/* Breadcrumb + nav */}
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        {parent && (
          <button
            type="button"
            aria-label="Go up"
            className="shrink-0 rounded border border-border px-2 py-0.5 text-[11px] text-dim transition-colors hover:bg-card hover:text-text"
            onClick={() => navigate(parent)}
          >
            ↑
          </button>
        )}
        {currentPath ? (
          <BreadcrumbNav
            path={currentPath}
            allowedRoots={allowedRoots}
            onNavigate={navigate}
          />
        ) : (
          <span className="text-[11px] text-muted">Loading…</span>
        )}
      </div>

      {/* Folder listing */}
      <div className="h-40 overflow-y-auto">
        {loading ? (
          <div className="flex h-full items-center justify-center text-[11px] text-muted">
            Loading…
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center text-[11px] text-red">
            {error}
          </div>
        ) : entries.length === 0 ? (
          <div className="flex h-full items-center justify-center text-[11px] text-muted">
            No subdirectories
          </div>
        ) : (
          <ul>
            {entries.map((entry) => (
              <li key={entry.path}>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] transition-colors hover:bg-card"
                  onClick={() => navigate(entry.path)}
                >
                  <span className="text-[11px] text-dim">📁</span>
                  <span className="truncate text-text">{entry.name}</span>
                  <span className="ml-auto text-[10px] text-muted">→</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Select button */}
      <div className="flex items-center gap-2 border-t border-border px-3 py-2">
        <button
          type="button"
          disabled={!currentPath || isCurrentSelected}
          className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1 text-[11px] text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-40"
          onClick={handleSelect}
        >
          {isCurrentSelected ? 'Already selected' : 'Select this folder'}
        </button>
        {currentPath && (
          <span className="min-w-0 truncate font-mono text-[10px] text-muted">{currentPath}</span>
        )}
      </div>

      {/* Selected paths */}
      {selected.length > 0 && (
        <div className="border-t border-border px-3 py-2">
          <p className="mb-1.5 text-[10px] uppercase tracking-wider text-muted">Selected workspaces</p>
          <div className="flex flex-wrap gap-1.5">
            {selected.map((path) => (
              <span
                key={path}
                className="flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 font-mono text-[10px] text-dim"
              >
                <span className="max-w-48 truncate">{path}</span>
                <button
                  type="button"
                  aria-label={`Remove ${path}`}
                  className="text-muted transition-colors hover:text-red"
                  onClick={() => handleRemove(path)}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
