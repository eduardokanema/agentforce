import { useEffect, useRef, useState } from 'react';
import ConfirmDialog from '../components/ConfirmDialog';
import { useToast } from '../hooks/useToast';
import type { Connector } from '../lib/types';
import {
  configureConnector,
  deleteConnector,
  getConnectors,
  testConnector,
} from '../lib/api';

const KNOWN_CONNECTORS = [
  { name: 'github', display_name: 'GitHub', description: 'Access repos and PRs' },
  { name: 'anthropic', display_name: 'Anthropic', description: 'Claude API key' },
  { name: 'slack', display_name: 'Slack', description: 'Send notifications' },
  { name: 'linear', display_name: 'Linear', description: 'Track issues' },
  { name: 'sentry', display_name: 'Sentry', description: 'Error monitoring' },
  { name: 'notion', display_name: 'Notion', description: 'Documentation' },
] as const;

type KnownConnector = (typeof KNOWN_CONNECTORS)[number];
type ConnectorStatus = {
  tone: 'success' | 'error' | 'info';
  message: string;
};

function getConnectorData(connectors: Connector[], connector: KnownConnector): Connector {
  return connectors.find((entry) => entry.name === connector.name) ?? {
    name: connector.name,
    display_name: connector.display_name,
    active: false,
  };
}

function statusDotClassName(active: boolean): string {
  return active ? 'bg-green shadow-[0_0_0_3px_theme(colors.green/10)]' : 'bg-muted';
}

function statusTextClassName(tone: ConnectorStatus['tone']): string {
  if (tone === 'success') {
    return 'text-green';
  }

  if (tone === 'info') {
    return 'text-cyan';
  }

  return 'text-red';
}

