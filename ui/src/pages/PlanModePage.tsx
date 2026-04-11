import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import FileBrowser from "../components/FileBrowser";
import ModelSelector from "../components/ModelSelector";
import SpaceProgress from "../components/SpaceProgress";
import DraftSummaryPanel from "../components/planning/DraftSummaryPanel";
import BlackHoleConfigPanel from "../components/planning/BlackHoleConfigPanel";
import BlackHoleHero from "../components/planning/BlackHoleHero";
import BlackHoleLedger from "../components/planning/BlackHoleLedger";
import CockpitSupportDrawer from "../components/planning/CockpitSupportDrawer";
import ExecutionProfileControls from "../components/planning/ExecutionProfileControls";
import FlightPlanProgressRail from "../components/planning/FlightPlanProgressRail";
import PlannerStreamPanel, {
  type PlannerStreamEventView,
} from "../components/planning/PlannerStreamPanel";
import PlannerTranscriptPanel from "../components/planning/PlannerTranscriptPanel";
import PlanningSubstepTracker from "../components/planning/PlanningSubstepTracker";
import TaskTimelinePanel from "../components/planning/TaskTimelinePanel";
import ValidationBoard from "../components/planning/ValidationBoard";
import {
  createBlackHoleCampaign,
  createPlanDraft,
  getBlackHoleCampaign,
  getModels,
  getPlanDraft,
  patchPlanDraftSpec,
  pauseBlackHoleCampaign,
  resumeBlackHoleCampaign,
  retryPlanRun,
  sendPlanDraftMessage,
  startPlanDraft,
  stopBlackHoleCampaign,
  submitPlanDraftPreflight,
} from "../lib/api";
import {
  type CockpitPhaseId,
  derivePlanFlow,
  type PlanningSubstepId,
} from "../lib/planFlow";
import { collectAdvisoryFlightChecks } from "../lib/planChecks";
import type {
  BlackHoleCampaignState,
  BlackHoleConfig,
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
  type BlackHoleCampaignUpdatedEvent,
  type BlackHoleLoopRecordedEvent,
  type PlanningEvent,
} from "../lib/ws";

const PLANNING_PROFILE_KEYS = [
  { key: "planner", label: "Planner" },
  { key: "critic_technical", label: "Technical Critic" },
  { key: "critic_practical", label: "Practical Critic" },
  { key: "resolver", label: "Resolver" },
] as const;

const PLANMODE_PERSISTED_WORKSPACES_KEY = "agentforce-planmode-workspaces-v1";
const PLANMODE_PERSISTED_MODELS_KEY = "agentforce-planmode-models-v1";
const PLANMODE_PERSISTED_PROFILES_KEY = "agentforce-planmode-profiles-v1";
const THINKING_LEVELS = ["low", "medium", "high", "xhigh"] as const;

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
  const thinking = typeof candidate.thinking === "string"
    && THINKING_LEVELS.includes(candidate.thinking as typeof THINKING_LEVELS[number])
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

function defaultBlackHoleConfig(draft: MissionDraft): BlackHoleConfig {
  return {
    mode: "black_hole",
    objective: draft.draft_spec.goal || firstTurnPrompt(draft) || "Iteratively improve the repository until the acceptance criteria is satisfied.",
    analyzer: "python_fn_length",
    scope: "repo",
    global_acceptance: [],
    loop_limits: {
      max_loops: 8,
      max_no_progress: 2,
      function_line_limit: 300,
    },
    gate_policy: {
      require_test_delta: true,
      public_surface_policy: "justify",
    },
    docs_manifest_path: null,
    notes: "",
  };
}

