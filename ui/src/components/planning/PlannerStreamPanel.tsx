export interface PlannerStreamEventView {
  type: string;
  phase: string;
  status: string;
  content?: string;
}

interface PlannerStreamPanelProps {
  events: PlannerStreamEventView[];
  busy: boolean;
}

export default function PlannerStreamPanel({ events, busy }: PlannerStreamPanelProps) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="section-title">Planner Stream</h2>
          <p className="mt-1 text-xs text-dim">Status events are retained without raw chunk buffers.</p>
        </div>
        <span className="rounded-full border border-border bg-surface px-3 py-1 font-mono text-[11px] text-dim">
          {busy ? 'streaming' : 'idle'}
        </span>
      </div>

      <div className="mt-4 space-y-2">
        {events.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-dim">
            Awaiting planner traffic.
          </div>
        ) : null}
        {events.map((event, index) => (
          <div
            key={`${event.type}-${event.status}-${index}`}
            className="rounded-lg border border-border bg-surface px-3 py-2"
          >
            <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">
              {event.type} · {event.phase} · {event.status}
            </div>
            {event.content ? (
              <p className="mt-1 text-sm text-text">{event.content}</p>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}
