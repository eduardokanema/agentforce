import type { CockpitPhaseId, CockpitPhaseState } from '../../lib/planFlow';

interface FlightPlanProgressRailProps {
  phases: CockpitPhaseState[];
  selectedPhase: CockpitPhaseId;
  onSelectPhase: (phaseId: CockpitPhaseId) => void;
}

function nodeClassName(phase: CockpitPhaseState, selected: boolean): string {
  if (phase.status === 'blocked') {
    return [
      'border-red/50 bg-red/10 text-red shadow-[0_0_18px_rgba(255,107,107,0.2)]',
      selected ? 'ring-1 ring-red/40' : '',
    ].join(' ');
  }
  if (phase.status === 'current') {
    return [
      'border-cyan/50 bg-cyan/12 text-cyan shadow-[0_0_18px_rgba(34,211,238,0.22)]',
      selected ? 'ring-1 ring-cyan/40' : '',
    ].join(' ');
  }
  if (phase.status === 'complete') {
    return [
      'border-green/35 bg-green/10 text-green',
      selected ? 'ring-1 ring-green/30' : '',
    ].join(' ');
  }
  if (phase.status === 'up_next') {
    return [
      'border-amber/35 bg-amber/10 text-amber',
      selected ? 'ring-1 ring-amber/30' : '',
    ].join(' ');
  }
  return 'border-border bg-surface text-dim';
}

function connectorClassName(left: CockpitPhaseState, right: CockpitPhaseState): string {
  if (left.status === 'complete' && (right.status === 'complete' || right.status === 'current' || right.status === 'blocked')) {
    return 'bg-gradient-to-r from-green/45 via-cyan/28 to-cyan/12';
  }
  if (right.status === 'current' || right.status === 'blocked') {
    return 'bg-gradient-to-r from-cyan/20 to-transparent';
  }
  if (right.status === 'up_next') {
    return 'bg-gradient-to-r from-amber/14 to-transparent';
  }
  return 'bg-border';
}

export default function FlightPlanProgressRail({
  phases,
  selectedPhase,
  onSelectPhase,
}: FlightPlanProgressRailProps) {
  return (
    <section className="overflow-hidden rounded-[1.25rem] border border-border bg-[radial-gradient(circle_at_top,rgba(34,211,238,0.12),transparent_58%),linear-gradient(180deg,rgba(17,28,46,0.96),rgba(13,21,37,0.92))] px-4 py-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan">
            Flight Progress
          </div>
          <h2 className="mt-2 text-[clamp(1.2rem,2vw,1.6rem)] font-semibold tracking-[-0.03em] text-white">
            Live stage in focus. Past stages stay reviewable.
          </h2>
        </div>
        <div className="rounded-full border border-border bg-black/10 px-3 py-1 font-mono text-[11px] text-dim">
          {phases.filter((phase) => phase.status === 'complete').length}/{phases.length} complete
        </div>
      </div>

      <div className="mt-5 overflow-x-auto pb-1">
        <div className="flex min-w-max items-start gap-2">
          {phases.map((phase, index) => {
            const selected = phase.id === selectedPhase;
            const interactive = phase.available;
            const expanded = phase.status === 'current' || phase.status === 'blocked';

            return (
              <div key={phase.id} className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={!interactive}
                  onClick={() => interactive && onSelectPhase(phase.id)}
                  className={[
                    expanded ? 'group min-w-[13rem] rounded-2xl border px-3 py-3 text-left transition-all duration-300' : 'group min-w-[8.4rem] rounded-2xl border px-3 py-3 text-left transition-all duration-300',
                    nodeClassName(phase, selected),
                    interactive ? 'hover:-translate-y-[1px]' : 'cursor-not-allowed opacity-70',
                  ].join(' ')}
                  aria-current={selected ? 'step' : undefined}
                >
                  <div className="flex items-center gap-3">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-current/18 bg-black/10 font-mono text-[11px] uppercase tracking-[0.12em]">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold text-text">
                          {phase.label}
                        </span>
                        <span className="h-2 w-2 shrink-0 rounded-full bg-current/80" />
                      </div>
                      <div className="mt-1 text-[10px] uppercase tracking-[0.14em] text-dim">
                        {phase.status.replace('_', ' ')}
                      </div>
                    </div>
                  </div>
                  {expanded ? (
                    <p className="mt-3 line-clamp-2 text-[12px] leading-5 text-dim">
                      {phase.railSummary || phase.summary}
                    </p>
                  ) : null}
                  {expanded && phase.blocker ? (
                    <div className="mt-3 text-[11px] text-red/85">
                      {phase.blocker}
                    </div>
                  ) : null}
                </button>
                {index < phases.length - 1 ? (
                  <div className={`mt-[2.25rem] h-[1px] w-10 shrink-0 ${connectorClassName(phase, phases[index + 1])}`} />
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
