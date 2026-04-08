import type { EventLogEntry } from '../lib/types';

export interface EventLogTableProps {
  entries: EventLogEntry[];
  className?: string;
}

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime())
    ? timestamp
    : date.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
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
                  {formatTimestamp(entry.timestamp)}
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
