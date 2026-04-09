import { useEffect, useState } from 'react';
import Terminal from './Terminal';
import { getTaskAttempts } from '../lib/api';
import type { TaskAttempt } from '../lib/types';

export interface RetryHistoryProps {
  missionId: string;
  taskId: string;
  currentRetryCount: number;
}

function getScoreClasses(score: number): string {
  if (score <= 4) {
    return 'bg-red/10 text-red border-red/30';
  }

  if (score <= 7) {
    return 'bg-amber/10 text-amber border-amber/30';
  }

  return 'bg-green/10 text-green border-green/30';
}

function summarizeReview(review: string): string {
  const trimmed = review.trim();
  if (trimmed.length <= 150) {
    return trimmed;
  }

  return `${trimmed.slice(0, 150).trimEnd()}…`;
}

export default function RetryHistory({ missionId, taskId, currentRetryCount }: RetryHistoryProps) {
  const [attempts, setAttempts] = useState<TaskAttempt[] | null>(null);
  const [selectedAttempt, setSelectedAttempt] = useState<number>(0);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let active = true;

    setAttempts(null);
    setLoadFailed(false);

    void getTaskAttempts(missionId, taskId)
      .then((response) => {
        if (!active) {
          return;
        }

        const nextAttempts = response.length > 0 ? response : [];
        setAttempts(nextAttempts);
        setSelectedAttempt(Math.max(0, nextAttempts.length - 1));
      })
      .catch(() => {
        if (active) {
          setLoadFailed(true);
        }
      });

    return () => {
      active = false;
    };
  }, [missionId, taskId, currentRetryCount]);

  if (currentRetryCount <= 0 || loadFailed) {
    return <p className="rounded-lg border border-border bg-card px-4 py-3 text-dim">First attempt — no history</p>;
  }

  if (attempts === null) {
    return (
      <div className="rounded-lg border border-border bg-card px-4 py-3">
        <div className="animate-pulse space-y-3">
          <div className="h-4 w-44 rounded bg-surface" />
          <div className="h-3 w-full rounded bg-surface" />
          <div className="h-3 w-3/4 rounded bg-surface" />
        </div>
        <p className="mt-3 text-dim">Loading retry history...</p>
      </div>
    );
  }

  if (attempts.length <= 1) {
    return <p className="rounded-lg border border-border bg-card px-4 py-3 text-dim">First attempt — no history</p>;
  }

  const currentAttempt = attempts[selectedAttempt] ?? attempts[attempts.length - 1];
  const currentReview = currentAttempt.review?.trim() ?? '';

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex flex-wrap gap-2">
        {attempts.map((attempt, index) => {
          const selected = index === selectedAttempt;

          return (
            <button
              key={attempt.attempt_number ?? index + 1}
              type="button"
              className={[
                'rounded-full border px-3 py-1 text-[11px] font-semibold transition-colors',
                selected ? 'bg-cyan-bg text-cyan border-cyan' : 'bg-surface text-dim border-border',
              ]
                .filter(Boolean)
                .join(' ')}
              onClick={() => setSelectedAttempt(index)}
            >
              {`Attempt ${attempt.attempt_number ?? index + 1}`}
            </button>
          );
        })}
      </div>

      <Terminal lines={(currentAttempt.output ?? '').split('\n')} done={true} />

      {currentReview ? (
        <div className="mt-3 rounded border border-border bg-surface p-3">
          <div className="mb-2 flex items-center gap-2">
            <span className={['inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold', getScoreClasses(currentAttempt.score ?? 0)].join(' ')}>
              {`${currentAttempt.score ?? 0}/10`}
            </span>
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
              Previous review
            </span>
          </div>
          <p className="text-[12px] leading-5 text-dim">{summarizeReview(currentReview)}</p>
        </div>
      ) : null}
    </div>
  );
}
