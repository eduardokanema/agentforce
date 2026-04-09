import type { MissionDraft, Model } from '../../lib/types';

interface ExecutionProfileControlsProps {
  draft: MissionDraft;
  models: Model[];
  onWorkerModelChange: (value: string) => void;
  onReviewerModelChange: (value: string) => void;
}

export default function ExecutionProfileControls({
  draft,
  models,
  onWorkerModelChange,
  onReviewerModelChange,
}: ExecutionProfileControlsProps) {
  const workerModel = draft.draft_spec.execution_defaults?.worker?.model ?? '';
  const reviewerModel = draft.draft_spec.execution_defaults?.reviewer?.model ?? '';

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="section-title">Execution Profile</h2>
      <p className="mt-1 text-xs text-dim">Mission-level worker and reviewer defaults stay visible on the controls rail.</p>

      <div className="mt-4 grid gap-4">
        <label className="block text-sm font-medium text-text">
          Worker model
          <select
            className="mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
            value={workerModel}
            onChange={(event) => onWorkerModelChange(event.currentTarget.value)}
          >
            {models.map((model) => (
              <option key={`worker-${model.id}`} value={model.id}>
                {model.name}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm font-medium text-text">
          Reviewer model
          <select
            className="mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
            value={reviewerModel}
            onChange={(event) => onReviewerModelChange(event.currentTarget.value)}
          >
            {models.map((model) => (
              <option key={`reviewer-${model.id}`} value={model.id}>
                {model.name}
              </option>
            ))}
          </select>
        </label>
      </div>
    </section>
  );
}
