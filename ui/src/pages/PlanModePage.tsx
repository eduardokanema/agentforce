import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import FileBrowser from '../components/FileBrowser';
import ModelSelector from '../components/ModelSelector';
import DraftSummaryPanel from '../components/planning/DraftSummaryPanel';
import ExecutionProfileControls from '../components/planning/ExecutionProfileControls';
import PlannerStreamPanel, { type PlannerStreamEventView } from '../components/planning/PlannerStreamPanel';
import PlannerTranscriptPanel from '../components/planning/PlannerTranscriptPanel';
import TaskTimelinePanel from '../components/planning/TaskTimelinePanel';
import ValidationBoard from '../components/planning/ValidationBoard';
import {
  createPlanDraft,
  getModels,
  getPlanDraft,
  patchPlanDraftSpec,
  sendPlanDraftMessage,
  startPlanDraft,
  submitPlanDraftPreflight,
} from '../lib/api';
import { collectAdvisoryFlightChecks } from '../lib/planChecks';
import type {
  ExecutionProfile,
  MissionDraft,
  MissionSpec,
  Model,
  PlanRun,
  PlanVersion,
  PreflightAnswer,
} from '../lib/types';
import { wsClient, type PlanningEvent } from '../lib/ws';

const PLANNING_PROFILE_KEYS = [
  { key: 'planner', label: 'Planner' },
  { key: 'critic_technical', label: 'Technical Critic' },
  { key: 'critic_practical', label: 'Practical Critic' },
  { key: 'resolver', label: 'Resolver' },
] as const;

const PLANNING_AGENTS = ['codex', 'claude', 'opencode'] as const;
const THINKING_LEVELS = ['low', 'medium', 'high', 'xhigh'] as const;

function getConflictMessage(caught: unknown): string | null {
  const error = caught as Error & { status?: number; payload?: { error?: string; revision?: number } };
  if (error.status !== 409) {
    return null;
  }
  const revision = typeof error.payload?.revision === 'number'
    ? ` Reload the latest draft revision ${error.payload.revision}.`
    : '';
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
  if (draft.draft_spec.name.trim() === '') {
    issues.push('Mission name is required.');
  }
  if (draft.draft_spec.goal.trim() === '') {
    issues.push('Mission goal is required.');
  }
  if (draft.draft_spec.tasks.length === 0) {
    issues.push('Add at least one task.');
  }
  return issues;
}

function getPlanningProfiles(draft: MissionDraft | null): Record<string, ExecutionProfile> {
  const raw = draft?.validation?.planning_profiles;
  if (!raw || typeof raw !== 'object') {
    return {};
  }
  return raw as Record<string, ExecutionProfile>;
}

function getProfileValue(
  draft: MissionDraft | null,
  key: string,
): ExecutionProfile {
  const stored = getPlanningProfiles(draft)[key] ?? {};
  return {
    agent: stored.agent ?? 'codex',
    model: stored.model ?? 'gpt-5.4',
    thinking: stored.thinking ?? (key === 'critic_technical' || key === 'critic_practical' ? 'xhigh' : 'high'),
  };
}

function formatCurrency(value: number | undefined): string {
  return `$${(value ?? 0).toFixed(4)}`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return 'Pending';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function summarizeStep(stepName: string): string {
  return stepName.replace(/_/g, ' ');
}

function toPlannerEventView(event: PlanningEvent): PlannerStreamEventView {
  return {
    type: event.type,
    phase: event.step ?? event.plan_version_id ?? 'runtime',
    status: event.status ?? (event.type.includes('started') ? 'started' : 'updated'),
    content: event.summary ?? event.message,
  };
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
  }));
}

