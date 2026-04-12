import { useCallback, useEffect, useRef, useState } from 'react';
import ConfirmDialog from '../components/ConfirmDialog';
import { useToast } from '../hooks/useToast';
import type { Provider, ProviderModel } from '../lib/types';
import {
  activateProvider,
  configureProvider,
  deactivateProvider,
  deleteProvider,
  getProviders,
  refreshProviderModels,
  testProvider,
  updateProviderModels,
} from '../lib/api';

// ── Icons / meta ──────────────────────────────────────────────────────────────

const PROVIDER_META: Record<string, { emoji: string }> = {
  openrouter: { emoji: '⚡' },
  ollama: { emoji: '🦙' },
  opencode: { emoji: '◈' },
  claude: { emoji: '◆' },
  codex: { emoji: '○' },
};

// ── Model row ─────────────────────────────────────────────────────────────────

function ModelRow({
  model,
  enabled,
  isCli,
  onToggle,
}: {
  model: ProviderModel;
  enabled: boolean;
  isCli: boolean;
  onToggle: (id: string, checked: boolean) => void;
}) {
  return (
    <div className="flex items-center gap-3 rounded px-1 py-1 hover:bg-surface">
      <input
        type="checkbox"
        id={`model-${model.id}`}
        checked={enabled}
        onChange={(e) => onToggle(model.id, e.target.checked)}
        className="h-3.5 w-3.5 cursor-pointer rounded border border-border accent-cyan"
      />
      <label htmlFor={`model-${model.id}`} className="flex-1 cursor-pointer text-[12px]">
        <span className="text-text">{model.name}</span>
        {model.cost_per_1k_input > 0 ? (
          <span className="ml-2 font-mono text-[10px] text-muted">
            ${model.cost_per_1k_input.toFixed(4)}/{model.cost_per_1k_output.toFixed(4)} per 1k
          </span>
        ) : (
          <span className="ml-2 font-mono text-[10px] text-green">
            {isCli ? 'Plan' : 'free'}
          </span>
        )}
        <span className="ml-2 text-[10px] text-dim">{model.latency_label}</span>
        {Array.isArray(model.supported_thinking) && model.supported_thinking.length > 0 ? (
          <span className="ml-2 text-[10px] text-dim">
            Thinking {model.supported_thinking.join('/')}
          </span>
        ) : null}
      </label>
    </div>
  );
}

// ── Unified provider card ─────────────────────────────────────────────────────

