import { useEffect, useState } from 'react';
import { createFilesystemFolder, getConfig, getFilesystemListing } from '../lib/api';
import type { FilesystemEntry } from '../lib/types';

interface FileBrowserProps {
  selected: string[];
  onSelect: (paths: string[]) => void;
  initialPath?: string;
  selectionMode?: 'single' | 'multiple';
  selectedLabel?: string;
  selectButtonLabel?: string;
  allowRemoval?: boolean;
  allowCreateFolder?: boolean;
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

export default function FileBrowser({
  selected,
  onSelect,
  initialPath,
  selectionMode = 'multiple',
  selectedLabel = 'Selected workspaces',
  selectButtonLabel = 'Select this folder',
  allowRemoval = true,
  allowCreateFolder = true,
}: FileBrowserProps) {
  const [allowedRoots, setAllowedRoots] = useState<string[]>([]);
  const [currentPath, setCurrentPath] = useState('');
  const [entries, setEntries] = useState<FilesystemEntry[]>([]);
  const [parent, setParent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newFolderName, setNewFolderName] = useState('');
  const [creatingFolder, setCreatingFolder] = useState(false);

  async function loadListing(path: string): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const listing = await getFilesystemListing(path);
      setCurrentPath(listing.path);
      setEntries(listing.entries.filter((e) => e.is_dir));
      setParent(listing.parent);
      setLoading(false);
    } catch (err) {
      const nextError = err instanceof Error ? err : new Error('Failed to load directory');
      if (nextError.message.includes('403')) {
        setError('Path outside allowed directories');
      } else if (nextError.message.includes('404')) {
        setError('Directory not found');
      } else {
        setError(nextError.message);
      }
      setLoading(false);
      throw nextError;
    }
  }

  // Load config on mount
  useEffect(() => {
    let cancelled = false;
    getConfig()
      .then(async (cfg) => {
        if (cancelled) return;
        const roots = cfg.filesystem.allowed_base_paths;
        setAllowedRoots(roots);
        const fallbackPath = roots.length > 0 ? roots[0] : '';
        const preferredPath = initialPath?.trim() || cfg.filesystem.default_start_path?.trim();
        try {
          await loadListing(preferredPath || fallbackPath);
        } catch {
          if (cancelled || !preferredPath || preferredPath === fallbackPath) {
            return;
          }
          try {
            await loadListing(fallbackPath);
          } catch {
            return;
          }
        }
      })
      .catch(() => {
        if (!cancelled) {
          void loadListing('').catch(() => {});
        }
      });
    return () => { cancelled = true; };
  }, [initialPath]);

  const navigate = (path: string) => {
    void loadListing(path).catch(() => {});
  };

  const handleSelect = () => {
    if (!currentPath || selected.includes(currentPath)) return;
    if (selectionMode === 'single') {
      onSelect([currentPath]);
      return;
    }
    onSelect([...selected, currentPath]);
  };

  const handleRemove = (path: string) => {
    onSelect(selected.filter((p) => p !== path));
  };

  const handleCreateFolder = async () => {
    const folderName = newFolderName.trim();
    if (!currentPath || !folderName) {
      return;
    }
    setCreatingFolder(true);
    setError(null);
    try {
      const created = await createFilesystemFolder(currentPath, folderName);
      setNewFolderName('');
      navigate(created.path);
    } catch (err) {
      const nextError = err instanceof Error ? err : new Error('Failed to create directory');
      setError(nextError.message);
    } finally {
      setCreatingFolder(false);
    }
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

      {allowCreateFolder && (
        <div className="flex items-center gap-2 border-t border-border px-3 py-2">
          <input
            type="text"
            value={newFolderName}
            onChange={(event) => setNewFolderName(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                void handleCreateFolder();
              }
            }}
            placeholder="New folder name"
            className="w-full rounded border border-border bg-card px-3 py-1.5 text-[12px] text-text outline-none placeholder:text-dim focus:border-cyan/50"
          />
          <button
            type="button"
            disabled={!currentPath || !newFolderName.trim() || creatingFolder}
            className="inline-flex shrink-0 items-center rounded-full border border-border px-3 py-1 text-[11px] text-dim transition-colors hover:bg-card hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => {
              void handleCreateFolder();
            }}
          >
            {creatingFolder ? 'Creating…' : 'Create folder'}
          </button>
        </div>
      )}

      {/* Select button */}
      <div className="flex items-center gap-2 border-t border-border px-3 py-2">
        <button
          type="button"
          disabled={!currentPath || isCurrentSelected}
          className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1 text-[11px] text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-40"
          onClick={handleSelect}
        >
          {isCurrentSelected ? (selectionMode === 'single' ? 'Current start folder' : 'Already selected') : selectButtonLabel}
        </button>
        {currentPath && (
          <span className="min-w-0 truncate font-mono text-[10px] text-muted">{currentPath}</span>
        )}
      </div>

      {/* Selected paths */}
      {selected.length > 0 && (
        <div className="border-t border-border px-3 py-2">
          <p className="mb-1.5 text-[10px] uppercase tracking-wider text-muted">{selectedLabel}</p>
          <div className="flex flex-wrap gap-1.5">
            {selected.map((path) => (
              <span
                key={path}
                className="flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 font-mono text-[10px] text-dim"
              >
                <span className="max-w-48 truncate">{path}</span>
                {allowRemoval ? (
                  <button
                    type="button"
                    aria-label={`Remove ${path}`}
                    className="text-muted transition-colors hover:text-red"
                    onClick={() => handleRemove(path)}
                  >
                    ×
                  </button>
                ) : null}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
