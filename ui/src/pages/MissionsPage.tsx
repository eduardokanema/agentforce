import { Link } from 'react-router-dom';
import AgentChip from '../components/AgentChip';
import ConnectionBanner from '../components/ConnectionBanner';
import MissionProgressBar from '../components/MissionProgressBar';
import StatusBadge from '../components/StatusBadge';
import { useMissionList } from '../hooks/useMissionList';

function LoadingSkeleton() {
  return (
    <div aria-label="Loading missions" className="grid gap-4">
      {Array.from({ length: 3 }).map((_, index) => (
        <div
          key={index}
          className="animate-pulse rounded-xl border border-border bg-card p-5"
        >
          <div className="space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div className="h-5 w-48 rounded bg-surface" />
              <div className="h-6 w-24 rounded-full bg-surface" />
            </div>
            <div className="h-1.5 w-full rounded bg-surface" />
            <div className="flex flex-wrap items-center gap-3">
              <div className="h-4 w-20 rounded bg-surface" />
              <div className="h-4 w-28 rounded bg-surface" />
              <div className="h-5 w-36 rounded-full bg-surface" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function MissionsPage() {
  const { missions, loading } = useMissionList();

  return (
    <div className="min-h-screen bg-bg text-text">
      <ConnectionBanner />

      <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-8">
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">AgentForce Missions</h1>
        </header>

        {loading ? (
          <LoadingSkeleton />
        ) : missions.length === 0 ? (
          <section className="rounded-xl border border-border bg-card p-8 text-sm text-dim">
            <h2 className="text-base font-semibold text-text">No missions yet</h2>
            <p className="mt-2">Missions will appear here once they start.</p>
          </section>
        ) : (
          <ul className="grid gap-4">
            {missions.map((mission) => (
              <li
                key={mission.mission_id}
                className="rounded-lg border border-border bg-card p-5 transition-colors duration-200 hover:bg-card-hover"
              >
                <article className="space-y-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-2">
                      <Link
                        className="text-lg font-semibold text-text transition-colors hover:text-blue hover:no-underline"
                        to={`/mission/${mission.mission_id}`}
                      >
                        {mission.name}
                      </Link>
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge status={mission.status} />
                        <span className="text-xs uppercase tracking-[0.08em] text-dim">
                          {mission.done_tasks} / {mission.total_tasks} tasks
                        </span>
                      </div>
                    </div>

                    <span className="text-sm text-dim">{mission.duration}</span>
                  </div>

                  <MissionProgressBar pct={mission.pct} />

                  <div className="flex flex-wrap items-center gap-3">
                    <AgentChip agent={mission.worker_agent} model={mission.worker_model} />
                  </div>
                </article>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
