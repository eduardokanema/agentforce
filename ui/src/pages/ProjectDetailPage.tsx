import { useEffect, useState, type ReactNode } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import ConfirmDialog from '../components/ConfirmDialog';
import ProjectShellHeader from '../components/ProjectShellHeader';
import {
  archiveProject,
  deleteProject,
  getProject,
  unarchiveProject,
  updateProject,
} from '../lib/api';
import { useToast } from '../hooks/useToast';
import {
  PROJECTS_ROUTE,
  projectHistoryRoute,
  projectPlanRoute,
  projectSettingsRoute,
  projectOverviewRoute,
  type ProjectHarnessView,
  type ProjectSection,
} from '../lib/types';

const ALLOWED_SECTIONS = new Set<ProjectSection>(['overview', 'history', 'settings']);

function formatLabel(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  return value.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase());
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function statusTone(status: string): string {
  switch (status) {
    case 'running':
    case 'reviewing':
      return 'text-cyan border-cyan/30 bg-cyan/10';
    case 'ready':
    case 'queued':
      return 'text-teal border-teal/30 bg-teal/10';
    case 'completed':
      return 'text-green border-green/30 bg-green/10';
    case 'blocked':
    case 'failed':
      return 'text-red border-red/30 bg-red/10';
    default:
      return 'text-amber border-amber/30 bg-amber/10';
  }
}

function LoadingState() {
  return (
    <div className="space-y-4">
      <div className="animate-pulse rounded-lg border border-border bg-card px-4 py-4">
        <div className="h-5 w-48 rounded bg-surface" />
        <div className="mt-3 h-4 w-72 rounded bg-surface" />
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="h-16 rounded bg-surface" />
          <div className="h-16 rounded bg-surface" />
          <div className="h-16 rounded bg-surface" />
          <div className="h-16 rounded bg-surface" />
        </div>
      </div>
    </div>
  );
}

function SectionCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border bg-card px-4 py-4">
      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{title}</div>
      {description ? <p className="mt-1 text-sm text-dim">{description}</p> : null}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export default function ProjectDetailPage() {
  const { id, section } = useParams<{ id?: string; section?: ProjectSection }>();
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [project, setProject] = useState<ProjectHarnessView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editGoal, setEditGoal] = useState('');
  const [editWorkingDirectories, setEditWorkingDirectories] = useState('');
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  useEffect(() => {
    if (!id) {
      setProject(null);
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);
    getProject(id)
      .then((value) => {
        if (!active) {
          return;
        }
        setProject(value);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active) {
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load project');
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [id, refreshIndex]);

  useEffect(() => {
    if (!project) {
      return;
    }
    setEditName(project.summary.name);
    setEditGoal(project.project?.description ?? project.context.goal ?? '');
    setEditWorkingDirectories((project.project?.settings.working_directories ?? project.context.working_directories).join('\n'));
  }, [project]);

  if (!id) {
    return <Navigate to={PROJECTS_ROUTE} replace />;
  }

  const currentSection: ProjectSection = section && ALLOWED_SECTIONS.has(section) ? section : 'overview';
  if (section && !ALLOWED_SECTIONS.has(section)) {
    return <Navigate to={projectOverviewRoute(id)} replace />;
  }

  const refresh = () => {
    setRefreshIndex((value) => value + 1);
  };

  const handleSave = async () => {
    try {
      const next = await updateProject(id, {
        name: editName,
        goal: editGoal,
        working_directories: editWorkingDirectories
          .split('\n')
          .map((value) => value.trim())
          .filter(Boolean),
      });
      setProject(next);
      setEditing(false);
      addToast('Project settings updated', 'success');
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed to update project', 'error');
    }
  };

  const handleArchiveToggle = async () => {
    if (!project) {
      return;
    }
    try {
      if (project.lifecycle.archived) {
        await unarchiveProject(id);
        addToast('Project unarchived', 'success');
      } else {
        await archiveProject(id);
        addToast('Project archived', 'success');
      }
      refresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed to update lifecycle', 'error');
    }
  };

  const handleDelete = async () => {
    try {
      await deleteProject(id);
      addToast('Project deleted', 'success');
      navigate(PROJECTS_ROUTE);
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed to delete project', 'error');
    }
  };

  if (loading) {
    return <LoadingState />;
  }

  if (error || !project) {
    return (
      <section className="rounded-lg border border-red/30 bg-red-bg/20 px-4 py-5">
        <div className="text-sm font-semibold text-red">Unable to load project</div>
        <p className="mt-1 text-sm text-dim">{error ?? 'Project not found'}</p>
      </section>
    );
  }

  const selectedPlan = project.selected_plan;
  const scheduler = project.scheduler;

  return (
    <div className="grid gap-4">
      <ProjectShellHeader summary={project.summary} section={currentSection} />

      {currentSection === 'overview' ? (
        <div className="grid gap-4">
          <SectionCard
            title="Project Home"
            description="The project is the source of truth for memory, settings, active plans, and mission history."
          >
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-lg border border-border bg-surface px-3 py-3">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Active plans</div>
                <div className="mt-1 text-2xl font-semibold text-text">{project.plans?.length ?? 0}</div>
              </div>
              <div className="rounded-lg border border-border bg-surface px-3 py-3">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Ready queue</div>
                <div className="mt-1 text-2xl font-semibold text-text">{scheduler?.queue.length ?? 0}</div>
              </div>
              <div className="rounded-lg border border-border bg-surface px-3 py-3">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Blocked nodes</div>
                <div className="mt-1 text-2xl font-semibold text-text">{scheduler?.blocked.length ?? 0}</div>
              </div>
              <div className="rounded-lg border border-border bg-surface px-3 py-3">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Recent mission runs</div>
                <div className="mt-1 text-2xl font-semibold text-text">{project.history?.mission_runs.length ?? 0}</div>
              </div>
            </div>
          </SectionCard>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.9fr)]">
            <SectionCard title="Plan Portfolio" description="One project can own many plans at once.">
              <div className="space-y-3">
                {(project.plans ?? []).map((plan) => (
                  <article key={plan.plan_id} className="rounded-lg border border-border bg-surface px-4 py-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <h3 className="text-lg font-semibold text-text">{plan.name}</h3>
                        <p className="mt-1 text-sm text-dim">{plan.objective}</p>
                      </div>
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${statusTone(plan.status)}`}>
                        {formatLabel(plan.status)}
                      </span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-dim">
                      <span>{plan.node_count} nodes</span>
                      <span>{plan.quick_task ? 'Quick task' : 'Plan DAG'}</span>
                      <span>{plan.merged_project_scope.length} project scope</span>
                      <span>Updated {formatTimestamp(plan.updated_at)}</span>
                    </div>
                    <div className="mt-3">
                      <Link
                        className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 hover:no-underline"
                        to={`${projectPlanRoute(project.summary.project_id)}?plan=${encodeURIComponent(plan.plan_id)}`}
                      >
                        Open workspace
                      </Link>
                    </div>
                  </article>
                ))}
              </div>
            </SectionCard>

            <SectionCard title="Selected Plan" description="Current focus inside the project workspace.">
              {selectedPlan ? (
                <div className="space-y-3">
                  <div className="rounded-lg border border-border bg-surface px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Plan</div>
                    <div className="mt-1 text-lg font-semibold text-text">{selectedPlan.name}</div>
                    <div className="mt-1 text-sm text-dim">{selectedPlan.objective}</div>
                  </div>
                  <div className="rounded-lg border border-border bg-surface px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Graph</div>
                    <div className="mt-1 text-sm text-text">{selectedPlan.graph.nodes.length} high-level nodes</div>
                  </div>
                  <div className="rounded-lg border border-border bg-surface px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Latest mission overlay</div>
                    <div className="mt-1 text-sm text-text">{formatTimestamp(selectedPlan.history.mission_runs[0]?.updated_at)}</div>
                  </div>
                  <Link
                    className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 hover:no-underline"
                    to={`${projectPlanRoute(project.summary.project_id)}?plan=${encodeURIComponent(selectedPlan.plan_id)}`}
                  >
                    Open plan workspace
                  </Link>
                </div>
              ) : (
                <div className="text-sm text-dim">No plan selected yet.</div>
              )}
            </SectionCard>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Active Queue" description="Project-level scheduler output.">
              <div className="space-y-2">
                {(scheduler?.queue ?? []).slice(0, 6).map((item) => (
                  <div key={`${item.plan_id}:${item.node_id}`} className="rounded-lg border border-border bg-surface px-3 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-semibold text-text">{item.title}</div>
                      <div className="text-[11px] text-dim">P{item.scheduler_priority}</div>
                    </div>
                    <div className="mt-1 text-xs text-dim">{item.plan_name}</div>
                  </div>
                ))}
                {scheduler?.queue.length === 0 ? <div className="text-sm text-dim">No ready nodes.</div> : null}
              </div>
            </SectionCard>

            <SectionCard title="Current Blockers" description="Dependency or touch-scope blockers across active plans.">
              <div className="space-y-2">
                {(scheduler?.blocked ?? []).slice(0, 6).map((item) => (
                  <div key={`${item.plan_id}:${item.node_id}`} className="rounded-lg border border-border bg-surface px-3 py-3">
                    <div className="text-sm font-semibold text-text">{item.title}</div>
                    <div className="mt-1 text-xs text-dim">{item.conflict_reason ?? 'Blocked'}</div>
                  </div>
                ))}
                {scheduler?.blocked.length === 0 ? <div className="text-sm text-dim">No blockers.</div> : null}
              </div>
            </SectionCard>
          </div>
        </div>
      ) : null}

      {currentSection === 'history' ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <SectionCard title="Plan Versions" description="Immutable launchable versions.">
            <div className="space-y-2">
              {(project.history?.plan_versions ?? []).map((version) => (
                <article key={version.version_id} className="rounded-lg border border-border bg-surface px-3 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-text">{version.name}</div>
                    <div className="text-[11px] text-dim">{version.version_id.slice(-8)}</div>
                  </div>
                  <div className="mt-1 text-xs text-dim">{version.changelog[0] ?? 'Approved version snapshot'}</div>
                </article>
              ))}
              {(project.history?.plan_versions.length ?? 0) === 0 ? <div className="text-sm text-dim">No versions yet.</div> : null}
            </div>
          </SectionCard>

          <SectionCard title="Mission Runs" description="Execution overlays attached to approved plan versions.">
            <div className="space-y-2">
              {(project.history?.mission_runs ?? []).map((run) => (
                <article key={run.mission_run_id} className="rounded-lg border border-border bg-surface px-3 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-text">{run.mission_id ?? run.mission_run_id}</div>
                    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${statusTone(run.status)}`}>
                      {formatLabel(run.status)}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-dim">Updated {formatTimestamp(run.updated_at)}</div>
                </article>
              ))}
              {(project.history?.mission_runs.length ?? 0) === 0 ? <div className="text-sm text-dim">No mission runs yet.</div> : null}
            </div>
          </SectionCard>

          <SectionCard title="Planner Transcript" description="Planner internals are visible here, not on the main surface.">
            <div className="space-y-2">
              {(project.plans ?? []).map((plan) => (
                <article key={plan.plan_id} className="rounded-lg border border-border bg-surface px-3 py-3">
                  <div className="text-sm font-semibold text-text">{plan.name}</div>
                  <div className="mt-1 text-xs text-dim">Provider: {String(plan.planner_debug?.provider ?? '—')}</div>
                </article>
              ))}
            </div>
          </SectionCard>
        </div>
      ) : null}

      {currentSection === 'settings' ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <SectionCard title="Project Settings" description="Project metadata, related projects, and workspace defaults.">
            <div className="grid gap-3">
              <input
                className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan/40"
                value={editName}
                onChange={(event) => setEditName(event.target.value)}
                placeholder="Project name"
              />
              <textarea
                className="min-h-[120px] rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan/40"
                value={editGoal}
                onChange={(event) => setEditGoal(event.target.value)}
                placeholder="Project description"
              />
              <textarea
                className="min-h-[120px] rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm text-text outline-none focus:border-cyan/40"
                value={editWorkingDirectories}
                onChange={(event) => setEditWorkingDirectories(event.target.value)}
                placeholder="One working directory per line"
              />
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15"
                  onClick={handleSave}
                >
                  Save settings
                </button>
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
                  onClick={() => setEditing((value) => !value)}
                >
                  {editing ? 'Hide raw details' : 'Show raw details'}
                </button>
              </div>
              {editing ? (
                <pre className="overflow-x-auto rounded-lg border border-border bg-surface px-3 py-3 text-xs text-dim">
                  {JSON.stringify(project.project ?? {}, null, 2)}
                </pre>
              ) : null}
            </div>
          </SectionCard>

          <SectionCard title="Lifecycle" description="Archive or delete this project.">
            <div className="space-y-3">
              <Link
                className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card hover:no-underline"
                to={projectHistoryRoute(project.summary.project_id)}
              >
                Open history
              </Link>
              <Link
                className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card hover:no-underline"
                to={projectSettingsRoute(project.summary.project_id)}
              >
                Refresh settings
              </Link>
              <button
                type="button"
                className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
                onClick={handleArchiveToggle}
              >
                {project.lifecycle.archived ? 'Unarchive project' : 'Archive project'}
              </button>
              <button
                type="button"
                className="inline-flex items-center rounded-full border border-red/30 px-3 py-1.5 text-[11px] font-semibold text-red transition-colors hover:bg-red/10"
                disabled={!project.lifecycle.can_delete}
                onClick={() => setConfirmDeleteOpen(true)}
              >
                Delete project
              </button>
            </div>
          </SectionCard>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete project?"
        message="This removes the project container. It is only allowed when there are no plans left in the project."
        confirmLabel="Delete project"
        onCancel={() => setConfirmDeleteOpen(false)}
        onConfirm={() => {
          setConfirmDeleteOpen(false);
          void handleDelete();
        }}
      />
    </div>
  );
}
