import { useEffect, useMemo, useState } from 'react';
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import ProjectShellHeader from '../components/ProjectShellHeader';
import {
  approveProjectPlan,
  createProjectPlan,
  getProject,
  readjustProjectPlan,
  startProjectPlan,
} from '../lib/api';
import { useToast } from '../hooks/useToast';
import {
  PROJECTS_ROUTE,
  projectPlanRoute,
  type LabsConfig,
  type ProjectHarnessView,
  type ProjectPlanNodeView,
} from '../lib/types';

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

function computeLevels(nodes: ProjectPlanNodeView[]): Map<string, number> {
  const byId = new Map(nodes.map((node) => [node.node_id, node]));
  const levels = new Map<string, number>();

  const visit = (nodeId: string, seen = new Set<string>()): number => {
    if (levels.has(nodeId)) {
      return levels.get(nodeId) ?? 0;
    }
    const node = byId.get(nodeId);
    if (!node || seen.has(nodeId)) {
      return 0;
    }
    seen.add(nodeId);
    const deps = node.dependencies.filter((dependency) => byId.has(dependency));
    const level = deps.length === 0
      ? 0
      : 1 + Math.max(...deps.map((dependency) => visit(dependency, new Set(seen))));
    levels.set(nodeId, level);
    return level;
  };

  nodes.forEach((node) => {
    visit(node.node_id);
  });

  return levels;
}

function LoadingState() {
  return (
    <div className="space-y-4">
      <div className="animate-pulse rounded-lg border border-border bg-card px-4 py-4">
        <div className="h-5 w-56 rounded bg-surface" />
        <div className="mt-3 h-4 w-72 rounded bg-surface" />
        <div className="mt-4 grid gap-3 lg:grid-cols-[280px_minmax(0,1fr)_320px]">
          <div className="h-80 rounded bg-surface" />
          <div className="h-80 rounded bg-surface" />
          <div className="h-80 rounded bg-surface" />
        </div>
      </div>
    </div>
  );
}

