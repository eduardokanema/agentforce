import { Link } from 'react-router-dom';
import { PROJECTS_ROUTE, type ProjectSection, type ProjectSummaryView } from '../lib/types';
import ProjectSectionNav from './ProjectSectionNav';

function formatLabel(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }

  return value.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase());
}

function stageTone(stage: ProjectSummaryView['current_stage']): string {
  switch (stage) {
    case 'planning':
    case 'ready_to_launch':
      return 'text-amber border-amber/30 bg-amber/10';
    case 'executing':
      return 'text-cyan border-cyan/30 bg-cyan/10';
    case 'blocked':
      return 'text-red border-red/30 bg-red/10';
    case 'completed':
      return 'text-green border-green/30 bg-green/10';
    default:
      return 'text-dim border-border bg-surface';
  }
}

export default function ProjectShellHeader({
  summary,
  section,
}: {
  summary: ProjectSummaryView;
  section: ProjectSection;
}) {
  const activePlans = summary.active_plan_count ?? 0;
  const runningPlans = summary.running_plan_count ?? 0;
  const blockedNodes = summary.blocked_node_count ?? 0;
  return (
    <div className="grid gap-4">
      <header className="rounded-lg border border-border bg-card px-4 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">Project</div>
            <h1 className="text-3xl font-semibold tracking-tight">{summary.name}</h1>
            <p className="mt-1 text-sm text-dim font-mono">{summary.repo_root}</p>
            <p className="mt-2 max-w-[72ch] text-sm text-dim">
              Keep memory, settings, active plans, and mission history inside one long-lived workspace.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${stageTone(summary.current_stage)}`}>
              {formatLabel(summary.current_stage)}
            </span>
            <span className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-dim">
              {formatLabel(summary.mode)}
            </span>
            <Link
              className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card hover:no-underline"
              to={PROJECTS_ROUTE}
            >
              Back to Projects
            </Link>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-4">
          <div className="rounded-lg border border-border bg-surface px-3 py-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Current stage</div>
            <div className="mt-1 text-[13px] text-text">{formatLabel(summary.current_stage)}</div>
          </div>
          <div className="rounded-lg border border-border bg-surface px-3 py-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Next action</div>
            <div className="mt-1 text-[13px] text-text">{summary.next_action_label?.trim() || summary.next_action?.trim() || '—'}</div>
          </div>
          <div className="rounded-lg border border-border bg-surface px-3 py-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Working directory</div>
            <div className="mt-1 break-words font-mono text-[12px] text-text">{summary.primary_working_directory?.trim() || summary.repo_root}</div>
          </div>
          <div className="rounded-lg border border-border bg-surface px-3 py-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Mission status</div>
            <div className="mt-1 text-[13px] text-text">{formatLabel(summary.status)}</div>
          </div>
          <div className="rounded-lg border border-border bg-surface px-3 py-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Plan portfolio</div>
            <div className="mt-1 text-[13px] text-text">{activePlans} active plan{activePlans === 1 ? '' : 's'}</div>
          </div>
          <div className="rounded-lg border border-border bg-surface px-3 py-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Running now</div>
            <div className="mt-1 text-[13px] text-text">{runningPlans} active execution{runningPlans === 1 ? '' : 's'}</div>
          </div>
          <div className="rounded-lg border border-border bg-surface px-3 py-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Blocked nodes</div>
            <div className="mt-1 text-[13px] text-text">{blockedNodes}</div>
          </div>
        </div>
      </header>

      <ProjectSectionNav projectId={summary.project_id} currentSection={section} />
    </div>
  );
}