function normalizeBlackHoleConfig(value: unknown, draft: MissionDraft): BlackHoleConfig {
  const defaults = defaultBlackHoleConfig(draft);
  if (!value || typeof value !== "object") {
    return defaults;
  }
  const candidate = value as Record<string, unknown>;
  const loopLimits = candidate.loop_limits && typeof candidate.loop_limits === "object"
    ? candidate.loop_limits as Record<string, unknown>
    : {};
  const gatePolicy = candidate.gate_policy && typeof candidate.gate_policy === "object"
    ? candidate.gate_policy as Record<string, unknown>
    : {};
  return {
    ...defaults,
    mode: "black_hole",
    objective: typeof candidate.objective === "string" && candidate.objective.trim() ? candidate.objective : defaults.objective,
    analyzer: typeof candidate.analyzer === "string" && candidate.analyzer.trim() ? candidate.analyzer : defaults.analyzer,
    scope: typeof candidate.scope === "string" && candidate.scope.trim() ? candidate.scope : defaults.scope,
    global_acceptance: Array.isArray(candidate.global_acceptance) ? candidate.global_acceptance.map(String) : defaults.global_acceptance,
    loop_limits: {
      max_loops: typeof loopLimits.max_loops === "number" ? loopLimits.max_loops : defaults.loop_limits.max_loops,
      max_no_progress: typeof loopLimits.max_no_progress === "number" ? loopLimits.max_no_progress : defaults.loop_limits.max_no_progress,
      function_line_limit: typeof loopLimits.function_line_limit === "number"
        ? loopLimits.function_line_limit
        : defaults.loop_limits.function_line_limit,
    },
    gate_policy: {
      require_test_delta: typeof gatePolicy.require_test_delta === "boolean"
        ? gatePolicy.require_test_delta
        : defaults.gate_policy?.require_test_delta,
      public_surface_policy: typeof gatePolicy.public_surface_policy === "string"
        ? gatePolicy.public_surface_policy
        : defaults.gate_policy?.public_surface_policy,
    },
    docs_manifest_path: typeof candidate.docs_manifest_path === "string" && candidate.docs_manifest_path.trim()
      ? candidate.docs_manifest_path
      : null,
    notes: typeof candidate.notes === "string" ? candidate.notes : defaults.notes,
  };
}

function hasPersistedBlackHoleConfig(draft: MissionDraft | null): boolean {
  return Boolean(draft && draft.validation && typeof draft.validation.black_hole_config === "object" && draft.validation.black_hole_config);
}

function blackHoleMetricLabel(config: BlackHoleConfig | null): string {
  if (!config) {
    return "Campaign metric";
  }
  if (config.analyzer === "docs_section_coverage") {
    return "Missing manifest paths";
  }
  return `Functions > ${config.loop_limits.function_line_limit ?? 300} lines`;
}

function blackHoleMetricValue(
  config: BlackHoleConfig | null,
  metric: Record<string, unknown> | undefined,
): string | number {
  if (!metric) {
    return "—";
  }
  if (config?.analyzer === "docs_section_coverage") {
    const missing = metric.missing_paths;
    return typeof missing === "number" ? missing : "—";
  }
  const violations = metric.violations;
  return typeof violations === "number" ? violations : "—";
}

