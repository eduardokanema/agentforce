import { useEffect, useState } from 'react';
import FileBrowser from '../components/FileBrowser';
import { useToast } from '../hooks/useToast';
import type { AppConfig, DefaultCaps } from '../lib/types';
import { getConfig, updateConfig } from '../lib/api';

const DEFAULTS: DefaultCaps = {
  max_concurrent_workers: 2,
  max_retries_per_task: 2,
  max_wall_time_minutes: 60,
  max_cost_usd: 0,
};

const DEFAULT_WORKSPACE_BROWSER_START = '~/Projects';

const FIELDS: {
  key: keyof DefaultCaps;
  label: string;
  min: number;
  max: number;
  step: number;
  help?: string;
}[] = [
  { key: 'max_concurrent_workers', label: 'Max Concurrent Workers', min: 1, max: 8, step: 1 },
  { key: 'max_retries_per_task', label: 'Max Retries per Task', min: 1, max: 5, step: 1 },
  { key: 'max_wall_time_minutes', label: 'Max Wall Time (minutes)', min: 10, max: 480, step: 10 },
  {
    key: 'max_cost_usd',
    label: 'Max Cost (USD)',
    min: 0,
    max: 1000,
    step: 0.5,
    help: '0 = unlimited (no budget cap)',
  },
];

export default function SettingsPage() {
  const { addToast } = useToast();
  const [caps, setCaps] = useState<DefaultCaps>(DEFAULTS);
  const [defaultStartPath, setDefaultStartPath] = useState(DEFAULT_WORKSPACE_BROWSER_START);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getConfig()
      .then((cfg) => {
        if (cfg.default_caps) setCaps(cfg.default_caps);
        if (cfg.filesystem?.default_start_path != null) {
          setDefaultStartPath(cfg.filesystem.default_start_path || DEFAULT_WORKSPACE_BROWSER_START);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleChange = (key: keyof DefaultCaps, raw: string) => {
    const value = key === 'max_cost_usd' ? parseFloat(raw) : parseInt(raw, 10);
    setCaps((prev) => ({ ...prev, [key]: isNaN(value) ? prev[key] : value }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const result = await updateConfig({
        default_caps: caps,
        filesystem: {
          allowed_base_paths: [],
          default_start_path: defaultStartPath,
        } as AppConfig['filesystem'],
      });
      setCaps(result.default_caps);
      setDefaultStartPath(result.filesystem.default_start_path || DEFAULT_WORKSPACE_BROWSER_START);
      addToast('Settings saved', 'success');
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Save failed', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setCaps(DEFAULTS);
    setDefaultStartPath(DEFAULT_WORKSPACE_BROWSER_START);
    addToast('Reset to defaults — click Save to persist', 'success');
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="page-head">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-dim">
          Configure mission defaults and the initial folder used by the workspace browser.
        </p>
      </header>

      <section className="rounded-lg border border-border bg-card p-6">
        {loading ? (
          <div className="space-y-4">
            {FIELDS.map((f) => (
              <div key={f.key} className="animate-pulse space-y-1">
                <div className="h-3 w-40 rounded bg-surface" />
                <div className="h-9 w-full max-w-xs rounded bg-surface" />
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-5">
            <div>
              <div className="mb-2 block text-[12px] font-medium text-text">
                Workspace Browser Start Path
              </div>
              <p className="mb-3 text-[11px] text-muted">
                Navigate to the folder you want the shared workspace browser to open in by default. You can also create a folder here before selecting it.
              </p>
              <FileBrowser
                selected={defaultStartPath ? [defaultStartPath] : []}
                onSelect={(paths) => setDefaultStartPath(paths[0] ?? DEFAULT_WORKSPACE_BROWSER_START)}
                initialPath={defaultStartPath}
                selectionMode="single"
                selectedLabel="Selected start folder"
                selectButtonLabel="Use this folder"
                allowRemoval={false}
                allowCreateFolder
              />
            </div>

            {FIELDS.map((f) => (
              <div key={f.key}>
                <label
                  htmlFor={`cap-${f.key}`}
                  className="mb-1 block text-[12px] font-medium text-text"
                >
                  {f.label}
                </label>
                <input
                  id={`cap-${f.key}`}
                  type="number"
                  min={f.min}
                  max={f.max}
                  step={f.step}
                  value={caps[f.key]}
                  onChange={(e) => handleChange(f.key, e.target.value)}
                  className="w-full max-w-xs rounded border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan/50"
                />
                {f.help && (
                  <p className="mt-1 text-[11px] text-muted">{f.help}</p>
                )}
              </div>
            ))}

            <div className="flex items-center gap-3 pt-2">
              <button
                type="button"
                disabled={saving}
                onClick={() => void handleSave()}
                className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-4 py-1.5 text-[12px] font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                onClick={handleReset}
                className="inline-flex items-center rounded-full border border-border px-4 py-1.5 text-[12px] text-dim transition-colors hover:bg-surface"
              >
                Reset to defaults
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
