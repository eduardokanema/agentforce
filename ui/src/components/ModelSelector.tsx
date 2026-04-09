import type { Model } from '../lib/types';

export interface ModelSelectorProps {
  models: Model[];
  selected: string[];
  onChange: (ids: string[]) => void;
}

function formatCost(model: Model): string {
  return `$${model.cost_per_1k_input.toFixed(3)}/1k`;
}

function latencyClassName(label: string): string {
  if (label === 'Fast') {
    return 'text-green bg-green-bg border-green/20';
  }
  if (label === 'Standard') {
    return 'text-amber bg-amber-bg border-amber/20';
  }
  return 'text-purple bg-purple-bg border-purple/20';
}

export default function ModelSelector({ models, selected, onChange }: ModelSelectorProps) {
  const selectedSet = new Set(selected);

  const toggleModel = (modelId: string): void => {
    const isSelected = selectedSet.has(modelId);
    if (isSelected) {
      if (selected.length === 1) {
        return;
      }
      onChange(selected.filter((id) => id !== modelId));
      return;
    }

    onChange([...selected, modelId]);
  };

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {models.map((model) => {
        const isSelected = selectedSet.has(model.id);
        const cardClassName = [
          'rounded-lg border p-3 text-left transition-colors',
          isSelected
            ? 'cursor-pointer border-cyan bg-cyan-bg'
            : 'cursor-pointer border-border bg-surface hover:bg-card-hover',
        ].join(' ');

        return (
          <button
            key={model.id}
            type="button"
            className={cardClassName}
            onClick={() => toggleModel(model.id)}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="font-semibold text-text">{model.name}</div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-dim">
                  <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-muted">{model.provider}</span>
                  <span>{formatCost(model)}</span>
                </div>
              </div>
              <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${latencyClassName(model.latency_label)}`}>
                {model.latency_label}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