function blackHoleHeroDescription(config: BlackHoleConfig | null, campaign: BlackHoleCampaignState["campaign"]): string {
  if (campaign?.stop_reason) {
    return campaign.stop_reason;
  }
  if (!config) {
    return "The accretion disk stays alive between loops so the current campaign state is always visible.";
  }
  if (config.analyzer === "docs_section_coverage") {
    return "The lensed arcs track documentation coverage gaps while the central ring reflects the currently targeted section.";
  }
  return `The bright crescent reflects the hottest refactor target while the outer arcs stay warped around the current ${config.loop_limits.function_line_limit ?? 300}-line limit.`;
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

function PreflightQuestionsPanel({
  draft,
  answers,
  submitting,
  onAnswerChange,
  onSubmit,
  onSkip,
}: {
  draft: MissionDraft;
  answers: Record<string, PreflightAnswer>;
  submitting: boolean;
  onAnswerChange: (questionId: string, answer: PreflightAnswer) => void;
  onSubmit: () => void;
  onSkip: () => void;
}) {
  const questions = draft.preflight_questions ?? [];

  return (
    <section className="rounded-[1.15rem] border border-amber/30 bg-[radial-gradient(circle_at_top,rgba(251,191,36,0.12),transparent_62%),var(--color-card)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">Preflight Questions</h2>
          <p className="mt-1 text-xs text-dim">
            Clarify only what changes structure, dependencies, or acceptance criteria.
          </p>
        </div>
        <div className="rounded-full border border-amber/30 bg-amber/10 px-3 py-1 font-mono text-[11px] text-amber">
          {questions.length} pending
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {questions.map((question, index) => {
          const answer = answers[question.id] ?? {};
          return (
            <article
              key={question.id}
              className="rounded-xl border border-border bg-surface p-3"
            >
              <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                Question {index + 1}
              </div>
              <div className="mt-2 text-sm font-semibold text-text">
                {question.prompt}
              </div>
              {question.reason ? (
                <p className="mt-1 text-xs text-dim">{question.reason}</p>
              ) : null}
              <div className="mt-3 grid gap-2">
                {question.options.map((option) => (
                  <label
                    key={`${question.id}-${option}`}
                    className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-text"
                  >
                    <input
                      type="radio"
                      name={`preflight-${question.id}`}
                      checked={answer.selected_option === option}
                      onChange={() =>
                        onAnswerChange(question.id, {
                          ...answer,
                          selected_option: option,
                        })}
                    />
                    <span>{option}</span>
                  </label>
                ))}
                {question.allow_custom !== false ? (
                  <input
                    className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                    placeholder="Custom reply"
                    value={answer.custom_answer ?? ""}
                    onChange={(event) =>
                      onAnswerChange(question.id, {
                        ...answer,
                        custom_answer: event.currentTarget.value,
                      })}
                  />
                ) : null}
              </div>
            </article>
          );
        })}
      </div>

      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button
          type="button"
          className="rounded-full border border-border px-4 py-2 text-sm font-semibold text-dim transition-colors hover:bg-card-hover disabled:cursor-not-allowed disabled:opacity-50"
          disabled={submitting}
          onClick={onSkip}
        >
          Skip For Now
        </button>
        <button
          type="button"
          className="rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={submitting}
          onClick={onSubmit}
        >
          Start Planning
        </button>
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
          const modelObj = models.find((model) => model.id === profile.model);
          const modelName = modelObj
            ? `[${modelObj.provider}] ${modelObj.name}`
            : profile.model || "Default";
          return (
            <div key={key} className="rounded-lg border border-border bg-surface p-3">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                {label}
              </div>
              <div className="truncate text-sm font-semibold text-text" title={modelName}>
                {modelName}
              </div>
              <div className="mt-1 text-xs text-dim">
                Thinking <span className="font-medium text-text">{profile.thinking}</span>
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
  onWorkerModelChange,
  onReviewerModelChange,
  onWorkerThinkingChange,
  onReviewerThinkingChange,
}: {
  draft: MissionDraft;
  models: Model[];
  savingDraft: boolean;
  onSaveSummary: () => void;
  onTaskChange: (taskId: string, patch: Partial<MissionSpec["tasks"][number]>) => void;
  onNameChange: (value: string) => void;
  onGoalChange: (value: string) => void;
  onDodChange: (value: string[]) => void;
  onWorkerModelChange: (value: string) => void;
  onReviewerModelChange: (value: string) => void;
  onWorkerThinkingChange: (value: string) => void;
  onReviewerThinkingChange: (value: string) => void;
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
        models={models}
        onWorkerModelChange={onWorkerModelChange}
        onReviewerModelChange={onReviewerModelChange}
        onWorkerThinkingChange={onWorkerThinkingChange}
        onReviewerThinkingChange={onReviewerThinkingChange}
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
  currentRun,
  streaming,
  launching,
  launchReadiness,
  onRetryRun,
  onAnswerChange,
  onSubmitPreflight,
  onSkipPreflight,
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
  currentRun: PlanRun | null;
  streaming: boolean;
  launching: boolean;
  launchReadiness: ReturnType<typeof derivePlanFlow>["launchReadiness"];
  onRetryRun: (runId: string) => void;
  onAnswerChange: (questionId: string, answer: PreflightAnswer) => void;
  onSubmitPreflight: () => void;
  onSkipPreflight: () => void;
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
                  {draft.approved_models.length} approved model{draft.approved_models.length === 1 ? "" : "s"}
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

    return (
      <section className="rounded-[1.15rem] border border-border bg-card p-5">
        <h2 className="section-title">Preflight Complete</h2>
        <p className="mt-3 max-w-[62ch] text-sm leading-7 text-dim">
          Clarifications are resolved. The cockpit will keep the recorded answers in the transcript and logbook without competing with the live stage.
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
  const [selectedModels, setSelectedModels] = useState<string[]>(
    readStoredJson<string[]>(PLANMODE_PERSISTED_MODELS_KEY, []),
  );
  const [initialPlanningProfiles, setInitialPlanningProfiles] = useState<Record<string, ExecutionProfile>>(
    normalizePlanningProfiles(readStoredJson<Record<string, unknown>>(PLANMODE_PERSISTED_PROFILES_KEY, getDefaultPlanProfiles())),
  );
  const [draft, setDraft] = useState<MissionDraft | null>(null);
  const [blackHoleState, setBlackHoleState] = useState<BlackHoleCampaignState | null>(null);
  const [blackHoleConfigDraft, setBlackHoleConfigDraft] = useState<BlackHoleConfig | null>(null);
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
  const [syncingBlackHole, setSyncingBlackHole] = useState(false);
  const [preflightAnswers, setPreflightAnswers] = useState<Record<string, PreflightAnswer>>({});
  const [pageError, setPageError] = useState<string | null>(null);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);

  const effectiveSelectedModels = useMemo(
    () =>
      selectedModels.length > 0
        ? selectedModels
        : models.map((model) => model.id),
    [models, selectedModels],
  );

  const loadDraft = async (nextDraftId: string): Promise<void> => {
    setLoadingDraft(true);
    setPageError(null);
    try {
      const loaded = await getPlanDraft(nextDraftId);
      const persistedBlackHole = hasPersistedBlackHoleConfig(loaded)
        ? await getBlackHoleCampaign(nextDraftId)
        : {
            draft_id: nextDraftId,
            config: null,
            campaign: null,
            loops: [],
          };
      setDraft(loaded);
      setBlackHoleState(persistedBlackHole);
      setBlackHoleConfigDraft(
        normalizeBlackHoleConfig(
          persistedBlackHole.config ?? loaded.validation?.black_hole_config,
          loaded,
        ),
      );
      setStreaming(planningBusy(latestRun(loaded)));
      setPreflightAnswers(loaded.preflight_answers ?? {});
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
        const defaultModel = loadedModels[0]?.id || "";
        const defaultAgent = loadedModels[0]?.provider_id || "codex";
        const availableModelIds = new Set(loadedModels.map((model) => model.id));
        setSelectedModels((current) => {
          const valid = normalizeWorkspacePaths(current).filter((modelId) => availableModelIds.has(modelId));
          if (valid.length > 0) {
            return valid;
          }
          return loadedModels.map((model) => model.id);
        });

        setInitialPlanningProfiles((current) => {
          const next = { ...current };
          (Object.keys(next) as Array<keyof typeof next>).forEach((key) => {
            if (!availableModelIds.has(String(next[key].model || ""))) {
              next[key] = {
                ...next[key],
                model: defaultModel,
                agent: defaultAgent,
              };
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
      PLANMODE_PERSISTED_MODELS_KEY,
      JSON.stringify(selectedModels),
    );
  }, [selectedModels]);

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
      setBlackHoleState(null);
      setBlackHoleConfigDraft(null);
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

    const blackHoleHandler = (_event: BlackHoleCampaignUpdatedEvent | BlackHoleLoopRecordedEvent): void => {
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
    wsClient.on("black_hole_campaign_updated", blackHoleHandler);
    wsClient.on("black_hole_loop_recorded", blackHoleHandler);

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
      wsClient.off("black_hole_campaign_updated", blackHoleHandler);
      wsClient.off("black_hole_loop_recorded", blackHoleHandler);
    };
  }, [draftId]);

  const canCreateDraft =
    prompt.trim() !== "" &&
    workspaces.length > 0 &&
    effectiveSelectedModels.length > 0 &&
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
        approved_models: effectiveSelectedModels,
        workspace_paths: workspaces,
        companion_profile: {
          id: "planner",
          label: "Planner",
          ...initialPlanningProfiles.planner,
        },
        validation: {
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

  const handleStartBlackHole = async (): Promise<void> => {
    if (!draft || !blackHoleConfigDraft) {
      return;
    }
    setSyncingBlackHole(true);
    setPageError(null);
    setConflictMessage(null);
    try {
      await createBlackHoleCampaign(draft.id, draft.revision, blackHoleConfigDraft);
      await loadDraft(draft.id);
    } catch (caught) {
      setPageError(
        caught instanceof Error ? caught.message : "Failed to start black-hole campaign.",
      );
    } finally {
      setSyncingBlackHole(false);
    }
  };

  const handlePauseBlackHole = async (): Promise<void> => {
    if (!draft) {
      return;
    }
    setSyncingBlackHole(true);
    setPageError(null);
    try {
      await pauseBlackHoleCampaign(draft.id);
      await loadDraft(draft.id);
    } catch (caught) {
      setPageError(
        caught instanceof Error ? caught.message : "Failed to pause black-hole campaign.",
      );
    } finally {
      setSyncingBlackHole(false);
    }
  };

  const handleResumeBlackHole = async (): Promise<void> => {
    if (!draft) {
      return;
    }
    setSyncingBlackHole(true);
    setPageError(null);
    try {
      await resumeBlackHoleCampaign(draft.id, blackHoleConfigDraft ?? undefined);
      await loadDraft(draft.id);
    } catch (caught) {
      setPageError(
        caught instanceof Error ? caught.message : "Failed to resume black-hole campaign.",
      );
    } finally {
      setSyncingBlackHole(false);
    }
  };

  const handleStopBlackHole = async (): Promise<void> => {
    if (!draft) {
      return;
    }
    setSyncingBlackHole(true);
    setPageError(null);
    try {
      await stopBlackHoleCampaign(draft.id);
      await loadDraft(draft.id);
    } catch (caught) {
      setPageError(
        caught instanceof Error ? caught.message : "Failed to stop black-hole campaign.",
      );
    } finally {
      setSyncingBlackHole(false);
    }
  };

  const validationIssues = draftValidationIssues(draft);
  const advisoryIssues = useMemo(
    () =>
      loadingModels
        ? []
        : collectAdvisoryFlightChecks(
          draft,
          models.map((model) => model.id),
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
  const blackHoleCampaign = blackHoleState?.campaign ?? null;
  const blackHoleLoops = blackHoleState?.loops ?? [];
  const blackHoleActive = Boolean(blackHoleCampaign || hasPersistedBlackHoleConfig(draft));
  const latestBlackHoleLoop = blackHoleLoops[blackHoleLoops.length - 1];
  const blackHoleMetricName = blackHoleMetricLabel(blackHoleConfigDraft);

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
  const handleWorkerModelChange = (value: string): void => {
    updateCurrentDraft((current) =>
      updateDraftSpec(current, {
        ...current.draft_spec,
        execution_defaults: {
          ...current.draft_spec.execution_defaults,
          worker: {
            agent:
              current.draft_spec.execution_defaults?.worker?.agent ?? "codex",
            thinking:
              current.draft_spec.execution_defaults?.worker?.thinking ?? "medium",
            model: value,
          },
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
  const handleReviewerModelChange = (value: string): void => {
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
          reviewer: {
            agent:
              current.draft_spec.execution_defaults?.reviewer?.agent ?? "codex",
            thinking:
              current.draft_spec.execution_defaults?.reviewer?.thinking ?? "medium",
            model: value,
          },
        },
      }),
    );
  };
  const handleWorkerThinkingChange = (value: string): void => {
    updateCurrentDraft((current) =>
      updateDraftSpec(current, {
        ...current.draft_spec,
        execution_defaults: {
          ...current.draft_spec.execution_defaults,
          worker: {
            agent:
              current.draft_spec.execution_defaults?.worker?.agent ?? "codex",
            model:
              current.draft_spec.execution_defaults?.worker?.model ??
              models[0]?.id ??
              "",
            thinking: value,
          },
          reviewer: current.draft_spec.execution_defaults?.reviewer ?? {
            agent: "codex",
            model:
              current.draft_spec.execution_defaults?.reviewer?.model ??
              models[0]?.id ??
              "",
            thinking: "medium",
          },
        },
      }),
    );
  };
  const handleReviewerThinkingChange = (value: string): void => {
    updateCurrentDraft((current) =>
      updateDraftSpec(current, {
        ...current.draft_spec,
        execution_defaults: {
          ...current.draft_spec.execution_defaults,
          worker: current.draft_spec.execution_defaults?.worker ?? {
            agent: "codex",
            model:
              current.draft_spec.execution_defaults?.worker?.model ??
              models[0]?.id ??
              "",
            thinking: "medium",
          },
          reviewer: {
            agent:
              current.draft_spec.execution_defaults?.reviewer?.agent ?? "codex",
            model:
              current.draft_spec.execution_defaults?.reviewer?.model ??
              models[0]?.id ??
              "",
            thinking: value,
          },
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
          onWorkerModelChange={handleWorkerModelChange}
          onReviewerModelChange={handleReviewerModelChange}
          onWorkerThinkingChange={handleWorkerThinkingChange}
          onReviewerThinkingChange={handleReviewerThinkingChange}
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

      {blackHoleActive ? (
        <BlackHoleHero
          campaignState={blackHoleCampaign?.status ?? "orbit_ready"}
          campaignStatus={blackHoleCampaign?.status}
          loopNumber={blackHoleCampaign?.current_loop ?? 0}
          metricLabel={blackHoleMetricName}
          metricBefore={blackHoleMetricValue(blackHoleConfigDraft, latestBlackHoleLoop?.metric_before as Record<string, unknown> | undefined)}
          metricAfter={blackHoleMetricValue(
            blackHoleConfigDraft,
            ((blackHoleCampaign?.last_metric as Record<string, unknown> | undefined) ?? (latestBlackHoleLoop?.metric_after as Record<string, unknown> | undefined)),
          )}
          title="Black Hole Campaign Telemetry"
          description={blackHoleHeroDescription(blackHoleConfigDraft, blackHoleCampaign)}
        />
      ) : (
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
      )}

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
                Approved models
              </div>
              <ModelSelector
                models={models}
                selected={effectiveSelectedModels}
                onChange={setSelectedModels}
              />
            </div>

            <div className="mt-6">
              <div className="mb-3 text-sm font-medium text-text">
                Planning Stack
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                {PLANNING_PROFILE_KEYS.map(({ key, label }) => {
                  const profile = initialPlanningProfiles[key];
                  return (
                    <div
                      key={key}
                      className="rounded-xl border border-border bg-surface p-3"
                    >
                      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted">
                        {label}
                      </div>
                      <div className="grid gap-2">
                        <select
                          className="w-full rounded-lg border border-border bg-card px-2 py-1.5 text-xs text-text outline-none focus:border-cyan"
                          value={profile.model ?? ""}
                          onChange={(event) => {
                            const modelId = event.target.value;
                            const model = models.find((item) => item.id === modelId);
                            setInitialPlanningProfiles((current) => ({
                              ...current,
                              [key]: {
                                ...profile,
                                model: modelId,
                                agent: model?.provider_id || profile.agent,
                              },
                            }));
                          }}
                        >
                          {models.map((model) => (
                            <option key={model.id} value={model.id}>
                              [{model.provider}] {model.name}
                            </option>
                          ))}
                        </select>
                        <select
                          className="w-full rounded-lg border border-border bg-card px-2 py-1.5 text-xs text-text outline-none focus:border-cyan"
                          value={profile.thinking ?? ""}
                          onChange={(event) =>
                            setInitialPlanningProfiles((current) => ({
                              ...current,
                              [key]: { ...profile, thinking: event.target.value },
                            }))}
                        >
                          {THINKING_LEVELS.map((thinking) => (
                            <option key={thinking} value={thinking}>
                              {thinking}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="mt-5 flex items-center justify-between gap-3">
              <span className="text-[11px] text-dim">
                {loadingModels
                  ? "Loading models..."
                  : `${effectiveSelectedModels.length} approved model(s) armed`}
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
            {blackHoleConfigDraft ? (
              <div className="grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(16rem,0.95fr)]">
                <BlackHoleConfigPanel
                  config={blackHoleConfigDraft}
                  campaign={blackHoleCampaign}
                  busy={syncingBlackHole}
                  onChange={setBlackHoleConfigDraft}
                  onStart={() => {
                    void handleStartBlackHole();
                  }}
                  onPause={() => {
                    void handlePauseBlackHole();
                  }}
                  onResume={() => {
                    void handleResumeBlackHole();
                  }}
                  onStop={() => {
                    void handleStopBlackHole();
                  }}
                />
                <BlackHoleLedger
                  campaign={blackHoleCampaign}
                  loops={blackHoleLoops}
                />
              </div>
            ) : null}
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
              currentRun={currentRun}
              streaming={streaming}
              launching={launching}
              launchReadiness={planFlow.launchReadiness}
              onRetryRun={(runId) => {
                void handleRetryRun(runId);
              }}
              onAnswerChange={(questionId, answer) => {
                setPreflightAnswers((current) => ({
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
