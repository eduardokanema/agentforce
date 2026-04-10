import type { MissionSummaryStatus, TaskStatus } from '../lib/types';

export type StatusBadgeStatus = TaskStatus | MissionSummaryStatus;

export const STATUS_BADGE_CLASSES = {
  pending: 'text-dim bg-surface border-border/80',
  spec_writing: 'text-blue bg-blue-bg border-blue/20',
  tests_written: 'text-blue bg-blue-bg border-blue/20',
  in_progress: 'text-blue bg-blue-bg border-blue/20',
  completed: 'text-teal bg-teal/10 border-teal/20',
  reviewing: 'text-blue bg-blue-bg border-blue/20',
  review_approved: 'text-green bg-green-bg border-green/20',
  review_rejected: 'text-amber bg-amber-bg border-amber/20',
  needs_human: 'text-amber bg-amber-bg border-amber/20',
  retry: 'text-dim bg-surface border-border/80',
  failed: 'text-red bg-red-bg border-red/20',
  blocked: 'text-amber bg-amber-bg border-amber/20',
  active: 'text-blue bg-blue-bg border-blue/20',
  complete: 'text-green bg-green-bg border-green/20',
  draft: 'text-amber bg-amber-bg border-amber/20',
} as const satisfies Record<StatusBadgeStatus, string>;

export const STATUS_BADGE_LABELS: Record<StatusBadgeStatus, string> = {
  pending: 'pending',
  spec_writing: 'spec writing',
  tests_written: 'tests written',
  in_progress: 'in progress',
  completed: 'completed',
  reviewing: 'reviewing',
  review_approved: 'review approved',
  review_rejected: 'review rejected',
  needs_human: 'needs human',
  retry: 'retry',
  failed: 'failed',
  blocked: 'blocked',
  active: 'active',
  complete: 'complete',
  draft: 'draft',
};

export interface StatusBadgeProps {
  status: StatusBadgeStatus;
  className?: string;
}

export function getStatusBadgeClassName(status: StatusBadgeStatus): string {
  return STATUS_BADGE_CLASSES[status];
}

function formatStatusLabel(status: StatusBadgeStatus): string {
  return STATUS_BADGE_LABELS[status] ?? status.replace(/_/g, ' ');
}

export default function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const badgeClasses = [
    'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.05em] whitespace-nowrap before:content-[\'\'] before:h-1.5 before:w-1.5 before:shrink-0 before:rounded-full before:bg-current',
    getStatusBadgeClassName(status),
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return <span className={badgeClasses}>{formatStatusLabel(status)}</span>;
}