export default function ProjectPlanPage({
  labs: _labs,
}: {
  labs?: LabsConfig;
}) {
  const { id } = useParams<{ id?: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { addToast } = useToast();
  const [project, setProject] = useState<ProjectHarnessView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [objective, setObjective] = useState('');
  const [planName, setPlanName] = useState('');
  const [quickTask, setQuickTask] = useState(false);
  const [actionPending, setActionPending] = useState<string | null>(null);

  const selectedPlanId = searchParams.get('plan');

  useEffect(() => {
    if (!id) {
      setProject(null);
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);
    getProject(id, { planId: selectedPlanId })
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
        setError(err instanceof Error ? err.message : 'Failed to load project workspace');
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [id, refreshIndex, selectedPlanId]);

  useEffect(() => {
    const firstNodeId = project?.selected_plan?.graph.nodes[0]?.node_id ?? null;
    setSelectedNodeId((current) => {
      if (current && project?.selected_plan?.graph.nodes.some((node) => node.node_id === current)) {
        return current;
      }
      return firstNodeId;
    });
  }, [project?.selected_plan?.plan_id, project?.selected_plan?.graph.nodes]);

  const selectedPlan = project?.selected_plan ?? null;
  const selectedNode = selectedPlan?.graph.nodes.find((node) => node.node_id === selectedNodeId) ?? null;
  const scheduler = project?.scheduler ?? null;

  const graphColumns = useMemo(() => {
    if (!selectedPlan) {
      return [] as Array<{ level: number; nodes: ProjectPlanNodeView[] }>;
    }
    const levels = computeLevels(selectedPlan.graph.nodes);
    const groups = new Map<number, ProjectPlanNodeView[]>();
    selectedPlan.graph.nodes.forEach((node) => {
      const level = levels.get(node.node_id) ?? 0;
      const list = groups.get(level) ?? [];
      list.push(node);
      groups.set(level, list);
    });
    return Array.from(groups.entries())
      .sort((left, right) => left[0] - right[0])
      .map(([level, nodes]) => ({ level, nodes }));
  }, [selectedPlan]);

  if (!id) {
    return <Navigate to={PROJECTS_ROUTE} replace />;
  }

  const refresh = () => {
    setRefreshIndex((value) => value + 1);
  };

  const handleSelectPlan = (planId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set('plan', planId);
    setSearchParams(next, { replace: true });
  };

  const handleCreatePlan = async () => {
    if (!objective.trim()) {
      addToast('Objective is required', 'error');
      return;
    }
    setActionPending('create');
    try {
      const created = await createProjectPlan(id, {
        name: planName.trim() || undefined,
        objective: objective.trim(),
        quick_task: quickTask,
      });
      addToast(quickTask ? 'Quick task created' : 'Plan created', 'success');
      setObjective('');
      setPlanName('');
      setQuickTask(false);
      navigate(`${projectPlanRoute(id)}?plan=${encodeURIComponent(created.plan_id)}`);
      refresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed to create plan', 'error');
    } finally {
      setActionPending(null);
    }
  };

  const handleApprove = async () => {
    if (!selectedPlan) {
      return;
    }
    setActionPending('approve');
    try {
      await approveProjectPlan(selectedPlan.plan_id);
      addToast('Plan version approved', 'success');
      refresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed to approve plan', 'error');
    } finally {
      setActionPending(null);
    }
  };

  const handleStart = async () => {
    if (!selectedPlan) {
      return;
    }
    setActionPending('start');
    try {
      await startProjectPlan(selectedPlan.plan_id);
      addToast('Mission run started', 'success');
      refresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed to start plan', 'error');
    } finally {
      setActionPending(null);
    }
  };

  const handleReadjust = async () => {
    if (!selectedPlan) {
      return;
    }
    setActionPending('readjust');
    try {
      const created = await readjustProjectPlan(selectedPlan.plan_id);
      addToast('Readjusted plan created', 'success');
      navigate(`${projectPlanRoute(id)}?plan=${encodeURIComponent(created.plan_id)}`);
      refresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Failed to readjust plan', 'error');
    } finally {
      setActionPending(null);
    }
  };

  if (loading) {
    return <LoadingState />;
  }

  if (error || !project) {
    return (
      <section className="rounded-lg border border-red/30 bg-red-bg/20 px-4 py-5">
        <div className="text-sm font-semibold text-red">Unable to load plan workspace</div>
        <p className="mt-1 text-sm text-dim">{error ?? 'Project not found'}</p>
      </section>
    );
  }

  return (
    <div className="grid gap-4">
      <ProjectShellHeader summary={project.summary} section="plan" />

      <section className="rounded-lg border border-border bg-card px-4 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">New plan</div>
            <h2 className="mt-1 text-xl font-semibold text-text">Intent to DAG</h2>
            <p className="mt-1 max-w-[64ch] text-sm text-dim">
              Draft a new plan directly inside this project. Quick tasks become one-node plans automatically.
            </p>
          </div>
          <button
            type="button"
            className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={actionPending === 'create'}
            onClick={handleCreatePlan}
          >
            {actionPending === 'create' ? 'Creating…' : quickTask ? 'Create quick task' : 'Create plan'}
          </button>
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-[240px_minmax(0,1fr)_140px]">
          <input
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan/40"
            placeholder="Optional plan name"
            value={planName}
            onChange={(event) => setPlanName(event.target.value)}
          />
          <textarea
            className="min-h-[88px] rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan/40"
            placeholder="Describe the project outcome or quick task"
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
          />
          <label className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text">
            <input type="checkbox" checked={quickTask} onChange={(event) => setQuickTask(event.target.checked)} />
            Quick task
          </label>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)_320px]">
        <aside className="space-y-4">
          <section className="rounded-lg border border-border bg-card px-4 py-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">Plan portfolio</div>
            <div className="mt-3 space-y-2">
              {(project.plans ?? []).map((plan) => {
                const selected = plan.plan_id === selectedPlan?.plan_id;
                return (
                  <button
                    key={plan.plan_id}
                    type="button"
                    className={[
                      'w-full rounded-lg border px-3 py-3 text-left transition-colors',
                      selected
                        ? 'border-cyan/30 bg-cyan/10'
                        : 'border-border bg-surface hover:border-border-lit hover:bg-card',
                    ].join(' ')}
                    onClick={() => handleSelectPlan(plan.plan_id)}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="text-sm font-semibold text-text">{plan.name}</div>
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${statusTone(plan.status)}`}>
                        {formatLabel(plan.status)}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-dim">{plan.objective}</div>
                    <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-dim">
                      <span>{plan.node_count} node{plan.node_count === 1 ? '' : 's'}</span>
                      <span>{plan.quick_task ? 'Quick task' : 'Plan DAG'}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="rounded-lg border border-border bg-card px-4 py-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">Scheduler queue</div>
            <div className="mt-3 space-y-2 text-sm text-text">
              <div className="rounded-lg border border-border bg-surface px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Ready nodes</div>
                <div className="mt-1 text-lg font-semibold">{scheduler?.queue.length ?? 0}</div>
              </div>
              <div className="rounded-lg border border-border bg-surface px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Running reservations</div>
                <div className="mt-1 text-lg font-semibold">{scheduler?.running.length ?? 0}</div>
              </div>
              <div className="rounded-lg border border-border bg-surface px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Blocked nodes</div>
                <div className="mt-1 text-lg font-semibold">{scheduler?.blocked.length ?? 0}</div>
              </div>
            </div>
          </section>
        </aside>

        <section className="rounded-lg border border-border bg-card px-4 py-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">Plan workspace</div>
              <h2 className="mt-1 text-2xl font-semibold text-text">{selectedPlan?.name ?? 'No plan selected'}</h2>
              <p className="mt-1 max-w-[64ch] text-sm text-dim">{selectedPlan?.objective ?? 'Select a plan from the portfolio to inspect its DAG.'}</p>
            </div>
            {selectedPlan ? (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={actionPending !== null}
                  onClick={handleApprove}
                >
                  {actionPending === 'approve' ? 'Approving…' : selectedPlan.selected_version_id ? 'Re-approve version' : 'Approve version'}
                </button>
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={actionPending !== null || !selectedPlan.selected_version_id}
                  onClick={handleStart}
                >
                  {actionPending === 'start' ? 'Starting…' : 'Start mission overlay'}
                </button>
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={actionPending !== null}
                  onClick={handleReadjust}
                >
                  {actionPending === 'readjust' ? 'Creating…' : 'Readjust plan'}
                </button>
              </div>
            ) : null}
          </div>

          {selectedPlan ? (
            <>
              <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-dim">
                <span className={`inline-flex items-center rounded-full border px-2 py-0.5 font-semibold uppercase tracking-[0.08em] ${statusTone(selectedPlan.status)}`}>
                  {formatLabel(selectedPlan.status)}
                </span>
                <span className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5">
                  {selectedPlan.quick_task ? 'Quick task' : 'Plan DAG'}
                </span>
                <span className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5">
                  {selectedPlan.graph.nodes.length} nodes
                </span>
                <span className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5">
                  Version {selectedPlan.selected_version_id?.slice(-8) ?? 'draft'}
                </span>
              </div>

              <div className="mt-4 overflow-x-auto">
                <div className="flex min-w-max gap-4 pb-2">
                  {graphColumns.map((column) => (
                    <div key={column.level} className="w-[260px] shrink-0 space-y-3">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">
                        Stage {column.level + 1}
                      </div>
                      {column.nodes.map((node) => {
                        const selected = node.node_id === selectedNode?.node_id;
                        return (
                          <button
                            key={node.node_id}
                            type="button"
                            className={[
                              'w-full rounded-xl border px-3 py-3 text-left transition-colors',
                              selected
                                ? 'border-cyan/30 bg-cyan/10'
                                : 'border-border bg-surface hover:border-border-lit hover:bg-card',
                            ].join(' ')}
                            onClick={() => setSelectedNodeId(node.node_id)}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="text-sm font-semibold text-text">{node.title}</div>
                              <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${statusTone(node.runtime.status)}`}>
                                {formatLabel(node.runtime.status)}
                              </span>
                            </div>
                            <div className="mt-2 text-xs text-dim">{node.description}</div>
                            <div className="mt-3 grid gap-2 text-[11px] text-dim">
                              <div>{node.dependencies.length} deps</div>
                              <div>{node.subtasks.length} subtasks</div>
                              <div>{node.touch_scope.length} touch scope</div>
                              <div>{node.merged_project_scope.length} project scope</div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>
            </>
          ) : (
            <div className="mt-4 rounded-lg border border-border bg-surface px-4 py-8 text-sm text-dim">
              No plan selected yet.
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <section className="rounded-lg border border-border bg-card px-4 py-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">Node drawer</div>
            {selectedNode ? (
              <div className="mt-3 space-y-4">
                <div>
                  <h3 className="text-lg font-semibold text-text">{selectedNode.title}</h3>
                  <p className="mt-1 text-sm text-dim">{selectedNode.description}</p>
                </div>
                <div className="grid gap-3">
                  <div className="rounded-lg border border-border bg-surface px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Runtime</div>
                    <div className="mt-1 text-sm text-text">{formatLabel(selectedNode.runtime.status)}</div>
                    <div className="mt-1 text-xs text-dim">{selectedNode.runtime.reason ?? 'Ready for scheduler evaluation.'}</div>
                  </div>
                  <div className="rounded-lg border border-border bg-surface px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Subtasks</div>
                    <ul className="mt-2 space-y-1 text-sm text-text">
                      {selectedNode.subtasks.length > 0 ? selectedNode.subtasks.map((subtask) => (
                        <li key={subtask}>{subtask}</li>
                      )) : <li>—</li>}
                    </ul>
                  </div>
                  <div className="rounded-lg border border-border bg-surface px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Touch scope</div>
                    <ul className="mt-2 space-y-1 text-sm text-text">
                      {selectedNode.touch_scope.length > 0 ? selectedNode.touch_scope.map((scope) => (
                        <li key={scope} className="break-all">{scope}</li>
                      )) : <li>—</li>}
                    </ul>
                  </div>
                  <div className="rounded-lg border border-border bg-surface px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Outputs and evidence</div>
                    <div className="mt-2 text-sm text-text">Outputs: {selectedNode.outputs.length || 0}</div>
                    <div className="mt-1 text-sm text-text">Evidence: {selectedNode.evidence.length || 0}</div>
                    <div className="mt-1 text-xs text-dim">Owner project: {selectedNode.owner_project_id || project.summary.project_id}</div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-3 text-sm text-dim">Select a node to inspect its subtasks, touch scope, and runtime.</div>
            )}
          </section>

          <section className="rounded-lg border border-border bg-card px-4 py-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">History / Debug</div>
            <div className="mt-3 space-y-3 text-sm text-text">
              <div className="rounded-lg border border-border bg-surface px-3 py-3">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Versions</div>
                <div className="mt-1 text-lg font-semibold">{selectedPlan?.history.versions.length ?? 0}</div>
              </div>
              <div className="rounded-lg border border-border bg-surface px-3 py-3">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Mission runs</div>
                <div className="mt-1 text-lg font-semibold">{selectedPlan?.history.mission_runs.length ?? 0}</div>
              </div>
              <div className="rounded-lg border border-border bg-surface px-3 py-3">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Planner provider</div>
                <div className="mt-1">{String(selectedPlan?.planner_debug?.provider ?? '—')}</div>
              </div>
              <div className="rounded-lg border border-border bg-surface px-3 py-3">
                <div className="text-[10px] uppercase tracking-[0.08em] text-muted">Latest mission update</div>
                <div className="mt-1">{formatTimestamp(selectedPlan?.history.mission_runs[0]?.updated_at)}</div>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
