import type { EventLogEntry } from '../lib/types';

export interface EventLogTableProps {
  entries: EventLogEntry[];
  className?: string;
}

function formatAbsoluteTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleString();
}

function formatRelativeTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }

  const diffSeconds = Math.floor((Date.now() - date.getTime()) / 1000);
  const absSeconds = Math.abs(diffSeconds);

  if (absSeconds < 60) {
    return diffSeconds >= 0 ? `${absSeconds}s ago` : `in ${absSeconds}s`;
  }

  const absMinutes = Math.floor(absSeconds / 60);
  if (absMinutes < 60) {
    return diffSeconds >= 0 ? `${absMinutes}m ago` : `in ${absMinutes}m`;
  }

  const absHours = Math.floor(absMinutes / 60);
  if (absHours < 24) {
    return diffSeconds >= 0 ? `${absHours}h ago` : `in ${absHours}h`;
  }

  const absDays = Math.floor(absHours / 24);
  return diffSeconds >= 0 ? `${absDays}d ago` : `in ${absDays}d`;
}

function formatDetails(details: string): string {
  return details.length > 140 ? details.slice(0, 140) : details;
}

export default function EventLogTable({ entries, className = '' }: EventLogTableProps) {
  return (
    <div className={['overflow-hidden rounded-lg border border-border bg-card', className].filter(Boolean).join(' ')}>
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-surface text-left text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">
            <th className="border-b border-border px-4 py-2">Time</th>
            <th className="border-b border-border px-4 py-2">Event</th>
            <th className="border-b border-border px-4 py-2">Task</th>
            <th className="border-b border-border px-4 py-2">Details</th>
          </tr>
        </thead>
        <tbody>
          {entries.length === 0 ? (
            <tr>
              <td className="px-4 py-3 text-dim" colSpan={4}>
                No events yet.
              </td>
            </tr>
          ) : (
            entries.map((entry) => (
              <tr key={`${entry.timestamp}-${entry.event_type}-${entry.task_id ?? ''}`} className="border-b border-border last:border-b-0">
                <td className="px-4 py-2 align-middle text-[11px] whitespace-nowrap text-muted">
                  <span title={formatAbsoluteTimestamp(entry.timestamp)}>{formatRelativeTimestamp(entry.timestamp)}</span>
                </td>
                <td className="px-4 py-2 align-middle">
                  <span className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5 text-[11px] uppercase tracking-[0.05em] text-dim">
                    {entry.event_type.replace(/_/g, ' ')}
                  </span>
                </td>
                <td className="px-4 py-2 align-middle text-[12px] text-text">{entry.task_id ?? '—'}</td>
                <td className="max-w-[420px] truncate px-4 py-2 align-middle text-[12px] text-dim">
                  {formatDetails(entry.details)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
