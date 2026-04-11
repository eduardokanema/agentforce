import type { PlanningSubstepState } from '../../lib/planFlow';

interface PlanningSubstepTrackerProps {
  steps: PlanningSubstepState[];
  title?: string;
}

function chipClassName(status: PlanningSubstepState['status']): string {
  switch (status) {
    case 'running':
      return 'border-cyan/40 bg-cyan/10 text-cyan';
    case 'complete':
      return 'border-green/30 bg-green/10 text-green';
    case 'failed':
      return 'border-red/40 bg-red/10 text-red';
    case 'stale':
      return 'border-amber/40 bg-amber/10 text-amber';
    default:
      return 'border-border bg-surface text-dim';
  }
}

export default function PlanningSubstepTracker({
  steps,
  title = 'Planning Substeps',
}: PlanningSubstepTrackerProps) {
  return (
    <section className="rounded-[1.15rem] border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="section-title">{title}</h2>
          <p className="mt-1 text-xs text-dim">
            Canonical backend steps, compressed to what matters right now.
          </p>
        </div>
        <div className="rounded-full border border-border bg-surface px-3 py-1 font-mono text-[11px] text-dim">
          {steps.filter((step) => step.status === 'complete').length}/{steps.length}
        </div>
      </div>

      <div className="mt-4 space-y-2">
        {steps.map((step, index) => (
          <article
            key={step.id}
            className={[
              'relative overflow-hidden rounded-xl border px-3 py-3 transition-colors',
              chipClassName(step.status),
            ].join(' ')}
          >
            {step.status === 'running' ? (
              <div className="pointer-events-none absolute inset-x-0 top-0 h-8 bg-gradient-to-r from-transparent via-white/5 to-transparent animate-[scan-line_2.2s_linear_infinite]" />
            ) : null}
            <div className="relative flex items-start gap-3">
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-current/18 bg-black/10 font-mono text-[11px] uppercase tracking-[0.12em] text-inherit">
                {String(index + 1).padStart(2, '0')}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-text">
                      {step.label}
                    </div>
                    <div className="mt-1 text-[10px] uppercase tracking-[0.14em] text-dim">
                      {step.status}
                    </div>
                  </div>
                  <span className="rounded-full border border-current/20 px-2 py-0.5 text-[10px] uppercase tracking-[0.12em]">
                    {step.timestamp ? new Date(step.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Pending'}
                  </span>
                </div>
                {step.summary && step.status !== 'complete' ? (
                  <p className="mt-2 text-[12px] leading-5 text-dim">
                    {step.summary}
                  </p>
                ) : null}
                {step.status === 'complete' && step.summary ? (
                  <p className="mt-2 text-[12px] leading-5 text-dim">
                    Locked in.
                  </p>
                ) : null}
                {step.status === 'idle' && !step.summary ? (
                  <p className="mt-2 text-[12px] leading-5 text-dim">
                    Waiting for the orbit to reach this checkpoint.
                  </p>
                ) : null}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
