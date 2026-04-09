import { useState } from 'react';

interface YamlDrawerProps {
  yamlText: string;
  importing: boolean;
  onApplyImport: (yaml: string) => Promise<void>;
}

export default function YamlDrawer({ yamlText, importing, onApplyImport }: YamlDrawerProps) {
  const [importYaml, setImportYaml] = useState('');
  const [importError, setImportError] = useState<string | null>(null);

  return (
    <details open className="rounded-lg border border-border bg-card p-4">
      <summary className="cursor-pointer text-sm font-semibold text-text">YAML Drawer</summary>
      <div className="mt-4 space-y-4">
        <div>
          <div className="mb-2 text-xs font-medium uppercase tracking-[0.08em] text-muted">
            Exported YAML
          </div>
          <textarea
            aria-label="Mission YAML export"
            readOnly
            rows={16}
            className="w-full rounded-lg border border-border bg-surface p-3 font-mono text-xs text-text outline-none"
            value={yamlText}
          />
        </div>

        <div>
          <div className="mb-2 text-xs font-medium uppercase tracking-[0.08em] text-muted">
            Import YAML
          </div>
          <textarea
            aria-label="Import YAML"
            rows={10}
            className="w-full rounded-lg border border-border bg-surface p-3 font-mono text-xs text-text outline-none focus:border-cyan"
            placeholder="Paste YAML here, then apply it explicitly."
            value={importYaml}
            onInput={(event) => {
              setImportYaml(event.currentTarget.value);
              setImportError(null);
            }}
          />
          {importError ? (
            <div role="alert" className="mt-2 rounded-lg border border-red/20 bg-red-bg px-3 py-2 text-sm text-red">
              parse error: {importError}
            </div>
          ) : null}
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              className="rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={importing || importYaml.trim() === ''}
              onClick={() => {
                void (async () => {
                  try {
                    await onApplyImport(importYaml);
                    setImportYaml('');
                    setImportError(null);
                  } catch (caught) {
                    setImportError(caught instanceof Error ? caught.message : 'Failed to import YAML.');
                  }
                })();
              }}
            >
              Apply YAML
            </button>
          </div>
        </div>
      </div>
    </details>
  );
}
