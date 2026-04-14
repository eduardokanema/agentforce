import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { archiveProject, createProject, getProjects, unarchiveProject } from '../lib/api';
import { useToast } from '../hooks/useToast';
import { PLAN_ROUTE, projectRoute, type ProjectSummaryView } from '../lib/types';

const PROJECT_STATUS_CLASSES: Record<ProjectSummaryView['status'], string> = {
  planning: 'text-amber border-amber/30 bg-amber/10',
  ready: 'text-teal border-teal/30 bg-teal/10',
  running: 'text-cyan border-cyan/30 bg-cyan/10',
  blocked: 'text-red border-red/30 bg-red/10',
  completed: 'text-green border-green/30 bg-green/10',
  archived: 'text-dim border-border bg-surface',
  idle: 'text-dim border-border bg-surface',
};

function formatLabel(value: string): string {
  if (!value) {
    return '—';
  }

  return value.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase());
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function statusPillClassName(status: ProjectSummaryView['status']): string {
  return PROJECT_STATUS_CLASSES[status];
}

function modePillClassName(mode: ProjectSummaryView['mode']): string {
  return mode === 'optimize'
    ? 'text-amber border-amber/30 bg-amber/10'
    : 'text-teal border-teal/30 bg-teal/10';
}

function LoadingState() {
  return (
    <div aria-label="Loading projects" className="grid gap-4">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={index} className="animate-pulse overflow-hidden rounded-lg border border-border bg-card">
          <div className="flex flex-col gap-3 px-4 py-4">
            <div className="flex items-center gap-2">
              <div className="h-4 w-52 rounded bg-surface" />
              <div className="h-5 w-20 rounded-full bg-surface" />
              <div className="h-5 w-20 rounded-full bg-surface" />
              <div className="ml-auto h-3 w-28 rounded bg-surface" />
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="h-12 rounded bg-surface" />
              <div className="h-12 rounded bg-surface" />
              <div className="h-12 rounded bg-surface" />
              <div className="h-12 rounded bg-surface" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <section className="rounded-lg border border-border bg-card px-4 py-5 text-sm text-dim">
      <span>No projects yet. </span>
      <Link className="text-cyan hover:no-underline" to={PLAN_ROUTE}>
        Start in Plan Mode →
      </Link>
    </section>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section role="alert" className="rounded-lg border border-red/30 bg-red-bg/20 px-4 py-5">
      <div className="text-sm font-semibold text-red">Unable to load projects</div>
      <p className="mt-1 text-sm text-dim">{message}</p>
      <button
        type="button"
        className="mt-3 inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
        onClick={onRetry}
      >
        Retry
      </button>
    </section>
  );
}

function ProjectCard({
  project,
  onArchiveToggle,
}: {
  project: ProjectSummaryView;
  onArchiveToggle: (project: ProjectSummaryView) => void;
}) {
  const repoRoot = project.repo_root.trim() || '—';
  const primaryWorkingDirectory = project.primary_working_directory?.trim() || repoRoot;
  const blocker = project.blocker?.trim() || '—';
  const nextAction = project.next_action?.trim() || '—';
  const goal = project.goal?.trim() || '—';
  const workspaceLabel = project.workspace_count > 1
    ? `${project.workspace_count} working directories`
    : '1 working directory';

  return (
    <article className="group rounded-lg border border-border bg-card transition-all duration-200 hover:border-border-lit hover:shadow-[0_0_24px_rgba(34,211,238,0.1)]">
      <div className="flex flex-col gap-4 px-4 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <Link className="text-[15px] font-semibold text-text transition-colors hover:text-cyan hover:no-underline" to={projectRoute(project.project_id)}>
            {project.name}
          </Link>
          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${statusPillClassName(project.status)}`}>
            {formatLabel(project.status)}
          </span>
          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${modePillClassName(project.mode)}`}>
            {formatLabel(project.mode)}
          </span>
          <span className="ml-auto font-mono text-[11px] text-dim">
            Updated {formatTimestamp(project.updated_at)}
          </span>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Repo root</div>
            <div className="mt-1 truncate font-mono text-[12px] text-text">{repoRoot}</div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Working directory</div>
            <div className="mt-1 truncate font-mono text-[12px] text-text">{primaryWorkingDirectory}</div>
            <div className="mt-1 text-[11px] text-dim">{workspaceLabel}</div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Planning goal</div>
            <div className="mt-1 text-[12px] text-text">{goal}</div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Planned tasks</div>
            <div className="mt-1 text-[12px] text-text">{project.planned_task_count}</div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Blocker</div>
            <div className="mt-1 text-[12px] text-text">{blocker}</div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Next action</div>
            <div className="mt-1 text-[12px] text-text">{nextAction}</div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <Link
            className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 hover:no-underline"
            to={projectRoute(project.project_id)}
          >
            Open Project
          </Link>
          <button
            type="button"
            className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
            onClick={() => onArchiveToggle(project)}
          >
            {project.status === 'archived' ? 'Unarchive' : 'Archive'}
          </button>
        </div>
      </div>
    </article>
  );
}

