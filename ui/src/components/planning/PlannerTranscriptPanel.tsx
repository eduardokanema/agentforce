import type { DraftTurn } from '../../lib/types';

interface PlannerTranscriptPanelProps {
  turns: DraftTurn[];
  message: string;
  busy: boolean;
  onMessageChange: (value: string) => void;
  onSend: () => void;
}

export default function PlannerTranscriptPanel({
  turns,
  message,
  busy,
  onMessageChange,
  onSend,
}: PlannerTranscriptPanelProps) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="section-title">Flight Director</h2>
          <p className="mt-1 text-xs text-dim">Transcript-driven planning with mission-control status intact.</p>
        </div>
        <span className="rounded-full border border-border bg-surface px-3 py-1 font-mono text-[11px] text-dim">
          {turns.length} turn(s)
        </span>
      </div>

      <div className="mt-4 space-y-3">
        {turns.map((turn, index) => (
          <article
            key={`${turn.role}-${index}-${turn.content.slice(0, 24)}`}
            className="rounded-lg border border-border bg-surface px-3 py-3"
          >
            <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-muted">
              {turn.role === 'user' ? 'Director' : 'Planner'}
            </div>
            <p className="whitespace-pre-wrap text-sm text-text">{turn.content}</p>
          </article>
        ))}
      </div>

      <div className="mt-4">
        <label className="mb-2 block text-sm font-medium text-text" htmlFor="planner-follow-up">
          Follow-up turn
        </label>
        <textarea
          id="planner-follow-up"
          rows={4}
          className="w-full rounded-lg border border-border bg-surface p-3 text-sm text-text outline-none placeholder:text-dim focus:border-cyan"
          placeholder="Tell the planner what to adjust..."
          value={message}
          onInput={(event) => onMessageChange(event.currentTarget.value)}
        />
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            className="rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={busy || message.trim() === ''}
            onClick={onSend}
          >
            Send to Planner
          </button>
        </div>
      </div>
    </section>
  );
}
