import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import ConfirmDialog from '../components/ConfirmDialog';
import Breadcrumb from '../components/Breadcrumb';
import RetryHistory from '../components/RetryHistory';
import ReviewPanel from '../components/ReviewPanel';
import StatusBadge from '../components/StatusBadge';
import StatsBar from '../components/StatsBar';
import StructuredStream from '../components/StructuredStream';
import TokenMeter from '../components/TokenMeter';
import { changeTaskModel, getModels, injectPrompt, markTaskFailed, resolveHumanBlock, retryTask, stopTask } from '../lib/api';
import { useMission } from '../hooks/useMission';
import { useTaskStream } from '../hooks/useTaskStream';
import { useToast } from '../hooks/useToast';
import type { Model, TaskSpec, TaskState, TaskStatus } from '../lib/types';

const THINKING_LEVELS = ['low', 'medium', 'high', 'xhigh'] as const;

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
  const { events, done } = useTaskStream(missionId, taskId);
  const [injectMsg, setInjectMsg] = useState('');
  const [changeModelInput, setChangeModelInput] = useState('');
  const [changeReviewerModelInput, setChangeReviewerModelInput] = useState('');
  const [changeWorkerThinkingInput, setChangeWorkerThinkingInput] = useState('medium');
  const [changeReviewerThinkingInput, setChangeReviewerThinkingInput] = useState('medium');
  const [showChangeModel, setShowChangeModel] = useState(false);
  const [models, setModels] = useState<Model[]>([]);
  const [destructiveChoiceId, setDestructiveChoiceId] = useState('approve_once');
  const [destructiveMessage, setDestructiveMessage] = useState('');

  useEffect(() => {
    getModels().then(setModels).catch(() => { /* best-effort */ });
  }, []);
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
  const destructiveContext = taskState?.human_intervention_context ?? {};
  const destructiveOptions = taskState?.human_intervention_options ?? [];
  const destructiveActionKey = typeof destructiveContext.action_key === 'string' ? destructiveContext.action_key : '';
  const isDestructiveIntervention = taskState?.status === 'needs_human'
    && taskState?.human_intervention_kind === 'destructive_action';
  const errorMessage = (taskState?.error_message ?? '').trim();
  const injectEnabled = taskState?.status === 'in_progress';
  const currentModel = taskSpec?.execution?.worker?.model
    ?? mission?.execution?.tasks?.[taskId]?.worker?.model
    ?? mission?.execution?.defaults.worker?.model
    ?? mission?.worker_model
    ?? null;
  const currentReviewerModel = taskSpec?.execution?.reviewer?.model
    ?? mission?.execution?.tasks?.[taskId]?.reviewer?.model
    ?? mission?.execution?.defaults.reviewer?.model
    ?? null;
  const currentWorkerThinking = taskSpec?.execution?.worker?.thinking
    ?? mission?.execution?.tasks?.[taskId]?.worker?.thinking
    ?? mission?.execution?.defaults.worker?.thinking
    ?? 'medium';
  const currentReviewerThinking = taskSpec?.execution?.reviewer?.thinking
    ?? mission?.execution?.tasks?.[taskId]?.reviewer?.thinking
    ?? mission?.execution?.defaults.reviewer?.thinking
    ?? 'medium';
  const changeModelDirty = (
    changeModelInput !== (currentModel ?? '')
    || changeReviewerModelInput !== (currentReviewerModel ?? '')
    || changeWorkerThinkingInput !== currentWorkerThinking
    || changeReviewerThinkingInput !== currentReviewerThinking
  );
  const hasReviewPanel = Boolean(
    reviewFeedback.trim()
      || reviewScore > 0
      || (criteriaResults && Object.keys(criteriaResults).length > 0)
      || blockingIssues.length > 0
      || (suggestions && suggestions.length > 0),
  );
  const streamDone = done || ['completed', 'review_approved', 'review_rejected', 'failed', 'needs_human', 'blocked'].includes(taskState?.status ?? 'pending');

  useEffect(() => {
    if (!isDestructiveIntervention) {
      return;
    }
    setDestructiveChoiceId(destructiveOptions[0]?.id ?? 'approve_once');
    setDestructiveMessage('');
  }, [destructiveActionKey, destructiveOptions, isDestructiveIntervention]);

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

  const handleChangeModel = async (): Promise<void> => {
    const workerModel = changeModelInput.trim();
    const reviewerModel = changeReviewerModelInput.trim();
    if (!changeModelDirty) {
      return;
    }

    const workerAgent = models.find((model) => model.id === workerModel)?.provider_id ?? null;
    const reviewerAgent = models.find((model) => model.id === reviewerModel)?.provider_id ?? null;

    try {
      const result = await changeTaskModel(missionId, taskId, {
        worker_agent: workerAgent,
        worker_model: workerModel || null,
        worker_thinking: changeWorkerThinkingInput,
        reviewer_agent: reviewerAgent,
        reviewer_model: reviewerModel || null,
        reviewer_thinking: changeReviewerThinkingInput,
      });
      addToast(result.retried ? 'Models changed — task re-queued' : 'Models updated', 'success');
      setChangeModelInput('');
      setChangeReviewerModelInput('');
      setChangeWorkerThinkingInput('medium');
      setChangeReviewerThinkingInput('medium');
      setShowChangeModel(false);
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Failed to change model', 'error');
    }
  };

  const handleResolveDestructiveAction = async (): Promise<void> => {
    const choiceId = destructiveChoiceId || destructiveOptions[0]?.id || 'approve_once';
    const message = destructiveMessage.trim();
    if (choiceId === 'revise' && message.length === 0) {
      addToast('Add instructions before revising the action', 'error');
      return;
    }

    try {
      await resolveHumanBlock(missionId, taskId, {
        choice_id: choiceId,
        message,
      });
      addToast('Destructive action decision saved', 'success');
      setDestructiveMessage('');
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Failed to resolve destructive action', 'error');
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
        <button
          type="button"
          className="rounded border border-cyan/30 px-3 py-1 text-[12px] text-cyan transition-colors hover:bg-cyan/10"
          onClick={() => {
            setShowChangeModel((v) => !v);
            setChangeModelInput(currentModel ?? '');
            setChangeReviewerModelInput(currentReviewerModel ?? '');
            setChangeWorkerThinkingInput(currentWorkerThinking);
            setChangeReviewerThinkingInput(currentReviewerThinking);
          }}
        >
          Change Model
        </button>
      </div>

      {showChangeModel ? (
        <div className="mb-4 grid gap-2 md:grid-cols-[1fr_1fr_auto_auto]">
          <div className="grid gap-2">
            <select
              className="flex-1 rounded border border-border bg-surface px-3 py-1 font-mono text-[12px] text-text outline-none transition-colors focus:border-cyan disabled:opacity-50"
              value={changeModelInput}
              disabled={models.length === 0}
              onChange={(event) => { setChangeModelInput(event.target.value); }}
              aria-label="Worker model"
            >
              <option value="">{models.length === 0 ? 'Loading models…' : 'Worker model…'}</option>
              {Object.entries(
                models.reduce<Record<string, Model[]>>((acc, m) => {
                  (acc[m.provider] ??= []).push(m);
                  return acc;
                }, {}),
              ).map(([provider, providerModels]) => (
                <optgroup key={provider} label={provider}>
                  {providerModels.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
            <select
              className="flex-1 rounded border border-border bg-surface px-3 py-1 font-mono text-[12px] text-text outline-none transition-colors focus:border-cyan"
              value={changeWorkerThinkingInput}
              onChange={(event) => { setChangeWorkerThinkingInput(event.target.value); }}
              aria-label="Worker thinking"
            >
              {THINKING_LEVELS.map((level) => (
                <option key={`worker-thinking-${level}`} value={level}>
                  Thinking · {level}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-2">
            <select
              className="flex-1 rounded border border-border bg-surface px-3 py-1 font-mono text-[12px] text-text outline-none transition-colors focus:border-cyan disabled:opacity-50"
              value={changeReviewerModelInput}
              disabled={models.length === 0}
              onChange={(event) => { setChangeReviewerModelInput(event.target.value); }}
              aria-label="Reviewer model"
            >
              <option value="">{models.length === 0 ? 'Loading models…' : 'Reviewer model…'}</option>
              {Object.entries(
                models.reduce<Record<string, Model[]>>((acc, m) => {
                  (acc[m.provider] ??= []).push(m);
                  return acc;
                }, {}),
              ).map(([provider, providerModels]) => (
                <optgroup key={provider} label={provider}>
                  {providerModels.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
            <select
              className="flex-1 rounded border border-border bg-surface px-3 py-1 font-mono text-[12px] text-text outline-none transition-colors focus:border-cyan"
              value={changeReviewerThinkingInput}
              onChange={(event) => { setChangeReviewerThinkingInput(event.target.value); }}
              aria-label="Reviewer thinking"
            >
              {THINKING_LEVELS.map((level) => (
                <option key={`reviewer-thinking-${level}`} value={level}>
                  Thinking · {level}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="rounded border border-cyan/30 px-3 py-1 text-[12px] text-cyan transition-colors hover:bg-cyan/10 disabled:cursor-not-allowed disabled:opacity-40"
            disabled={!changeModelDirty}
            onClick={() => { void handleChangeModel(); }}
          >
            {taskState.status === 'pending' ? 'Save' : 'Change & Retry'}
          </button>
          <button
            type="button"
            className="rounded border border-border px-3 py-1 text-[12px] text-dim transition-colors hover:bg-surface"
            onClick={() => {
              setShowChangeModel(false);
              setChangeModelInput('');
              setChangeReviewerModelInput('');
              setChangeWorkerThinkingInput('medium');
              setChangeReviewerThinkingInput('medium');
            }}
          >
            Cancel
          </button>
        </div>
      ) : null}

      <StatsBar
        className="mb-7"
        stats={[
          { label: 'Status', value: <StatusBadge status={taskState.status} /> },
          { label: 'Model', value: <span className="block truncate font-mono text-sm font-normal">{currentModel ?? <span className="text-dim/60">default</span>}</span> },
          { label: 'Reviewer', value: <span className="block truncate font-mono text-sm font-normal">{currentReviewerModel ?? <span className="text-dim/60">default</span>}</span> },
          { label: 'Review Score', value: reviewScore > 0 ? formatScore(reviewScore) : '—' },
          { label: 'Retries', value: retryCount },
          { label: 'Duration', value: duration },
        ]}
      />

      <section className="sec">
        <h2 className="section-title">Live Stream</h2>
        <StructuredStream events={events} done={streamDone} />
        {streamDone ? <p className="mt-2 text-[12px] text-dim">(stream complete)</p> : null}
      </section>

      {retryCount > 0 ? (
        <section className="sec">
          <h2 className="section-title">Previous Reviews</h2>
          <RetryHistory missionId={missionId} taskId={taskId} currentRetryCount={retryCount} />
        </section>
      ) : null}

      {isDestructiveIntervention ? (
        <section className="sec">
          <h2 className="section-title">Destructive Action Requires Approval</h2>
          <div className="rounded-lg border border-red/30 bg-red-bg p-4 text-sm">
            <div className="space-y-2">
              <p className="font-semibold text-red">{typeof destructiveContext.summary === 'string' ? destructiveContext.summary : 'Potential destructive action requested'}</p>
              <p className="whitespace-pre-wrap leading-6 text-text">{typeof destructiveContext.risk === 'string' ? destructiveContext.risk : humanInterventionMessage}</p>
              {typeof destructiveContext.proposed_action === 'string' ? (
                <p className="rounded border border-red/20 bg-surface px-3 py-2 font-mono text-[12px] text-text">{destructiveContext.proposed_action}</p>
              ) : null}
              {Array.isArray(destructiveContext.targets) && destructiveContext.targets.length > 0 ? (
                <p className="text-[12px] text-dim">Targets: {destructiveContext.targets.join(', ')}</p>
              ) : null}
            </div>

            <div className="mt-4 grid gap-2 md:grid-cols-2">
              {destructiveOptions.map((option) => (
                <label
                  key={option.id}
                  className={`rounded border px-3 py-2 transition-colors ${
                    destructiveChoiceId === option.id
                      ? 'border-red/50 bg-red/10'
                      : 'border-border bg-surface hover:border-red/30'
                  }`}
                >
                  <input
                    type="radio"
                    className="mr-2"
                    name="destructive-action-choice"
                    value={option.id}
                    checked={destructiveChoiceId === option.id}
                    onChange={() => { setDestructiveChoiceId(option.id); }}
                  />
                  <span className="font-semibold text-text">{option.label}</span>
                  {option.description ? <span className="mt-1 block text-[12px] leading-5 text-dim">{option.description}</span> : null}
                </label>
              ))}
            </div>

            <textarea
              rows={3}
              className="mt-3 w-full rounded border border-border bg-surface px-3 py-2 font-mono text-[12px] text-text outline-none transition-colors focus:border-red"
              placeholder={destructiveChoiceId === 'revise' ? 'Required alternate instructions...' : 'Optional operator note...'}
              value={destructiveMessage}
              onChange={(event) => { setDestructiveMessage(event.target.value); }}
            />
            <button
              type="button"
              className="mt-3 rounded border border-red/30 bg-red-bg px-3 py-1 text-[12px] font-semibold text-red transition-colors hover:bg-red/10 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={destructiveChoiceId === 'revise' && destructiveMessage.trim().length === 0}
              onClick={() => { void handleResolveDestructiveAction(); }}
            >
              Submit Decision
            </button>
          </div>
        </section>
      ) : humanInterventionMessage ? (
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
          <h2 className="section-title">Final Review</h2>
          <ReviewPanel
            feedback={reviewFeedback}
            score={reviewScore}
            criteriaResults={criteriaResults}
            blockingIssues={blockingIssues}
            suggestions={suggestions}
          />
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
