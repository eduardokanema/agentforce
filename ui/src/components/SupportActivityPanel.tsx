import { useMemo } from "react";
import type { SupportActivitySource } from "../lib/supportActivity";
import {
  formatExecutionProfile,
  formatSupportActivityDateTime,
  supportActivityEvents,
  supportActivityFindings,
} from "../lib/supportActivity";
import StructuredStream from "./StructuredStream";

function findingTone(severity: string): { badge: string; card: string } {
  switch (severity.toLowerCase()) {
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
        badge: "bg-amber/70 text-amber-bg",
        card: "bg-amber-bg/20 border-amber/10",
      };
    case "warning":
      return {
        badge: "bg-amber text-amber-bg",
        card: "bg-amber-bg/30 border-amber/15",
      };
    case "suggestion":
      return {
        badge: "bg-cyan text-cyan-bg",
        card: "bg-cyan/10 border-cyan/20",
      };
    default:
      return {
        badge: "bg-green text-green-bg",
        card: "bg-green-bg/40 border-green/20",
      };
  }
}

export default function SupportActivityPanel({
  sourceId,
  label,
  source,
}: {
  sourceId: string;
  label: string;
  source: SupportActivitySource | null;
}) {
  const events = useMemo(() => supportActivityEvents(sourceId, label, source), [label, source, sourceId]);
  const findings = useMemo(() => supportActivityFindings(source), [source]);
  const profile = formatExecutionProfile(source?.metadata?.profile);
  const streamDone = source?.status !== "running" && source?.status !== "started";

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-border bg-surface px-4 py-3">
          <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Status</div>
          <div className="mt-2 text-sm font-semibold text-text">
            {source?.status?.replaceAll("_", " ") ?? "idle"}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface px-4 py-3">
          <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Latest Timestamp</div>
          <div className="mt-2 text-sm font-semibold text-text">
            {formatSupportActivityDateTime(source?.completed_at || source?.started_at || null)}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface px-4 py-3">
          <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Usage</div>
          <div className="mt-2 text-sm font-semibold text-text">
            {source ? `${source.tokens_in ?? 0} in / ${source.tokens_out ?? 0} out` : "Waiting"}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface px-4 py-3">
          <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Profile</div>
          <div className="mt-2 text-sm font-semibold text-text">
            {profile ?? "Not recorded"}
          </div>
        </div>
      </div>

      <StructuredStream events={events} done={streamDone} />

      {findings.length > 0 ? (
        <section className="rounded-lg border border-border bg-card p-4">
          <div className="text-[11px] uppercase tracking-[0.08em] text-dim">
            Structured findings
          </div>
          <div className="mt-3 space-y-2">
            {findings.map((finding) => {
              const tone = findingTone(finding.severity);
              return (
                <article
                  key={finding.id}
                  className={`rounded-lg border px-3 py-3 ${tone.card}`}
                >
                  <div className="flex items-start gap-2">
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide ${tone.badge}`}
                    >
                      {finding.severity}
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-text">
                        {finding.title}
                      </div>
                      {finding.detail ? (
                        <p className="mt-1 text-xs leading-relaxed text-dim">
                          {finding.detail}
                        </p>
                      ) : null}
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ) : null}
    </div>
  );
}
