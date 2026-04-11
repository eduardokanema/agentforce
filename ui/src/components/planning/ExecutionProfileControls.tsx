import type { MissionDraft, Model } from '../../lib/types';

const THINKING_LEVELS = ['low', 'medium', 'high', 'xhigh'] as const;

interface ExecutionProfileControlsProps {
  draft: MissionDraft;
  models: Model[];
  onWorkerModelChange: (value: string) => void;
  onReviewerModelChange: (value: string) => void;
  onWorkerThinkingChange: (value: string) => void;
  onReviewerThinkingChange: (value: string) => void;
}

export default function ExecutionProfileControls({
  draft,
  models,
  onWorkerModelChange,
  onReviewerModelChange,
  onWorkerThinkingChange,
  onReviewerThinkingChange,
}: ExecutionProfileControlsProps) {
  const workerModel = draft.draft_spec.execution_defaults?.worker?.model ?? '';
  const reviewerModel = draft.draft_spec.execution_defaults?.reviewer?.model ?? '';
  const workerThinking = draft.draft_spec.execution_defaults?.worker?.thinking ?? 'medium';
  const reviewerThinking = draft.draft_spec.execution_defaults?.reviewer?.thinking ?? 'medium';

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
        Mission Defaults
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            Worker
          </div>
          <select
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
            value={workerModel}
            onChange={(event) => onWorkerModelChange(event.currentTarget.value)}
          >
            {models.map((model) => (
              <option key={`worker-${model.id}`} value={model.id}>
                {model.name}
              </option>
            ))}
          </select>
          <select
            className="mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
            value={workerThinking}
            onChange={(event) => onWorkerThinkingChange(event.currentTarget.value)}
          >
            {THINKING_LEVELS.map((level) => (
              <option key={`worker-thinking-${level}`} value={level}>
                Thinking · {level}
              </option>
            ))}
          </select>
        </div>

        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            Reviewer
          </div>
          <select
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
            value={reviewerModel}
            onChange={(event) => onReviewerModelChange(event.currentTarget.value)}
          >
            {models.map((model) => (
              <option key={`reviewer-${model.id}`} value={model.id}>
                {model.name}
              </option>
            ))}
          </select>
          <select
            className="mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
            value={reviewerThinking}
            onChange={(event) => onReviewerThinkingChange(event.currentTarget.value)}
          >
            {THINKING_LEVELS.map((level) => (
              <option key={`reviewer-thinking-${level}`} value={level}>
                Thinking · {level}
              </option>
            ))}
          </select>
        </div>
      </div>
    </section>
  );
}
