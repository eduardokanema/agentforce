import { Link } from 'react-router-dom';
import MissionCard from '../components/MissionCard';
import { archiveMission, deleteMission, restartMission, stopMission, unarchiveMission } from '../lib/api';
import { useMissionList } from '../hooks/useMissionList';
import { useToast } from '../hooks/useToast';
import type { MissionSummary } from '../lib/types';

function LoadingSkeleton() {
  return (
    <div aria-label="Loading missions" className="grid gap-4">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={index} className="animate-pulse overflow-hidden rounded-lg border border-border bg-card">
          <div className="pl-5 pr-4 py-3 flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <div className="h-4 w-48 rounded bg-surface" />
              <div className="h-5 w-20 rounded-full bg-surface" />
              <div className="ml-auto h-3 w-14 rounded bg-surface" />
            </div>
            <div className="h-1.5 w-full rounded bg-surface" />
            <div className="flex gap-4">
              <div className="h-3 w-16 rounded bg-surface" />
              <div className="h-3 w-16 rounded bg-surface" />
              <div className="h-3 w-16 rounded bg-surface" />
              <div className="h-3 w-32 rounded bg-surface" />
            </div>
            <div className="flex items-center gap-2">
              <div className="h-4 w-48 rounded-full bg-surface" />
              <div className="h-4 w-20 rounded-full bg-surface" />
              <div className="h-3 w-16 rounded bg-surface" />
            </div>
            <div className="flex gap-2">
              <div className="h-5 w-16 rounded-full bg-surface" />
              <div className="h-5 w-20 rounded-full bg-surface" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function getRunningCount(missions: MissionSummary[]): number {
  return missions.filter((mission) => mission.status === 'active' || mission.status === 'in_progress').length;
}

function getDoneCount(missions: MissionSummary[]): number {
  return missions.filter((mission) => (
    mission.status === 'complete' || mission.status === 'completed' || mission.status === 'review_approved'
  )).length;
}

function getCostTotal(missions: MissionSummary[]): number {
  return missions.reduce((total, mission) => total + (mission.cost_usd ?? 0), 0);
}

function getTokenTotal(missions: MissionSummary[]): number {
  return missions.reduce((total, mission) => total + (mission.tokens_in ?? 0) + (mission.tokens_out ?? 0), 0);
}

function MetricsStrip({ missions }: { missions: MissionSummary[] }) {
  const total = missions.length;
  const running = getRunningCount(missions);
  const done = getDoneCount(missions);
  const cost = getCostTotal(missions);
  const tokens = getTokenTotal(missions);

  return (
    <div className="flex flex-wrap gap-6 border-b border-border bg-surface px-4 py-2 text-[11px] text-dim">
      <span>Total: {total}</span>
      <span>Running: {running}</span>
      <span>Done: {done}</span>
      <span>Cost: ${cost.toFixed(2)}</span>
      <span>Tokens: {tokens}</span>
    </div>
  );
}

export default function MissionsPage() {
  const { missions, loading, refresh } = useMissionList();
  const { addToast } = useToast();

  const handleStop = async (missionId: string): Promise<void> => {
    try {
      await stopMission(missionId);
      addToast('Mission stopped', 'success');
      refresh();
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Failed to stop mission', 'error');
    }
  };

  const handleRestart = async (missionId: string): Promise<void> => {
    try {
      await restartMission(missionId);
      addToast('Mission restarted', 'success');
      refresh();
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Failed to restart mission', 'error');
    }
  };

  const handleArchive = async (missionId: string): Promise<void> => {
    try {
      await archiveMission(missionId);
      refresh();
      addToast('Mission archived', 'info', {
        label: 'Undo',
        onClick: () => {
          void unarchiveMission(missionId)
            .then(() => { refresh(); })
            .catch(() => undefined);
        },
      });
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Failed to archive mission', 'error');
    }
  };

  const handleDelete = async (missionId: string): Promise<void> => {
    try {
      await deleteMission(missionId);
      addToast('Mission deleted', 'info');
      refresh();
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Failed to delete mission', 'error');
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">AgentForce Missions</h1>
          <p className="mt-1 text-sm text-dim">Track mission progress, cost, and controls from one list.</p>
        </div>
        <Link
          className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 hover:no-underline"
          to="/plan"
        >
          + New Mission
        </Link>
      </header>

      {!loading ? <MetricsStrip missions={missions} /> : null}

      {loading ? (
        <LoadingSkeleton />
      ) : missions.length === 0 ? (
        <section className="rounded-lg border border-border bg-card px-4 py-5 text-sm text-dim">
          <span>No missions yet. </span>
          <Link className="text-cyan hover:no-underline" to="/plan">
            Launch one with Plan Mode →
          </Link>
        </section>
      ) : (
        <ul className="grid gap-4">
          {missions.map((mission) => (
            <li key={mission.mission_id}>
              <MissionCard
                mission={mission}
                onArchive={() => {
                  void handleArchive(mission.mission_id);
                }}
                onDelete={() => {
                  void handleDelete(mission.mission_id);
                }}
                onRestart={() => {
                  void handleRestart(mission.mission_id);
                }}
                onStop={() => {
                  void handleStop(mission.mission_id);
                }}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
