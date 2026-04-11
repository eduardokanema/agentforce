import type { BlackHoleCampaign, BlackHoleLoop } from "../../lib/types";

interface BlackHoleLedgerProps {
  campaign?: BlackHoleCampaign | null;
  loops: BlackHoleLoop[];
}

function formatMetric(metric: Record<string, unknown> | undefined, key: string): string {
  const value = metric?.[key];
  if (typeof value === "number") {
    return value.toLocaleString();
  }
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  return "—";
}

function formatCurrency(value?: number): string {
  return `$${(value ?? 0).toFixed(4)}`;
}

export default function BlackHoleLedger({ campaign, loops }: BlackHoleLedgerProps) {
  return (
    <section className="rounded-[1.15rem] border border-border bg-card p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan">
            Loop Ledger
          </div>
          <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em] text-text">
            Candidate-by-candidate provenance
          </h2>
          <p className="mt-2 max-w-[56ch] text-sm leading-7 text-dim">
            Each loop records one ranked candidate, one child mission, and the measured delta after the mission settles.
          </p>
        </div>
        <div className="rounded-full border border-border bg-surface px-3 py-1 font-mono text-[11px] text-dim">
          {campaign ? `${campaign.current_loop}/${campaign.max_loops} loops` : "0 loops"}
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {loops.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-dim">
            No black-hole loops recorded yet.
          </div>
        ) : null}

        {loops.map((loop) => (
          <article key={`${loop.campaign_id}-${loop.loop_no}`} className="rounded-xl border border-border bg-surface p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                  Loop {String(loop.loop_no).padStart(2, "0")}
                </div>
                <div className="mt-1 text-sm font-semibold text-text">
                  {loop.candidate_summary || loop.candidate_id || "Candidate pending"}
                </div>
                <div className="mt-2 font-mono text-[11px] text-dim">
                  {loop.plan_run_id ? `plan ${loop.plan_run_id}` : "plan pending"} · {loop.mission_id ? `mission ${loop.mission_id}` : "mission pending"}
                </div>
              </div>
              <div className="rounded-full border border-border bg-card px-3 py-1 font-mono text-[11px] text-dim">
                {loop.status}
              </div>
            </div>

            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <div className="rounded-lg border border-border bg-card px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Before</div>
                <div className="mt-1 text-sm font-semibold text-text">
                  {formatMetric(loop.metric_before, "violations")} violations
                </div>
                <div className="mt-1 text-[11px] text-dim">
                  max {formatMetric(loop.metric_before, "max_line_count")}
                </div>
              </div>
              <div className="rounded-lg border border-border bg-card px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">After</div>
                <div className="mt-1 text-sm font-semibold text-text">
                  {formatMetric(loop.metric_after, "violations")} violations
                </div>
                <div className="mt-1 text-[11px] text-dim">
                  max {formatMetric(loop.metric_after, "max_line_count")}
                </div>
              </div>
              <div className="rounded-lg border border-border bg-card px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Delta</div>
                <div className="mt-1 text-sm font-semibold text-text">
                  {typeof loop.normalized_delta === "number" ? loop.normalized_delta.toFixed(1) : "—"}
                </div>
                <div className="mt-1 text-[11px] text-dim">{formatCurrency(loop.cost_usd)} total loop cost</div>
              </div>
            </div>

            {loop.review_summary ? (
              <p className="mt-3 text-sm leading-6 text-dim">{loop.review_summary}</p>
            ) : null}
            {loop.gate_reason ? (
              <div className="mt-3 rounded-lg border border-red/20 bg-red/5 px-3 py-2 text-sm text-red">
                {loop.gate_reason}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
