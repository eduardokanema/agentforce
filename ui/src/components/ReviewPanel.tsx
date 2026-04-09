import { renderMarkdown } from '../lib/markdown';

export interface ReviewPanelProps {
  feedback: string;
  score: number;
  criteriaResults?: Record<string, string>;
  blockingIssues?: string[];
  suggestions?: string[];
}

type ScoreTone = {
  container: string;
  border: string;
  text: string;
};

function getScoreTone(score: number): ScoreTone {
  if (score <= 4) {
    return {
      container: 'bg-red/10 border-red/30 text-red',
      border: 'border-red/30',
      text: 'text-red',
    };
  }

  if (score <= 7) {
    return {
      container: 'bg-amber/10 border-amber/30 text-amber',
      border: 'border-amber/30',
      text: 'text-amber',
    };
  }

  return {
    container: 'bg-green/10 border-green/30 text-green',
    border: 'border-green/30',
    text: 'text-green',
  };
}

function normalizeResult(value: string): string {
  return value.trim().toLowerCase();
}

function getCriterionIcon(value: string): string {
  const normalized = normalizeResult(value);
  if (
    ['met', 'pass', 'passed', 'ok', 'true', 'yes', 'done', 'complete', 'approved'].includes(normalized)
  ) {
    return '✓';
  }

  if (
    ['fail', 'failed', 'false', 'no', 'missing', 'blocked', 'rejected', 'not met'].includes(normalized)
  ) {
    return '✗';
  }

  return '~';
}

function getCriterionTone(value: string): string {
  const icon = getCriterionIcon(value);
  if (icon === '✓') {
    return 'text-green';
  }
  if (icon === '✗') {
    return 'text-red';
  }
  return 'text-amber';
}

function truncateFeedback(text: string, limit: number): string {
  const trimmed = text.trim();
  if (trimmed.length <= limit) {
    return trimmed;
  }

  return `${trimmed.slice(0, limit).trimEnd()}…`;
}

export default function ReviewPanel({
  feedback,
  score,
  criteriaResults,
  blockingIssues,
  suggestions,
}: ReviewPanelProps) {
  const tone = getScoreTone(score);
  const hasCriteria = Boolean(criteriaResults && Object.keys(criteriaResults).length > 0);
  const hasBlockingIssues = Boolean(blockingIssues && blockingIssues.length > 0);
  const hasSuggestions = Boolean(suggestions && suggestions.length > 0);

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-4 flex flex-wrap items-start gap-4">
        <div
          className={[
            'flex h-[60px] w-[60px] shrink-0 items-center justify-center rounded-full border text-xl font-bold tabular-nums',
            tone.container,
            score >= 8 ? 'animate-[pulse-glow_3s_ease_infinite]' : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          {`${score}/10`}
        </div>

        <div className="min-w-0 flex-1">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-[0.09em] text-muted">
              Review Feedback
            </span>
            <span className={['inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold', tone.border, tone.text].join(' ')}>
              {score >= 8 ? 'strong' : score >= 5 ? 'mixed' : 'needs work'}
            </span>
          </div>

          <div
            className="prose-like text-[13px] leading-6 text-dim"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(feedback) }}
          />
        </div>
      </div>

      {hasCriteria ? (
        <div className="mb-4 rounded-lg border border-border bg-surface p-3">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            Criteria Results
          </div>
          <div className="space-y-2">
            {Object.entries(criteriaResults ?? {}).map(([criterion, value]) => {
              const icon = getCriterionIcon(value);
              const toneClass = getCriterionTone(value);

              return (
                <div key={criterion} className="flex items-start gap-2 text-[12px] leading-5">
                  <span className={['mt-0.5 font-bold', toneClass].join(' ')}>{icon}</span>
                  <div className="min-w-0">
                    <span className="font-semibold text-text">{criterion}</span>
                    <span className="ml-2 text-dim">{value}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {hasBlockingIssues ? (
        <div className="mb-4 rounded border border-red/20 bg-red/10 p-3 text-[12px]">
          <div className="mb-2 font-semibold text-red">⚠ Blocking Issues</div>
          <ul className="ml-4 list-disc space-y-1 text-text">
            {(blockingIssues ?? []).map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {hasSuggestions ? (
        <details className="rounded border border-amber/20 bg-amber/10 p-3 text-[12px]">
          <summary className="cursor-pointer font-semibold text-amber">
            💡 Suggestions ({suggestions?.length ?? 0})
          </summary>
          <ul className="ml-4 mt-2 list-disc space-y-1 text-dim">
            {(suggestions ?? []).map((suggestion) => (
              <li key={suggestion}>{truncateFeedback(suggestion, 500)}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
