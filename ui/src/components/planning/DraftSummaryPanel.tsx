import type { MissionDraft } from '../../lib/types';

interface DraftSummaryPanelProps {
  draft: MissionDraft;
  saving: boolean;
  onNameChange: (value: string) => void;
  onGoalChange: (value: string) => void;
  onDodChange: (value: string[]) => void;
  onSave: () => void;
}

function joinLines(values: string[]): string {
  return values.join('\n');
}

function parseLines(value: string): string[] {
  return value
    .split('\n')
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export default function DraftSummaryPanel({
  draft,
  saving,
  onNameChange,
  onGoalChange,
  onDodChange,
  onSave,
}: DraftSummaryPanelProps) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="section-title">Mission Summary</h2>
          <p className="mt-1 text-xs text-dim">Revision {draft.revision} · edit inline, save to persist.</p>
        </div>
        <button
          type="button"
          className="rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={saving}
          onClick={onSave}
        >
          Save Summary
        </button>
      </div>

      <div className="mt-4 space-y-4">
        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            Mission Name
          </div>
          <input
            id="mission-name"
            aria-label="Mission name"
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
            value={draft.draft_spec.name}
            onInput={(event) => onNameChange(event.currentTarget.value)}
          />
        </div>
        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            Goal
          </div>
          <textarea
            id="mission-goal"
            rows={3}
            className="w-full rounded-lg border border-border bg-surface p-3 text-sm text-text outline-none focus:border-cyan"
            value={draft.draft_spec.goal}
            onInput={(event) => onGoalChange(event.currentTarget.value)}
          />
        </div>
        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            Definition of Done
          </div>
          <textarea
            id="mission-dod"
            aria-label="Definition of done"
            rows={3}
            className="w-full rounded-lg border border-border bg-surface p-3 text-sm text-text outline-none focus:border-cyan"
            placeholder="One criterion per line…"
            value={joinLines(draft.draft_spec.definition_of_done)}
            onInput={(event) => onDodChange(parseLines(event.currentTarget.value))}
          />
        </div>
      </div>
    </section>
  );
}
