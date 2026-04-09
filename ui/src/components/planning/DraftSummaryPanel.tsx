import type { MissionDraft } from '../../lib/types';

interface DraftSummaryPanelProps {
  draft: MissionDraft;
  saving: boolean;
  onNameChange: (value: string) => void;
  onGoalChange: (value: string) => void;
  onSave: () => void;
}

export default function DraftSummaryPanel({
  draft,
  saving,
  onNameChange,
  onGoalChange,
  onSave,
}: DraftSummaryPanelProps) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="section-title">Mission Summary</h2>
          <p className="mt-1 text-xs text-dim">Revision {draft.revision} is the only live draft state.</p>
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
          <label className="block text-sm font-medium text-text" htmlFor="mission-name">
            Mission name
          </label>
          <input
            id="mission-name"
            aria-label="Mission name"
            className="mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
            value={draft.draft_spec.name}
            onInput={(event) => onNameChange(event.currentTarget.value)}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-text" htmlFor="mission-goal">
            Goal
          </label>
          <textarea
            id="mission-goal"
            rows={3}
            className="mt-2 w-full rounded-lg border border-border bg-surface p-3 text-sm text-text outline-none focus:border-cyan"
            value={draft.draft_spec.goal}
            onInput={(event) => onGoalChange(event.currentTarget.value)}
          />
        </div>
      </div>
    </section>
  );
}
