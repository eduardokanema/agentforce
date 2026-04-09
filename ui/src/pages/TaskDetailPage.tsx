import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import ConfirmDialog from '../components/ConfirmDialog';
import Breadcrumb from '../components/Breadcrumb';
import RetryHistory from '../components/RetryHistory';
import ReviewPanel from '../components/ReviewPanel';
import StatusBadge from '../components/StatusBadge';
import StatsBar from '../components/StatsBar';
import TokenMeter from '../components/TokenMeter';
import Terminal from '../components/Terminal';
import { injectPrompt, markTaskFailed, resolveHumanBlock, retryTask, stopTask } from '../lib/api';
import { useMission } from '../hooks/useMission';
import { useTaskStream } from '../hooks/useTaskStream';
import { useToast } from '../hooks/useToast';
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

type ParsedReview = {
  feedback: string;
  score?: number;
  criteriaResults?: Record<string, string>;
  blockingIssues?: string[];
  suggestions?: string[];
};

function getTaskState(taskState: TaskState | undefined, taskSpec: TaskSpec, missionStartedAt: string): TaskState {
  return (
    taskState ?? {
      task_id: taskSpec.id,
      status: 'pending' as TaskStatus,
      retries: 0,
      retry_count: 0,
      review_score: 0,
      human_intervention_needed: false,
      last_updated: missionStartedAt,
    }
  );
}

function parseReviewFeedback(reviewFeedback: string): ParsedReview | null {
  const text = reviewFeedback.trim();
  if (!text) {
    return null;
  }

  try {
    const parsed = JSON.parse(text) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { feedback: text };
    }

    const review = parsed as Record<string, unknown>;
    const feedback = typeof review.feedback === 'string'
      ? review.feedback
      : typeof review.review === 'string'
        ? review.review
        : typeof review.message === 'string'
          ? review.message
          : text;
    const scoreValue = review.score ?? review.review_score;
    const score = typeof scoreValue === 'number'
      ? scoreValue
      : typeof scoreValue === 'string' && scoreValue.trim() !== '' && Number.isFinite(Number(scoreValue))
        ? Number(scoreValue)
        : undefined;
    const criteriaResultsValue = review.criteriaResults ?? review.criteria_results;
    const criteriaResults = criteriaResultsValue && typeof criteriaResultsValue === 'object' && !Array.isArray(criteriaResultsValue)
      ? (Object.fromEntries(
          Object.entries(criteriaResultsValue as Record<string, unknown>).filter(
            ([, value]) => typeof value === 'string',
          ),
        ) as Record<string, string>)
      : undefined;
    const blockingIssuesValue = review.blockingIssues ?? review.blocking_issues;
    const blockingIssues = Array.isArray(blockingIssuesValue)
      ? blockingIssuesValue.filter((value): value is string => typeof value === 'string')
      : undefined;
    const suggestionsValue = review.suggestions;
    const suggestions = Array.isArray(suggestionsValue)
      ? suggestionsValue.filter((value): value is string => typeof value === 'string')
      : undefined;

    return {
      feedback,
      score,
      criteriaResults,
      blockingIssues,
      suggestions,
    };
  } catch {
    return { feedback: text };
  }
}

function getRetryCount(taskState: TaskState): number {
  return taskState.retry_count ?? taskState.retries;
}

function canStopTask(status: TaskStatus): boolean {
  return status === 'in_progress';
}

function canRetryTask(status: TaskStatus): boolean {
  return ['blocked', 'failed', 'review_rejected', 'needs_human', 'retry'].includes(status);
}

function canMarkFailedTask(status: TaskStatus): boolean {
  return status === 'needs_human';
}

function canResolveBlock(status: TaskStatus): boolean {
  return status === 'needs_human';
}

function LoadingState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="animate-pulse space-y-3">
        <div className="h-4 w-44 rounded bg-surface" />
        <div className="h-3 w-60 rounded bg-surface" />
        <div className="h-3 w-32 rounded bg-surface" />
      </div>
      <p className="mt-3 text-dim">{message}</p>
    </div>
  );
}

