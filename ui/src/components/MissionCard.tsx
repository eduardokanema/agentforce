import { useState } from 'react';
import { Link } from 'react-router-dom';
import ConfirmDialog from './ConfirmDialog';
import MissionProgressBar from './MissionProgressBar';
import StatusBadge from './StatusBadge';
import { useElapsedTime } from '../hooks/useElapsedTime';
import type { MissionSummary } from '../lib/types';

interface MissionCardProps {
  mission: MissionSummary;
  onStop: () => void;
  onRestart: () => void;
  onArchive: () => void;
  onDelete: () => void;
}

function accentBarClassName(status: MissionSummary['status']): string {
  if (status === 'in_progress' || status === 'active') {
    return 'bg-cyan';
  }

  if (status === 'completed' || status === 'review_approved' || status === 'complete') {
    return 'bg-green';
  }

  if (status === 'failed') {
    return 'bg-red';
  }

  return 'bg-border';
}

function isRunningStatus(status: MissionSummary['status']): boolean {
  return status === 'in_progress' || status === 'active';
}

function formatRelativeDate(startedAt: string): string {
  const startedMs = Date.parse(startedAt);
  if (Number.isNaN(startedMs)) {
    return '—';
  }

  const diffMs = startedMs - Date.now();
  const absSeconds = Math.round(Math.abs(diffMs) / 1000);
  if (absSeconds < 60) {
    return diffMs < 0 ? `${absSeconds}s ago` : `in ${absSeconds}s`;
  }

  const absMinutes = Math.round(absSeconds / 60);
  if (absMinutes < 60) {
    return diffMs < 0 ? `${absMinutes}m ago` : `in ${absMinutes}m`;
  }

  const absHours = Math.round(absMinutes / 60);
  return diffMs < 0 ? `${absHours}h ago` : `in ${absHours}h`;
}

function truncateTitle(title: string | null | undefined, maxLength: number): string {
  const text = title?.trim() ?? '';
  if (!text) {
    return '—';
  }

  if (text.length <= maxLength) {
    return text;
  }

  return `${text.slice(0, maxLength - 1)}…`;
}

function getModelChips(mission: MissionSummary): string[] {
  const models = mission.models?.filter(Boolean) ?? [];
  if (models.length > 0) {
    return models;
  }

  const workerModel = mission.execution?.defaults.worker?.model?.trim();
  const reviewerModel = mission.execution?.defaults.reviewer?.model?.trim();
  if (workerModel || reviewerModel) {
    return [
      workerModel ? `worker:${workerModel}` : '',
      reviewerModel && reviewerModel !== workerModel ? `reviewer:${reviewerModel}` : '',
    ].filter(Boolean);
  }

  return mission.worker_model ? [mission.worker_model] : [];
}

export default function MissionCard({ mission, onStop, onRestart, onArchive, onDelete }: MissionCardProps) {
  const elapsed = useElapsedTime(mission.started_at);
  const accentClassName = accentBarClassName(mission.status);
  const running = isRunningStatus(mission.status);
  const workspace = mission.workspace?.trim() || '—';
  const modelChips = getModelChips(mission);
  const retries = mission.retries ?? 0;
  const activeTaskTitle = truncateTitle(mission.active_task_title, 40);
  const relativeCreated = formatRelativeDate(mission.started_at);
  const [pendingAction, setPendingAction] = useState<null | {
    title: string;
    message: string;
    confirmLabel: string;
    variant: 'danger' | 'warning';
    action: () => void;
  }>(null);

  const confirmPendingAction = (): void => {
    const action = pendingAction?.action;
    setPendingAction(null);

    if (!action) {
      return;
    }

    void Promise.resolve(action()).catch(() => undefined);
  };

  return (
    <>
      <article className="group relative overflow-hidden rounded-lg border border-border bg-card transition-shadow duration-200 hover:shadow-[0_0_0_1px_theme(colors.border-lit),0_4px_24px_theme(colors.glow-cyan)]">
        <div className={`absolute bottom-0 left-0 top-0 w-0.5 ${accentClassName}`} />

        <div className="flex flex-col gap-2 px-4 py-3 pl-5">
          <div className="flex flex-wrap items-center gap-2">
            <Link className="text-[14px] font-semibold text-text transition-colors hover:text-cyan hover:no-underline" to={`/mission/${mission.mission_id}`}>
              {mission.name}
            </Link>
            <StatusBadge status={mission.status} />
            <span className="ml-auto font-mono text-[11px] text-dim tabular-nums">{elapsed}</span>
          </div>

          <div className="relative overflow-hidden">
            <MissionProgressBar pct={mission.pct} />
            {running ? (
              <div className="pointer-events-none absolute inset-0 animate-[scan-line_2s_linear_infinite] bg-gradient-to-r from-transparent via-white/5 to-transparent" />
            ) : null}
          </div>

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-dim">
            <span>{mission.done_tasks}/{mission.total_tasks} tasks</span>
            <span>{retries} retries</span>
            <span>${(mission.cost_usd ?? 0).toFixed(4)}</span>
            <span className="truncate">{activeTaskTitle}</span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="max-w-[200px] truncate rounded-full border border-border px-2 py-0.5 font-mono text-[10px] text-muted">
              {workspace}
            </span>
            {modelChips.map((model) => (
              <span key={model} className="inline-flex items-center rounded-full border border-border px-1.5 py-0.5 text-[10px] text-dim">
                {model}
              </span>
            ))}
            <span className="font-mono text-[10px] text-dim">{relativeCreated}</span>
          </div>

          <div className="flex items-center gap-2 pt-0.5 opacity-0 transition-opacity group-hover:opacity-100">
            <button
              type="button"
              className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-[10px] text-red transition-colors hover:bg-red/10"
              onClick={() => {
                setPendingAction({
                  title: `Stop mission "${mission.name}"?`,
                  message: 'This will halt the mission immediately.',
                  confirmLabel: 'Stop Mission',
                  variant: 'danger',
                  action: onStop,
                });
              }}
            >
              ⏹ Stop
            </button>
            <button
              type="button"
              className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-[10px] text-amber transition-colors hover:bg-amber/10"
              onClick={() => {
                setPendingAction({
                  title: `Restart mission "${mission.name}"?`,
                  message: 'This will queue a fresh run from the current mission state.',
                  confirmLabel: 'Restart Mission',
                  variant: 'warning',
                  action: onRestart,
                });
              }}
            >
              ↺ Restart
            </button>
            <button
              type="button"
              className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-[10px] text-dim transition-colors hover:bg-surface"
              onClick={onArchive}
            >
              ⊘ Archive
            </button>
            <button
              type="button"
              className="ml-auto inline-flex items-center rounded-full border border-border px-2 py-0.5 text-[10px] text-red/60 transition-colors hover:bg-red/10 hover:text-red"
              onClick={() => {
                setPendingAction({
                  title: `Delete mission "${mission.name}"?`,
                  message: 'This will permanently hide the mission. It cannot be undone.',
                  confirmLabel: 'Delete',
                  variant: 'danger',
                  action: onDelete,
                });
              }}
            >
              ✕ Delete
            </button>
          </div>
        </div>
      </article>

      <ConfirmDialog
        confirmLabel={pendingAction?.confirmLabel}
        message={pendingAction?.message ?? ''}
        open={pendingAction !== null}
        title={pendingAction?.title ?? ''}
        variant={pendingAction?.variant}
        onCancel={() => {
          setPendingAction(null);
        }}
        onConfirm={confirmPendingAction}
      />
    </>
  );
}