export default function ConnectorsPage() {
  const tokenRef = useRef<HTMLInputElement | null>(null);
  const { addToast } = useToast();
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [configuringName, setConfiguringName] = useState<string | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [statusByConnector, setStatusByConnector] = useState<Record<string, ConnectorStatus>>({});
  const [pendingDelete, setPendingDelete] = useState<null | { name: string; displayName: string }>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async (): Promise<void> => {
      setLoading(true);
      setError(null);

      try {
        const data = await getConnectors();
        if (!cancelled) {
          setConnectors(data);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : 'Failed to load connectors');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, []);

  const refreshConnectors = async (): Promise<void> => {
    const data = await getConnectors();
    setConnectors(data);
  };

  const clearToken = (): void => {
    if (tokenRef.current) {
      tokenRef.current.value = '';
    }
  };

  const setConnectorStatus = (name: string, status: ConnectorStatus | null): void => {
    setStatusByConnector((current) => {
      if (!status) {
        const next = { ...current };
        delete next[name];
        return next;
      }

      return { ...current, [name]: status };
    });
  };

  const handleConfigure = (name: string): void => {
    setConfiguringName((current) => (current === name ? null : name));
    setShowToken(false);
    setConnectorStatus(name, null);
  };

  const handleSave = async (name: string): Promise<void> => {
    const token = tokenRef.current?.value.trim() ?? '';

    if (!token) {
      addToast('API token is required', 'error');
      return;
    }

    setConnectorStatus(name, null);

    try {
      await configureConnector(name, token);
      const result = await testConnector(name);

      if (!result.ok) {
        addToast(result.error ?? 'Unknown connector error', 'error');
        return;
      }

      clearToken();
      setShowToken(false);
      addToast('Connector connected', 'success');
      await refreshConnectors();
    } catch (caught) {
      addToast(caught instanceof Error ? caught.message : 'Failed to configure connector', 'error');
    }
  };

  const handleRemove = async (name: string, displayName: string): Promise<void> => {
    setPendingDelete({ name, displayName });
  };

  const visibleConnectors = KNOWN_CONNECTORS.map((connector) => getConnectorData(connectors, connector));
  const loadingCards = (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {KNOWN_CONNECTORS.map((connector) => (
        <article key={connector.name} className="animate-pulse rounded-lg border border-border bg-card p-4">
          <div className="space-y-3">
            <div className="h-4 w-32 rounded bg-surface" />
            <div className="h-3 w-48 rounded bg-surface" />
            <div className="h-3 w-24 rounded bg-surface" />
            <div className="flex gap-2 pt-2">
              <div className="h-7 w-20 rounded-full bg-surface" />
              <div className="h-7 w-20 rounded-full bg-surface" />
            </div>
          </div>
        </article>
      ))}
    </section>
  );

  const confirmRemove = async (): Promise<void> => {
    const target = pendingDelete;
    setPendingDelete(null);

    if (!target) {
      return;
    }

    try {
      await deleteConnector(target.name);
      if (configuringName === target.name) {
        setConfiguringName(null);
        clearToken();
        setShowToken(false);
      }
      setConnectorStatus(target.name, null);
      addToast(`Connector "${target.displayName}" removed`, 'success');
      await refreshConnectors();
    } catch (caught) {
      addToast(caught instanceof Error ? caught.message : 'Failed to remove connector', 'error');
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <header className="page-head">
        <h1 className="text-3xl font-semibold tracking-tight">Connectors</h1>
        <p className="mt-1 text-sm text-dim">Manage API tokens for external services</p>
      </header>

      {error ? (
        <div className="rounded-lg border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
          {error}
        </div>
      ) : null}

      {loading ? (
        loadingCards
      ) : (
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {visibleConnectors.map((connector) => {
          const isConfiguring = configuringName === connector.name;

          return (
            <article key={connector.name} className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="font-semibold">{connector.display_name}</h2>
                    <span
                      aria-hidden="true"
                      className={`h-2.5 w-2.5 rounded-full ${statusDotClassName(connector.active)}`}
                    />
                    <span className="text-[11px] text-dim">{connector.active ? 'Active' : 'Inactive'}</span>
                  </div>
                  <p className="mt-1 text-dim text-[12px]">{KNOWN_CONNECTORS.find((entry) => entry.name === connector.name)?.description}</p>
                </div>
              </div>

              {connector.active && connector.token_last4 ? (
                <p className="mt-3 font-mono text-[11px] text-muted">Token: ••••{connector.token_last4}</p>
              ) : null}

              {connector.last_configured ? (
                <p className="mt-1 text-[11px] text-dim">Last configured {connector.last_configured}</p>
              ) : null}

              <div className="mt-4 flex flex-wrap items-center gap-2">
                {connector.active ? (
                  <button
                    type="button"
                    className="inline-flex items-center rounded-full border border-border px-2.5 py-1 text-[11px] text-dim transition-colors hover:bg-surface"
                    onClick={() => {
                      handleConfigure(connector.name);
                    }}
                  >
                    Reconfigure
                  </button>
                ) : (
                  <button
                    type="button"
                    className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-2.5 py-1 text-[11px] text-cyan transition-colors hover:bg-cyan/15"
                    onClick={() => {
                      handleConfigure(connector.name);
                    }}
                  >
                    Configure
                  </button>
                )}
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-border px-2.5 py-1 text-[11px] text-red transition-colors hover:bg-red/10"
                  onClick={() => {
                    void handleRemove(connector.name, connector.display_name);
                  }}
                >
                  Remove
                </button>
              </div>

              {isConfiguring ? (
                <div className="mt-4 space-y-3 border-t border-border pt-4">
                  <div className="flex items-center gap-2">
                    <input
                      ref={tokenRef}
                      type={showToken ? 'text' : 'password'}
                      placeholder="Paste API token..."
                      autoComplete="off"
                      className="min-w-0 flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text outline-none transition-colors placeholder:text-muted focus:border-cyan/50"
                    />
                    <button
                      type="button"
                      className="inline-flex items-center justify-center rounded-md border border-border px-3 py-2 text-sm text-dim transition-colors hover:bg-surface"
                      aria-label={showToken ? 'Hide token' : 'Show token'}
                      onClick={() => {
                        setShowToken((current) => !current);
                      }}
                    >
                      👁
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15"
                      onClick={() => {
                        void handleSave(connector.name);
                      }}
                    >
                      Save &amp; Test
                    </button>
                  </div>
                </div>
              ) : null}
            </article>
          );
        })}
      </section>
      )}

      <ConfirmDialog
        confirmLabel="Remove Connector"
        message={pendingDelete ? `This will remove "${pendingDelete.displayName}" and disconnect it from the app.` : ''}
        open={pendingDelete !== null}
        title={pendingDelete ? `Remove connector "${pendingDelete.displayName}"?` : ''}
        variant="danger"
        onCancel={() => {
          setPendingDelete(null);
        }}
        onConfirm={() => {
          void confirmRemove();
        }}
      />
    </div>
  );
}
