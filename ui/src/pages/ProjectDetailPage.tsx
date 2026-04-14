import { useEffect, useState, type ReactNode } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import ConfirmDialog from '../components/ConfirmDialog';
import { archiveProject, deleteProject, getMission, getPlanDraft, getProject, unarchiveProject, updateProject } from '../lib/api';
import { useToast } from '../hooks/useToast';
import {
  PROJECTS_ROUTE,
  type MissionDraft,
  type MissionState,
  type PlanRun,
  type ProjectHarnessView,
  type ProjectCycleView,
} from '../lib/types';

const PROJECT_STATUS_CLASSES: Record<ProjectCycleView['status'], string> = {
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
      <div className="mt-1 text-[13px] text-text">{value}</div>
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

function CycleCard({ cycle }: { cycle: ProjectCycleView }) {
  const blocker = cycle.blocker?.trim() || '—';
  const nextAction = cycle.next_action?.trim() || '—';

  return (
    <article className="rounded-lg border border-border bg-card px-4 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[14px] font-semibold text-text">{cycle.title}</h3>
        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${badgeClassName(cycle.status)}`}>
          {formatLabel(cycle.status)}
        </span>
        <span className="ml-auto font-mono text-[11px] text-dim">
          Updated {formatTimestamp(cycle.updated_at)}
        </span>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <ValueCard label="Draft" value={cycle.draft_id?.trim() || '—'} />
        <ValueCard label="Mission" value={cycle.mission_id?.trim() || '—'} />
        <ValueCard label="Blocker" value={blocker} />
        <ValueCard label="Next action" value={nextAction} />
      </div>
    </article>
  );
}

function CockpitSection({ title, children }: { title: string; children: ReactNode }) {
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

export default function ProjectDetailPage() {
  const { id } = useParams();
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
        setDetailError(draftResult.reason instanceof Error ? draftResult.reason.message : 'Failed to load draft details');
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
  const implementedDocs = project.docs_status.implemented.length > 0
    ? project.docs_status.implemented.join(', ')
    : 'None';
  const plannedDocs = project.docs_status.planned.length > 0
    ? project.docs_status.planned.join(', ')
    : 'None';
  const policyMode = formatLabel(project.policy_summary.mode);
  const evidence = project.evidence;
  const context = project.context;
  const primaryWorkingDirectory = context.primary_working_directory?.trim() || summary.repo_root;
  const planningFocused = summary.status === 'planning' || summary.status === 'ready';

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">Project Harness</div>
          <h1 className="text-3xl font-semibold tracking-tight">{summary.name}</h1>
          <p className="mt-1 text-sm text-dim font-mono">{summary.repo_root}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {project.lifecycle.can_edit ? (
            <button
              type="button"
              className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
              onClick={() => setEditing((value) => !value)}
            >
              {editing ? 'Close edit' : 'Edit project'}
            </button>
          ) : null}
          <button
            type="button"
            className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
            onClick={() => { void handleArchiveToggle(); }}
          >
            {project.lifecycle.archived ? 'Unarchive' : 'Archive'}
          </button>
          {project.lifecycle.can_delete ? (
            <button
              type="button"
              className="inline-flex items-center rounded-full border border-red/30 bg-red-bg/20 px-3 py-1.5 text-[11px] font-semibold text-red transition-colors hover:bg-red-bg/30"
              onClick={() => setConfirmDeleteOpen(true)}
            >
              Delete
            </button>
          ) : null}
          <Link
            className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 hover:no-underline"
            to={PROJECTS_ROUTE}
          >
            Back to Projects
          </Link>
          <button
            type="button"
            className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
            onClick={refresh}
          >
            Refresh
          </button>
        </div>
      </header>

      {project.lifecycle.archived ? (
        <section className="rounded-lg border border-border bg-surface px-4 py-3 text-sm text-dim">
          This project is archived. It stays readable, but it is hidden from the default Projects list until unarchived.
        </section>
      ) : null}

      {editing ? (
        <section className="rounded-lg border border-border bg-card px-4 py-4">
          <div className="text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">Edit project</div>
          <div className="mt-3 grid gap-3">
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
                Save changes
              </button>
              <button
                type="button"
                className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card"
                onClick={() => setEditing(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </section>
      ) : null}

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <ValueCard label="Status" value={formatLabel(summary.status)} />
        <ValueCard label="Working directory" value={primaryWorkingDirectory} />
        <ValueCard label="Planned tasks" value={String(context.planned_task_count)} />
        <ValueCard label="Updated" value={formatTimestamp(summary.updated_at)} />
        <ValueCard label="Active mission" value={summary.active_mission_id?.trim() || '—'} />
      </section>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="grid gap-4">
          <CockpitSection title="Project Context">
            <div className="grid gap-3">
              <ValueCard label="Planning focus" value={planningFocused ? 'Planning stays primary' : 'Mission progress stays primary'} />
              <ValueCard label="Goal" value={context.goal?.trim() || '—'} />
              <ListCard label="Definition of done" items={context.definition_of_done} />
              <ListCard label="Working directories" items={context.working_directories} emptyLabel={summary.repo_root} />
              <ListCard label="Task preview" items={context.task_titles.slice(0, 6)} emptyLabel="No planned tasks yet" />
            </div>
          </CockpitSection>

          <CockpitSection title="Plan">
            <div className="grid gap-3">
              <ValueCard label="Draft" value={activeCycle?.draft_id?.trim() || '—'} />
              <ValueCard label="Draft status" value={draft?.status ? formatLabel(draft.status) : '—'} />
              <ValueCard label="Plan run" value={latestPlanRun(draft)?.status ? formatLabel(latestPlanRun(draft)?.status || '') : activeCycle?.latest_plan_run_id?.trim() || '—'} />
              <ValueCard label="Plan step" value={latestPlanRun(draft)?.current_step ? formatLabel(latestPlanRun(draft)?.current_step || '') : '—'} />
              <ValueCard label="Plan version" value={activeCycle?.latest_plan_version_id?.trim() || '—'} />
              <ValueCard label="Planned tasks" value={draft ? String(draft.draft_spec.tasks.length) : String(context.planned_task_count)} />
              <ValueCard label="Preflight" value={draft?.preflight_status ? formatLabel(draft.preflight_status) : '—'} />
              {activeCycle?.draft_id ? (
                <Link
                  className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 hover:no-underline"
                  to={`/plan/${activeCycle.draft_id}`}
                >
                  Open Plan
                </Link>
              ) : (
                <Link
                  className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 hover:no-underline"
                  to="/plan"
                >
                  Start Planning
                </Link>
              )}
            </div>
          </CockpitSection>

          <CockpitSection title="Now">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <ValueCard label="Status" value={formatLabel(summary.status)} />
              <ValueCard label="Blocker" value={summary.blocker?.trim() || '—'} />
              <ValueCard label="Mode" value={policyMode} />
            </div>
          </CockpitSection>

          <CockpitSection title="Next">
            <div className="grid gap-3 md:grid-cols-2">
              <ValueCard label="Next action" value={summary.next_action?.trim() || '—'} />
              <ValueCard label="Active cycle" value={summary.active_cycle_id?.trim() || '—'} />
            </div>
          </CockpitSection>

          <CockpitSection title="Evidence">
            <div className="grid gap-3 md:grid-cols-2">
              <ValueCard label="Contract" value={evidence.contract_summary?.trim() || '—'} />
              <ValueCard label="Verifier" value={evidence.verifier_summary?.trim() || '—'} />
              <ValueCard label="Artifacts" value={evidence.artifact_summary?.trim() || '—'} />
              <ValueCard label="Stream" value={evidence.stream_summary?.trim() || '—'} />
              <ValueCard label="Docs implemented" value={implementedDocs} />
              <ValueCard label="Docs planned" value={plannedDocs} />
            </div>
            <div className="mt-3 text-[12px] text-dim">
              Optimize available: {project.policy_summary.optimize_available ? 'yes' : 'no'}
              {' · '}
              Derived policy: {project.policy_summary.derived ? 'yes' : 'no'}
            </div>
          </CockpitSection>
        </div>

        <div className="grid gap-4">
          <CockpitSection title="Current Cycle">
            <div className="grid gap-3">
              <ValueCard label="Active cycle" value={summary.active_cycle_id?.trim() || '—'} />
              <ValueCard label="Cycle status" value={activeCycle ? formatLabel(activeCycle.status) : '—'} />
              <ValueCard label="Blocker" value={activeCycle?.blocker?.trim() || '—'} />
              <ValueCard label="Next action" value={activeCycle?.next_action?.trim() || '—'} />
            </div>
          </CockpitSection>

          <CockpitSection title="Missions">
            <div className="grid gap-3">
              <ValueCard label="Mission" value={activeCycle?.mission_id?.trim() || '—'} />
              <ValueCard label="Mission progress" value={missionProgress(mission)} />
              <ValueCard label="Active task" value={activeTaskTitle(mission)} />
              <ValueCard label="Retries" value={mission ? String(mission.total_retries) : '—'} />
              {activeCycle?.mission_id ? (
                <div className="flex flex-wrap gap-2">
                  <Link
                    className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card hover:no-underline"
                    to={`/mission/${activeCycle.mission_id}`}
                  >
                    Open Mission
                  </Link>
                  <Link
                    className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card hover:no-underline"
                    to="/missions"
                  >
                    Mission fleet view
                  </Link>
                </div>
              ) : (
                <div className="text-[12px] text-dim">
                  Missions appear here after launch. Keep planning inside this project until the cycle is ready.
                </div>
              )}
            </div>
          </CockpitSection>
        </div>
      </div>

      {detailError ? (
        <section className="rounded-lg border border-amber/30 bg-amber/10 px-4 py-3 text-sm text-amber">
          {detailError}
        </section>
      ) : null}

      <CockpitSection title="History">
        <div className="grid gap-3">
          {activeCycle ? <CycleCard cycle={activeCycle} /> : <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-dim">No active cycle yet.</div>}
          {project.cycles.length > 1 ? (
            <div className="grid gap-3">
              {project.cycles
                .filter((cycle) => cycle.cycle_id !== activeCycle?.cycle_id)
                .map((cycle) => (
                  <CycleCard key={cycle.cycle_id} cycle={cycle} />
                ))}
            </div>
          ) : null}
        </div>
      </CockpitSection>

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
