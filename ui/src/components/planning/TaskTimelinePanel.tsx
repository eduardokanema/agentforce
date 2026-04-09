import type { MissionDraft, TaskSpec } from '../../lib/types';

interface TaskTimelinePanelProps {
  draft: MissionDraft;
  saving: boolean;
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
  onTaskChange,
  onSave,
}: TaskTimelinePanelProps) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="section-title">Task Timeline</h2>
          <p className="mt-1 text-xs text-dim">Structured task edits patch the revisioned draft spec.</p>
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
        {draft.draft_spec.tasks.map((task) => (
          <article key={task.id} className="rounded-lg border border-border bg-surface p-3">
            <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.08em] text-muted">
              Task {task.id}
            </div>
            <input
              className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
              value={task.title}
              onInput={(event) => onTaskChange(task.id, { title: event.currentTarget.value })}
            />
            <textarea
              rows={2}
              className="mt-2 w-full rounded-lg border border-border bg-card p-3 text-sm text-text outline-none focus:border-cyan"
              value={task.description}
              onInput={(event) => onTaskChange(task.id, { description: event.currentTarget.value })}
            />
            <label className="mt-3 block text-xs font-medium uppercase tracking-[0.08em] text-muted">
              Acceptance Criteria
              <textarea
                aria-label={`Task ${task.id} acceptance criteria`}
                rows={3}
                className="mt-2 w-full rounded-lg border border-border bg-card p-3 text-sm text-text outline-none focus:border-cyan"
                value={joinLines(task.acceptance_criteria)}
                onInput={(event) => onTaskChange(task.id, {
                  acceptance_criteria: parseLines(event.currentTarget.value),
                })}
              />
            </label>
            <label className="mt-3 block text-xs font-medium uppercase tracking-[0.08em] text-muted">
              Dependencies
              <input
                aria-label={`Task ${task.id} dependencies`}
                className="mt-2 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                value={task.dependencies.join(', ')}
                onInput={(event) => onTaskChange(task.id, {
                  dependencies: event.currentTarget.value
                    .split(',')
                    .map((entry) => entry.trim())
                    .filter(Boolean),
                })}
              />
            </label>
            <label className="mt-3 block text-xs font-medium uppercase tracking-[0.08em] text-muted">
              Max Retries
              <input
                aria-label={`Task ${task.id} max retries`}
                type="number"
                min={0}
                className="mt-2 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                value={task.max_retries}
                onInput={(event) => onTaskChange(task.id, {
                  max_retries: Math.max(0, Number(event.currentTarget.value) || 0),
                })}
              />
            </label>
            <label className="mt-3 block text-xs font-medium uppercase tracking-[0.08em] text-muted">
              Output Artifacts
              <textarea
                aria-label={`Task ${task.id} output artifacts`}
                rows={2}
                className="mt-2 w-full rounded-lg border border-border bg-card p-3 text-sm text-text outline-none focus:border-cyan"
                value={joinLines(task.output_artifacts)}
                onInput={(event) => onTaskChange(task.id, {
                  output_artifacts: parseLines(event.currentTarget.value),
                })}
              />
            </label>
          </article>
        ))}
      </div>
    </section>
  );
}