function planningBusy(run: PlanRun | null): boolean {
  return run?.status === 'queued' || run?.status === 'running';
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
    <section className="rounded-lg border border-amber/30 bg-[radial-gradient(circle_at_top,rgba(251,191,36,0.12),transparent_62%),var(--color-card)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">Preflight Questions</h2>
          <p className="mt-1 text-xs text-dim">Answer the important clarifications before the first full planning run. Each question supports a custom reply when the listed options do not fit.</p>
        </div>
        <div className="rounded-full border border-amber/30 bg-amber/10 px-3 py-1 font-mono text-[11px] text-amber">
          {questions.length} pending
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {questions.map((question, index) => {
          const answer = answers[question.id] ?? {};
          return (
            <article key={question.id} className="rounded-xl border border-border bg-surface p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Question {index + 1}</div>
                  <div className="mt-1 text-sm font-semibold text-text">{question.prompt}</div>
                  {question.reason ? (
                    <p className="mt-1 text-xs text-dim">{question.reason}</p>
                  ) : null}
                </div>
              </div>
              <div className="mt-3 grid gap-2">
                {question.options.map((option) => (
                  <label key={`${question.id}-${option}`} className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-text">
                    <input
                      type="radio"
                      name={`preflight-${question.id}`}
                      checked={answer.selected_option === option}
                      onChange={() => onAnswerChange(question.id, { ...answer, selected_option: option })}
                    />
                    <span>{option}</span>
                  </label>
                ))}
                {question.allow_custom !== false ? (
                  <input
                    className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                    placeholder="Custom reply"
                    value={answer.custom_answer ?? ''}
                    onChange={(event) => onAnswerChange(question.id, { ...answer, custom_answer: event.currentTarget.value })}
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

function PlanningProfilesPanel({
  draft,
  models,
  onChange,
}: {
  draft: MissionDraft;
  models: Model[];
  onChange: (key: string, profile: ExecutionProfile) => void;
}) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3">
        <h2 className="section-title">Planning Stack</h2>
        <p className="mt-1 text-xs text-dim">Planner, adversaries, and resolver use the current model interfaces and persist with the draft.</p>
      </div>
      <div className="space-y-3">
        {PLANNING_PROFILE_KEYS.map(({ key, label }) => {
          const profile = getProfileValue(draft, key);
          return (
            <div key={key} className="rounded-lg border border-border bg-surface p-3">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">{label}</div>
              <div className="grid gap-3 md:grid-cols-3">
                <label className="text-xs text-dim">
                  Agent
                  <select
                    className="mt-1 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                    value={profile.agent ?? 'codex'}
                    onChange={(event) => onChange(key, { ...profile, agent: event.currentTarget.value })}
                  >
                    {PLANNING_AGENTS.map((agent) => (
                      <option key={`${key}-${agent}`} value={agent}>{agent}</option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-dim">
                  Model
                  <select
                    className="mt-1 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                    value={profile.model ?? ''}
                    onChange={(event) => onChange(key, { ...profile, model: event.currentTarget.value })}
                  >
                    <option value="gpt-5.4">gpt-5.4</option>
                    {models.map((model) => (
                      <option key={`${key}-${model.id}`} value={model.id}>{model.name}</option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-dim">
                  Thinking
                  <select
                    className="mt-1 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                    value={profile.thinking ?? 'high'}
                    onChange={(event) => onChange(key, { ...profile, thinking: event.currentTarget.value })}
                  >
                    {THINKING_LEVELS.map((thinking) => (
                      <option key={`${key}-${thinking}`} value={thinking}>{thinking}</option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function PlanHistoryPanel({ draft }: { draft: MissionDraft }) {
  const currentRun = latestRun(draft);
  const currentVersion = latestVersion(draft);

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="section-title">Planning History</h2>
          <p className="mt-1 text-xs text-dim">Stored runs, versions, and changelog checkpoints for future reviews and metrics.</p>
        </div>
        <div className="rounded-full border border-cyan/20 bg-cyan/10 px-3 py-1 text-[11px] font-mono text-cyan">
          {currentRun ? `${formatCurrency(currentRun.cost_usd)} planning` : 'No runs yet'}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1.05fr)_minmax(16rem,0.95fr)]">
        <div className="space-y-3">
          {(draft.plan_runs ?? []).map((run) => (
            <article
              key={run.id}
              className={`rounded-xl border px-3 py-3 transition-all ${
                run.status === 'running'
                  ? 'border-cyan/40 bg-cyan/10 shadow-[0_0_0_1px_rgba(34,211,238,0.08)]'
                  : 'border-border bg-surface'
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-semibold text-text">{run.trigger_kind === 'follow_up' ? 'Follow-up run' : 'Initial run'}</div>
                <div className="rounded-full border border-border bg-card px-2.5 py-1 font-mono text-[11px] text-dim">
                  {run.status}
                </div>
              </div>
              <p className="mt-2 text-sm text-text">{run.trigger_message || 'Automatic first-pass planning run.'}</p>
              <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-dim">
                <span className="rounded-full border border-border bg-card px-2.5 py-1">Revision {run.base_revision}</span>
                <span className="rounded-full border border-border bg-card px-2.5 py-1">{run.steps.length} steps</span>
                <span className="rounded-full border border-border bg-card px-2.5 py-1">{formatCurrency(run.cost_usd)}</span>
              </div>
            </article>
          ))}
          {(draft.plan_runs ?? []).length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-dim">
              No planning runs stored yet.
            </div>
          ) : null}
        </div>

        <div className="rounded-xl border border-border bg-surface p-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Latest Version</div>
          <div className="mt-2 text-sm font-semibold text-text">
            {currentVersion ? currentVersion.id : 'Pending'}
          </div>
          <div className="mt-1 text-xs text-dim">
            {currentVersion ? `Created ${formatDateTime(currentVersion.created_at)}` : 'No version checkpoint yet.'}
          </div>
          <div className="mt-3 space-y-2">
            {(currentVersion?.changelog ?? draft.planning_summary?.changelog ?? []).map((entry, index) => (
              <div key={`${entry}-${index}`} className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-text">
                {entry}
              </div>
            ))}
            {!(currentVersion?.changelog?.length || draft.planning_summary?.changelog?.length) ? (
              <div className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-dim">
                The reviewed changelog will appear here after the resolver finishes.
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}

export default function PlanModePage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const draftId = searchParams.get('draft');

  const [prompt, setPrompt] = useState('');
  const [workspaces, setWorkspaces] = useState<string[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [companionModel, setCompanionModel] = useState('');
  const [draft, setDraft] = useState<MissionDraft | null>(null);
  const [followUpMessage, setFollowUpMessage] = useState('');
  const [liveEvents, setLiveEvents] = useState<PlannerStreamEventView[]>([]);
  const [loadingModels, setLoadingModels] = useState(true);
  const [loadingDraft, setLoadingDraft] = useState(false);
  const [creatingDraft, setCreatingDraft] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [submittingPreflight, setSubmittingPreflight] = useState(false);
  const [preflightAnswers, setPreflightAnswers] = useState<Record<string, PreflightAnswer>>({});
  const [pageError, setPageError] = useState<string | null>(null);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);

  const effectiveSelectedModels = useMemo(
    () => (selectedModels.length > 0 ? selectedModels : models.map((model) => model.id)),
    [models, selectedModels],
  );

  const loadDraft = async (id: string): Promise<void> => {
    setLoadingDraft(true);
    setPageError(null);
    try {
      const loaded = await getPlanDraft(id);
      setDraft(loaded);
      setStreaming(planningBusy(latestRun(loaded)));
      setPreflightAnswers(loaded.preflight_answers ?? {});
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : 'Failed to load draft.');
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
        setSelectedModels((current) => (current.length > 0 ? current : loadedModels.map((model) => model.id)));
        setCompanionModel((current) => current || loadedModels[0]?.id || 'gpt-5.4');
      } catch (caught) {
        if (!cancelled) {
          setPageError(caught instanceof Error ? caught.message : 'Failed to load models.');
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
    if (!draftId) {
      setDraft(null);
      setLiveEvents([]);
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
      setLiveEvents((current) => current.concat(toPlannerEventView(event)).slice(-20));
      if (event.type === 'plan_run_failed' || event.type === 'plan_run_stale' || event.type === 'plan_head_promoted') {
        setStreaming(false);
      } else {
        setStreaming(true);
      }
      void loadDraft(draftId);
    };

    wsClient.on('plan_run_queued', handler);
    wsClient.on('plan_run_started', handler);
    wsClient.on('plan_step_started', handler);
    wsClient.on('plan_step_completed', handler);
    wsClient.on('plan_version_created', handler);
    wsClient.on('plan_head_promoted', handler);
    wsClient.on('plan_run_stale', handler);
    wsClient.on('plan_run_failed', handler);
    wsClient.on('plan_cost_update', handler);

    return () => {
      wsClient.off('plan_run_queued', handler);
      wsClient.off('plan_run_started', handler);
      wsClient.off('plan_step_started', handler);
      wsClient.off('plan_step_completed', handler);
      wsClient.off('plan_version_created', handler);
      wsClient.off('plan_head_promoted', handler);
      wsClient.off('plan_run_stale', handler);
      wsClient.off('plan_run_failed', handler);
      wsClient.off('plan_cost_update', handler);
    };
  }, [draftId]);

  const canCreateDraft = prompt.trim() !== ''
    && workspaces.length > 0
    && effectiveSelectedModels.length > 0
    && companionModel.trim() !== '';

  const updateCurrentDraft = (updater: (current: MissionDraft) => MissionDraft): void => {
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
      const response = await patchPlanDraftSpec(draft.id, draft.revision, draft.draft_spec, draft.validation);
      await loadDraft(response.id);
    } catch (caught) {
      const conflict = getConflictMessage(caught);
      if (conflict) {
        setConflictMessage(conflict);
        await loadDraft(draft.id);
      } else {
        setPageError(caught instanceof Error ? caught.message : 'Failed to save draft.');
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
          id: 'planner',
          label: 'Planner',
          model: companionModel,
        },
      });
      setSearchParams({ draft: created.id });
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : 'Failed to create planning draft.');
    } finally {
      setCreatingDraft(false);
    }
  };

  const handleFollowUp = async (): Promise<void> => {
    if (!draft || followUpMessage.trim() === '') {
      return;
    }

    setStreaming(true);
    setConflictMessage(null);
    setPageError(null);
    try {
      await sendPlanDraftMessage(draft.id, followUpMessage);
      setFollowUpMessage('');
      await loadDraft(draft.id);
    } catch (caught) {
      setStreaming(false);
      setPageError(caught instanceof Error ? caught.message : 'Planner turn failed.');
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
      setPageError(caught instanceof Error ? caught.message : 'Failed to launch mission.');
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
    setPageError(null);
    try {
      await submitPlanDraftPreflight(draft.id, preflightAnswers, skip);
      await loadDraft(draft.id);
    } catch (caught) {
      setStreaming(false);
      setPageError(caught instanceof Error ? caught.message : 'Failed to submit preflight answers.');
    } finally {
      setSubmittingPreflight(false);
    }
  };

  const handlePlanningProfileChange = (key: string, profile: ExecutionProfile): void => {
    updateCurrentDraft((current) => ({
      ...current,
      validation: {
        ...current.validation,
        planning_profiles: {
          ...getPlanningProfiles(current),
          [key]: profile,
        },
      },
    }));
  };

  const validationIssues = draftValidationIssues(draft);
  const advisoryIssues = useMemo(
    () => (loadingModels ? [] : collectAdvisoryFlightChecks(draft, models.map((model) => model.id))),
    [draft, loadingModels, models],
  );
  const currentRun = latestRun(draft);
  const preflightPending = draft?.preflight_status === 'pending' && (draft.preflight_questions?.length ?? 0) > 0;
  const streamEvents = useMemo(
    () => [...buildRunEvents(currentRun), ...liveEvents].slice(-20),
    [currentRun, liveEvents],
  );

  if (!draftId) {
    return (
      <div className="flex flex-col gap-5">
        <header className="page-head">
          <h1 className="text-3xl font-semibold tracking-tight">Flight Director Cockpit</h1>
          <p className="mt-1 text-sm text-dim">Create a planning draft, auto-start the first run, and keep the reviewed version ready for launch.</p>
        </header>

        {pageError ? (
          <div className="rounded-lg border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
            {pageError}
          </div>
        ) : null}

        <section className="rounded-lg border border-border bg-card p-4">
          <label className="block text-sm font-medium text-text" htmlFor="plan-prompt">
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
            <div className="mb-2 text-sm font-medium text-text">Working directories</div>
            <FileBrowser selected={workspaces} onSelect={setWorkspaces} />
          </div>

          <div className="mt-4">
            <div className="mb-2 text-sm font-medium text-text">Approved models</div>
            <ModelSelector
              models={models}
              selected={effectiveSelectedModels}
              onChange={setSelectedModels}
            />
          </div>

          <label className="mt-4 block text-sm font-medium text-text">
            Companion model
            <select
              className="mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
              value={companionModel}
              onChange={(event) => setCompanionModel(event.currentTarget.value)}
            >
              <option value="gpt-5.4">gpt-5.4</option>
              {models.map((model) => (
                <option key={model.id} value={model.id}>{model.name}</option>
              ))}
            </select>
          </label>

          <div className="mt-5 flex items-center justify-between gap-3">
            <span className="text-[11px] text-dim">
              {loadingModels ? 'Loading models...' : `${effectiveSelectedModels.length} approved model(s) armed`}
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
      </div>
    );
  }

  if (loadingDraft || !draft) {
    return (
      <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-dim">
        {pageError ?? 'Loading planning draft...'}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <header className="page-head">
        <h1 className="text-3xl font-semibold tracking-tight">Flight Director Cockpit</h1>
        <p className="mt-1 text-sm text-dim">Flight Director conversation on the left, engineering controls on the right.</p>
      </header>

      {pageError ? (
        <div className="rounded-lg border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
          {pageError}
        </div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(24rem,0.8fr)]">
        <div className="space-y-5">
          <PlannerTranscriptPanel
            turns={draft.turns}
            message={followUpMessage}
            busy={streaming || preflightPending}
            onMessageChange={setFollowUpMessage}
            onSend={() => {
              void handleFollowUp();
            }}
          />
          {preflightPending ? (
            <PreflightQuestionsPanel
              draft={draft}
              answers={preflightAnswers}
              submitting={submittingPreflight}
              onAnswerChange={(questionId, answer) => {
                setPreflightAnswers((current) => ({
                  ...current,
                  [questionId]: answer,
                }));
              }}
              onSubmit={() => {
                void handleSubmitPreflight(false);
              }}
              onSkip={() => {
                void handleSubmitPreflight(true);
              }}
            />
          ) : null}
          <PlannerStreamPanel events={streamEvents} busy={streaming} />
          <PlanHistoryPanel draft={draft} />
        </div>

        <aside className="space-y-5">
          <section className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="section-title">Engineering Controls</h2>
                <p className="mt-1 text-xs text-dim">Mission summary, task timeline, validation, execution, and launch.</p>
                <p className="mt-2 text-sm font-semibold text-text">{draft.draft_spec.name || 'Untitled mission draft'}</p>
                {preflightPending ? (
                  <p className="mt-2 text-xs text-amber">Preflight answers are required before the first planning run and launch.</p>
                ) : null}
              </div>
              <button
                type="button"
                className="rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={launching || validationIssues.length > 0 || streaming || preflightPending}
                onClick={() => {
                  void handleLaunch();
                }}
              >
                Launch Mission
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-dim">
              <span className="rounded-full border border-border bg-surface px-3 py-1">
                Run {currentRun?.status ?? 'idle'}
              </span>
              <span className="rounded-full border border-border bg-surface px-3 py-1">
                Cost {formatCurrency(currentRun?.cost_usd)}
              </span>
              <span className="rounded-full border border-border bg-surface px-3 py-1">
                Tokens {(currentRun?.tokens_in ?? 0) + (currentRun?.tokens_out ?? 0)}
              </span>
            </div>
          </section>

          <DraftSummaryPanel
            draft={draft}
            saving={savingDraft}
            onNameChange={(value) => {
              updateCurrentDraft((current) => updateDraftSpec(current, {
                ...current.draft_spec,
                name: value,
              }));
            }}
            onGoalChange={(value) => {
              updateCurrentDraft((current) => updateDraftSpec(current, {
                ...current.draft_spec,
                goal: value,
              }));
            }}
            onDodChange={(value) => {
              updateCurrentDraft((current) => updateDraftSpec(current, {
                ...current.draft_spec,
                definition_of_done: value,
              }));
            }}
            onSave={() => {
              void persistDraftSpec();
            }}
          />

          <TaskTimelinePanel
            draft={draft}
            saving={savingDraft}
            models={models}
            onTaskChange={(taskId, patch) => {
              updateCurrentDraft((current) => updateDraftSpec(current, {
                ...current.draft_spec,
                tasks: current.draft_spec.tasks.map((task) => (
                  task.id === taskId ? { ...task, ...patch } : task
                )),
              }));
            }}
            onSave={() => {
              void persistDraftSpec();
            }}
          />

          <ExecutionProfileControls
            draft={draft}
            models={models}
            onWorkerModelChange={(value) => {
              updateCurrentDraft((current) => updateDraftSpec(current, {
                ...current.draft_spec,
                execution_defaults: {
                  ...current.draft_spec.execution_defaults,
                  worker: {
                    agent: current.draft_spec.execution_defaults?.worker?.agent ?? 'codex',
                    thinking: current.draft_spec.execution_defaults?.worker?.thinking ?? 'medium',
                    model: value,
                  },
                  reviewer: current.draft_spec.execution_defaults?.reviewer ?? {
                    agent: 'codex',
                    thinking: 'low',
                    model: current.draft_spec.execution_defaults?.reviewer?.model ?? models[0]?.id ?? '',
                  },
                },
              }));
            }}
            onReviewerModelChange={(value) => {
              updateCurrentDraft((current) => updateDraftSpec(current, {
                ...current.draft_spec,
                execution_defaults: {
                  ...current.draft_spec.execution_defaults,
                  worker: current.draft_spec.execution_defaults?.worker ?? {
                    agent: 'codex',
                    thinking: 'medium',
                    model: current.draft_spec.execution_defaults?.worker?.model ?? models[0]?.id ?? '',
                  },
                  reviewer: {
                    agent: current.draft_spec.execution_defaults?.reviewer?.agent ?? 'codex',
                    thinking: current.draft_spec.execution_defaults?.reviewer?.thinking ?? 'low',
                    model: value,
                  },
                },
              }));
            }}
          />

          <PlanningProfilesPanel
            draft={draft}
            models={models}
            onChange={handlePlanningProfileChange}
          />

          <ValidationBoard
            conflictMessage={conflictMessage}
            summaryIssues={validationIssues}
            advisoryIssues={advisoryIssues}
          />
        </aside>
      </div>
    </div>
  );
}
