import { useEffect, useState, type ReactNode } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import ConfirmDialog from '../components/ConfirmDialog';
import ProjectShellHeader from '../components/ProjectShellHeader';
import {
  archiveProject,
  deleteProject,
  getMission,
  getPlanDraft,
  getProject,
  unarchiveProject,
  updateProject,
} from '../lib/api';
import { useToast } from '../hooks/useToast';
import {
  PROJECTS_ROUTE,
  projectMissionRoute,
  projectPlanRoute,
  projectOverviewRoute,
  type MissionDraft,
  type MissionState,
  type PlanRun,
  type ProjectCycleView,
  type ProjectHarnessView,
  type ProjectSection,
} from '../lib/types';

const ALLOWED_SECTIONS = new Set<ProjectSection>(['overview', 'history', 'settings']);

const PROJECT_STATUS_CLASSES: Record<ProjectCycleView['status'], string> = {
  planning: 'text-amber border-amber/30 bg-amber/10',
  ready: 'text-teal border-teal/30 bg-teal/10',
  running: 'text-cyan border-cyan/30 bg-cyan/10',
  blocked: 'text-red border-red/30 bg-red/10',
  completed: 'text-green border-green/30 bg-green/10',
  archived: 'text-dim border-border bg-surface',
  idle: 'text-dim border-border bg-surface',
};

