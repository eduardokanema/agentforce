import { useParams } from 'react-router-dom';
import Breadcrumb from '../components/Breadcrumb';
import StatusBadge from '../components/StatusBadge';
import StatsBar from '../components/StatsBar';
import TerminalPanel from '../components/TerminalPanel';
import { useMission } from '../hooks/useMission';
import { useTaskStream } from '../hooks/useTaskStream';
import type { TaskSpec, TaskState, TaskStatus } from '../lib/types';

function formatDuration(startedAt?: string | null, completedAt?: string | null): string {
  if (!startedAt) {
    return '—';
  }

  const started = new Date(startedAt).getTime();
  const ended = completedAt ? new Date(completedAt).getTime() : Date.now();
  if (!Number.isFinite(started) || !Number.isFinite(ended)) {
    return '—';
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

function formatScore(score: number): string {
  return Number.isInteger(score) ? `${score}/10` : `${score.toFixed(1)}/10`;
}

function getTaskState(taskState: TaskState | undefined, taskSpec: TaskSpec, missionStartedAt: string): TaskState {
  return (
    taskState ?? {
      task_id: taskSpec.id,
      status: 'pending' as TaskStatus,
      retries: 0,
      review_score: 0,
      human_intervention_needed: false,
      last_updated: missionStartedAt,
    }
  );
}

function LoadingState({ message }: { message: string }) {
  return (
    <main className="site-main">
      <p className="rounded-lg border border-border bg-card px-4 py-3 text-dim">{message}</p>
    </main>
  );
}

function TaskDetailContent({ missionId, taskId }: { missionId: string; taskId: string }) {
  const { mission, loading, error } = useMission(missionId);
  const { lines, done } = useTaskStream(missionId, taskId);

  if (loading && !mission) {
    return <LoadingState message="Loading task..." />;
  }

  if (error && !mission) {
    return <LoadingState message={error} />;
  }

  if (!mission) {
    return <LoadingState message="Mission not found." />;
  }

  const taskSpec = mission.spec.tasks.find((task) => task.id === taskId);
  if (!taskSpec) {
    return <LoadingState message="Task not found." />;
  }

  const taskState = getTaskState(mission.task_states[taskId], taskSpec, mission.started_at);
  const reviewScore = taskState.review_score > 0 ? formatScore(taskState.review_score) : '—';
  const duration = formatDuration(taskState.started_at ?? mission.started_at, taskState.completed_at);
  const reviewFeedback = (taskState.review_feedback ?? '').trim();
  const blockingIssues = (taskState.blocking_issues ?? []).filter((issue) => issue.trim().length > 0);
  const humanInterventionMessage = (taskState.human_intervention_message ?? '').trim();
  const errorMessage = (taskState.error_message ?? '').trim();

  return (
    <main className="site-main">
      <Breadcrumb missionId={missionId} missionName={mission.spec.name} taskTitle={taskSpec.title} className="mb-6" />

      <div className="page-head">
        <h1>{taskSpec.title}</h1>
        <StatusBadge status={taskState.status} />
      </div>

      <StatsBar
        className="mb-7"
        stats={[
          { label: 'Status', value: <StatusBadge status={taskState.status} /> },
          { label: 'Review Score', value: reviewScore },
          { label: 'Retries', value: taskState.retries },
          { label: 'Duration', value: duration },
        ]}
      />

      <section className="sec">
        <h2 className="section-title">Live Stream</h2>
        <TerminalPanel lines={lines} />
        {done ? <p className="mt-2 text-[12px] text-dim">(stream complete)</p> : null}
      </section>

      {reviewFeedback ? (
        <section className="sec">
          <h2 className="section-title">Review Panel</h2>
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <span className="text-sm font-semibold text-text">Review Feedback</span>
              <span className="inline-flex rounded border border-border bg-surface px-2 py-0.5 text-xs font-semibold text-dim">
                {reviewScore}
              </span>
            </div>
            <p className="whitespace-pre-wrap text-sm leading-6 text-dim">{reviewFeedback}</p>
          </div>
        </section>
      ) : null}

      {blockingIssues.length > 0 ? (
        <section className="sec">
          <h2 className="section-title">Blocking Issues</h2>
          <div className="rounded-lg border border-amber/20 bg-amber-bg p-4 text-sm text-amber">
            <ul className="list-disc space-y-1 pl-5 text-text">
              {blockingIssues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}

      {humanInterventionMessage ? (
        <section className="sec">
          <h2 className="section-title">Human Intervention</h2>
          <div className="rounded-lg border border-amber/20 bg-amber-bg p-4 text-sm text-amber">
            <p className="whitespace-pre-wrap leading-6 text-text">{humanInterventionMessage}</p>
          </div>
        </section>
      ) : null}

      {errorMessage ? (
        <section className="sec">
          <h2 className="section-title">Error</h2>
          <div className="rounded-lg border border-red/20 bg-red-bg p-4 text-sm text-red">
            <p className="whitespace-pre-wrap leading-6 text-text">{errorMessage}</p>
          </div>
        </section>
      ) : null}
    </main>
  );
}

export default function TaskDetailPage() {
  const params = useParams<{ mission_id?: string; task_id?: string }>();

  if (!params.mission_id || !params.task_id) {
    return <LoadingState message="Missing mission or task id." />;
  }

  return <TaskDetailContent missionId={params.mission_id} taskId={params.task_id} />;
}
