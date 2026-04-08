import { Link, useParams } from 'react-router-dom';
import Breadcrumb from '../components/Breadcrumb';
import EventLogTable from '../components/EventLogTable';
import StatusBadge from '../components/StatusBadge';
import StatsBar from '../components/StatsBar';
import { useMission } from '../hooks/useMission';
import type { EventLogEntry, TaskState, TaskStatus } from '../lib/types';

type MissionBadgeStatus = 'active' | 'complete' | 'failed' | 'needs_human';

function formatDuration(startedAt: string, completedAt?: string | null): string {
  const started = new Date(startedAt).getTime();
  const ended = completedAt ? new Date(completedAt).getTime() : Date.now();

  if (!Number.isFinite(started) || !Number.isFinite(ended)) {
    return '?';
  }

  const seconds = Math.max(0, Math.floor((ended - started) / 1000));
  if (seconds < 60) {
    return `${seconds}s`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  }

  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function getMissionStatus(taskStates: Record<string, TaskState>): MissionBadgeStatus {
  const states = Object.values(taskStates);
  if (states.some((taskState) => taskState.status === 'failed')) {
    return 'failed';
  }
  if (states.some((taskState) => taskState.human_intervention_needed || taskState.status === 'needs_human')) {
    return 'needs_human';
  }
  if (states.every((taskState) => taskState.status === 'review_approved')) {
    return 'complete';
  }
  return 'active';
}

function getScoreClassName(score: number): string {
  if (score <= 4) {
    return 'text-red bg-red-bg border-red/20';
  }
  if (score <= 7) {
    return 'text-amber bg-amber-bg border-amber/20';
  }
  return 'text-green bg-green-bg border-green/20';
}

function formatScore(score: number): string {
  return Number.isInteger(score) ? `${score}/10` : `${score.toFixed(1)}/10`;
}

function MissionDetailPageLoading({ message }: { message: string }) {
  return (
    <main className="site-main">
      <p className="rounded-lg border border-border bg-card px-4 py-3 text-dim">{message}</p>
    </main>
  );
}

function MissionDetailPageContent({ missionId }: { missionId: string }) {
  const { mission, loading, error } = useMission(missionId);

  if (loading && !mission) {
    return <MissionDetailPageLoading message="Loading mission..." />;
  }

  if (error && !mission) {
    return <MissionDetailPageLoading message={error} />;
  }

  if (!mission) {
    return <MissionDetailPageLoading message="Mission not found." />;
  }

  const completedTasks = Object.values(mission.task_states).filter(
    (taskState) => taskState.status === 'review_approved',
  ).length;
  const totalTasks = mission.spec.tasks.length;
  const avgScores = Object.values(mission.task_states)
    .map((taskState) => taskState.review_score)
    .filter((score) => score > 0);
  const avgReviewScore = avgScores.length > 0
    ? (avgScores.reduce((sum, score) => sum + score, 0) / avgScores.length).toFixed(1)
    : '—';
  const workerAgent = mission.worker_agent
    ? `${mission.worker_agent}${mission.worker_model ? ` · ${mission.worker_model}` : ''}`
    : '—';
  const eventLog: EventLogEntry[] = [...(mission.event_log ?? [])].slice(-50).reverse();

  const stats = [
    { label: 'Tasks Completed', value: `${completedTasks} / ${totalTasks}` },
    { label: 'Duration', value: formatDuration(mission.started_at, mission.completed_at) },
    { label: 'Total Retries', value: mission.total_retries },
    { label: 'Avg Review Score', value: avgReviewScore },
    { label: 'Human Interventions', value: mission.total_human_interventions },
    { label: 'Worker Agent', value: workerAgent },
  ];

  return (
    <main className="site-main">
      <Breadcrumb missionId={missionId} missionName={mission.spec.name} className="mb-6" />

      <div className="page-head">
        <h1>{mission.spec.name}</h1>
        <StatusBadge status={getMissionStatus(mission.task_states)} />
      </div>

      <StatsBar stats={stats} className="mb-7" />

      <section className="sec">
        <h2 className="section-title">Tasks</h2>
        <div className="overflow-hidden rounded-lg border border-border bg-card">
          <table className="w-full border-collapse">
            <thead>
              <tr className="bg-surface text-left text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">
                <th className="border-b border-border px-4 py-2">Task #</th>
                <th className="border-b border-border px-4 py-2">Title</th>
                <th className="border-b border-border px-4 py-2">Retries</th>
                <th className="border-b border-border px-4 py-2">Score</th>
                <th className="border-b border-border px-4 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {mission.spec.tasks.map((taskSpec, index) => {
                const taskState = mission.task_states[taskSpec.id] ?? {
                  task_id: taskSpec.id,
                  status: 'pending' as TaskStatus,
                  retries: 0,
                  review_score: 0,
                  human_intervention_needed: false,
                  last_updated: mission.started_at,
                };
                const score = taskState.review_score;

                return (
                  <tr key={taskSpec.id} className="border-b border-border last:border-b-0">
                    <td className="px-4 py-2 align-middle text-[12px] text-muted">
                      <Link className="text-dim hover:text-text hover:no-underline" to={`/mission/${missionId}/task/${taskSpec.id}`}>
                        {index + 1}
                      </Link>
                    </td>
                    <td className="px-4 py-2 align-middle">
                      <Link className="text-text hover:text-text hover:no-underline" to={`/mission/${missionId}/task/${taskSpec.id}`}>
                        {taskSpec.title}
                      </Link>
                    </td>
                    <td className="px-4 py-2 align-middle text-[12px] text-muted">
                      {taskState.retries > 0 ? `${taskState.retries}r` : '—'}
                    </td>
                    <td className="px-4 py-2 align-middle">
                      {score > 0 ? (
                        <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-bold ${getScoreClassName(score)}`}>
                          {formatScore(score)}
                        </span>
                      ) : (
                        <span className="text-dim">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2 align-middle">
                      <StatusBadge status={taskState.status} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="sec">
        <h2 className="section-title">Event Log</h2>
        <EventLogTable entries={eventLog} />
      </section>
    </main>
  );
}

export default function MissionDetailPage() {
  const params = useParams<{ id?: string }>();

  if (!params.id) {
    return <MissionDetailPageLoading message="Missing mission id." />;
  }

  return <MissionDetailPageContent missionId={params.id} />;
}
