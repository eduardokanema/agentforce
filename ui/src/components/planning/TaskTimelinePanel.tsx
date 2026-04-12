import ExecutionProfileSelect from '../ExecutionProfileSelect';
import { executionProfileFromOption, optionIdFromExecutionProfile } from '../../lib/executionProfiles';
import type { ExecutionConfig, MissionDraft, Model, TaskSpec } from '../../lib/types';

interface TaskTimelinePanelProps {
  draft: MissionDraft;
  saving: boolean;
  models: Model[];
  onTaskChange: (taskId: string, patch: Partial<TaskSpec>) => void;
  onSave: () => void;
}

function joinLines(values: string[]): string {
  return values.join('\n');
}

function parseLines(value: string): string[] {
  return value
    .split('\n')
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export default function TaskTimelinePanel({
  draft,
  saving,
  models,
  onTaskChange,
  onSave,
}: TaskTimelinePanelProps) {
  const tasks = draft.draft_spec.tasks;
  const defaultWorkerProfile = draft.draft_spec.execution_defaults?.worker ?? null;
  const defaultReviewerProfile = draft.draft_spec.execution_defaults?.reviewer ?? null;

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="section-title">Task Timeline</h2>
          <p className="mt-1 text-xs text-dim">
            {tasks.length} task{tasks.length !== 1 ? 's' : ''} · patch-on-change, save to persist
          </p>
        </div>
        <button
          type="button"
          className="rounded-full border border-border px-4 py-2 text-sm text-dim transition-colors hover:bg-card-hover disabled:cursor-not-allowed disabled:opacity-50"
          disabled={saving}
          onClick={onSave}
        >
          Save Tasks
        </button>
      </div>

      <div className="mt-4 space-y-3">
        {tasks.map((task, idx) => {
          const taskNum = String(idx + 1).padStart(2, '0');
          const hasBadDeps = task.dependencies.some(
            (dep) => !tasks.find((t) => t.id === dep),
          );
          const taskStatusColor = hasBadDeps ? 'border-amber text-amber bg-amber-bg/20' : 'border-border text-muted bg-card';
          const taskWorkerProfileId = optionIdFromExecutionProfile(task.execution?.worker ?? null, models);
          const taskReviewerProfileId = optionIdFromExecutionProfile(task.execution?.reviewer ?? null, models);

          const handleWorkerProfileChange = (value: string): void => {
            const worker = executionProfileFromOption(models.find((model) => model.id === value));
            const execution: ExecutionConfig | null = worker
              ? { worker, reviewer: task.execution?.reviewer ?? null }
              : task.execution?.reviewer
                ? { worker: null, reviewer: task.execution.reviewer }
                : null;
            onTaskChange(task.id, { execution });
          };

          const handleReviewerProfileChange = (value: string): void => {
            const reviewer = executionProfileFromOption(models.find((model) => model.id === value));
            const execution: ExecutionConfig | null = reviewer
              ? { worker: task.execution?.worker ?? null, reviewer }
              : task.execution?.worker
                ? { worker: task.execution.worker, reviewer: null }
                : null;
            onTaskChange(task.id, { execution });
          };

          return (
            <article
              key={task.id}
              className="relative overflow-hidden rounded-lg border border-border bg-surface transition-all duration-200 hover:border-border-lit"
            >
              <div className="space-y-3 p-4">
                {/* Header */}
                <div className="flex items-center gap-3">
                  <span className={`flex-shrink-0 rounded-full border px-2 py-0.5 font-mono text-[11px] font-bold transition-colors ${taskStatusColor}`}>
                    {taskNum}
                  </span>
                  <input
                    aria-label={`Task ${task.id} title`}
                    className="flex-1 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-semibold text-text outline-none focus:border-cyan"
                    value={task.title}
                    onInput={(event) => onTaskChange(task.id, { title: event.currentTarget.value })}
                  />
                </div>

                {/* Description */}
                <textarea
                  aria-label={`Task ${task.id} description`}
                  rows={2}
                  className="w-full rounded-lg border border-border bg-card p-3 text-sm text-text outline-none focus:border-cyan"
                  value={task.description}
                  onInput={(event) => onTaskChange(task.id, { description: event.currentTarget.value })}
                />

                {/* Acceptance Criteria */}
                <div>
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                    Acceptance Criteria
                  </div>
                  <textarea
                    aria-label={`Task ${task.id} acceptance criteria`}
                    rows={3}
                    className="w-full rounded-lg border border-border bg-card p-3 text-sm text-text outline-none focus:border-cyan"
                    value={joinLines(task.acceptance_criteria)}
                    onInput={(event) => onTaskChange(task.id, {
                      acceptance_criteria: parseLines(event.currentTarget.value),
                    })}
                  />
                </div>

                {/* Dependencies + Output Artifacts */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                      Dependencies
                    </div>
                    {tasks.filter((t) => t.id !== task.id).length === 0 ? (
                      <p className="text-xs italic text-dim">No other tasks</p>
                    ) : (
                      <div className="space-y-1">
                        {tasks
                          .filter((t) => t.id !== task.id)
                          .map((otherTask) => {
                            const otherIdx = tasks.findIndex((t) => t.id === otherTask.id);
                            const otherNum = String(otherIdx + 1).padStart(2, '0');
                            const checked = task.dependencies.includes(otherTask.id);
                            return (
                              <label
                                key={otherTask.id}
                                className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-text hover:bg-card"
                              >
                                <input
                                  type="checkbox"
                                  className="accent-cyan"
                                  checked={checked}
                                  onChange={() => {
                                    const deps = checked
                                      ? task.dependencies.filter((d) => d !== otherTask.id)
                                      : [...task.dependencies, otherTask.id];
                                    onTaskChange(task.id, { dependencies: deps });
                                  }}
                                />
                                <span className="flex-shrink-0 font-mono text-muted">{otherNum}</span>
                                <span className="truncate">{otherTask.title}</span>
                              </label>
                            );
                          })}
                      </div>
                    )}
                  </div>

                  <div>
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                      Output Artifacts
                    </div>
                    <textarea
                      aria-label={`Task ${task.id} output artifacts`}
                      rows={4}
                      className="w-full rounded-lg border border-border bg-card p-3 text-sm text-text outline-none focus:border-cyan"
                      value={joinLines(task.output_artifacts)}
                      onInput={(event) => onTaskChange(task.id, {
                        output_artifacts: parseLines(event.currentTarget.value),
                      })}
                    />
                  </div>
                </div>

                {/* Execution row */}
                <div className="grid grid-cols-[1fr_1fr_80px] gap-3 items-end">
                  <div>
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                      Worker Profile
                    </div>
                    <ExecutionProfileSelect
                      aria-label={`Task ${task.id} worker model`}
                      className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                      value={taskWorkerProfileId}
                      onChange={handleWorkerProfileChange}
                      options={models}
                      emptyLabel={
                        defaultWorkerProfile
                          ? `Inherit (${defaultWorkerProfile.agent} · ${defaultWorkerProfile.model} · ${defaultWorkerProfile.thinking ?? 'medium'})`
                          : 'Inherit default worker profile'
                      }
                    />
                  </div>

                  <div>
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                      Reviewer Profile
                    </div>
                    <ExecutionProfileSelect
                      aria-label={`Task ${task.id} reviewer model`}
                      className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                      value={taskReviewerProfileId}
                      onChange={handleReviewerProfileChange}
                      options={models}
                      emptyLabel={
                        defaultReviewerProfile
                          ? `Inherit (${defaultReviewerProfile.agent} · ${defaultReviewerProfile.model} · ${defaultReviewerProfile.thinking ?? 'medium'})`
                          : 'Inherit default reviewer profile'
                      }
                    />
                  </div>

                  <div>
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                      Retries
                    </div>
                    <input
                      aria-label={`Task ${task.id} max retries`}
                      type="number"
                      min={0}
                      max={9}
                      className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                      value={task.max_retries}
                      onInput={(event) => onTaskChange(task.id, {
                        max_retries: Math.max(0, Number(event.currentTarget.value) || 0),
                      })}
                    />
                  </div>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
