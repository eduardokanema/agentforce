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

type Severity = "critical" | "high" | "medium" | "low";

function severityStyle(s: string): { badge: string; card: string } {
  const level = s.toLowerCase() as Severity;
  switch (level) {
    case "critical":
      return {
        badge: "bg-red text-red-bg",
        card: "bg-red-bg/40 border-red/20",
      };
    case "high":
      return {
        badge: "bg-amber text-amber-bg",
        card: "bg-amber-bg/40 border-amber/20",
      };
    case "medium":
      return {
        badge: "bg-amber/60 text-amber-bg",
        card: "bg-amber-bg/20 border-amber/10",
      };
    default:
      return {
        badge: "bg-green text-green-bg",
        card: "bg-green-bg/40 border-green/20",
      };
  }
}

export default function PlannerStreamPanel({
  events,
  busy,
}: PlannerStreamPanelProps) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="section-title">Planner Stream</h2>
          <p className="mt-1 text-xs text-dim">
            Status events are retained without raw chunk buffers.
          </p>
        </div>
        <span className={`flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-[11px] ${busy ? 'border-cyan/50 bg-cyan/10 text-cyan shadow-[0_0_8px_rgba(34,211,238,0.2)]' : 'border-border bg-surface text-dim'}`}>
          {busy ? "streaming" : "idle"}
          {busy && <span className="inline-block h-2.5 w-1.5 bg-cyan animate-data-blink" />}
        </span>
      </div>

      <div className="mt-4 space-y-2 relative">
        {events.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-dim animate-fade-in-up">
            Awaiting planner traffic.
          </div>
        ) : null}
        {events.map((event, index) => (
          <div
            key={`${event.type}-${event.status}-${index}`}
            className="rounded-lg border border-border bg-surface px-3 py-2 animate-slide-in-right opacity-0"
            style={{ animationDelay: `${index * 50}ms`, animationFillMode: 'forwards' }}
          >
            <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">
              {event.type} · {event.phase} · {event.status}
            </div>
            {event.content ? (
              <div className="mt-1 text-sm text-text">
                {event.content.includes("```json") ? (
                  <div className="space-y-2">
                    {event.content.split("```json").map((part, i) => {
                      if (i === 0) return part ? <p key={i}>{part}</p> : null;
                      const [jsonPart, ...rest] = part.split("```");
                      try {
                        const parsed = JSON.parse(jsonPart);
                        return (
                          <div key={i} className="space-y-3">
                            <p className="text-sm leading-relaxed text-text">
                              {parsed.summary}
                            </p>
                            {parsed.issues?.length > 0 && (
                              <ul className="space-y-2">
                                {parsed.issues.map(
                                  (
                                    issue: {
                                      severity: string;
                                      title: string;
                                      fix?: string;
                                    },
                                    i: number,
                                  ) => {
                                    const style = severityStyle(issue.severity);
                                    return (
                                      <li
                                        key={i}
                                        className={`rounded-md border px-3 py-2.5 ${style.card}`}
                                      >
                                        <div className="flex items-center gap-2">
                                          <span
                                            className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide ${style.badge}`}
                                          >
                                            {issue.severity}
                                          </span>
                                          <p className="text-sm font-medium text-text">
                                            {issue.title}
                                          </p>
                                        </div>
                                        {issue.fix && (
                                          <p className="mt-1.5 pl-0 text-xs leading-relaxed text-dim">
                                            {issue.fix}
                                          </p>
                                        )}
                                      </li>
                                    );
                                  },
                                )}
                              </ul>
                            )}

                            {rest.join("```") ? (
                              <p>{rest.join("```")}</p>
                            ) : null}
                          </div>
                        );
                      } catch {
                        return (
                          <pre
                            key={i}
                            className="overflow-x-auto rounded-lg bg-black/20 p-3 font-mono text-xs"
                          >
                            {part}
                          </pre>
                        );
                      }
                    })}
                  </div>
                ) : event.content.trim().startsWith("{") &&
                  event.content.trim().endsWith("}") ? (
                  <pre className="overflow-x-auto rounded-lg bg-black/20 p-3 font-mono text-xs text-cyan">
                    {(() => {
                      try {
                        return JSON.stringify(
                          JSON.parse(event.content),
                          null,
                          2,
                        );
                      } catch {
                        return event.content;
                      }
                    })()}
                  </pre>
                ) : (
                  <p>{event.content}</p>
                )}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}
