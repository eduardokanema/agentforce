import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import FileBrowser from "../components/FileBrowser";
import SpaceProgress from "../components/SpaceProgress";
import ExecutionProfileSelect from "../components/ExecutionProfileSelect";
import DraftSummaryPanel from "../components/planning/DraftSummaryPanel";
import CockpitSupportDrawer from "../components/planning/CockpitSupportDrawer";
import ExecutionProfileControls from "../components/planning/ExecutionProfileControls";
import FlightPlanProgressRail from "../components/planning/FlightPlanProgressRail";
import PlannerStreamPanel, {
  type PlannerStreamEventView,
} from "../components/planning/PlannerStreamPanel";
import PreflightQuestionsPanel from "../components/planning/PreflightQuestionsPanel";
import PlannerTranscriptPanel from "../components/planning/PlannerTranscriptPanel";
import PlanningSubstepTracker from "../components/planning/PlanningSubstepTracker";
import TaskTimelinePanel from "../components/planning/TaskTimelinePanel";
import ValidationBoard from "../components/planning/ValidationBoard";
import {
  createPlanDraft,
  getModels,
  getPlanDraft,
  patchPlanDraftSpec,
  retryPlanRun,
  sendPlanDraftMessage,
  startPlanDraft,
  submitPlanDraftRepair,
  submitPlanDraftPreflight,
} from "../lib/api";
import { isBlackHoleDraft, SIMPLE_PLAN_DRAFT_KIND } from "../lib/draftKinds";
import {
  type CockpitPhaseId,
  derivePlanFlow,
  type PlanningSubstepId,
} from "../lib/planFlow";
import { collectAdvisoryFlightChecks } from "../lib/planChecks";
import {
  executionProfileFromOption,
  optionIdFromExecutionProfile,
  profileLabel,
} from "../lib/executionProfiles";
import type {
  ExecutionProfile,
  MissionDraft,
  MissionSpec,
  Model,
  PlanRun,
  PlanStep,
  PlanVersion,
  PreflightAnswer,
} from "../lib/types";
import {
  wsClient,
  type PlanningEvent,
} from "../lib/ws";

const PLANNING_PROFILE_KEYS = [
  { key: "planner", label: "Planner" },
  { key: "critic_technical", label: "Technical Critic" },
  { key: "critic_practical", label: "Practical Critic" },
  { key: "resolver", label: "Resolver" },
] as const;

const PLANMODE_PERSISTED_WORKSPACES_KEY = "agentforce-planmode-workspaces-v1";
const PLANMODE_LEGACY_PROFILES_KEY = "agentforce-planmode-profiles-v1";
const PLANMODE_PERSISTED_PROFILES_KEY = "agentforce-planmode-profiles-v2";

function readStoredJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") {
    return fallback;
  }
  try {
    const raw = window.localStorage.getItem(key);
    if (raw == null) {
      return fallback;
    }
    const parsed = JSON.parse(raw) as T;
    return parsed;
  } catch {
    return fallback;
  }
}

function getDefaultPlanProfiles(): Record<string, ExecutionProfile> {
  return {
    planner: { agent: "claude", model: "", thinking: "medium" },
    critic_technical: { agent: "claude", model: "", thinking: "medium" },
    critic_practical: { agent: "claude", model: "", thinking: "medium" },
    resolver: { agent: "claude", model: "", thinking: "medium" },
  };
}

function normalizeWorkspacePaths(workspacePaths: string[] = []): string[] {
  return workspacePaths.filter((path) => typeof path === "string" && path.trim() !== "");
}

function normalizePlanningProfile(value: unknown): ExecutionProfile {
  if (!value || typeof value !== "object") {
    return { agent: "claude", model: "", thinking: "medium" };
  }
  const candidate = value as Record<string, unknown>;
  const agent = typeof candidate.agent === "string" && candidate.agent.trim() !== ""
    ? candidate.agent
    : "claude";
  const model = typeof candidate.model === "string" ? candidate.model : "";
  const thinking = typeof candidate.thinking === "string" && candidate.thinking.trim() !== ""
    ? candidate.thinking
    : "medium";
  return { agent, model, thinking };
}

function normalizePlanningProfiles(value: unknown): Record<string, ExecutionProfile> {
  const defaults = getDefaultPlanProfiles();
  if (!value || typeof value !== "object") {
    return defaults;
  }
  const source = value as Record<string, unknown>;
  return PLANNING_PROFILE_KEYS.reduce<Record<string, ExecutionProfile>>((acc, { key }) => {
    acc[key] = normalizePlanningProfile(source[key]);
    return acc;
  }, {});
}

function getConflictMessage(caught: unknown): string | null {
  const error = caught as Error & {
    status?: number;
    payload?: { error?: string; revision?: number };
  };
  if (error.status !== 409) {
    return null;
  }
  const revision =
    typeof error.payload?.revision === "number"
      ? ` Reload the latest draft revision ${error.payload.revision}.`
      : "";
  return `Conflict detected while saving this draft.${revision}`;
}

function updateDraftSpec(draft: MissionDraft, draftSpec: MissionSpec): MissionDraft {
  return {
    ...draft,
    draft_spec: draftSpec,
  };
}

function draftValidationIssues(draft: MissionDraft | null): string[] {
  if (!draft) {
    return [];
  }

  const issues: string[] = [];
  if (draft.draft_spec.name.trim() === "") {
    issues.push("Mission name is required.");
  }
  if (draft.draft_spec.goal.trim() === "") {
    issues.push("Mission goal is required.");
  }
  if (draft.draft_spec.tasks.length === 0) {
    issues.push("Add at least one task.");
  }
  return issues;
}

function getPlanningProfiles(draft: MissionDraft | null): Record<string, ExecutionProfile> {
  const raw = draft?.validation?.planning_profiles;
  if (!raw || typeof raw !== "object") {
    return {};
  }
  return raw as Record<string, ExecutionProfile>;
}

function getProfileValue(draft: MissionDraft | null, key: string): ExecutionProfile {
  const stored = getPlanningProfiles(draft)[key] ?? {};
  return {
    agent: stored.agent ?? "codex",
    model: stored.model ?? "",
    thinking: stored.thinking ?? "medium",
  };
}

