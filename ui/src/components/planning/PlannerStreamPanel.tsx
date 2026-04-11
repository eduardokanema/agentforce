import { useEffect, useMemo, useRef, useState } from "react";

export interface PlannerStreamEventView {
  type: string;
  phase: string;
  status: string;
  content?: string;
  timestamp?: string | null;
  live?: boolean;
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

function formatClock(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function labelForEvent(event: PlannerStreamEventView): string {
  const type = event.type.replace(/_/g, " ");
  if (type === "plan_cost_update") return "usage";
  if (type === "plan_step_started") return "step started";
  if (type === "plan_step_completed") return "step completed";
  if (type === "plan_run_started") return "run started";
  if (type === "plan_run_failed") return "run failed";
  if (type === "plan_run_queued") return "queued";
  return type;
}

function toneForEvent(event: PlannerStreamEventView): string {
  if (event.type === "plan_cost_update") {
    return "border-emerald-400/20 bg-[linear-gradient(135deg,rgba(16,185,129,0.12),rgba(16,185,129,0.04))] text-green";
  }
  if (event.status === "failed" || event.type === "plan_run_failed") {
    return "border-red/20 bg-red/5 text-red";
  }
  if (event.status === "running" || event.status === "started") {
    return "border-cyan/20 bg-cyan/5 text-cyan";
  }
  return "border-border bg-surface text-dim";
}

export default function PlannerStreamPanel({
  events,
  busy,
}: PlannerStreamPanelProps) {
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const eventViews = useMemo(
      () => events.map((event, index) => ({
      ...event,
      key: `${event.type}-${event.phase}-${event.status}-${index}`,
      label: labelForEvent(event),
      tone: toneForEvent(event),
      time: event.live ? 'LIVE' : formatClock(event.timestamp ?? ''),
    })),
    [events],
  );

  useEffect(() => {
    if (!autoScroll) {
      return;
    }
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [autoScroll, eventViews.length]);

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="section-title">Planner Stream</h2>
          <p className="mt-1 text-xs text-dim">Flight Director Cockpit activity feed.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className={[
              "rounded border px-2 py-0.5 font-mono text-[11px] transition-colors",
              autoScroll ? "border-cyan/30 bg-cyan/10 text-cyan" : "border-border text-dim hover:bg-surface",
            ].join(" ")}
            onClick={() => setAutoScroll((current) => !current)}
          >
            {autoScroll ? "↓ Auto" : "↑ Manual"}
          </button>
          <span className={`flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-[11px] ${busy ? 'border-cyan/50 bg-cyan/10 text-cyan shadow-[0_0_8px_rgba(34,211,238,0.2)]' : 'border-border bg-surface text-dim'}`}>
            {busy ? "streaming" : "idle"}
            {busy && <span className="inline-block h-2.5 w-1.5 bg-cyan animate-data-blink" />}
          </span>
        </div>
      </div>

      <div ref={scrollRef} className="mt-4 max-h-[560px] overflow-y-auto">
        <div className="space-y-2 relative">
        {eventViews.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-dim">
            Awaiting planner traffic.
          </div>
        ) : null}
        {eventViews.map((event) => (
          <div
            key={event.key}
            className={`rounded-lg border px-3 py-3 ${event.tone}`}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-current/20 bg-black/5 px-2 py-0.5 text-[10px] uppercase tracking-[0.08em]">
                  {event.label}
                </span>
                <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">
                  {event.phase} · {event.status}
                </span>
              </div>
              <span className="font-mono text-[11px] text-dim">
                {event.time || 'Pending'}
              </span>
            </div>
            {event.content ? (
              <div className="mt-1 text-sm text-text">
                {event.type === "plan_cost_update" ? (
                  <div className="mt-3 rounded border border-current/10 bg-black/10 px-3 py-2 font-mono text-[12px] text-text">
                    {event.content}
                  </div>
                ) : event.content.includes("```json") ? (
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
                ) : (
                  <p>{event.content}</p>
                )}
              </div>
            ) : null}
          </div>
        ))}
        </div>
      </div>
    </section>
  );
}
