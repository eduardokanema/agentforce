import type { PlanningFollowUp } from "../../lib/types";

interface PlanningFollowUpPanelProps {
  followUps: PlanningFollowUp[];
  title?: string;
  description?: string;
}

function sourceLabel(source: string): string {
  if (source === "preflight") {
    return "Preflight";
  }
  if (source === "repair") {
    return "Repair";
  }
  if (source === "follow_up_prompt") {
    return "Prompt";
  }
  return source.replace(/_/g, " ");
}

function resolutionText(followUp: PlanningFollowUp): string | null {
  return followUp.custom_answer?.trim()
    || followUp.selected_option?.trim()
    || null;
}

export default function PlanningFollowUpPanel({
  followUps,
  title = "Delegated to Solver",
  description = "These planning questions were converted into execution-owned tasks. Launch stays open as long as the generated tasks are present in the mission.",
}: PlanningFollowUpPanelProps) {
  return (
    <section className="rounded-[1.15rem] border border-cyan/30 bg-[radial-gradient(circle_at_top,rgba(34,211,238,0.14),transparent_60%),var(--color-card)] p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">{title}</h2>
          <p className="mt-1 max-w-[68ch] text-sm leading-7 text-dim">{description}</p>
        </div>
        <div className="rounded-full border border-cyan/25 bg-cyan/10 px-3 py-1 font-mono text-[11px] text-cyan">
          {followUps.length} follow-up{followUps.length === 1 ? "" : "s"}
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {followUps.map((followUp) => {
          const resolution = resolutionText(followUp);
          return (
            <article key={followUp.id} className="rounded-xl border border-border bg-surface p-4">
              <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.08em] text-muted">
                <span>{sourceLabel(followUp.source)}</span>
                <span className="rounded-full border border-border bg-card px-2 py-0.5 normal-case tracking-normal text-dim">
                  {followUp.status}
                </span>
              </div>
              <div className="mt-2 text-sm font-semibold text-text">{followUp.prompt}</div>
              {followUp.reason ? (
                <p className="mt-1 text-xs leading-6 text-dim">{followUp.reason}</p>
              ) : null}
              {resolution ? (
                <div className="mt-3 rounded-lg border border-cyan/20 bg-cyan/6 px-3 py-2 text-sm text-text">
                  Recorded preference: {resolution}
                </div>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-dim">
                {followUp.generated_task_ids.map((taskId) => (
                  <span key={taskId} className="rounded-full border border-border bg-card px-3 py-1 font-mono">
                    Task {taskId}
                  </span>
                ))}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