function ProviderCard({
  provider,
  onRefresh,
}: {
  provider: Provider;
  onRefresh: () => void;
}) {
  const { addToast } = useToast();
  const isCli = provider.type === 'cli';
  const meta = PROVIDER_META[provider.id] ?? { emoji: '◆' };

  // API key form state (API providers only)
  const [configuring, setConfiguring] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const keyRef = useRef<HTMLInputElement>(null);

  // Test feedback
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string } | null>(null);
  const testTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Refresh (API providers only)
  const [refreshing, setRefreshing] = useState(false);

  // Confirm dialogs
  const [pendingDeactivate, setPendingDeactivate] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(false);

  // Model list state
  const allModelIds = provider.all_models.map((m) => m.id);
  const [enabledIds, setEnabledIds] = useState<string[]>(
    provider.enabled_models ?? allModelIds,
  );
  const [modelFilter, setModelFilter] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const saveModels = useCallback(
    (ids: string[]) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(async () => {
        try {
          await updateProviderModels(provider.id, ids);
        } catch (err) {
          addToast(err instanceof Error ? err.message : 'Failed to update models', 'error');
        }
      }, 400);
    },
    [provider.id, addToast],
  );

  const handleToggle = (modelId: string, checked: boolean) => {
    const next = checked ? [...enabledIds, modelId] : enabledIds.filter((id) => id !== modelId);
    setEnabledIds(next);
    saveModels(next);
  };

  const handleSaveKey = async () => {
    const key = keyRef.current?.value.trim() ?? '';
    if (!key) { addToast('API key is required', 'error'); return; }
    setSaving(true);
    try {
      await configureProvider(provider.id, key);
      if (keyRef.current) keyRef.current.value = '';
      setShowKey(false);
      setConfiguring(false);
      const result = await testProvider(provider.id);
      if (!result.ok) {
        addToast(`Key saved but test failed: ${result.error ?? 'unknown'}`, 'error');
      } else {
        addToast(`${provider.display_name} connected`, 'success');
      }
      onRefresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed to save key', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    if (testTimer.current) clearTimeout(testTimer.current);
    try {
      const result = await testProvider(provider.id);
      setTestResult(result);
      testTimer.current = setTimeout(() => setTestResult(null), 6000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Test failed';
      setTestResult({ ok: false, error: msg });
      testTimer.current = setTimeout(() => setTestResult(null), 6000);
    } finally {
      setTesting(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const result = await refreshProviderModels(provider.id);
      addToast(`Model list refreshed (${result.count ?? 0} models)`, 'success');
      onRefresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Refresh failed', 'error');
    } finally {
      setRefreshing(false);
    }
  };

  const handleActivate = async () => {
    if (provider.is_default) return;
    try {
      await activateProvider(provider.id);
      addToast(`${provider.display_name} set as default executor`, 'success');
      onRefresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed', 'error');
    }
  };

  const handleClearDefault = async () => {
    try {
      await activateProvider('');  // empty = clear
      addToast('Default executor cleared', 'success');
      onRefresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed', 'error');
    }
  };

  const handleProviderDeactivate = async () => {
    try {
      await deactivateProvider(provider.id);
      addToast(`${provider.display_name} deactivated`, 'success');
      onRefresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed', 'error');
    } finally {
      setPendingDeactivate(false);
    }
  };

  const handleRemove = async () => {
    try {
      await deleteProvider(provider.id);
      addToast(`${provider.display_name} removed`, 'success');
      onRefresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed', 'error');
    } finally {
      setPendingDelete(false);
    }
  };

  const filteredModels = provider.all_models.filter(
    (m) =>
      !modelFilter ||
      m.name.toLowerCase().includes(modelFilter.toLowerCase()) ||
      m.id.toLowerCase().includes(modelFilter.toLowerCase()),
  );

  const selectAll = () => {
    const ids = provider.all_models.map((m) => m.id);
    setEnabledIds(ids);
    saveModels(ids);
  };

  const selectNone = () => {
    setEnabledIds([]);
    saveModels([]);
  };

  const selectFiltered = () => {
    const fids = filteredModels.map((m) => m.id);
    const merged = [...new Set([...enabledIds, ...fids])];
    setEnabledIds(merged);
    saveModels(merged);
  };

  const deselectFiltered = () => {
    const fset = new Set(filteredModels.map((m) => m.id));
    const remaining = enabledIds.filter((id) => !fset.has(id));
    setEnabledIds(remaining);
    saveModels(remaining);
  };

  return (
    <article
      className={[
        'rounded-lg border bg-card transition-all',
        isCli && provider.is_default
          ? 'border-cyan/40 shadow-[0_0_0_1px_theme(colors.cyan/8)]'
          : 'border-border',
        !provider.active ? 'opacity-60' : '',
      ].join(' ')}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 p-4">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{meta.emoji}</span>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-semibold">{provider.display_name}</h2>
              <span
                className={`h-2 w-2 rounded-full ${
                  provider.active
                    ? 'bg-green shadow-[0_0_0_3px_theme(colors.green/10)]'
                    : 'bg-muted'
                }`}
              />
              <span className="text-[11px] text-dim">
                {provider.active ? 'Active' : isCli ? 'Not installed' : 'Inactive'}
              </span>
              {isCli && provider.binary && (
                <code className="rounded bg-surface px-1 py-0.5 font-mono text-[10px] text-muted">
                  {provider.binary}
                </code>
              )}
            </div>
            <p className="mt-0.5 text-[11px] text-dim">{provider.description}</p>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {isCli ? (
            /* CLI: Set Default / ✓ Default toggle + Refresh Models */
            <>
              {provider.is_default ? (
                <button
                  type="button"
                  onClick={() => void handleClearDefault()}
                  className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-2.5 py-1 text-[11px] text-cyan transition-colors hover:border-red/30 hover:bg-red/10 hover:text-red"
                  title="Click to clear default"
                >
                  ✓ Default
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void handleActivate()}
                  className="inline-flex items-center rounded-full border border-border px-2.5 py-1 text-[11px] text-dim transition-colors hover:bg-surface"
                >
                  Set Default
                </button>
              )}
              {provider.id !== 'opencode' && (
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-border px-2.5 py-1 text-[11px] text-dim transition-colors hover:bg-surface"
                  disabled={refreshing}
                  onClick={() => void handleRefresh()}
                >
                  {refreshing ? 'Refreshing…' : '↻ Refresh Models'}
                </button>
              )}
            </>
          ) : (
            /* API: Configure / Test / Refresh / Deactivate / Remove */
            <>
              {provider.requires_key && (
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-border px-2.5 py-1 text-[11px] text-dim transition-colors hover:bg-surface"
                  onClick={() => setConfiguring((v) => !v)}
                >
                  {provider.active ? 'Reconfigure' : 'Connect'}
                </button>
              )}
              <button
                type="button"
                className="inline-flex items-center rounded-full border border-border px-2.5 py-1 text-[11px] text-dim transition-colors hover:bg-surface"
                disabled={testing}
                onClick={() => void handleTest()}
              >
                {testing ? 'Testing…' : provider.requires_key ? 'Test' : 'Check Connection'}
              </button>
              {provider.active && provider.requires_key && (
                <>
                  <button
                    type="button"
                    className="inline-flex items-center rounded-full border border-border px-2.5 py-1 text-[11px] text-dim transition-colors hover:bg-surface"
                    disabled={refreshing}
                    onClick={() => void handleRefresh()}
                  >
                    {refreshing ? 'Refreshing…' : '↻ Refresh Models'}
                  </button>
                  <button
                    type="button"
                    className="inline-flex items-center rounded-full border border-border px-2.5 py-1 text-[11px] text-amber transition-colors hover:bg-amber/10"
                    onClick={() => setPendingDeactivate(true)}
                  >
                    Deactivate
                  </button>
                  <button
                    type="button"
                    className="inline-flex items-center rounded-full border border-border px-2.5 py-1 text-[11px] text-red transition-colors hover:bg-red/10"
                    onClick={() => setPendingDelete(true)}
                  >
                    Remove
                  </button>
                </>
              )}
            </>
          )}
        </div>
      </div>

      {/* API key form (API providers only) */}
      {configuring && provider.requires_key && (
        <div className="mx-4 mb-4 space-y-3 rounded-md border border-border bg-surface p-3">
          <div className="flex items-center gap-2">
            <input
              ref={keyRef}
              type={showKey ? 'text' : 'password'}
              placeholder="Paste API key…"
              autoComplete="off"
              className="min-w-0 flex-1 rounded border border-border bg-background px-3 py-2 text-sm text-text outline-none placeholder:text-muted focus:border-cyan/50"
            />
            <button
              type="button"
              aria-label={showKey ? 'Hide key' : 'Show key'}
              className="inline-flex h-9 w-9 items-center justify-center rounded border border-border text-dim transition-colors hover:bg-card"
              onClick={() => setShowKey((v) => !v)}
            >
              👁
            </button>
          </div>
          <button
            type="button"
            className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:opacity-50"
            disabled={saving}
            onClick={() => void handleSaveKey()}
          >
            {saving ? 'Saving…' : 'Save & Test'}
          </button>
        </div>
      )}

      {/* Test result banner */}
      {testResult !== null && (
        <div
          className={`mx-4 mb-3 flex items-center gap-2 rounded-md border px-3 py-2 text-[12px] ${
            testResult.ok
              ? 'border-green/30 bg-green/10 text-green'
              : 'border-red/30 bg-red/10 text-red'
          }`}
        >
          <span>{testResult.ok ? '✓' : '✗'}</span>
          <span>{testResult.ok ? 'Connection OK' : (testResult.error ?? 'Connection failed')}</span>
        </div>
      )}

      {/* Last configured */}
      {provider.last_configured && (
        <p className="px-4 pb-1 text-[11px] text-muted">
          Configured {new Date(provider.last_configured).toLocaleDateString()}
        </p>
      )}

      {/* Model list */}
      {provider.all_models.length > 0 && (
        <div className="border-t border-border px-4 py-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-dim">
              Models ({enabledIds.length}/{provider.all_models.length} enabled)
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                className="rounded border border-border px-1.5 py-0.5 text-[10px] text-dim transition-colors hover:bg-surface"
                onClick={selectAll}
              >
                All
              </button>
              <button
                type="button"
                className="rounded border border-border px-1.5 py-0.5 text-[10px] text-dim transition-colors hover:bg-surface"
                onClick={selectNone}
              >
                None
              </button>
              {modelFilter && filteredModels.length < provider.all_models.length && (
                <>
                  <button
                    type="button"
                    className="rounded border border-border px-1.5 py-0.5 text-[10px] text-cyan transition-colors hover:bg-surface"
                    onClick={selectFiltered}
                  >
                    +Filtered
                  </button>
                  <button
                    type="button"
                    className="rounded border border-border px-1.5 py-0.5 text-[10px] text-dim transition-colors hover:bg-surface"
                    onClick={deselectFiltered}
                  >
                    −Filtered
                  </button>
                </>
              )}
            </div>
            {provider.all_models.length > 8 && (
              <input
                type="search"
                placeholder="Filter models…"
                value={modelFilter}
                onChange={(e) => setModelFilter(e.target.value)}
                className="ml-auto w-40 rounded border border-border bg-surface px-2 py-0.5 text-[11px] text-text outline-none placeholder:text-muted focus:border-cyan/50"
              />
            )}
          </div>
          <div className="max-h-64 space-y-0.5 overflow-y-auto pr-1">
            {filteredModels.map((model) => (
              <ModelRow
                key={model.id}
                model={model}
                enabled={enabledIds.includes(model.id)}
                isCli={isCli}
                onToggle={handleToggle}
              />
            ))}
            {filteredModels.length === 0 && modelFilter && (
              <p className="py-2 text-center text-[11px] text-muted">No models match "{modelFilter}"</p>
            )}
          </div>
        </div>
      )}

      {/* CLI: not installed hint */}
      {isCli && !provider.active && (
        <div className="border-t border-border px-4 py-3 text-[11px] text-muted">
          Install with:{' '}
          <code className="rounded bg-surface px-1 py-0.5 font-mono text-[10px]">
            {provider.id === 'opencode'
              ? 'npm install -g opencode-ai'
              : provider.id === 'claude'
              ? 'npm install -g @anthropic-ai/claude-code'
              : 'npm install -g @openai/codex'}
          </code>
        </div>
      )}

      {/* CLI: OpenCode no models hint */}
      {isCli && provider.id === 'opencode' && provider.all_models.length === 0 && provider.active && (
        <div className="border-t border-border px-4 py-3 text-[11px] text-muted">
          Connect OpenRouter above to populate the model list for OpenCode.
        </div>
      )}

      <ConfirmDialog
        confirmLabel="Deactivate"
        message={`Remove the ${provider.display_name} API key. The model list is preserved.`}
        open={pendingDeactivate}
        title={`Deactivate ${provider.display_name}?`}
        variant="warning"
        onCancel={() => setPendingDeactivate(false)}
        onConfirm={() => void handleProviderDeactivate()}
      />
      <ConfirmDialog
        confirmLabel="Remove"
        message={`Remove the ${provider.display_name} API key and all saved preferences.`}
        open={pendingDelete}
        title={`Remove ${provider.display_name}?`}
        variant="danger"
        onCancel={() => setPendingDelete(false)}
        onConfirm={() => void handleRemove()}
      />
    </article>
  );
}

export default function ConnectorsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setProviders(await getProviders());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="flex flex-col gap-6">
      <header className="page-head">
        <h1 className="text-3xl font-semibold tracking-tight">Models</h1>
        <p className="mt-1 text-sm text-dim">
          Configure AI providers and CLI executors — all can run LLM commands for your missions
        </p>
      </header>

      {error && (
        <div className="rounded-lg border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-4">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="animate-pulse rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-3">
                <div className="h-8 w-8 rounded bg-surface" />
                <div className="space-y-2">
                  <div className="h-4 w-32 rounded bg-surface" />
                  <div className="h-3 w-48 rounded bg-surface" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <section className="space-y-4">
          {providers.map((provider) => (
            <ProviderCard key={provider.id} provider={provider} onRefresh={() => void load()} />
          ))}
        </section>
      )}
    </div>
  );
}