function TaskDetailContent({ missionId, taskId }: { missionId: string; taskId: string }) {
  const { mission, loading, error } = useMission(missionId);
  const { addToast } = useToast();
  const { lines, done } = useTaskStream(missionId, taskId);
  const [injectMsg, setInjectMsg] = useState('');
  const [pendingAction, setPendingAction] = useState<null | {
    title: string;
    message: string;
    confirmLabel: string;
    variant: 'danger' | 'warning';
    action: () => Promise<void>;
  }>(null);
  const taskSpec = mission?.spec.tasks.find((task) => task.id === taskId);
  const taskState = mission && taskSpec ? getTaskState(mission.task_states[taskId], taskSpec, mission.started_at) : null;
  const reviewPayload = useMemo(
    () => parseReviewFeedback(taskState?.review_feedback ?? ''),
    [taskState?.review_feedback],
  );
  const reviewFeedback = reviewPayload?.feedback ?? (taskState?.review_feedback ?? '').trim();
  const reviewScore = reviewPayload?.score ?? taskState?.review_score ?? 0;
  const criteriaResults = reviewPayload?.criteriaResults;
  const blockingIssues = reviewPayload?.blockingIssues ?? (taskState?.blocking_issues ?? []).filter((issue) => issue.trim().length > 0);
  const suggestions = reviewPayload?.suggestions;
  const retryCount = taskState ? getRetryCount(taskState) : 0;
  const duration = formatDuration(taskState?.started_at ?? mission?.started_at, taskState?.completed_at);
  const humanInterventionMessage = (taskState?.human_intervention_message ?? '').trim();
  const errorMessage = (taskState?.error_message ?? '').trim();
  const injectEnabled = taskState?.status === 'in_progress';
  const hasReviewPanel = Boolean(
    reviewFeedback.trim()
      || reviewScore > 0
      || (criteriaResults && Object.keys(criteriaResults).length > 0)
      || blockingIssues.length > 0
      || (suggestions && suggestions.length > 0),
  );

  if (loading && !mission) {
    return <LoadingState message="Loading task..." />;
  }

  if (error && !mission) {
    return <LoadingState message={error} />;
  }

  if (!mission) {
    return <LoadingState message="Mission not found." />;
  }

  if (!taskSpec) {
    return <LoadingState message="Task not found." />;
  }

  if (!taskState) {
    return <LoadingState message="Task not found." />;
  }

  const handleInject = async (): Promise<void> => {
    const message = injectMsg.trim();
    if (!message) {
      return;
    }

    try {
      await injectPrompt(missionId, taskId, message);
      addToast('Instruction delivered', 'success');
      setInjectMsg('');
    } catch (error) {
      addToast(
        error instanceof Error && error.message.includes('409')
          ? 'Agent not ready'
          : error instanceof Error
            ? error.message
            : 'Failed to deliver instruction',
        error instanceof Error && error.message.includes('409') ? 'info' : 'error',
      );
    }
  };

  const confirmPendingAction = async (): Promise<void> => {
    const action = pendingAction?.action;
    setPendingAction(null);

    if (!action) {
      return;
    }

    try {
      await action();
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Action failed', 'error');
    }
  };

  return (
    <div>
      <Breadcrumb missionId={missionId} missionName={mission.spec.name} taskTitle={taskSpec.title} className="mb-6" />

      <div className="page-head">
        <h1>{taskSpec.title}</h1>
        <StatusBadge status={taskState.status} />
      </div>

      <div className="mb-4">
        <TokenMeter
          tokensIn={taskState.tokens_in ?? 0}
          tokensOut={taskState.tokens_out ?? 0}
          costUsd={taskState.cost_usd ?? 0}
          label="task tokens"
        />
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded border border-red/30 px-3 py-1 text-[12px] text-red transition-colors hover:bg-red/10 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!canStopTask(taskState.status)}
          onClick={() => {
            setPendingAction({
              title: `Stop task "${taskSpec.title}"?`,
              message: 'This will stop the task immediately.',
              confirmLabel: 'Stop Task',
              variant: 'danger',
              action: async () => {
                await stopTask(missionId, taskId);
                addToast('Task stopped', 'success');
              },
            });
          }}
        >
          Stop
        </button>
        <button
          type="button"
          className="rounded border border-amber/30 px-3 py-1 text-[12px] text-amber transition-colors hover:bg-amber/10 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!canRetryTask(taskState.status)}
          onClick={() => {
            setPendingAction({
              title: `Retry task "${taskSpec.title}"?`,
              message: 'This will create a fresh retry attempt for the task.',
              confirmLabel: 'Retry Task',
              variant: 'warning',
              action: async () => {
                await retryTask(missionId, taskId);
                addToast('Task retry queued', 'success');
              },
            });
          }}
        >
          Retry
        </button>
        <button
          type="button"
          className="rounded border border-red/30 px-3 py-1 text-[12px] text-red/70 transition-colors hover:bg-red/10 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!canMarkFailedTask(taskState.status)}
          onClick={() => {
            setPendingAction({
              title: `Mark task "${taskSpec.title}" as failed?`,
              message: 'This will resolve the task as failed.',
              confirmLabel: 'Mark Failed',
              variant: 'danger',
              action: async () => {
                await markTaskFailed(missionId, taskId);
                addToast('Task marked as failed', 'success');
              },
            });
          }}
        >
          Mark Failed
        </button>
        <button
          type="button"
          className="rounded border border-green/30 px-3 py-1 text-[12px] text-green transition-colors hover:bg-green/10 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!canResolveBlock(taskState.status)}
          onClick={() => {
            setPendingAction({
              title: `Resolve human block for task "${taskSpec.title}"?`,
              message: 'This will mark the human block as resolved and continue the workflow.',
              confirmLabel: 'Resolve Block',
              variant: 'warning',
              action: async () => {
                await resolveHumanBlock(missionId, taskId, 'Human guidance applied.');
                addToast('Human block resolved', 'success');
              },
            });
          }}
        >
          Resolve Block
        </button>
      </div>

      <StatsBar
        className="mb-7"
        stats={[
          { label: 'Status', value: <StatusBadge status={taskState.status} /> },
          { label: 'Review Score', value: reviewScore > 0 ? formatScore(reviewScore) : '—' },
          { label: 'Retries', value: retryCount },
          { label: 'Duration', value: duration },
        ]}
      />

      <section className="sec">
        <h2 className="section-title">Live Stream</h2>
        <Terminal lines={lines} done={done} />
        {done ? <p className="mt-2 text-[12px] text-dim">(stream complete)</p> : null}
      </section>

      {injectEnabled ? (
        <section className="sec">
          <details className="sec" open>
            <summary className="section-title cursor-pointer">Send Instruction to Agent</summary>
            <div className="mt-3 rounded-lg border border-border bg-card p-4">
              <textarea
                rows={3}
                className="w-full rounded border border-border bg-surface px-3 py-2 font-mono text-[12px] text-text outline-none transition-colors focus:border-cyan"
                value={injectMsg}
                onChange={(event) => {
                  setInjectMsg(event.target.value);
                }}
              />
              <button
                type="button"
                className="mt-3 rounded border border-cyan/30 bg-cyan-bg px-3 py-1 text-[12px] font-semibold text-cyan transition-colors hover:bg-cyan/10 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={injectMsg.trim().length === 0}
                onClick={() => {
                  void handleInject();
                }}
              >
                Send Instruction
              </button>
            </div>
          </details>
        </section>
      ) : null}

      {hasReviewPanel ? (
        <section className="sec">
          <h2 className="section-title">Review Panel</h2>
          <ReviewPanel
            feedback={reviewFeedback}
            score={reviewScore}
            criteriaResults={criteriaResults}
            blockingIssues={blockingIssues}
            suggestions={suggestions}
          />
        </section>
      ) : null}

      {retryCount > 0 ? (
        <section className="sec">
          <h2 className="section-title">Retry History</h2>
          <RetryHistory missionId={missionId} taskId={taskId} currentRetryCount={retryCount} />
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

      <ConfirmDialog
        confirmLabel={pendingAction?.confirmLabel}
        message={pendingAction?.message ?? ''}
        open={pendingAction !== null}
        title={pendingAction?.title ?? ''}
        variant={pendingAction?.variant}
        onCancel={() => {
          setPendingAction(null);
        }}
        onConfirm={() => {
          void confirmPendingAction();
        }}
      />
    </div>
  );
}

export default function TaskDetailPage() {
  const params = useParams<{ mission_id?: string; task_id?: string }>();

  if (!params.mission_id || !params.task_id) {
    return <LoadingState message="Missing mission or task id." />;
  }

  return <TaskDetailContent missionId={params.mission_id} taskId={params.task_id} />;
}
