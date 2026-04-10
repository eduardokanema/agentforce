import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useToast } from '../hooks/useToast';
import { useDaemonStatus } from '../hooks/useDaemonStatus';
import { daemonStop, daemonRestart, daemonDequeue, stopMission } from '../lib/api';
import type { DaemonJobInfo } from '../lib/types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return '—';
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m ago`;
}

function abbrev(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}

// ---------------------------------------------------------------------------
// Job type badge
// ---------------------------------------------------------------------------

function JobTypeBadge({ jobType }: { jobType: string }) {
  if (jobType === 'plan_run') {
    return (
      <span className="rounded border border-amber/30 bg-amber-bg px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber">
        Plan Run
      </span>
    );
  }
  return (
    <span className="rounded border border-cyan/30 bg-cyan-bg px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-cyan">
      Mission
    </span>
  );
}

// ---------------------------------------------------------------------------
// Daemon status panel
// ---------------------------------------------------------------------------

function DaemonStatusPanel({
  running,
  lastHeartbeat,
  onStop,
  onRestart,
  busy,
}: {
  running: boolean;
  lastHeartbeat: string | null;
  onStop: () => void;
  onRestart: () => void;
  busy: boolean;
}) {
  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <div className="flex flex-wrap items-center gap-4">
        {/* Status indicator */}
        <div className="flex items-center gap-2.5">
          <span
            className={[
              'h-3 w-3 rounded-full',
              running
                ? 'bg-green animate-[pulse-glow_2s_ease-in-out_infinite]'
                : 'bg-red',
            ].join(' ')}
          />
          <span className="text-sm font-semibold text-text">
            {running ? 'Daemon running' : 'Daemon offline'}
          </span>
        </div>

        {/* Last heartbeat */}
        <span className="text-[11px] text-muted">
          Last heartbeat: {formatRelative(lastHeartbeat)}
        </span>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Controls */}
        {running && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={onStop}
              className="rounded border border-amber/40 bg-amber-bg px-3 py-1.5 text-[12px] font-medium text-amber transition-colors hover:bg-amber/20 disabled:opacity-50"
            >
              Stop Daemon
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onRestart}
              className="rounded border border-cyan/40 bg-cyan-bg px-3 py-1.5 text-[12px] font-medium text-cyan transition-colors hover:bg-cyan/20 disabled:opacity-50"
            >
              Restart Daemon
            </button>
          </div>
        )}

        {!running && (
          <span className="text-[12px] text-muted">
            Start the daemon via CLI: <code className="font-mono text-text">agentforce daemon start</code>
          </span>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Active threads panel
// ---------------------------------------------------------------------------

function ActiveThreadsPanel({
  jobs,
  onStop,
  busy,
}: {
  jobs: DaemonJobInfo[];
  onStop: (job: DaemonJobInfo) => void;
  busy: string | null;
}) {
  return (
    <section>
      <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-dim">
        In Flight — {jobs.length} thread{jobs.length !== 1 ? 's' : ''}
      </h2>
      {jobs.length === 0 ? (
        <div className="rounded-lg border border-border bg-card px-5 py-8 text-center text-sm text-muted">
          No threads in flight
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {jobs.map((job) => (
            <ActiveJobCard
              key={job.job_id}
              job={job}
              onStop={onStop}
              isBusy={busy === job.job_id}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ActiveJobCard({
  job,
  onStop,
  isBusy,
}: {
  job: DaemonJobInfo;
  onStop: (job: DaemonJobInfo) => void;
  isBusy: boolean;
}) {
  const targetId = job.mission_id ?? job.job_id;
  const href = job.job_type === 'plan_run' ? `/plan/${targetId}` : `/mission/${targetId}`;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1.5 min-w-0">
          <JobTypeBadge jobType={job.job_type} />
          <Link
            to={href}
            className="truncate text-[13px] font-mono text-text hover:text-cyan transition-colors"
            title={targetId}
          >
            {abbrev(targetId)}
          </Link>
        </div>
        <button
          type="button"
          disabled={isBusy || job.job_type !== 'mission'}
          onClick={() => onStop(job)}
          title={job.job_type !== 'mission' ? 'Stop via Plan Mode' : 'Stop mission'}
          className="shrink-0 rounded border border-red/40 bg-red-bg px-2.5 py-1 text-[11px] font-medium text-red transition-colors hover:bg-red/20 disabled:opacity-40"
        >
          {isBusy ? '…' : 'Stop'}
        </button>
      </div>
      <div className="text-[11px] text-muted">
        Running since {formatRelative(job.enqueued_at)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Launch queue panel
// ---------------------------------------------------------------------------

function LaunchQueuePanel({
  jobs,
  onDequeue,
  busy,
}: {
  jobs: DaemonJobInfo[];
  onDequeue: (job: DaemonJobInfo) => void;
  busy: string | null;
}) {
  return (
    <section>
      <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-dim">
        Launch Queue — {jobs.length} job{jobs.length !== 1 ? 's' : ''} waiting
      </h2>
      {jobs.length === 0 ? (
        <div className="rounded-lg border border-border bg-card px-5 py-8 text-center text-sm text-muted">
          Launch queue is empty
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-card">
          {jobs.map((job, index) => {
            const targetId = job.mission_id ?? job.job_id;
            const href = job.job_type === 'plan_run' ? `/plan/${targetId}` : `/mission/${targetId}`;
            return (
              <div
                key={job.job_id}
                className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
              >
                {/* Position */}
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-surface text-[11px] text-dim">
                  {index + 1}
                </span>

                {/* Type badge */}
                <JobTypeBadge jobType={job.job_type} />

                {/* ID link */}
                <Link
                  to={href}
                  className="flex-1 truncate font-mono text-[12px] text-text hover:text-cyan transition-colors min-w-0"
                  title={targetId}
                >
                  {abbrev(targetId)}
                </Link>

                {/* Enqueued time */}
                <span className="shrink-0 text-[11px] text-muted">
                  {formatRelative(job.enqueued_at)}
                </span>

                {/* Remove button */}
                <button
                  type="button"
                  disabled={busy === job.job_id}
                  onClick={() => onDequeue(job)}
                  className="shrink-0 rounded border border-border px-2.5 py-1 text-[11px] text-dim transition-colors hover:border-red/40 hover:text-red disabled:opacity-40"
                >
                  {busy === job.job_id ? '…' : 'Remove'}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function GroundControlPage() {
  const { addToast } = useToast();
  const { status, loading, error, refetch } = useDaemonStatus();

  const [daemonBusy, setDaemonBusy] = useState(false);
  const [stopBusy, setStopBusy] = useState<string | null>(null);
  const [dequeueBusy, setDequeueBusy] = useState<string | null>(null);

  const handleStop = async () => {
    setDaemonBusy(true);
    try {
      await daemonStop();
      addToast('Daemon stopping…', 'success');
      setTimeout(refetch, 1000);
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Stop failed', 'error');
    } finally {
      setDaemonBusy(false);
    }
  };

  const handleRestart = async () => {
    if (!window.confirm('Restart the daemon? In-flight jobs will be drained and re-queued.')) return;
    setDaemonBusy(true);
    try {
      await daemonRestart();
      addToast('Daemon restarting…', 'success');
      setTimeout(refetch, 2000);
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Restart failed', 'error');
    } finally {
      setDaemonBusy(false);
    }
  };

  const handleStopJob = async (job: DaemonJobInfo) => {
    const targetId = job.mission_id ?? job.job_id;
    setStopBusy(job.job_id);
    try {
      await stopMission(targetId);
      addToast('Mission stopping…', 'success');
      await refetch();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Stop failed', 'error');
    } finally {
      setStopBusy(null);
    }
  };

  const handleDequeue = async (job: DaemonJobInfo) => {
    setDequeueBusy(job.job_id);
    try {
      await daemonDequeue(job.job_id);
      addToast('Removed from queue', 'success');
      await refetch();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Dequeue failed', 'error');
    } finally {
      setDequeueBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="page-head">
        <h1 className="text-3xl font-semibold tracking-tight">Ground Control</h1>
        <p className="mt-1 text-sm text-dim">
          Daemon supervisor — monitor active threads, manage the launch queue, and control the daemon lifecycle.
        </p>
      </header>

      {loading && (
        <div className="rounded-lg border border-border bg-card px-5 py-10 text-center text-sm text-muted animate-pulse">
          Contacting Ground Control…
        </div>
      )}

      {!loading && error && (
        <div className="rounded-lg border border-red/30 bg-red-bg px-5 py-6 text-sm text-red">
          {error.includes('503') || error.toLowerCase().includes('daemon not active')
            ? <>Daemon is not active. Restart the server with: <code className="font-mono">python3 -m agentforce.cli.cli serve --daemon</code></>
            : error}
        </div>
      )}

      {!loading && !error && status && (
        <>
          <DaemonStatusPanel
            running={status.running}
            lastHeartbeat={status.last_heartbeat}
            onStop={handleStop}
            onRestart={handleRestart}
            busy={daemonBusy}
          />

          <ActiveThreadsPanel
            jobs={status.active}
            onStop={handleStopJob}
            busy={stopBusy}
          />

          <LaunchQueuePanel
            jobs={status.queue}
            onDequeue={handleDequeue}
            busy={dequeueBusy}
          />
        </>
      )}
    </div>
  );
}