function formatCurrency(value: number | undefined): string {
  return `$${(value ?? 0).toFixed(4)}`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "Pending";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function summarizeStep(stepName: string): string {
  return stepName.replace(/_/g, " ");
}

function latestRun(draft: MissionDraft | null): PlanRun | null {
  return draft?.plan_runs?.[0] ?? null;
}

function latestVersion(draft: MissionDraft | null): PlanVersion | null {
  return draft?.plan_versions?.[0] ?? null;
}

function buildRunEvents(run: PlanRun | null): PlannerStreamEventView[] {
  if (!run) {
    return [];
  }
  return run.steps.map((step) => ({
    type: step.name,
    phase: summarizeStep(step.name),
    status: step.status,
    content: step.summary || step.message || undefined,
    timestamp: step.completed_at || step.started_at || null,
  }));
}

function planningBusy(run: PlanRun | null): boolean {
  return run?.status === "queued" || run?.status === "running";
}

function latestFailedRun(draft: MissionDraft | null): PlanRun | null {
  return (draft?.plan_runs ?? []).find((run) => run.status === "failed" || run.status === "stale") ?? null;
}

function firstTurnPrompt(draft: MissionDraft | null): string {
  if (!draft) {
    return "";
  }
  const firstUserTurn = draft.turns.find((turn) => turn.role === "user");
  return firstUserTurn?.content ?? "";
}

function countStepIssues(step: PlanStep | null | undefined): number {
  const issues = step?.metadata?.issues;
  return Array.isArray(issues) ? issues.length : 0;
}

function plannerProgressPct(
  currentPhaseId: CockpitPhaseId,
  phaseCountComplete: number,
  substepCompleteCount: number,
): number {
  const base = (phaseCountComplete / 6) * 100;
  if (currentPhaseId !== "draft" && currentPhaseId !== "stress_test") {
    return Math.round(base);
  }
  const extra = (substepCompleteCount / 5) * (100 / 6);
  return Math.round(Math.min(100, base + extra));
}

function toPlannerEventView(event: PlanningEvent): PlannerStreamEventView {
  return {
    type: event.type,
    phase: event.step ?? event.plan_version_id ?? "runtime",
    status:
      event.status ?? (event.type.includes("started") ? "started" : "updated"),
    content: event.summary ?? event.message,
    live: true,
  };
}

function joinIssueTitles(step: PlanStep | null | undefined): string {
  const issues = step?.metadata?.issues;
  if (!Array.isArray(issues) || issues.length === 0) {
    return step?.summary || step?.message || "No detailed findings recorded.";
  }
  return issues
    .map((issue) => {
      if (!issue || typeof issue !== "object") {
        return "";
      }
      const title = "title" in issue ? String(issue.title ?? "").trim() : "";
      const severity = "severity" in issue ? String(issue.severity ?? "").trim() : "";
      return [severity, title].filter(Boolean).join(" · ");
    })
    .filter(Boolean)
    .join(" | ");
}

function StepFindingCard({
  title,
  step,
}: {
  title: string;
  step: PlanStep | null | undefined;
}) {
  const status = step?.status ?? "idle";
  const issueCount = countStepIssues(step);

  return (
    <article className="rounded-[1.05rem] border border-border bg-card px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
            {title}
          </div>
          <div className="mt-2 text-sm font-semibold tracking-[-0.02em] text-text">
            {status.replace("_", " ")}
          </div>
        </div>
        <div className="rounded-full border border-border bg-surface px-3 py-1 font-mono text-[11px] text-dim">
          {issueCount} issue{issueCount === 1 ? "" : "s"}
        </div>
      </div>
      <p className="mt-2 text-[12px] leading-5 text-dim">
        {joinIssueTitles(step)}
      </p>
      <div className="mt-3 font-mono text-[11px] text-dim">
        {formatDateTime(step?.completed_at || step?.started_at || null)}
      </div>
    </article>
  );
}

type SupportPanelId = "edit" | "transcript" | "logbook";

function PhaseHero({
  phaseLabel,
  selectedPhaseStatus,
  currentPhaseId,
  nextAction,
  activeSummary,
  currentRun,
  currentVersion,
  completedPhases,
  completedSubsteps,
  latestRunIssue,
  launchReadinessSummary,
  latestFailed,
  retryingRunId,
  onRetryLatestRun,
}: {
  phaseLabel: string;
  selectedPhaseStatus: ReturnType<typeof derivePlanFlow>["phases"][number]["status"];
  currentPhaseId: CockpitPhaseId;
  nextAction: string;
  activeSummary: string;
  currentRun: PlanRun | null;
  currentVersion: PlanVersion | null;
  completedPhases: number;
  completedSubsteps: number;
  latestRunIssue: string | null;
  launchReadinessSummary: string;
  latestFailed: PlanRun | null;
  retryingRunId: string | null;
  onRetryLatestRun: (runId: string) => void;
}) {
  const pct = plannerProgressPct(currentPhaseId, completedPhases, completedSubsteps);
  const phaseLabelText = selectedPhaseStatus === "complete"
    ? "Completed Stage"
    : selectedPhaseStatus === "up_next"
      ? "Upcoming Stage"
      : selectedPhaseStatus === "blocked"
        ? "Blocked Stage"
        : "Active Stage";

  return (
    <section className="overflow-hidden rounded-[1.3rem] border border-border bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.16),transparent_42%),radial-gradient(circle_at_bottom_right,rgba(46,204,138,0.12),transparent_36%),var(--color-card)] p-5">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_17rem]">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan">
            {phaseLabelText}
          </div>
          <h2 className="mt-2 text-[clamp(1.6rem,3vw,2.35rem)] font-semibold tracking-[-0.04em] text-text">
            {phaseLabel}
          </h2>
          <p className="mt-3 max-w-[68ch] text-sm leading-7 text-dim">
            {activeSummary}
          </p>
          <div className="mt-5 rounded-[1rem] border border-border bg-black/14 px-4 py-4">
            <div className="text-[11px] uppercase tracking-[0.1em] text-muted">Now Tracking</div>
            <div className="mt-2 text-base font-semibold tracking-[-0.03em] text-text">
              {nextAction}
            </div>
            <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-dim">
              <span className="rounded-full border border-border bg-surface px-3 py-1">
                {currentRun ? `Run ${currentRun.status}` : "Awaiting run"}
              </span>
              <span className="rounded-full border border-border bg-surface px-3 py-1">
                {formatCurrency(currentRun?.cost_usd)}
              </span>
              <span className="rounded-full border border-border bg-surface px-3 py-1">
                {currentVersion ? `Version ${currentVersion.id}` : "No promoted version"}
              </span>
            </div>
          </div>
          {latestRunIssue ? (
            <div className="mt-4 rounded-xl border border-red/25 bg-red/8 px-4 py-3 text-sm text-red">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span>{latestRunIssue}</span>
                {latestFailed ? (
                  <button
                    type="button"
                    className="rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-xs font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={retryingRunId === latestFailed.id}
                    onClick={() => onRetryLatestRun(latestFailed.id)}
                  >
                    {retryingRunId === latestFailed.id ? "Retrying..." : "Retry Latest Run"}
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>

        <div className="rounded-[1.1rem] border border-border bg-black/12 p-4">
          <SpaceProgress pct={pct} isRunning={currentRun?.status === "running"} />
          <div className="mt-4 text-[11px] uppercase tracking-[0.14em] text-muted">
            Mission Telemetry
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-dim">
            <span className="rounded-full border border-border bg-surface px-3 py-1">
              {completedPhases}/6 phases complete
            </span>
            <span className="rounded-full border border-border bg-surface px-3 py-1">
              {completedSubsteps}/5 planning steps
            </span>
            <span className="rounded-full border border-border bg-surface px-3 py-1">
              {(currentRun?.tokens_in ?? 0) + (currentRun?.tokens_out ?? 0)} tokens
            </span>
          </div>
          <p className="mt-4 text-sm leading-6 text-dim">
            {launchReadinessSummary}
          </p>
        </div>
      </div>
    </section>
  );
}

function SupportDock({
  activePanel,
  onToggle,
}: {
  activePanel: SupportPanelId | null;
  onToggle: (panel: SupportPanelId) => void;
}) {
  const items: Array<{ id: SupportPanelId; label: string; description: string }> = [
    { id: "edit", label: "Edit Mission", description: "Summary, tasks, and execution defaults." },
    { id: "transcript", label: "Transcript", description: "Planner turns and follow-up guidance." },
    { id: "logbook", label: "Logbook", description: "Run history, changelog, and planner stream." },
  ];

  return (
    <section className="rounded-[1.1rem] border border-border bg-card px-4 py-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan">
            Support Dock
          </div>
          <p className="mt-1 text-xs text-dim">
            Secondary tools stay out of the way until you call for them.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {items.map((item) => {
            const open = activePanel === item.id;
            return (
              <button
                key={item.id}
                type="button"
                className={[
                  "rounded-full border px-3 py-2 text-sm font-semibold transition-colors",
                  open
                    ? "border-cyan/35 bg-cyan/10 text-cyan"
                    : "border-border bg-surface text-dim hover:bg-card-hover hover:text-text",
                ].join(" ")}
                onClick={() => onToggle(item.id)}
              >
                {open ? `Hide ${item.label}` : item.label}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function PlanningProfilesSummary({
  draft,
  models,
}: {
  draft: MissionDraft;
  models: Model[];
}) {
  return (
    <section className="rounded-[1.15rem] border border-border bg-card p-4">
      <div className="mb-3">
        <h2 className="section-title">Planning Stack</h2>
        <p className="mt-1 text-xs text-dim">
          Configured models for this draft&apos;s planning loop.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {PLANNING_PROFILE_KEYS.map(({ key, label }) => {
          const profile = getProfileValue(draft, key);
          const optionId = optionIdFromExecutionProfile(profile, models);
          const modelObj = models.find((model) => model.id === optionId);
          const modelName = modelObj ? profileLabel(modelObj) : profile.model || "Default";
          return (
            <div key={key} className="rounded-lg border border-border bg-surface p-3">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                {label}
              </div>
              <div className="truncate text-sm font-semibold text-text" title={modelName}>
                {modelName}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function PlanHistoryPanel({
  draft,
  retryingRunId,
  onRetryRun,
}: {
  draft: MissionDraft;
  retryingRunId: string | null;
  onRetryRun: (runId: string) => void;
}) {
  const currentRun = latestRun(draft);
  const currentVersion = latestVersion(draft);

  return (
    <section className="rounded-[1.15rem] border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="section-title">Planning History</h2>
          <p className="mt-1 text-xs text-dim">
            Stored runs, versions, and changelog checkpoints.
          </p>
        </div>
        <div className="rounded-full border border-cyan/20 bg-cyan/10 px-3 py-1 text-[11px] font-mono text-cyan">
          {currentRun ? `${formatCurrency(currentRun.cost_usd)} planning` : "No runs yet"}
        </div>
      </div>

      <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1.05fr)_minmax(16rem,0.95fr)]">
        <div className="space-y-3">
          {(draft.plan_runs ?? []).map((run) => (
            <article
              key={run.id}
              className={`rounded-xl border px-3 py-3 transition-all ${
                run.status === "running"
                  ? "border-cyan/40 bg-cyan/10 shadow-[0_0_0_1px_rgba(34,211,238,0.08)]"
                  : "border-border bg-surface"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-semibold text-text">
                  {run.trigger_kind === "follow_up"
                    ? "Follow-up run"
                    : run.trigger_kind === "retry"
                      ? "Retry run"
                      : "Initial run"}
                </div>
                <div className="rounded-full border border-border bg-card px-2.5 py-1 font-mono text-[11px] text-dim">
                  {run.status}
                </div>
              </div>
              {run.status === "failed" && run.error_message ? (
                <div className="mt-2 rounded-lg border border-red/20 bg-red/5 px-3 py-2 text-xs text-red/80">
                  <span className="font-semibold">Error:</span> {run.error_message}
                </div>
              ) : (
                <p className="mt-2 text-sm text-text">
                  {run.trigger_message || "Automatic first-pass planning run."}
                </p>
              )}
              <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-dim">
                <span className="rounded-full border border-border bg-card px-2.5 py-1">
                  Revision {run.base_revision}
                </span>
                <span className="rounded-full border border-border bg-card px-2.5 py-1">
                  {run.steps.length} steps
                </span>
                <span className="rounded-full border border-border bg-card px-2.5 py-1">
                  {formatCurrency(run.cost_usd)}
                </span>
              </div>
              {run.status === "failed" || run.status === "stale" ? (
                <div className="mt-3 flex justify-end">
                  <button
                    type="button"
                    className="rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-xs font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={retryingRunId === run.id}
                    onClick={() => onRetryRun(run.id)}
                  >
                    {retryingRunId === run.id ? "Retrying..." : "Retry run"}
                  </button>
                </div>
              ) : null}
            </article>
          ))}
          {(draft.plan_runs ?? []).length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-dim">
              No planning runs stored yet.
            </div>
          ) : null}
        </div>

        <div className="rounded-xl border border-border bg-surface p-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            Latest Version
          </div>
          <div className="mt-2 text-sm font-semibold text-text">
            {currentVersion ? currentVersion.id : "Pending"}
          </div>
          <div className="mt-1 text-xs text-dim">
            {currentVersion
              ? `Created ${formatDateTime(currentVersion.created_at)}`
              : "No version checkpoint yet."}
          </div>
          <div className="mt-3 space-y-2">
            {(
              currentVersion?.changelog ??
              draft.planning_summary?.changelog ??
              []
            ).map((entry, index) => (
              <div
                key={`${entry}-${index}`}
                className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-text"
              >
                {entry}
              </div>
            ))}
            {!(
              currentVersion?.changelog?.length ||
              draft.planning_summary?.changelog?.length
            ) ? (
              <div className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-dim">
                Resolver changelog appears here after a reviewed version is promoted.
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}

function EngineeringControls({
  draft,
  models,
  savingDraft,
  onSaveSummary,
  onTaskChange,
  onNameChange,
  onGoalChange,
  onDodChange,
  onWorkerProfileChange,
  onReviewerProfileChange,
}: {
  draft: MissionDraft;
  models: Model[];
  savingDraft: boolean;
  onSaveSummary: () => void;
  onTaskChange: (taskId: string, patch: Partial<MissionSpec["tasks"][number]>) => void;
  onNameChange: (value: string) => void;
  onGoalChange: (value: string) => void;
  onDodChange: (value: string[]) => void;
  onWorkerProfileChange: (value: string) => void;
  onReviewerProfileChange: (value: string) => void;
}) {
  return (
    <section className="space-y-5 rounded-[1.15rem] border border-border bg-card p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">Engineering Controls</h2>
          <p className="mt-1 text-xs text-dim">
            Summary, tasks, and execution defaults remain editable while the active phase stays in focus.
          </p>
        </div>
        <div className="rounded-full border border-border bg-surface px-3 py-1 font-mono text-[11px] text-dim">
          Revision {draft.revision}
        </div>
      </div>

      <DraftSummaryPanel
        draft={draft}
        saving={savingDraft}
        onNameChange={onNameChange}
        onGoalChange={onGoalChange}
        onDodChange={onDodChange}
        onSave={onSaveSummary}
      />
      <TaskTimelinePanel
        draft={draft}
        saving={savingDraft}
        models={models}
        onTaskChange={onTaskChange}
        onSave={onSaveSummary}
      />
      <ExecutionProfileControls
        draft={draft}
        options={models}
        onWorkerProfileChange={onWorkerProfileChange}
        onReviewerProfileChange={onReviewerProfileChange}
      />
      <PlanningProfilesSummary draft={draft} models={models} />
    </section>
  );
}

function PhaseViewport({
  selectedPhase,
  draft,
  substeps,
  retryingRunId,
  loadingModels,
  conflictMessage,
  summaryIssues,
  advisoryIssues,
  preflightAnswers,
  submittingPreflight,
  repairAnswers,
  submittingRepair,
  currentRun,
  streaming,
  launching,
  launchReadiness,
  onRetryRun,
  onAnswerChange,
  onSubmitPreflight,
  onSkipPreflight,
  onSubmitRepair,
  onLaunch,
  onOpenSupportPanel,
}: {
  selectedPhase: CockpitPhaseId;
  draft: MissionDraft | null;
  substeps: ReturnType<typeof derivePlanFlow>["substeps"];
  retryingRunId: string | null;
  loadingModels: boolean;
  conflictMessage: string | null;
  summaryIssues: string[];
  advisoryIssues: string[];
  preflightAnswers: Record<string, PreflightAnswer>;
  submittingPreflight: boolean;
  repairAnswers: Record<string, PreflightAnswer>;
  submittingRepair: boolean;
  currentRun: PlanRun | null;
  streaming: boolean;
  launching: boolean;
  launchReadiness: ReturnType<typeof derivePlanFlow>["launchReadiness"];
  onRetryRun: (runId: string) => void;
  onAnswerChange: (questionId: string, answer: PreflightAnswer) => void;
  onSubmitPreflight: () => void;
  onSkipPreflight: () => void;
  onSubmitRepair: () => void;
  onLaunch: () => void;
  onOpenSupportPanel: (panel: SupportPanelId) => void;
}) {
  if (!draft) {
    return null;
  }

  const currentVersion = latestVersion(draft);
  const latestFailed = latestFailedRun(draft);
  const activeSubstep = substeps.find((step) => step.status === "running" || step.status === "failed" || step.status === "stale")
    ?? [...substeps].reverse().find((step) => step.status === "complete")
    ?? substeps[0];
  const stepsById = new Map<PlanningSubstepId, PlanStep>(
    (currentRun?.steps ?? [])
      .filter((step): step is PlanStep & { name: PlanningSubstepId } =>
        step.name === "planner_synthesis"
        || step.name === "mission_plan_pass"
        || step.name === "technical_critic"
        || step.name === "practical_critic"
        || step.name === "resolver")
      .map((step) => [step.name, step]),
  );

  if (selectedPhase === "briefing") {
    return (
      <section className="rounded-[1.15rem] border border-border bg-card p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="section-title">Mission Brief</h2>
            <h3 className="mt-2 text-xl font-semibold tracking-[-0.03em] text-text">
              {draft.draft_spec.name || "Untitled mission draft"}
            </h3>
          </div>
          <div className="rounded-full border border-border bg-surface px-3 py-1 font-mono text-[11px] text-dim">
            Revision {draft.revision}
          </div>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(18rem,0.9fr)]">
          <div className="space-y-4">
            <div className="rounded-xl border border-border bg-surface px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Original Prompt</div>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-text">
                {firstTurnPrompt(draft) || "No original prompt stored."}
              </p>
            </div>
            <div className="rounded-xl border border-border bg-surface px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Goal</div>
              <p className="mt-2 text-sm leading-7 text-text">{draft.draft_spec.goal}</p>
            </div>
          </div>
          <div className="space-y-4">
            <div className="rounded-xl border border-border bg-surface px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Mission Footprint</div>
              <div className="mt-3 flex flex-wrap gap-2">
                <span className="rounded-full border border-border bg-card px-3 py-1 font-mono text-[11px] text-dim">
                  {draft.workspace_paths.length} workspace{draft.workspace_paths.length === 1 ? "" : "s"}
                </span>
                <span className="rounded-full border border-border bg-card px-3 py-1 font-mono text-[11px] text-dim">
                  {PLANNING_PROFILE_KEYS.length} planning profiles
                </span>
                <span className="rounded-full border border-border bg-card px-3 py-1 font-mono text-[11px] text-dim">
                  {draft.draft_spec.tasks.length} task{draft.draft_spec.tasks.length === 1 ? "" : "s"}
                </span>
              </div>
            </div>
            <div className="rounded-xl border border-border bg-surface px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Planning Stack</div>
              <div className="mt-3 flex flex-wrap gap-2">
                {PLANNING_PROFILE_KEYS.map(({ key, label }) => {
                  const profile = getProfileValue(draft, key);
                  return (
                    <span key={key} className="rounded-full border border-border bg-card px-3 py-1 text-[11px] text-dim">
                      {label}: <span className="font-mono text-text">{profile.model || "Default"}</span>
                    </span>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </section>
    );
  }

  if (selectedPhase === "preflight") {
    const preflightPending = draft.preflight_status === "pending"
      && (draft.preflight_questions?.length ?? 0) > 0;
    const repairPending = draft.repair_status === "pending"
      && (draft.repair_questions?.length ?? 0) > 0;

    if (preflightPending) {
      return (
        <PreflightQuestionsPanel
          draft={draft}
          answers={preflightAnswers}
          submitting={submittingPreflight}
          onAnswerChange={onAnswerChange}
          onSubmit={onSubmitPreflight}
          onSkip={onSkipPreflight}
        />
      );
    }

    if (repairPending) {
      return (
        <PreflightQuestionsPanel
          draft={{
            ...draft,
            preflight_questions: draft.repair_questions,
          }}
          answers={repairAnswers}
          submitting={submittingRepair}
          title="Repair Questions"
          description={draft.repair_context?.gate_reason || "Answer these questions so the planner can repair the mission draft and continue."}
          submitLabel="Resume Planning"
          onAnswerChange={onAnswerChange}
          onSubmit={onSubmitRepair}
          onSkip={onSubmitRepair}
        />
      );
    }

    return (
      <section className="rounded-[1.15rem] border border-border bg-card p-5">
        <h2 className="section-title">{draft.repair_status === "manual_edit_required" ? "Repair Review" : "Preflight Complete"}</h2>
        <p className="mt-3 max-w-[62ch] text-sm leading-7 text-dim">
          {draft.repair_status === "manual_edit_required"
            ? (draft.repair_context?.gate_reason || "Repair rounds are exhausted. Open edit mode and fix the draft manually.")
            : "Clarifications are resolved. The cockpit will keep the recorded answers in the transcript and logbook without competing with the live stage."}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <span className="rounded-full border border-border bg-surface px-3 py-1 text-[11px] text-dim">
            {draft.preflight_status === "skipped" ? "Skipped" : "Answered"}
          </span>
          <span className="rounded-full border border-border bg-surface px-3 py-1 text-[11px] text-dim">
            {Object.keys(draft.preflight_answers ?? {}).length} response{Object.keys(draft.preflight_answers ?? {}).length === 1 ? "" : "s"}
          </span>
        </div>
        <div className="mt-4 rounded-xl border border-border bg-surface px-4 py-4">
          <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Recorded Answers</div>
          <div className="mt-3 space-y-2">
            {Object.entries(draft.preflight_answers ?? {}).map(([id, answer]) => (
              <div key={id} className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-text">
                <span className="font-mono text-[11px] text-dim">{id}</span>
                <div className="mt-1">{answer.custom_answer || answer.selected_option || "No answer recorded."}</div>
              </div>
            ))}
            {Object.keys(draft.preflight_answers ?? {}).length === 0 ? (
              <div className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-dim">
                No stored answers.
              </div>
            ) : null}
          </div>
        </div>
      </section>
    );
  }

  if (selectedPhase === "draft") {
    return (
      <div className="space-y-5">
        <section className="rounded-[1.15rem] border border-border bg-card p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan">
                Planning Orbit
              </div>
              <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em] text-text">
                {activeSubstep?.label || "Planner standing by"}
              </h2>
              <p className="mt-3 max-w-[64ch] text-sm leading-7 text-dim">
                {activeSubstep?.summary || "The planner is waiting for guidance or the first queued run."}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {latestFailed ? (
                <button
                  type="button"
                  className="rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={retryingRunId === latestFailed.id}
                  onClick={() => onRetryRun(latestFailed.id)}
                >
                  {retryingRunId === latestFailed.id ? "Retrying..." : "Retry Latest Run"}
                </button>
              ) : null}
              <button
                type="button"
                className="rounded-full border border-border bg-surface px-4 py-2 text-sm font-semibold text-dim transition-colors hover:bg-card-hover hover:text-text"
                onClick={() => onOpenSupportPanel("transcript")}
              >
                Open Transcript
              </button>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-dim">
            <span className="rounded-full border border-border bg-surface px-3 py-1">
              {currentRun ? `Run ${currentRun.status}` : "Awaiting run"}
            </span>
            <span className="rounded-full border border-border bg-surface px-3 py-1">
              {formatCurrency(currentRun?.cost_usd)}
            </span>
            <span className="rounded-full border border-border bg-surface px-3 py-1">
              {streaming ? "Planner streaming" : "Standing by"}
            </span>
          </div>
        </section>
        <PlanningSubstepTracker title="Live Planning Orbit" steps={substeps} />
      </div>
    );
  }

  if (selectedPhase === "stress_test") {
    return (
      <div className="space-y-5">
        <section className="rounded-[1.15rem] border border-border bg-card p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan">
                Stress Test
              </div>
              <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em] text-text">
                Critics and resolver are pressure-testing the mission.
              </h2>
              <p className="mt-3 max-w-[64ch] text-sm leading-7 text-dim">
                Focus on the latest blocker or confirmation signal. Detailed transcripts and full run history stay in the logbook.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {latestFailed ? (
                <button
                  type="button"
                  className="rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={retryingRunId === latestFailed.id}
                  onClick={() => onRetryRun(latestFailed.id)}
                >
                  {retryingRunId === latestFailed.id ? "Retrying..." : "Retry Latest Run"}
                </button>
              ) : null}
              <button
                type="button"
                className="rounded-full border border-border bg-surface px-4 py-2 text-sm font-semibold text-dim transition-colors hover:bg-card-hover hover:text-text"
                onClick={() => onOpenSupportPanel("logbook")}
              >
                Open Logbook
              </button>
            </div>
          </div>
        </section>
        <PlanningSubstepTracker title="Stress Test Orbit" steps={substeps} />
        <div className="space-y-3">
          <StepFindingCard title="Technical Critic" step={stepsById.get("technical_critic")} />
          <StepFindingCard title="Practical Critic" step={stepsById.get("practical_critic")} />
          <StepFindingCard title="Resolver" step={stepsById.get("resolver")} />
        </div>
        {latestFailed ? (
          <div className="rounded-xl border border-red/20 bg-red/8 px-4 py-4 text-sm text-red">
            Newest run issue: {latestFailed.error_message || `Run ${latestFailed.id} requires intervention.`}
          </div>
        ) : null}
      </div>
    );
  }

  if (selectedPhase === "finalize") {
    return (
      <div className="space-y-5">
        <section className="rounded-[1.15rem] border border-border bg-card p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="section-title">Finalize Review</h2>
              <p className="mt-3 max-w-[68ch] text-sm leading-7 text-dim">
                This pass is read-first. Check readiness, resolve blockers, then open edit mode only if the mission itself needs revision.
              </p>
            </div>
            <button
              type="button"
              className="rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15"
              onClick={() => onOpenSupportPanel("edit")}
            >
              Edit Mission
            </button>
          </div>
          <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-dim">
            <span className="rounded-full border border-border bg-surface px-3 py-1">
              {summaryIssues.length === 0 ? "No visible blockers" : `${summaryIssues.length} blocker${summaryIssues.length === 1 ? "" : "s"}`}
            </span>
            <span className="rounded-full border border-border bg-surface px-3 py-1">
              {advisoryIssues.length} advisory check{advisoryIssues.length === 1 ? "" : "s"}
            </span>
          </div>
        </section>
        <ValidationBoard
          conflictMessage={conflictMessage}
          summaryIssues={summaryIssues}
          advisoryIssues={loadingModels ? [] : advisoryIssues}
        />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <section className="rounded-[1.15rem] border border-border bg-[radial-gradient(circle_at_top,rgba(34,211,238,0.14),transparent_58%),var(--color-card)] p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="section-title">Launch Window</h2>
            <h3 className="mt-2 text-[clamp(1.4rem,2.2vw,2rem)] font-semibold tracking-[-0.03em] text-text">
              {draft.draft_spec.name || "Untitled mission draft"}
            </h3>
            <p className="mt-3 max-w-[70ch] text-sm leading-7 text-dim">
              Final reviewed version {currentVersion?.id ?? "pending"} is staged here. Confirm readiness, inspect the final changelog, and commit the mission when the window is clear.
            </p>
          </div>
          <button
            type="button"
            className="rounded-full border border-cyan/30 bg-cyan/10 px-5 py-2.5 text-sm font-semibold text-cyan transition-all hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={launching || summaryIssues.length > 0 || streaming || !!latestFailed}
            onClick={onLaunch}
          >
            {launching ? "Launching..." : "Launch Mission"}
          </button>
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1.08fr)_minmax(16rem,0.92fr)]">
          <div className="rounded-xl border border-border bg-surface px-4 py-4">
            <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Readiness</div>
            <div className="mt-2 text-lg font-semibold tracking-[-0.03em] text-text">
              {launchReadiness.ready ? "Window clear" : "Launch blocked"}
            </div>
            <p className="mt-2 text-sm leading-6 text-dim">
              {launchReadiness.summary}
            </p>
            {launchReadiness.blockers.length > 0 ? (
              <div className="mt-4 space-y-2">
                {launchReadiness.blockers.map((blocker) => (
                  <div key={blocker} className="rounded-lg border border-red/18 bg-red/5 px-3 py-2 text-sm text-red">
                    {blocker}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="space-y-4">
            <div className="rounded-xl border border-border bg-surface px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Launch Telemetry</div>
              <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-dim">
                <span className="rounded-full border border-border bg-card px-3 py-1">
                  {currentRun?.status ?? "idle"}
                </span>
                <span className="rounded-full border border-border bg-card px-3 py-1">
                  {currentVersion?.id ?? "Pending"}
                </span>
                <span className="rounded-full border border-border bg-card px-3 py-1">
                  {formatCurrency(currentRun?.cost_usd)}
                </span>
              </div>
              <div className="mt-3 text-sm leading-6 text-dim">
                {formatDateTime(currentVersion?.created_at ?? null)}
              </div>
            </div>
            <div className="rounded-xl border border-border bg-surface px-4 py-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Resolver Changelog</div>
                <button
                  type="button"
                  className="rounded-full border border-border bg-card px-3 py-1 text-[11px] font-semibold text-dim transition-colors hover:bg-card-hover hover:text-text"
                  onClick={() => onOpenSupportPanel("edit")}
                >
                  Edit Mission
                </button>
              </div>
              <div className="mt-3 space-y-2">
                {(currentVersion?.changelog ?? draft.planning_summary?.changelog ?? []).map((entry, index) => (
                  <div
                    key={`${entry}-${index}`}
                    className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-text"
                  >
                    {entry}
                  </div>
                ))}
                {!(currentVersion?.changelog?.length || draft.planning_summary?.changelog?.length) ? (
                  <div className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-dim">
                    Final resolver notes will land here after promotion.
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </section>

      <ValidationBoard
        conflictMessage={conflictMessage}
        summaryIssues={summaryIssues}
        advisoryIssues={loadingModels ? [] : advisoryIssues}
      />
    </div>
  );
}

export default function PlanModePage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const draftId = id || searchParams.get("draft");

  const [prompt, setPrompt] = useState("");
  const [workspaces, setWorkspaces] = useState<string[]>(
    normalizeWorkspacePaths(readStoredJson<string[]>(PLANMODE_PERSISTED_WORKSPACES_KEY, [])),
  );
  const [models, setModels] = useState<Model[]>([]);
  const [initialPlanningProfiles, setInitialPlanningProfiles] = useState<Record<string, ExecutionProfile>>(
    normalizePlanningProfiles(
      readStoredJson<Record<string, unknown>>(
        PLANMODE_PERSISTED_PROFILES_KEY,
        readStoredJson<Record<string, unknown>>(PLANMODE_LEGACY_PROFILES_KEY, getDefaultPlanProfiles()),
      ),
    ),
  );
  const [draft, setDraft] = useState<MissionDraft | null>(null);
  const [followUpMessage, setFollowUpMessage] = useState("");
  const [liveEvents, setLiveEvents] = useState<PlannerStreamEventView[]>([]);
  const [selectedPhase, setSelectedPhase] = useState<CockpitPhaseId>("briefing");
  const [autoFollowPhase, setAutoFollowPhase] = useState(true);
  const [activeSupportPanel, setActiveSupportPanel] = useState<SupportPanelId | null>(null);
  const [loadingModels, setLoadingModels] = useState(true);
  const [loadingDraft, setLoadingDraft] = useState(false);
  const [creatingDraft, setCreatingDraft] = useState(false);
  const [retryingRunId, setRetryingRunId] = useState<string | null>(null);
  const [savingDraft, setSavingDraft] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [submittingPreflight, setSubmittingPreflight] = useState(false);
  const [preflightAnswers, setPreflightAnswers] = useState<Record<string, PreflightAnswer>>({});
  const [repairAnswers, setRepairAnswers] = useState<Record<string, PreflightAnswer>>({});
  const [submittingRepair, setSubmittingRepair] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);

  const loadDraft = async (nextDraftId: string): Promise<void> => {
    setLoadingDraft(true);
    setPageError(null);
    try {
      const loaded = await getPlanDraft(nextDraftId);
      if (isBlackHoleDraft(loaded)) {
        navigate(`/black-hole/${nextDraftId}`, { replace: true });
        return;
      }
      setDraft(loaded);
      setStreaming(planningBusy(latestRun(loaded)));
      setPreflightAnswers(loaded.preflight_answers ?? {});
      setRepairAnswers(loaded.repair_answers ?? {});
    } catch (caught) {
      setPageError(
        caught instanceof Error ? caught.message : "Failed to load draft.",
      );
    } finally {
      setLoadingDraft(false);
    }
  };

  useEffect(() => {
    let cancelled = false;

    const load = async (): Promise<void> => {
      setLoadingModels(true);
      try {
        const loadedModels = await getModels();
        if (cancelled) {
          return;
        }
        setModels(loadedModels);
        setInitialPlanningProfiles((current) => {
          const next = { ...current };
          (Object.keys(next) as Array<keyof typeof next>).forEach((key) => {
            const optionId = optionIdFromExecutionProfile(next[key], loadedModels);
            const selected = loadedModels.find((model) => model.id === optionId) ?? loadedModels[0];
            if (selected) {
              next[key] = executionProfileFromOption(selected) ?? next[key];
            }
          });
          return next;
        });
      } catch (caught) {
        if (!cancelled) {
          setPageError(
            caught instanceof Error ? caught.message : "Failed to load models.",
          );
        }
      } finally {
        if (!cancelled) {
          setLoadingModels(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(
      PLANMODE_PERSISTED_WORKSPACES_KEY,
      JSON.stringify(normalizeWorkspacePaths(workspaces)),
    );
  }, [workspaces]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(
      PLANMODE_PERSISTED_PROFILES_KEY,
      JSON.stringify(initialPlanningProfiles),
    );
  }, [initialPlanningProfiles]);

  useEffect(() => {
    if (!draftId) {
      setDraft(null);
      setLiveEvents([]);
      setAutoFollowPhase(true);
      setSelectedPhase("briefing");
      setActiveSupportPanel(null);
      return;
    }
    void loadDraft(draftId);
  }, [draftId]);

  useEffect(() => {
    if (!draftId) {
      return undefined;
    }

    const handler = (event: PlanningEvent): void => {
      if (event.draft_id !== draftId) {
        return;
      }
      setLiveEvents((current) =>
        current.concat(toPlannerEventView(event)).slice(-20),
      );
      if (
        event.type === "plan_run_failed" ||
        event.type === "plan_run_stale" ||
        event.type === "plan_head_promoted"
      ) {
        setStreaming(false);
      } else {
        setStreaming(true);
      }
      void loadDraft(draftId);
    };

    wsClient.on("plan_run_queued", handler);
    wsClient.on("plan_run_started", handler);
    wsClient.on("plan_step_started", handler);
    wsClient.on("plan_step_completed", handler);
    wsClient.on("plan_version_created", handler);
    wsClient.on("plan_head_promoted", handler);
    wsClient.on("plan_run_stale", handler);
    wsClient.on("plan_run_failed", handler);
    wsClient.on("plan_cost_update", handler);
    return () => {
      wsClient.off("plan_run_queued", handler);
      wsClient.off("plan_run_started", handler);
      wsClient.off("plan_step_started", handler);
      wsClient.off("plan_step_completed", handler);
      wsClient.off("plan_version_created", handler);
      wsClient.off("plan_head_promoted", handler);
      wsClient.off("plan_run_stale", handler);
      wsClient.off("plan_run_failed", handler);
      wsClient.off("plan_cost_update", handler);
    };
  }, [draftId, navigate]);

  const canCreateDraft =
    prompt.trim() !== "" &&
    workspaces.length > 0 &&
    (initialPlanningProfiles.planner.model ?? "").trim() !== "";

  const updateCurrentDraft = (
    updater: (current: MissionDraft) => MissionDraft,
  ): void => {
    setDraft((current) => (current ? updater(current) : current));
  };

  const persistDraftSpec = async (): Promise<void> => {
    if (!draft) {
      return;
    }
    setSavingDraft(true);
    setConflictMessage(null);
    setPageError(null);
    try {
      const response = await patchPlanDraftSpec(
        draft.id,
        draft.revision,
        draft.draft_spec,
        draft.validation,
      );
      await loadDraft(response.id);
    } catch (caught) {
      const conflict = getConflictMessage(caught);
      if (conflict) {
        setConflictMessage(conflict);
        await loadDraft(draft.id);
      } else {
        setPageError(
          caught instanceof Error ? caught.message : "Failed to save draft.",
        );
      }
    } finally {
      setSavingDraft(false);
    }
  };

  const handleCreateDraft = async (): Promise<void> => {
    if (!canCreateDraft) {
      return;
    }

    setCreatingDraft(true);
    setPageError(null);
    try {
      const created = await createPlanDraft({
        prompt,
        workspace_paths: workspaces,
        companion_profile: {
          id: "planner",
          label: "Planner",
          ...initialPlanningProfiles.planner,
        },
        validation: {
          draft_kind: SIMPLE_PLAN_DRAFT_KIND,
          planning_profiles: initialPlanningProfiles,
        },
      });
      navigate(`/plan/${created.id}`);
    } catch (caught) {
      setPageError(
        caught instanceof Error
          ? caught.message
          : "Failed to create planning draft.",
      );
    } finally {
      setCreatingDraft(false);
    }
  };

  const handleFollowUp = async (): Promise<void> => {
    if (!draft || followUpMessage.trim() === "") {
      return;
    }

    setStreaming(true);
    setConflictMessage(null);
    setPageError(null);
    try {
      await sendPlanDraftMessage(draft.id, followUpMessage);
      setFollowUpMessage("");
      setAutoFollowPhase(true);
      await loadDraft(draft.id);
      setSelectedPhase("draft");
    } catch (caught) {
      setStreaming(false);
      setPageError(
        caught instanceof Error ? caught.message : "Planner turn failed.",
      );
    }
  };

  const handleRetryRun = async (runId: string): Promise<void> => {
    if (!draft || retryingRunId === runId) {
      return;
    }

    setRetryingRunId(runId);
    setStreaming(true);
    setAutoFollowPhase(true);
    setConflictMessage(null);
    setPageError(null);
    try {
      await retryPlanRun(runId);
      await loadDraft(draft.id);
    } catch (caught) {
      setStreaming(false);
      setPageError(
        caught instanceof Error ? caught.message : "Failed to retry planning run.",
      );
    } finally {
      setRetryingRunId((current) => (current === runId ? null : current));
    }
  };

  const handleLaunch = async (): Promise<void> => {
    if (!draft) {
      return;
    }
    setLaunching(true);
    setPageError(null);
    try {
      const response = await startPlanDraft(draft.id);
      navigate(`/mission/${response.mission_id}`);
    } catch (caught) {
      setPageError(
        caught instanceof Error ? caught.message : "Failed to launch mission.",
      );
    } finally {
      setLaunching(false);
    }
  };

  const handleSubmitPreflight = async (skip = false): Promise<void> => {
    if (!draft) {
      return;
    }
    setSubmittingPreflight(true);
    setStreaming(true);
    setAutoFollowPhase(true);
    setPageError(null);
    try {
      await submitPlanDraftPreflight(draft.id, preflightAnswers, skip);
      await loadDraft(draft.id);
    } catch (caught) {
      setStreaming(false);
      setPageError(
        caught instanceof Error
          ? caught.message
          : "Failed to submit preflight answers.",
      );
    } finally {
      setSubmittingPreflight(false);
    }
  };

  const handleSubmitRepair = async (): Promise<void> => {
    if (!draft) {
      return;
    }
    setSubmittingRepair(true);
    setStreaming(true);
    setAutoFollowPhase(true);
    setPageError(null);
    try {
      await submitPlanDraftRepair(draft.id, draft.revision, repairAnswers, {
        loop_no: draft.repair_context?.loop_no ?? null,
        repair_round: draft.repair_context?.repair_round ?? null,
        source_version_id: draft.repair_context?.source_version_id ?? null,
      });
      await loadDraft(draft.id);
    } catch (caught) {
      setStreaming(false);
      setPageError(
        caught instanceof Error
          ? caught.message
          : "Failed to submit repair answers.",
      );
    } finally {
      setSubmittingRepair(false);
    }
  };

  const validationIssues = draftValidationIssues(draft);
  const advisoryIssues = useMemo(
    () =>
      loadingModels
        ? []
        : collectAdvisoryFlightChecks(
          draft,
          Array.from(new Set(models.map((model) => model.model ?? model.model_id ?? model.id))),
        ),
    [draft, loadingModels, models],
  );
  const currentRun = latestRun(draft);
  const streamEvents = useMemo(
    () => [...buildRunEvents(currentRun), ...liveEvents].slice(-20),
    [currentRun, liveEvents],
  );
  const planFlow = useMemo(
    () => derivePlanFlow(draft, {
      conflictMessage,
      validationIssues,
    }),
    [draft, conflictMessage, validationIssues],
  );

  useEffect(() => {
    const selected = planFlow.phases.find((phase) => phase.id === selectedPhase);
    if (autoFollowPhase || !selected || !selected.available) {
      setSelectedPhase(planFlow.currentPhaseId);
    }
  }, [autoFollowPhase, planFlow.currentPhaseId, planFlow.phases, selectedPhase]);

  if (loadingDraft) {
    return (
      <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-dim">
        {pageError ?? "Loading planning draft..."}
      </div>
    );
  }

  const completedPhaseCount = planFlow.phases.filter((phase) => phase.status === "complete").length;
  const completedSubsteps = planFlow.substeps.filter((step) => step.status === "complete").length;
  const selectedPhaseState = planFlow.phases.find((phase) => phase.id === selectedPhase) ?? planFlow.phases[0];
  const heroAction = selectedPhase === planFlow.currentPhaseId
    ? planFlow.nextAction
    : selectedPhaseState.status === "complete"
      ? "Review what happened in this completed stage."
      : selectedPhaseState.status === "up_next"
        ? "This stage unlocks after the live stage completes."
        : selectedPhaseState.blocker ?? planFlow.nextAction;
  const latestFailed = latestFailedRun(draft);
  const handleTaskChange = (taskId: string, patch: Partial<MissionSpec["tasks"][number]>): void => {
    updateCurrentDraft((current) =>
      updateDraftSpec(current, {
        ...current.draft_spec,
        tasks: current.draft_spec.tasks.map((task) =>
          task.id === taskId ? { ...task, ...patch } : task,
        ),
      }),
    );
  };
  const handleNameChange = (value: string): void => {
    updateCurrentDraft((current) =>
      updateDraftSpec(current, {
        ...current.draft_spec,
        name: value,
      }),
    );
  };
  const handleGoalChange = (value: string): void => {
    updateCurrentDraft((current) =>
      updateDraftSpec(current, {
        ...current.draft_spec,
        goal: value,
      }),
    );
  };
  const handleDodChange = (value: string[]): void => {
    updateCurrentDraft((current) =>
      updateDraftSpec(current, {
        ...current.draft_spec,
        definition_of_done: value,
      }),
    );
  };
  const handleWorkerProfileChange = (value: string): void => {
    const selected = models.find((model) => model.id === value);
    const profile = executionProfileFromOption(selected);
    if (!profile) {
      return;
    }
    updateCurrentDraft((current) =>
      updateDraftSpec(current, {
        ...current.draft_spec,
        execution_defaults: {
          ...current.draft_spec.execution_defaults,
          worker: profile,
          reviewer: current.draft_spec.execution_defaults?.reviewer ?? {
            agent: "codex",
            thinking: "medium",
            model:
              current.draft_spec.execution_defaults?.reviewer?.model ??
              models[0]?.id ??
              "",
          },
        },
      }),
    );
  };
  const handleReviewerProfileChange = (value: string): void => {
    const selected = models.find((model) => model.id === value);
    const profile = executionProfileFromOption(selected);
    if (!profile) {
      return;
    }
    updateCurrentDraft((current) =>
      updateDraftSpec(current, {
        ...current.draft_spec,
        execution_defaults: {
          ...current.draft_spec.execution_defaults,
          worker: current.draft_spec.execution_defaults?.worker ?? {
            agent: "codex",
            thinking: "medium",
            model:
              current.draft_spec.execution_defaults?.worker?.model ??
              models[0]?.id ??
              "",
          },
          reviewer: profile,
        },
      }),
    );
  };

  const toggleSupportPanel = (panel: SupportPanelId): void => {
    setActiveSupportPanel((current) => (current === panel ? null : panel));
  };

  const supportPanelMeta = activeSupportPanel
    ? {
        edit: {
          title: "Edit Mission",
          description: "Mission summary, task sequencing, and execution defaults live here when you need to revise the plan.",
          label: "Edit mission panel",
        },
        transcript: {
          title: "Planner Transcript",
          description: "Review the conversation with the planner and send follow-up instructions without crowding the main stage.",
          label: "Planner transcript panel",
        },
        logbook: {
          title: "Mission Logbook",
          description: "Run history, changelog checkpoints, and planner stream stay archived here for on-demand review.",
          label: "Mission logbook panel",
        },
      }[activeSupportPanel]
    : null;

  const supportPanelContent = !draft || !activeSupportPanel ? null : (
    activeSupportPanel === "edit" ? (
      <div className="space-y-5">
        <ValidationBoard
          conflictMessage={conflictMessage}
          summaryIssues={validationIssues}
          advisoryIssues={advisoryIssues}
        />
        <EngineeringControls
          draft={draft}
          models={models}
          savingDraft={savingDraft}
          onSaveSummary={() => {
            void persistDraftSpec();
          }}
          onTaskChange={handleTaskChange}
          onNameChange={handleNameChange}
          onGoalChange={handleGoalChange}
          onDodChange={handleDodChange}
          onWorkerProfileChange={handleWorkerProfileChange}
          onReviewerProfileChange={handleReviewerProfileChange}
        />
      </div>
    ) : activeSupportPanel === "transcript" ? (
      <PlannerTranscriptPanel
        turns={draft.turns}
        message={followUpMessage}
        busy={streaming || draft.preflight_status === "pending"}
        onMessageChange={setFollowUpMessage}
        onSend={() => {
          void handleFollowUp();
        }}
      />
    ) : (
      <div className="space-y-5">
        <PlanHistoryPanel
          draft={draft}
          retryingRunId={retryingRunId}
          onRetryRun={(runId) => {
            void handleRetryRun(runId);
          }}
        />
        <PlannerStreamPanel events={streamEvents} busy={streaming} />
      </div>
    )
  );

  return (
    <div className="flex flex-col gap-6">
      <header className="page-head flex-wrap justify-between gap-4">
        <div>
          <h1 className="text-[clamp(1.7rem,3vw,2.35rem)] font-semibold tracking-[-0.04em] text-text">
            Flight Director Cockpit
          </h1>
          {draft?.draft_spec.name ? (
            <div className="mt-3 text-lg font-semibold tracking-[-0.03em] text-text">
              {draft.draft_spec.name}
            </div>
          ) : null}
          <p className="mt-2 max-w-[72ch] text-sm leading-7 text-dim">
            Guided mission planning with a live orbital map of what is happening now, what already happened, and what still blocks launch.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px] text-dim">
          <span className="rounded-full border border-border bg-surface px-3 py-1">
            {draft ? `Draft ${draft.id}` : "No draft"}
          </span>
          <span className={`rounded-full border px-3 py-1 ${planFlow.launchReadiness.ready ? "border-green/30 bg-green/10 text-green" : "border-amber/30 bg-amber/10 text-amber"}`}>
            {planFlow.launchReadiness.ready ? "Launch Ready" : "Launch Blocked"}
          </span>
        </div>
      </header>

      {pageError ? (
        <div className="rounded-lg border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
          {pageError}
        </div>
      ) : null}

      <FlightPlanProgressRail
        phases={planFlow.phases}
        selectedPhase={selectedPhase}
        onSelectPhase={(phaseId) => {
          setAutoFollowPhase(false);
          setSelectedPhase(phaseId);
        }}
      />

      <PhaseHero
        phaseLabel={selectedPhaseState.label}
        selectedPhaseStatus={selectedPhaseState.status}
        currentPhaseId={planFlow.currentPhaseId}
        nextAction={heroAction}
        activeSummary={selectedPhaseState.summary}
        currentRun={planFlow.currentRun}
        currentVersion={planFlow.latestVersion}
        completedPhases={completedPhaseCount}
        completedSubsteps={completedSubsteps}
        latestRunIssue={selectedPhase === planFlow.currentPhaseId ? planFlow.latestRunIssue : null}
        launchReadinessSummary={planFlow.launchReadiness.summary}
        latestFailed={latestFailed}
        retryingRunId={retryingRunId}
        onRetryLatestRun={(runId) => {
          void handleRetryRun(runId);
        }}
      />

      {!draft ? (
        <section className="rounded-[1.15rem] border border-border bg-card p-5">
          <div className="mb-5 max-w-[62ch]">
            <h2 className="section-title">Mission Brief</h2>
            <p className="mt-2 text-sm leading-7 text-dim">
              Define the mission, choose the workspaces, approve the planning models, and open the flight plan. Nothing else needs attention yet.
            </p>
          </div>
          <section className="rounded-[1.15rem] border border-border bg-card p-5">
            <label
              className="block text-sm font-medium text-text"
              htmlFor="plan-prompt"
            >
              Mission prompt
            </label>
            <textarea
              id="plan-prompt"
              rows={8}
              className="mt-2 w-full rounded-lg border border-border bg-surface p-3 text-sm text-text outline-none placeholder:text-dim focus:border-cyan"
              placeholder="Describe what you want to build..."
              value={prompt}
              onInput={(event) => setPrompt(event.currentTarget.value)}
            />

            <div className="mt-4">
              <div className="mb-2 text-sm font-medium text-text">
                Working directories
              </div>
              <FileBrowser selected={workspaces} onSelect={setWorkspaces} />
            </div>

            <div className="mt-4">
              <div className="mb-2 text-sm font-medium text-text">
                Planning Stack
              </div>
              <p className="text-xs text-dim">
                Choose the exact `Model + Thinking` profile for each planning role.
              </p>
            </div>

            <div className="mt-4">
              <div className="grid gap-4 sm:grid-cols-2">
                {PLANNING_PROFILE_KEYS.map(({ key, label }) => {
                  const selectedProfileId = optionIdFromExecutionProfile(
                    initialPlanningProfiles[key],
                    models,
                  );
                  return (
                    <div
                      key={key}
                      className="rounded-xl border border-border bg-surface p-3"
                    >
                      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted">
                        {label}
                      </div>
                      <ExecutionProfileSelect
                        options={models}
                        value={selectedProfileId}
                        onChange={(value) => {
                          const selected = models.find((item) => item.id === value);
                          const profile = executionProfileFromOption(selected);
                          if (!profile) {
                            return;
                          }
                          setInitialPlanningProfiles((current) => ({
                            ...current,
                            [key]: profile,
                          }));
                        }}
                        className="w-full rounded-lg border border-border bg-card px-2 py-1.5 text-xs text-text outline-none focus:border-cyan"
                        ariaLabel={`${label} execution profile`}
                      />
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="mt-5 flex items-center justify-between gap-3">
              <span className="text-[11px] text-dim">
                {loadingModels
                  ? "Loading models..."
                  : `${PLANNING_PROFILE_KEYS.length} execution profile(s) armed`}
              </span>
              <button
                type="button"
                disabled={!canCreateDraft || creatingDraft}
                className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => {
                  void handleCreateDraft();
                }}
              >
                Open Flight Plan
              </button>
            </div>
          </section>
        </section>
      ) : (
        <div className={activeSupportPanel ? "grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]" : "space-y-5"}>
          <div className="space-y-5">
            <SupportDock
              activePanel={activeSupportPanel}
              onToggle={toggleSupportPanel}
            />
            <PhaseViewport
              selectedPhase={selectedPhase}
              draft={draft}
              substeps={planFlow.substeps}
              retryingRunId={retryingRunId}
              loadingModels={loadingModels}
              conflictMessage={conflictMessage}
              summaryIssues={validationIssues}
              advisoryIssues={advisoryIssues}
              preflightAnswers={preflightAnswers}
              submittingPreflight={submittingPreflight}
              repairAnswers={repairAnswers}
              submittingRepair={submittingRepair}
              currentRun={currentRun}
              streaming={streaming}
              launching={launching}
              launchReadiness={planFlow.launchReadiness}
              onRetryRun={(runId) => {
                void handleRetryRun(runId);
              }}
              onAnswerChange={(questionId, answer) => {
                const updater = draft?.repair_status === "pending" ? setRepairAnswers : setPreflightAnswers;
                updater((current) => ({
                  ...current,
                  [questionId]: answer,
                }));
              }}
              onSubmitPreflight={() => {
                void handleSubmitPreflight(false);
              }}
              onSkipPreflight={() => {
                void handleSubmitPreflight(true);
              }}
              onSubmitRepair={() => {
                void handleSubmitRepair();
              }}
              onLaunch={() => {
                void handleLaunch();
              }}
              onOpenSupportPanel={(panel) => {
                setActiveSupportPanel(panel);
              }}
            />
          </div>
          {supportPanelMeta && supportPanelContent ? (
            <CockpitSupportDrawer
              title={supportPanelMeta.title}
              description={supportPanelMeta.description}
              label={supportPanelMeta.label}
              onClose={() => setActiveSupportPanel(null)}
            >
              {supportPanelContent}
            </CockpitSupportDrawer>
          ) : null}
        </div>
      )}
    </div>
  );
}
