import { Link, useNavigate, useParams } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import ConfirmDialog from "../components/ConfirmDialog";
import Breadcrumb from "../components/Breadcrumb";
import ExecutionProfileSelect from "../components/ExecutionProfileSelect";
import EventLogTable from "../components/EventLogTable";
import StatusBadge from "../components/StatusBadge";
import TokenMeter from "../components/TokenMeter";
import { createReadjustedDraft, finishMission, getModels, restartMission, stopMission, troubleshootMission, updateMissionDefaultModels } from "../lib/api";
import { useMission } from "../hooks/useMission";
import { useToast } from "../hooks/useToast";
import SpaceProgress from "../components/SpaceProgress";
import { executionProfileFromOption, optionIdFromExecutionProfile } from "../lib/executionProfiles";
import {
  projectHistoryRoute,
  projectPlanRoute,
  type EventLogEntry,
  type Model,
  type TaskSpec,
  type TaskState,
  type TaskStatus,
} from "../lib/types";

type MissionBadgeStatus =
  | "active"
  | "complete"
  | "failed"
  | "needs_human"
  | "in_progress"
  | "finished";

function formatDuration(
  startedAt: string,
  completedAt?: string | null,
): string {
  const started = new Date(startedAt).getTime();
  const ended = completedAt ? new Date(completedAt).getTime() : Date.now();

  if (!Number.isFinite(started) || !Number.isFinite(ended)) {
    return "?";
  }

  const seconds = Math.max(0, Math.floor((ended - started) / 1000));
  if (seconds < 60) {
    return `${seconds}s`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  }

  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function getMissionStatus(
  mission: {
    task_states: Record<string, TaskState>;
    finished_at?: string | null;
  },
): MissionBadgeStatus {
  if (mission.finished_at) {
    return "finished";
  }

  const taskStates = mission.task_states;
  const states = Object.values(taskStates);
  if (states.some((taskState) => taskState.status === "failed")) {
    return "failed";
  }
  if (
    states.some(
      (taskState) =>
        taskState.human_intervention_needed ||
        taskState.status === "needs_human",
    )
  ) {
    return "needs_human";
  }
  if (states.some((taskState) => taskState.status === "in_progress")) {
    return "in_progress";
  }
  if (states.every((taskState) => taskState.status === "review_approved")) {
    return "complete";
  }
  return "active";
}

function getScoreClassName(score: number): string {
  if (score <= 4) {
    return "text-red bg-red-bg border-red/20";
  }
  if (score <= 7) {
    return "text-amber bg-amber-bg border-amber/20";
  }
  return "text-green bg-green-bg border-green/20";
}

function formatScore(score: number): string {
  return Number.isInteger(score) ? `${score}/10` : `${score.toFixed(1)}/10`;
}

function formatExecutionProfile(profile?: {
  agent?: string | null;
  model?: string | null;
  thinking?: string | null;
} | null): string | null {
  if (!profile) {
    return null;
  }

  const parts = [profile.agent, profile.model, profile.thinking].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : null;
}

function formatActiveDuration(seconds?: number | null): string {
  const safeSeconds = Math.max(0, Math.floor(seconds ?? 0));
  if (safeSeconds < 60) {
    return `${safeSeconds}s`;
  }
  if (safeSeconds < 3600) {
    return `${Math.floor(safeSeconds / 60)}m ${safeSeconds % 60}s`;
  }
  return `${Math.floor(safeSeconds / 3600)}h ${Math.floor((safeSeconds % 3600) / 60)}m`;
}

function resolvedTaskWorkerModel(
  mission: {
    execution?: {
      tasks?: Record<string, { worker?: { model?: string | null } | null }> | null;
      defaults?: { worker?: { model?: string | null } | null };
    } | null;
    worker_model?: string;
  },
  taskSpec: TaskSpec,
): string | null {
  return (
    taskSpec.execution?.worker?.model
    ?? mission.execution?.tasks?.[taskSpec.id]?.worker?.model
    ?? mission.execution?.defaults?.worker?.model
    ?? mission.worker_model
    ?? null
  );
}

function getTaskState(
  taskState: TaskState | undefined,
  taskSpec: { id: string },
  startedAt: string,
): TaskState {
  return (
    taskState ?? {
      task_id: taskSpec.id,
      status: "pending",
      retries: 0,
      review_score: 0,
      human_intervention_needed: false,
      last_updated: startedAt,
    }
  );
}

function getDependencyLabel(
  dependencyId: string,
  taskIndexById: Map<string, number>,
): string {
  const dependencyIndex = taskIndexById.get(dependencyId);
  if (dependencyIndex === undefined) {
    return dependencyId;
  }

  return `#${String(dependencyIndex).padStart(2, "0")}`;
}

export function filterEventLogEntries(
  entries: EventLogEntry[],
  filterText: string,
): EventLogEntry[] {
  const filter = filterText.trim().toLowerCase();
  if (!filter) {
    return entries;
  }

  return entries.filter((entry) =>
    entry.event_type.toLowerCase().includes(filter),
  );
}

function MissionDetailPageLoading({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="animate-pulse space-y-3">
        <div className="h-4 w-40 rounded bg-surface" />
        <div className="h-3 w-64 rounded bg-surface" />
        <div className="h-3 w-32 rounded bg-surface" />
      </div>
      <p className="mt-3 text-dim">{message}</p>
    </div>
  );
}

function MissionDetailPageContent({
  missionId,
  projectId,
  projectName,
  embedded,
}: {
  missionId: string;
  projectId?: string;
  projectName?: string;
  embedded?: boolean;
}) {
  const navigate = useNavigate();
  const { mission, loading, error } = useMission(missionId);
  const { addToast } = useToast();
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [showDefaultModels, setShowDefaultModels] = useState(false);
  const [models, setModels] = useState<Model[]>([]);
  const [defaultWorkerProfileId, setDefaultWorkerProfileId] = useState("");
  const [defaultReviewerProfileId, setDefaultReviewerProfileId] = useState("");
  const [troubleshootPrompt, setTroubleshootPrompt] = useState("");
  const [troubleshootSaving, setTroubleshootSaving] = useState(false);
  const [pendingAction, setPendingAction] = useState<null | {
    title: string;
    message: string;
    confirmLabel: string;
    variant: "danger" | "warning";
    action: () => Promise<void>;
  }>(null);

  useEffect(() => {
    getModels().then(setModels).catch(() => { /* best-effort */ });
  }, []);
  const eventLog: EventLogEntry[] = useMemo(
    () => [...(mission?.event_log ?? [])].slice(-50).reverse(),
    [mission],
  );
  const filteredEventLog = useMemo(
    () => filterEventLogEntries(eventLog, eventTypeFilter),
    [eventLog, eventTypeFilter],
  );

  if (loading && !mission) {
    return <MissionDetailPageLoading message="Loading mission..." />;
  }

  if (error && !mission) {
    return <MissionDetailPageLoading message={error} />;
  }

  if (!mission) {
    return <MissionDetailPageLoading message="Mission not found." />;
  }

  const completedTasks = Object.values(mission.task_states).filter(
    (taskState) => taskState.status === "review_approved",
  ).length;
  const totalTasks = mission.spec.tasks.length;
  const avgScores = Object.values(mission.task_states)
    .map((taskState) => taskState.review_score)
    .filter((score) => score > 0);
  const avgReviewScore =
    avgScores.length > 0
      ? (
          avgScores.reduce((sum, score) => sum + score, 0) / avgScores.length
        ).toFixed(1)
      : "—";
  const taskIndexById = new Map(
    mission.spec.tasks.map((task, index) => [task.id, index + 1]),
  );
  const missionStatus = getMissionStatus(mission);
  const workspacePath =
    mission.working_dir?.trim() || mission.spec.working_dir?.trim() || "—";
  const workerExecution = formatExecutionProfile(mission.execution?.defaults.worker);
  const reviewerExecution = formatExecutionProfile(mission.execution?.defaults.reviewer);
  const missionDefaultsDirty = (
    defaultWorkerProfileId !== optionIdFromExecutionProfile(mission.execution?.defaults.worker, models)
    || defaultReviewerProfileId !== optionIdFromExecutionProfile(mission.execution?.defaults.reviewer, models)
  );
  const planning = mission.planning;
  let runningTaskIndex = 0;

  const confirmPendingAction = async (): Promise<void> => {
    const action = pendingAction?.action;
    setPendingAction(null);

    if (!action) {
      return;
    }

    try {
      await action();
    } catch (error) {
      addToast(
        error instanceof Error ? error.message : "Action failed",
        "error",
      );
    }
  };

  const openDefaultModelControls = (): void => {
    setDefaultWorkerProfileId(optionIdFromExecutionProfile(mission.execution?.defaults.worker, models));
    setDefaultReviewerProfileId(optionIdFromExecutionProfile(mission.execution?.defaults.reviewer, models));
    setShowDefaultModels((current) => !current);
  };

  const saveDefaultModels = async (): Promise<void> => {
    const workerProfile = executionProfileFromOption(models.find((model) => model.id === defaultWorkerProfileId));
    const reviewerProfile = executionProfileFromOption(models.find((model) => model.id === defaultReviewerProfileId));

    try {
      const result = await updateMissionDefaultModels(missionId, {
        worker_agent: workerProfile?.agent ?? null,
        worker_model: workerProfile?.model ?? null,
        worker_thinking: workerProfile?.thinking ?? null,
        reviewer_agent: reviewerProfile?.agent ?? null,
        reviewer_model: reviewerProfile?.model ?? null,
        reviewer_thinking: reviewerProfile?.thinking ?? null,
      });
      addToast(
        `Default models updated for not-started tasks; pinned ${result.pinned_tasks} started task${result.pinned_tasks === 1 ? "" : "s"}`,
        "success",
      );
      setShowDefaultModels(false);
    } catch (error) {
      addToast(error instanceof Error ? error.message : "Failed to update default models", "error");
    }
  };

  const submitTroubleshootPrompt = async (): Promise<void> => {
    const prompt = troubleshootPrompt.trim();
    if (!prompt) {
      addToast("Enter a troubleshooting prompt first", "error");
      return;
    }

    setTroubleshootSaving(true);
    try {
      await troubleshootMission(missionId, prompt);
      setTroubleshootPrompt("");
      addToast("Troubleshooting task added and mission restarted", "success");
    } catch (error) {
      addToast(error instanceof Error ? error.message : "Failed to add troubleshooting task", "error");
    } finally {
      setTroubleshootSaving(false);
    }
  };

  const submitFinishMission = async (): Promise<void> => {
    setTroubleshootSaving(true);
    try {
      await finishMission(missionId);
      addToast("Mission marked as finished", "success");
    } catch (error) {
      addToast(error instanceof Error ? error.message : "Failed to finish mission", "error");
    } finally {
      setTroubleshootSaving(false);
    }
  };

  return (
    <div>
      {embedded ? (
        <div className="mb-6 rounded-lg border border-border bg-card px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">Current Mission</div>
          <div className="mt-1 text-sm text-dim">
            {projectName ? `${projectName} mission execution` : 'Project mission execution'} stays inside the project surface.
          </div>
        </div>
      ) : (
        <Breadcrumb
          missionId={missionId}
          missionName={mission.spec.name}
          className="mb-6"
        />
      )}

      <div className="mb-6 flex flex-col gap-3">
        <div className="flex flex-wrap items-start gap-3">
          <h1 className="text-title">{mission.spec.name}</h1>
          <StatusBadge
            status={missionStatus}
            className={
              missionStatus === "in_progress"
                ? "animate-[pulse-glow_2s_ease_infinite]"
                : ""
            }
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 text-[11px] text-dim">
          <span className="inline-flex rounded-full border border-border bg-surface px-3 py-0.5 font-mono text-[11px] text-dim">
            Wall time {formatActiveDuration(mission.active_wall_time_seconds)}
          </span>
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted">
            Workspace path
          </span>
          <span
            className="max-w-[26rem] truncate rounded-full border border-border bg-surface px-3 py-0.5 font-mono text-[11px] text-muted"
            title={workspacePath}
          >
            {workspacePath}
          </span>
          {workerExecution ? (
            <span className="inline-flex rounded-full border border-border bg-surface px-3 py-0.5 font-mono text-[11px] text-muted">
              worker {workerExecution}
            </span>
          ) : null}
          {reviewerExecution ? (
            <span className="inline-flex rounded-full border border-border bg-surface px-3 py-0.5 font-mono text-[11px] text-muted">
              reviewer {reviewerExecution}
            </span>
          ) : null}
          {mission.execution?.mixed_roles.length ? (
            <span className="inline-flex rounded-full border border-cyan/30 bg-cyan/10 px-3 py-0.5 text-[10px] uppercase tracking-[0.08em] text-cyan">
              mixed {mission.execution.mixed_roles.join(", ")}
            </span>
          ) : null}
          {planning ? (
            <span className="inline-flex rounded-full border border-cyan/30 bg-cyan/10 px-3 py-0.5 font-mono text-[11px] text-cyan">
              planning ${planning.planning_cost_usd.toFixed(4)}
            </span>
          ) : null}
        </div>

        <TokenMeter
          tokensIn={mission.tokens_in ?? 0}
          tokensOut={mission.tokens_out ?? 0}
          costUsd={mission.cost_usd ?? mission.estimated_cost_usd ?? 0}
          label="mission tokens"
        />

        <SpaceProgress 
          className="mt-6"
          pct={totalTasks > 0 ? (completedTasks / totalTasks) * 100 : 0} 
          isRunning={missionStatus === "in_progress" || missionStatus === "active"}
        />
      </div>

      <div className="mb-6">
        <div className="section-title mb-2">{embedded ? 'Project Mission' : 'Mission Control'}</div>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded border border-cyan/30 px-3 py-1 text-[12px] text-cyan transition-colors hover:bg-cyan/10"
            onClick={openDefaultModelControls}
          >
            Change Default Models
          </button>
          <button
            type="button"
            className="rounded border border-cyan/30 px-3 py-1 text-[12px] text-cyan transition-colors hover:bg-cyan/10"
            onClick={() => {
              void createReadjustedDraft(missionId)
                .then((draft) => {
                  navigate(projectId ? `${projectPlanRoute(projectId)}?draft=${draft.id}` : `/plan?draft=${draft.id}`);
                })
                .catch((error) => {
                  addToast(
                    error instanceof Error ? error.message : "Failed to reopen planning",
                    "error",
                  );
                });
            }}
          >
            Readjust Plan
          </button>
          <button
            type="button"
            className="rounded border border-red/30 px-3 py-1 text-[12px] text-red transition-colors hover:bg-red/10"
            onClick={() => {
              setPendingAction({
                title: `Stop mission "${mission.spec.name}"?`,
                message: "This will stop the mission immediately.",
                confirmLabel: "Stop Mission",
                variant: "danger",
                action: async () => {
                  await stopMission(missionId);
                  addToast("Mission stopped", "success");
                },
              });
            }}
          >
            Stop Mission
          </button>
          <button
            type="button"
            className="rounded border border-amber/30 px-3 py-1 text-[12px] text-amber transition-colors hover:bg-amber/10"
            onClick={() => {
              setPendingAction({
                title: `Restart mission "${mission.spec.name}"?`,
                message:
                  "This will launch a fresh run from the current mission state.",
                confirmLabel: "Restart Mission",
                variant: "warning",
                action: async () => {
                  await restartMission(missionId);
                  addToast("Mission restarted", "success");
                },
              });
            }}
          >
            Restart Mission
          </button>
        </div>
      </div>

      {showDefaultModels ? (
        <div className="mb-4 grid gap-3 rounded-lg border border-border bg-surface p-3 md:grid-cols-[1fr_1fr_auto]">
          <label className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            Worker
            <ExecutionProfileSelect
              className="mt-1 w-full rounded border border-border bg-card px-3 py-2 font-mono text-[12px] normal-case tracking-normal text-text outline-none focus:border-cyan"
              options={models}
              value={defaultWorkerProfileId}
              onChange={setDefaultWorkerProfileId}
              ariaLabel="Mission default worker execution profile"
            />
          </label>
          <label className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            Reviewer
            <ExecutionProfileSelect
              className="mt-1 w-full rounded border border-border bg-card px-3 py-2 font-mono text-[12px] normal-case tracking-normal text-text outline-none focus:border-cyan"
              options={models}
              value={defaultReviewerProfileId}
              onChange={setDefaultReviewerProfileId}
              ariaLabel="Mission default reviewer execution profile"
            />
          </label>
          <div className="flex items-end gap-2">
            <button
              type="button"
              className="rounded border border-cyan/30 px-3 py-2 text-[12px] text-cyan transition-colors hover:bg-cyan/10 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={!missionDefaultsDirty}
              onClick={() => { void saveDefaultModels(); }}
            >
              Save Models
            </button>
            <button
              type="button"
              className="rounded border border-border px-3 py-2 text-[12px] text-dim transition-colors hover:bg-card-hover"
              onClick={() => setShowDefaultModels(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      <section className="sec">
        {planning ? (
          <div className="mb-4 rounded-2xl border border-cyan/20 bg-[radial-gradient(circle_at_top,rgba(34,211,238,0.14),transparent_62%),var(--color-card)] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-cyan">
                  Planning Lineage
                </div>
                <h2 className="mt-1 text-lg font-semibold text-text">Preflight Cost</h2>
                <p className="mt-1 text-sm text-dim">
                  Source version {planning.source_version_id} · run {planning.source_run_id}
                </p>
              </div>
              <div className="rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1 font-mono text-[11px] text-cyan">
                ${planning.planning_cost_usd.toFixed(4)}
              </div>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border border-border bg-surface px-3 py-3">
                <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Tokens</div>
                <div className="mt-1 text-sm text-text">
                  ↓ {planning.planning_tokens_in} in
                </div>
                <div className="text-sm text-text">
                  ↑ {planning.planning_tokens_out} out
                </div>
              </div>
              <div className="rounded-xl border border-border bg-surface px-3 py-3">
                <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Reviewed changelog</div>
                <div className="mt-1 space-y-1">
                  {planning.changelog.map((entry, index) => (
                    <div key={`${entry}-${index}`} className="text-sm text-text">{entry}</div>
                  ))}
                </div>
              </div>
            </div>
            {mission.source_draft_id ? (
              <Link
                className="mt-3 inline-flex text-sm font-medium text-cyan transition-colors hover:text-cyan/80"
                to={projectId ? `${projectPlanRoute(projectId)}?draft=${mission.source_draft_id}` : `/plan?draft=${mission.source_draft_id}`}
              >
                {projectId ? 'Return to project plan' : 'Return to planning history'}
              </Link>
            ) : null}
          </div>
        ) : null}

        <h2 className="section-title">Task Timeline</h2>
        <div className="grid grid-cols-1 gap-2">
          {mission.spec.tasks.map((taskSpec) => {
            const taskState = getTaskState(
              mission.task_states[taskSpec.id],
              taskSpec,
              mission.started_at,
            );
            const score = taskState.review_score;
            const dependencyLabels = taskSpec.dependencies.map((dependencyId) =>
              getDependencyLabel(dependencyId, taskIndexById),
            );
            const isRunning = taskState.status === "in_progress";
            const shouldAnimate = isRunning && runningTaskIndex < 5;

            if (isRunning) {
              runningTaskIndex += 1;
            }

            return (
              <Link
                key={taskSpec.id}
                className={[
                  "cursor-pointer rounded-lg border border-border bg-surface px-4 py-3 transition-colors hover:bg-card-hover",
                  shouldAnimate ? "relative overflow-hidden" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                to={`/mission/${missionId}/task/${taskSpec.id}`}
              >
                {shouldAnimate ? (
                  <div className="pointer-events-none absolute inset-x-0 top-0 h-10 bg-gradient-to-r from-transparent via-white/5 to-transparent animate-[scan-line_2s_linear_infinite]" />
                ) : null}

                <div className="relative flex items-start justify-between gap-3">
                  <div className="min-w-0 flex items-start gap-3">
                    <span className="inline-flex shrink-0 rounded-full border border-border bg-card px-2 py-0.5 font-mono text-[11px] text-dim">
                      {String(taskIndexById.get(taskSpec.id) ?? 0).padStart(
                        2,
                        "0",
                      )}
                    </span>
                    <div className="min-w-0">
                      <div className="text-[13px] font-medium text-text">
                        {taskSpec.title}
                      </div>
                      <p className="mt-0.5 truncate text-[11px] text-dim">
                        {taskSpec.description}
                      </p>
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
                    <StatusBadge status={taskState.status} />
                    {taskState.retries > 0 ? (
                      <span className="inline-flex rounded-full border border-amber/30 bg-amber-bg px-2 py-0.5 font-mono text-[11px] text-amber">
                        ↺{taskState.retries}
                      </span>
                    ) : null}
                    <span className="inline-flex rounded-full border border-border bg-card px-2 py-0.5 font-mono text-[11px] text-dim">
                      {resolvedTaskWorkerModel(mission, taskSpec) ?? "—"}
                    </span>
                    {score > 0 ? (
                      <span
                        className={`inline-flex rounded border px-2 py-0.5 text-[11px] font-bold ${getScoreClassName(score)}`}
                      >
                        {formatScore(score)}
                      </span>
                    ) : null}
                  </div>
                </div>

                {dependencyLabels.length > 0 ? (
                  <div className="relative mt-3 flex flex-wrap gap-1.5">
                    {dependencyLabels.map((dependencyLabel) => (
                      <span
                        key={`${taskSpec.id}-${dependencyLabel}`}
                        className="inline-flex rounded-full border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted"
                      >
                        needs {dependencyLabel}
                      </span>
                    ))}
                  </div>
                ) : null}
              </Link>
            );
          })}
        </div>
      </section>

      <section className="sec">
        <h2 className="section-title">Event Log</h2>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <label
            className="text-[11px] uppercase tracking-[0.08em] text-muted"
            htmlFor="mission-event-filter"
          >
            Event filter
          </label>
          <input
            id="mission-event-filter"
            className="min-w-0 rounded-full border border-border bg-card px-3 py-1.5 text-[12px] text-text placeholder:text-muted"
            placeholder="Filter event type"
            type="text"
            value={eventTypeFilter}
            onChange={(event) => setEventTypeFilter(event.target.value)}
          />
          {eventTypeFilter ? (
            <button
              type="button"
              className="rounded-full border border-border px-3 py-1 text-[11px] text-dim transition-colors hover:bg-card-hover"
              onClick={() => setEventTypeFilter("")}
            >
              Clear
            </button>
          ) : null}
        </div>
        <EventLogTable entries={filteredEventLog} />
      </section>

      {missionStatus === "complete" ? (
        <section className="sec">
          <h2 className="section-title">Finalize Mission</h2>
          <div className="rounded-2xl border border-border bg-card p-4">
            <p className="text-sm text-dim">
              The current task list is complete. Add a troubleshooting follow-up to reopen the mission,
              or mark it as definitively finished.
            </p>
            <label className="mt-4 block text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
              Troubleshooting prompt
              <textarea
                className="mt-2 min-h-28 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none transition-colors placeholder:text-muted focus:border-cyan"
                placeholder="Describe the follow-up issue to investigate."
                value={troubleshootPrompt}
                onChange={(event) => setTroubleshootPrompt(event.currentTarget.value)}
              />
            </label>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded border border-cyan/30 px-3 py-2 text-[12px] text-cyan transition-colors hover:bg-cyan/10 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={troubleshootSaving || !troubleshootPrompt.trim()}
                onClick={() => { void submitTroubleshootPrompt(); }}
              >
                Troubleshoot & Retry
              </button>
              <button
                type="button"
                className="rounded border border-green/30 px-3 py-2 text-[12px] text-green transition-colors hover:bg-green/10 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={troubleshootSaving}
                onClick={() => { void submitFinishMission(); }}
              >
                Mark as Finished
              </button>
            </div>
          </div>
        </section>
      ) : null}

      <ConfirmDialog
        confirmLabel={pendingAction?.confirmLabel}
        message={pendingAction?.message ?? ""}
        open={pendingAction !== null}
        title={pendingAction?.title ?? ""}
        variant={pendingAction?.variant}
        onCancel={() => {
          setPendingAction(null);
        }}
        onConfirm={() => {
          void confirmPendingAction();
        }}
      />
    </div>
  );
}

export default function MissionDetailPage({
  missionIdOverride,
  projectId,
  projectName,
  embedded,
}: {
  missionIdOverride?: string;
  projectId?: string;
  projectName?: string;
  embedded?: boolean;
}) {
  const params = useParams<{ id?: string }>();
  const missionId = missionIdOverride ?? params.id;

  if (!missionId) {
    return <MissionDetailPageLoading message="Missing mission id." />;
  }

  return (
    <MissionDetailPageContent
      missionId={missionId}
      projectId={projectId}
      projectName={projectName}
      embedded={embedded}
    />
  );
}
