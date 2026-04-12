import ExecutionProfileSelect from '../ExecutionProfileSelect';
import { optionIdFromExecutionProfile } from '../../lib/executionProfiles';
import type { MissionDraft, Model } from '../../lib/types';

interface ExecutionProfileControlsProps {
  draft: MissionDraft;
  options: Model[];
  onWorkerProfileChange: (value: string) => void;
  onReviewerProfileChange: (value: string) => void;
}

export default function ExecutionProfileControls({
  draft,
  options,
  onWorkerProfileChange,
  onReviewerProfileChange,
}: ExecutionProfileControlsProps) {
  const workerValue = optionIdFromExecutionProfile(
    draft.draft_spec.execution_defaults?.worker ?? null,
    options,
  );
  const reviewerValue = optionIdFromExecutionProfile(
    draft.draft_spec.execution_defaults?.reviewer ?? null,
    options,
  );

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
          <ExecutionProfileSelect
            options={options}
            value={workerValue}
            onChange={onWorkerProfileChange}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
            ariaLabel="Mission default worker execution profile"
          />
        </div>

        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            Reviewer
          </div>
          <ExecutionProfileSelect
            options={options}
            value={reviewerValue}
            onChange={onReviewerProfileChange}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
            ariaLabel="Mission default reviewer execution profile"
          />
        </div>
      </div>
    </section>
  );
}