export default function ProjectsPage() {
  const { addToast } = useToast();
  const [projects, setProjects] = useState<ProjectSummaryView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [repoRoot, setRepoRoot] = useState('');
  const [name, setName] = useState('');
  const [goal, setGoal] = useState('');
  const [workingDirectoriesText, setWorkingDirectoriesText] = useState('');

  useEffect(() => {
    let active = true;

    setLoading(true);
    getProjects({ includeArchived })
      .then((fetchedProjects) => {
        if (!active) {
          return;
        }

        setProjects(fetchedProjects);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active) {
          return;
        }

        setError(err instanceof Error ? err.message : 'Failed to load projects');
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [includeArchived, refreshIndex]);

  const refresh = () => {
    setRefreshIndex((value) => value + 1);
  };

  const resetCreateForm = () => {
    setRepoRoot('');
    setName('');
    setGoal('');
    setWorkingDirectoriesText('');
    setShowCreateForm(false);
  };

  const handleCreate = async (): Promise<void> => {
    try {
      await createProject({
        repo_root: repoRoot,
        name,
        goal,
        working_directories: workingDirectoriesText
          .split('\n')
          .map((value) => value.trim())
          .filter(Boolean),
      });
      addToast('Project created', 'success');
      resetCreateForm();
      setIncludeArchived(false);
      refresh();
    } catch (createError) {
      addToast(createError instanceof Error ? createError.message : 'Failed to create project', 'error');
    }
  };

  const handleArchiveToggle = async (project: ProjectSummaryView): Promise<void> => {
    try {
      if (project.status === 'archived') {
        await unarchiveProject(project.project_id);
        addToast('Project unarchived', 'success');
      } else {
        await archiveProject(project.project_id);
        addToast('Project archived', 'info');
      }
      refresh();
    } catch (archiveError) {
      addToast(archiveError instanceof Error ? archiveError.message : 'Failed to update archive state', 'error');
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">Primary surface</div>
          <h1 className="text-3xl font-semibold tracking-tight">Projects</h1>
          <p className="mt-1 text-sm text-dim">
            Projects keep repo root, working directories, and planning context together. Missions stay inside each
            project as a secondary drill-down.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15"
            onClick={() => setShowCreateForm((value) => !value)}
          >
            {showCreateForm ? 'Close new project' : 'New project'}
          </button>
          <Link
            className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 hover:no-underline"
            to={PLAN_ROUTE}
          >
            New project plan
          </Link>
          <button
            type="button"
            className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
            onClick={() => setIncludeArchived((value) => !value)}
          >
            {includeArchived ? 'Hide archived' : 'Show archived'}
          </button>
          <button
            type="button"
            className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
            onClick={refresh}
          >
            Refresh
          </button>
        </div>
      </header>

      {showCreateForm ? (
        <section className="rounded-lg border border-border bg-card px-4 py-4">
          <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Create project</div>
          <div className="mt-3 grid gap-3">
            <label className="grid gap-1 text-sm text-text">
              <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Repo root</span>
              <input className="rounded border border-border bg-surface px-3 py-2 text-sm" value={repoRoot} onChange={(event) => setRepoRoot(event.target.value)} />
            </label>
            <label className="grid gap-1 text-sm text-text">
              <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Name</span>
              <input className="rounded border border-border bg-surface px-3 py-2 text-sm" value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label className="grid gap-1 text-sm text-text">
              <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Goal</span>
              <textarea className="min-h-20 rounded border border-border bg-surface px-3 py-2 text-sm" value={goal} onChange={(event) => setGoal(event.target.value)} />
            </label>
            <label className="grid gap-1 text-sm text-text">
              <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Working directories</span>
              <textarea
                className="min-h-24 rounded border border-border bg-surface px-3 py-2 font-mono text-sm"
                placeholder="/repo/apps/core&#10;/repo/tests"
                value={workingDirectoriesText}
                onChange={(event) => setWorkingDirectoriesText(event.target.value)}
              />
            </label>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15"
                onClick={() => { void handleCreate(); }}
              >
                Save project
              </button>
              <button
                type="button"
                className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
                onClick={resetCreateForm}
              >
                Cancel
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} onRetry={refresh} />
      ) : projects.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="grid gap-4">
          {projects.map((project) => (
            <li key={project.project_id}>
              <ProjectCard project={project} onArchiveToggle={(value) => { void handleArchiveToggle(value); }} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