function formatLabel(value: string | null | undefined): string {
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

function badgeClassName(status: ProjectCycleView['status']): string {
  return PROJECT_STATUS_CLASSES[status];
}

function LoadingState() {
  return (
    <div aria-label="Loading project" className="space-y-4">
      <div className="animate-pulse rounded-lg border border-border bg-card px-4 py-4">
        <div className="h-5 w-48 rounded bg-surface" />
        <div className="mt-3 h-4 w-72 rounded bg-surface" />
        <div className="mt-5 grid gap-3 md:grid-cols-3">
          <div className="h-14 rounded bg-surface" />
          <div className="h-14 rounded bg-surface" />
          <div className="h-14 rounded bg-surface" />
        </div>
      </div>
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section role="alert" className="rounded-lg border border-red/30 bg-red-bg/20 px-4 py-5">
      <div className="text-sm font-semibold text-red">Unable to load project</div>
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

function ValueCard({ label, value }: { label: string; value: string }) {
  return (
    <article className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">{label}</div>
      <div className="mt-1 break-words text-[13px] text-text">{value}</div>
    </article>
  );
}

function ListCard({ label, items, emptyLabel = '—' }: { label: string; items: string[]; emptyLabel?: string }) {
  return (
    <article className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">{label}</div>
      {items.length > 0 ? (
        <ul className="mt-2 grid gap-1 text-[13px] text-text">
          {items.map((item) => (
            <li key={item} className="break-words">{item}</li>
          ))}
        </ul>
      ) : (
        <div className="mt-1 text-[13px] text-text">{emptyLabel}</div>
      )}
    </article>
  );
}

function SectionCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-card px-4 py-4">
      <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">{title}</div>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function latestPlanRun(draft: MissionDraft | null): PlanRun | null {
  if (!draft?.plan_runs?.length) {
    return null;
  }
  return draft.plan_runs[0] ?? null;
}

function missionProgress(mission: MissionState | null): string {
  if (!mission) {
    return '—';
  }
  const approved = Object.values(mission.task_states).filter((task) => task.status === 'review_approved').length;
  return `${approved}/${mission.spec.tasks.length} tasks approved`;
}

function activeTaskTitle(mission: MissionState | null): string {
  if (!mission) {
    return '—';
  }
  const activeTask = Object.values(mission.task_states).find((task) => (
    task.status === 'in_progress' || task.status === 'reviewing'
  ));
  if (!activeTask) {
    return '—';
  }
  return mission.spec.tasks.find((task) => task.id === activeTask.task_id)?.title || activeTask.task_id;
}

function cycleLabel(index: number): string {
  return `Plan ${index + 1}`;
}

function historyLabel(cycle: ProjectCycleView, index: number): string {
  if (cycle.mission_id && cycle.successor_cycle_id) {
    return `${cycleLabel(index)} · Mission completed · Replan followed`;
  }
  if (cycle.mission_id) {
    return `${cycleLabel(index)} · Mission launched`;
  }
  return `${cycleLabel(index)} · Planning`;
}

function HistoryCard({ cycle, index }: { cycle: ProjectCycleView; index: number }) {
  return (
    <article className="rounded-lg border border-border bg-card px-4 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[14px] font-semibold text-text">{historyLabel(cycle, index)}</h3>
        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${badgeClassName(cycle.status)}`}>
          {formatLabel(cycle.status)}
        </span>
        <span className="ml-auto font-mono text-[11px] text-dim">
          Updated {formatTimestamp(cycle.updated_at)}
        </span>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <ValueCard label="Plan draft" value={cycle.draft_id?.trim() || '—'} />
        <ValueCard label="Mission" value={cycle.mission_id?.trim() || '—'} />
        <ValueCard label="Blocker" value={cycle.blocker?.trim() || '—'} />
        <ValueCard label="Next action" value={cycle.next_action?.trim() || '—'} />
      </div>
    </article>
  );
}

export default function ProjectDetailPage() {
  const { id, section } = useParams<{ id?: string; section?: ProjectSection }>();
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [project, setProject] = useState<ProjectHarnessView | null>(null);
  const [draft, setDraft] = useState<MissionDraft | null>(null);
  const [mission, setMission] = useState<MissionState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editGoal, setEditGoal] = useState('');
  const [editWorkingDirectories, setEditWorkingDirectories] = useState('');
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  useEffect(() => {
    if (!id) {
      setLoading(false);
      setProject(null);
      return;
    }

    let active = true;
    setLoading(true);

    getProject(id)
      .then((fetchedProject) => {
        if (!active) {
          return;
        }

        setProject(fetchedProject);
        setDraft(null);
        setMission(null);
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
    const activeCycle = project.active_cycle ?? project.cycles.find((cycle) => cycle.cycle_id === project.active_cycle_id) ?? null;
    if (!activeCycle) {
      setDraft(null);
      setMission(null);
      return;
    }

    let active = true;
    setDetailError(null);

    void Promise.allSettled([
      activeCycle.draft_id ? getPlanDraft(activeCycle.draft_id) : Promise.resolve(null),
      activeCycle.mission_id ? getMission(activeCycle.mission_id) : Promise.resolve(null),
    ]).then(([draftResult, missionResult]) => {
      if (!active) {
        return;
      }

      if (draftResult.status === 'fulfilled') {
        setDraft(draftResult.value);
      } else if (activeCycle.draft_id) {
        setDetailError(draftResult.reason instanceof Error ? draftResult.reason.message : 'Failed to load plan details');
      }

      if (missionResult.status === 'fulfilled') {
        setMission(missionResult.value);
      } else if (activeCycle.mission_id) {
        setDetailError(missionResult.reason instanceof Error ? missionResult.reason.message : 'Failed to load mission details');
      }
    });

    return () => {
      active = false;
    };
  }, [project]);

  useEffect(() => {
    if (!project) {
      return;
    }
    setEditName(project.summary.name);
    setEditGoal(project.context.goal ?? '');
    setEditWorkingDirectories(project.context.working_directories.join('\n'));
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

  const handleSave = async (): Promise<void> => {
    if (!id) {
      return;
    }
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
      addToast('Project updated', 'success');
    } catch (saveError) {
      addToast(saveError instanceof Error ? saveError.message : 'Failed to update project', 'error');
    }
  };

  const handleArchiveToggle = async (): Promise<void> => {
    if (!id || !project) {
      return;
    }
    try {
      if (project.lifecycle.archived) {
        await unarchiveProject(id);
        addToast('Project unarchived', 'success');
      } else {
        await archiveProject(id);
        addToast('Project archived', 'info');
      }
      refresh();
    } catch (archiveError) {
      addToast(archiveError instanceof Error ? archiveError.message : 'Failed to update archive state', 'error');
    }
  };

  const handleDelete = async (): Promise<void> => {
    if (!id) {
      return;
    }
    try {
      await deleteProject(id);
      addToast('Project deleted', 'info');
      navigate(PROJECTS_ROUTE);
    } catch (deleteError) {
      addToast(deleteError instanceof Error ? deleteError.message : 'Failed to delete project', 'error');
    } finally {
      setConfirmDeleteOpen(false);
    }
  };

  if (loading) {
    return <LoadingState />;
  }

  if (error) {
    return <ErrorState message={error} onRetry={refresh} />;
  }

  if (!project) {
    return <Navigate to={PROJECTS_ROUTE} replace />;
  }

  const summary = project.summary;
  const activeCycle = project.active_cycle ?? project.cycles.find((cycle) => cycle.cycle_id === project.active_cycle_id) ?? null;
  const evidence = project.evidence;
  const context = project.context;
  const implementedDocs = project.docs_status.implemented.length > 0 ? project.docs_status.implemented.join(', ') : 'None';
  const plannedDocs = project.docs_status.planned.length > 0 ? project.docs_status.planned.join(', ') : 'None';
  const activePlanRun = latestPlanRun(draft);

  return (
    <div className="grid gap-4">
      <ProjectShellHeader summary={summary} section={currentSection} />

      {project.lifecycle.archived ? (
        <section className="rounded-lg border border-border bg-surface px-4 py-3 text-sm text-dim">
          This project is archived. It stays readable, but it is hidden from the default Projects list until unarchived.
        </section>
      ) : null}

      {detailError ? (
        <section className="rounded-lg border border-amber/30 bg-amber/10 px-4 py-3 text-sm text-amber">
          {detailError}
        </section>
      ) : null}

      {currentSection === 'overview' ? (
        <div className="grid gap-4">
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <ValueCard label="Project stage" value={formatLabel(summary.current_stage)} />
            <ValueCard label="Project blocker" value={summary.blocker?.trim() || '—'} />
            <ValueCard label="Current plan" value={summary.current_plan_id?.trim() || activeCycle?.draft_id?.trim() || '—'} />
            <ValueCard label="Current mission" value={summary.current_mission_id?.trim() || activeCycle?.mission_id?.trim() || '—'} />
          </section>

          <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
            <div className="grid gap-4">
              <SectionCard title="Project Context">
                <div className="grid gap-3">
                  <ValueCard label="Goal" value={context.goal?.trim() || '—'} />
                  <ListCard label="Definition of done" items={context.definition_of_done} />
                  <ListCard label="Working directories" items={context.working_directories} emptyLabel={summary.repo_root} />
                  <ListCard label="Task preview" items={context.task_titles.slice(0, 6)} emptyLabel="No planned tasks yet" />
                </div>
              </SectionCard>

              <SectionCard title="Current Plan">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  <ValueCard label="Plan draft" value={activeCycle?.draft_id?.trim() || '—'} />
                  <ValueCard label="Plan status" value={draft?.status ? formatLabel(draft.status) : 'No plan loaded'} />
                  <ValueCard label="Plan run" value={activePlanRun?.status ? formatLabel(activePlanRun.status) : 'No run yet'} />
                  <ValueCard label="Plan step" value={activePlanRun?.current_step ? formatLabel(activePlanRun.current_step) : '—'} />
                  <ValueCard label="Planned tasks" value={draft ? String(draft.draft_spec.tasks.length) : String(context.planned_task_count)} />
                  <ValueCard label="Preflight" value={draft?.preflight_status ? formatLabel(draft.preflight_status) : '—'} />
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Link
                    className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 hover:no-underline"
                    to={projectPlanRoute(summary.project_id)}
                  >
                    {summary.current_plan_id || activeCycle?.draft_id ? 'Continue plan' : 'Start plan'}
                  </Link>
                  {summary.current_mission_id || activeCycle?.mission_id ? (
                    <Link
                      className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card hover:no-underline"
                      to={projectMissionRoute(summary.project_id)}
                    >
                      Open mission
                    </Link>
                  ) : null}
                </div>
              </SectionCard>
            </div>

            <div className="grid gap-4">
              <SectionCard title="Now">
                <div className="grid gap-3">
                  <ValueCard label="Next action" value={summary.next_action_label?.trim() || summary.next_action?.trim() || '—'} />
                  <ValueCard label="Mission progress" value={missionProgress(mission)} />
                  <ValueCard label="Active task" value={activeTaskTitle(mission)} />
                  <ValueCard label="Planning policy" value={formatLabel(project.policy_summary.mode)} />
                </div>
              </SectionCard>

              <SectionCard title="Evidence">
                <div className="grid gap-3">
                  <ValueCard label="Contract" value={evidence.contract_summary?.trim() || '—'} />
                  <ValueCard label="Verifier" value={evidence.verifier_summary?.trim() || '—'} />
                  <ValueCard label="Artifacts" value={evidence.artifact_summary?.trim() || '—'} />
                  <ValueCard label="Stream" value={evidence.stream_summary?.trim() || '—'} />
                  <ValueCard label="Docs implemented" value={implementedDocs} />
                  <ValueCard label="Docs planned" value={plannedDocs} />
                </div>
              </SectionCard>
            </div>
          </div>
        </div>
      ) : null}

      {currentSection === 'history' ? (
        <SectionCard title="Project History">
          <div className="grid gap-3">
            {project.cycles.length > 0 ? (
              project.cycles.map((cycle, index) => (
                <HistoryCard key={cycle.cycle_id} cycle={cycle} index={index} />
              ))
            ) : (
              <div className="rounded-lg border border-border bg-surface px-4 py-3 text-sm text-dim">
                No plans or missions have been recorded for this project yet.
              </div>
            )}
          </div>
        </SectionCard>
      ) : null}

      {currentSection === 'settings' ? (
        <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <SectionCard title="Project Settings">
            <div className="grid gap-3">
              <label className="grid gap-1 text-sm text-text">
                <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Name</span>
                <input className="rounded border border-border bg-surface px-3 py-2 text-sm" value={editName} onChange={(event) => setEditName(event.target.value)} />
              </label>
              <label className="grid gap-1 text-sm text-text">
                <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Goal</span>
                <textarea className="min-h-20 rounded border border-border bg-surface px-3 py-2 text-sm" value={editGoal} onChange={(event) => setEditGoal(event.target.value)} />
              </label>
              <label className="grid gap-1 text-sm text-text">
                <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Working directories</span>
                <textarea className="min-h-24 rounded border border-border bg-surface px-3 py-2 font-mono text-sm" value={editWorkingDirectories} onChange={(event) => setEditWorkingDirectories(event.target.value)} />
              </label>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15"
                  onClick={() => { void handleSave(); }}
                >
                  Save project
                </button>
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
                  onClick={() => {
                    setEditName(project.summary.name);
                    setEditGoal(project.context.goal ?? '');
                    setEditWorkingDirectories(project.context.working_directories.join('\n'));
                    setEditing(false);
                  }}
                >
                  Reset
                </button>
              </div>
            </div>
          </SectionCard>

          <SectionCard title="Lifecycle">
            <div className="grid gap-3">
              <ValueCard label="Archive state" value={project.lifecycle.archived ? 'Archived' : 'Active'} />
              <ValueCard label="Can delete" value={project.lifecycle.can_delete ? 'Yes' : 'No'} />
              <ValueCard label="Has activity" value={project.lifecycle.has_activity ? 'Yes' : 'No'} />
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
                  onClick={() => { void handleArchiveToggle(); }}
                >
                  {project.lifecycle.archived ? 'Unarchive project' : 'Archive project'}
                </button>
                {project.lifecycle.can_delete ? (
                  <button
                    type="button"
                    className="inline-flex items-center rounded-full border border-red/30 bg-red-bg/20 px-3 py-1.5 text-[11px] font-semibold text-red transition-colors hover:bg-red-bg/30"
                    onClick={() => setConfirmDeleteOpen(true)}
                  >
                    Delete project
                  </button>
                ) : null}
              </div>
            </div>
          </SectionCard>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmDeleteOpen}
        title={`Delete project "${summary.name}"?`}
        message="This permanently removes the project record. This is only allowed for projects without draft or mission history."
        confirmLabel="Delete project"
        variant="danger"
        onCancel={() => setConfirmDeleteOpen(false)}
        onConfirm={() => { void handleDelete(); }}
      />
    </div>
  );
}
