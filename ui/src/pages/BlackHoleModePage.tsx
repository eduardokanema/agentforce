import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import FileBrowser from "../components/FileBrowser";
import ExecutionProfileSelect from "../components/ExecutionProfileSelect";
import BlackHoleConfigPanel from "../components/planning/BlackHoleConfigPanel";
import BlackHoleHero from "../components/planning/BlackHoleHero";
import BlackHoleLedger from "../components/planning/BlackHoleLedger";
import PlanningFollowUpPanel from "../components/planning/PlanningFollowUpPanel";
import PreflightQuestionsPanel from "../components/planning/PreflightQuestionsPanel";
import {
  createBlackHoleCampaign,
  createPlanDraft,
  getBlackHoleCampaign,
  getModels,
  getPlanDraft,
  pauseBlackHoleCampaign,
  resumeBlackHoleCampaign,
  stopBlackHoleCampaign,
  submitBlackHoleDraftRepair,
  submitPlanDraftPreflight,
} from "../lib/api";
import {
  blackHoleHeroDescription,
  blackHoleMetricLabel,
  blackHoleMetricValue,
  firstTurnPrompt,
  normalizeBlackHoleConfig,
} from "../lib/blackHole";
import { BLACK_HOLE_DRAFT_KIND, isBlackHoleDraft } from "../lib/draftKinds";
import { executionProfileFromOption, optionIdFromExecutionProfile } from "../lib/executionProfiles";
import {
  blackHoleDraftRoute,
  isBlackHoleEnabled,
  MISSIONS_ROUTE,
  planDraftRoute,
  type LabsConfig,
  BlackHoleCampaignState,
  BlackHoleConfig,
  ExecutionProfile,
  MissionDraft,
  Model,
  PreflightAnswer,
} from "../lib/types";
import {
  wsClient,
  type BlackHoleCampaignUpdatedEvent,
  type BlackHoleLoopRecordedEvent,
  type DraftUpdatedEvent,
} from "../lib/ws";

const PLANNING_PROFILE_KEYS = [
  { key: "planner", label: "Planner" },
  { key: "critic_technical", label: "Technical Critic" },
  { key: "critic_practical", label: "Practical Critic" },
  { key: "resolver", label: "Resolver" },
] as const;

const BLACK_HOLE_WORKSPACES_KEY = "agentforce-black-hole-workspaces-v1";
const BLACK_HOLE_LEGACY_PROFILES_KEY = "agentforce-black-hole-profiles-v1";
const BLACK_HOLE_PROFILES_KEY = "agentforce-black-hole-profiles-v2";

function readStoredJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") {
    return fallback;
  }
  try {
    const raw = window.localStorage.getItem(key);
    if (raw == null) {
      return fallback;
    }
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function normalizeWorkspacePaths(workspacePaths: string[] = []): string[] {
  return workspacePaths.filter((path) => typeof path === "string" && path.trim() !== "");
}

function getDefaultPlanProfiles(): Record<string, ExecutionProfile> {
  return {
    planner: { agent: "claude", model: "", thinking: "medium" },
    critic_technical: { agent: "claude", model: "", thinking: "medium" },
    critic_practical: { agent: "claude", model: "", thinking: "medium" },
    resolver: { agent: "claude", model: "", thinking: "medium" },
  };
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

export default function BlackHoleModePage({ labs }: { labs?: LabsConfig }): JSX.Element {
  const navigate = useNavigate();
  const params = useParams<{ id?: string }>();
  const [searchParams] = useSearchParams();
  const draftId = params.id ?? searchParams.get("draft") ?? "";
  const blackHoleEnabled = isBlackHoleEnabled(labs);

  const [prompt, setPrompt] = useState("");
  const [workspaces, setWorkspaces] = useState<string[]>(
    readStoredJson<string[]>(BLACK_HOLE_WORKSPACES_KEY, []),
  );
  const [models, setModels] = useState<Model[]>([]);
  const [planningProfiles, setPlanningProfiles] = useState<Record<string, ExecutionProfile>>(
    normalizePlanningProfiles(
      readStoredJson<Record<string, unknown>>(
        BLACK_HOLE_PROFILES_KEY,
        readStoredJson<Record<string, unknown>>(BLACK_HOLE_LEGACY_PROFILES_KEY, getDefaultPlanProfiles()),
      ),
    ),
  );
  const [draft, setDraft] = useState<MissionDraft | null>(null);
  const [campaignState, setCampaignState] = useState<BlackHoleCampaignState | null>(null);
  const [configDraft, setConfigDraft] = useState<BlackHoleConfig | null>(null);
  const [preflightAnswers, setPreflightAnswers] = useState<Record<string, PreflightAnswer>>({});
  const [repairAnswers, setRepairAnswers] = useState<Record<string, PreflightAnswer>>({});
  const [loadingModels, setLoadingModels] = useState(true);
  const [loadingDraft, setLoadingDraft] = useState(false);
  const [creatingDraft, setCreatingDraft] = useState(false);
  const [submittingPreflight, setSubmittingPreflight] = useState(false);
  const [submittingRepair, setSubmittingRepair] = useState(false);
  const [syncingCampaign, setSyncingCampaign] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);

  const canCreateDraft =
    prompt.trim() !== ""
    && workspaces.length > 0
    && (planningProfiles.planner.model ?? "").trim() !== "";

  useEffect(() => {
    if (!blackHoleEnabled) {
      navigate(MISSIONS_ROUTE, { replace: true });
    }
  }, [blackHoleEnabled, navigate]);

  const loadDraft = async (nextDraftId: string): Promise<void> => {
    setLoadingDraft(true);
    setPageError(null);
    try {
      const loaded = await getPlanDraft(nextDraftId);
      if (!isBlackHoleDraft(loaded)) {
        navigate(planDraftRoute(nextDraftId), { replace: true });
        return;
      }
      const state = await getBlackHoleCampaign(nextDraftId);
      setDraft(loaded);
      setCampaignState(state);
      setConfigDraft(
        normalizeBlackHoleConfig(state.config ?? loaded.validation?.black_hole_config, loaded),
      );
      setPreflightAnswers(loaded.preflight_answers ?? {});
      setRepairAnswers(loaded.repair_answers ?? {});
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : "Failed to load black hole draft.");
    } finally {
      setLoadingDraft(false);
    }
  };

  useEffect(() => {
    if (!blackHoleEnabled) {
      return;
    }
    let cancelled = false;
    const load = async (): Promise<void> => {
      setLoadingModels(true);
      try {
        const loadedModels = await getModels();
        if (cancelled) {
          return;
        }
        setModels(loadedModels);
        setPlanningProfiles((current) => {
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
          setPageError(caught instanceof Error ? caught.message : "Failed to load models.");
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
  }, [blackHoleEnabled]);

  useEffect(() => {
    if (!blackHoleEnabled) {
      return;
    }
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(BLACK_HOLE_WORKSPACES_KEY, JSON.stringify(normalizeWorkspacePaths(workspaces)));
  }, [workspaces]);

  useEffect(() => {
    if (!blackHoleEnabled) {
      return;
    }
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(BLACK_HOLE_PROFILES_KEY, JSON.stringify(planningProfiles));
  }, [planningProfiles]);

  useEffect(() => {
    if (!blackHoleEnabled) {
      return;
    }
    if (!draftId) {
      setDraft(null);
      setCampaignState(null);
      setConfigDraft(null);
      setPreflightAnswers({});
      return;
    }
    void loadDraft(draftId);
  }, [draftId, navigate, blackHoleEnabled]);

  useEffect(() => {
    if (!blackHoleEnabled) {
      return undefined;
    }
    if (!draftId) {
      return undefined;
    }

    const refreshDraft = (event: DraftUpdatedEvent | BlackHoleCampaignUpdatedEvent | BlackHoleLoopRecordedEvent): void => {
      if (event.draft_id !== draftId) {
        return;
      }
      void loadDraft(draftId);
    };

    wsClient.on("draft_updated", refreshDraft);
    wsClient.on("black_hole_campaign_updated", refreshDraft);
    wsClient.on("black_hole_loop_recorded", refreshDraft);

    return () => {
      wsClient.off("draft_updated", refreshDraft);
      wsClient.off("black_hole_campaign_updated", refreshDraft);
      wsClient.off("black_hole_loop_recorded", refreshDraft);
    };
  }, [draftId, navigate, blackHoleEnabled]);

  if (!blackHoleEnabled) {
    return <></>;
  }

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
          ...planningProfiles.planner,
        },
        validation: {
          draft_kind: BLACK_HOLE_DRAFT_KIND,
          planning_profiles: planningProfiles,
        },
        auto_start: false,
      });
      navigate(blackHoleDraftRoute(created.id));
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : "Failed to create black hole draft.");
    } finally {
      setCreatingDraft(false);
    }
  };

  const handleSubmitPreflight = async (skip: boolean): Promise<void> => {
    if (!draft) {
      return;
    }
    setSubmittingPreflight(true);
    setPageError(null);
    try {
      await submitPlanDraftPreflight(draft.id, preflightAnswers, skip);
      await loadDraft(draft.id);
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : "Failed to submit preflight answers.");
    } finally {
      setSubmittingPreflight(false);
    }
  };

  const handleStartCampaign = async (): Promise<void> => {
    if (!draft || !configDraft) {
      return;
    }
    setSyncingCampaign(true);
    setPageError(null);
    try {
      await createBlackHoleCampaign(draft.id, draft.revision, configDraft);
      await loadDraft(draft.id);
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : "Failed to arm black hole campaign.");
    } finally {
      setSyncingCampaign(false);
    }
  };

  const handleSubmitRepair = async (): Promise<void> => {
    if (!draft) {
      return;
    }
    setSubmittingRepair(true);
    setPageError(null);
    try {
      await submitBlackHoleDraftRepair(draft.id, draft.revision, repairAnswers, {
        loop_no: draft.repair_context?.loop_no ?? null,
        repair_round: draft.repair_context?.repair_round ?? null,
        source_version_id: draft.repair_context?.source_version_id ?? null,
      });
      await loadDraft(draft.id);
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : "Failed to submit repair answers.");
    } finally {
      setSubmittingRepair(false);
    }
  };

  const handlePauseCampaign = async (): Promise<void> => {
    if (!draft) {
      return;
    }
    setSyncingCampaign(true);
    setPageError(null);
    try {
      await pauseBlackHoleCampaign(draft.id);
      await loadDraft(draft.id);
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : "Failed to pause black hole campaign.");
    } finally {
      setSyncingCampaign(false);
    }
  };

  const handleResumeCampaign = async (): Promise<void> => {
    if (!draft) {
      return;
    }
    setSyncingCampaign(true);
    setPageError(null);
    try {
      await resumeBlackHoleCampaign(draft.id, configDraft ?? undefined);
      await loadDraft(draft.id);
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : "Failed to resume black hole campaign.");
    } finally {
      setSyncingCampaign(false);
    }
  };

  const handleStopCampaign = async (): Promise<void> => {
    if (!draft) {
      return;
    }
    setSyncingCampaign(true);
    setPageError(null);
    try {
      await stopBlackHoleCampaign(draft.id);
      await loadDraft(draft.id);
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : "Failed to stop black hole campaign.");
    } finally {
      setSyncingCampaign(false);
    }
  };

  const campaign = campaignState?.campaign ?? null;
  const loops = campaignState?.loops ?? [];
  const latestLoop = loops[loops.length - 1];
  const metricLabel = blackHoleMetricLabel(configDraft);
  const preflightPending = draft?.preflight_status === "pending" && (draft.preflight_questions?.length ?? 0) > 0;
  const repairPending = draft?.repair_status === "pending" && (draft.repair_questions?.length ?? 0) > 0;

  if (loadingDraft) {
    return (
      <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-dim">
        Loading black hole draft…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="page-head flex-wrap justify-between gap-4">
        <div>
          <h1 className="text-[clamp(1.7rem,3vw,2.35rem)] font-semibold tracking-[-0.04em] text-text">
            Black Hole Director
          </h1>
          {draft?.draft_spec.name ? (
            <div className="mt-3 text-lg font-semibold tracking-[-0.03em] text-text">
              {draft.draft_spec.name}
            </div>
          ) : null}
          <p className="mt-2 max-w-[72ch] text-sm leading-7 text-dim">
            Recursive planning campaigns that select one slice at a time, launch one child interaction, and loop until the global objective is satisfied or bounded limits stop the orbit.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px] text-dim">
          <span className="rounded-full border border-border bg-surface px-3 py-1">
            {draft ? `Draft ${draft.id}` : "No draft"}
          </span>
          <span className="rounded-full border border-amber/30 bg-amber/10 px-3 py-1 text-amber">
            Black Hole Plan
          </span>
        </div>
      </header>

      {pageError ? (
        <div className="rounded-lg border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
          {pageError}
        </div>
      ) : null}

      {!draft ? (
        <section className="rounded-[1.15rem] border border-border bg-card p-5">
          <div className="mb-5 max-w-[64ch]">
            <h2 className="section-title">Campaign Brief</h2>
            <p className="mt-2 text-sm leading-7 text-dim">
              Define the global objective, choose the workspaces, and arm the planning stack. This draft does not launch a simple plan run on creation.
            </p>
          </div>

          <label className="block text-sm font-medium text-text" htmlFor="black-hole-prompt">
            Objective prompt
          </label>
          <textarea
            id="black-hole-prompt"
            rows={8}
            className="mt-2 w-full rounded-lg border border-border bg-surface p-3 text-sm text-text outline-none placeholder:text-dim focus:border-amber"
            placeholder="Describe the recursive objective you want the campaign to pursue..."
            value={prompt}
            onInput={(event) => setPrompt(event.currentTarget.value)}
          />

          <div className="mt-4">
            <div className="mb-2 text-sm font-medium text-text">Working directories</div>
            <FileBrowser selected={workspaces} onSelect={setWorkspaces} />
          </div>

          <div className="mt-4">
            <div className="mb-2 text-sm font-medium text-text">Planning Stack</div>
            <p className="text-xs text-dim">
              Choose the exact `Model + Thinking` profile for each recursive planning role.
            </p>
          </div>

          <div className="mt-4">
            <div className="grid gap-4 sm:grid-cols-2">
              {PLANNING_PROFILE_KEYS.map(({ key, label }) => {
                const selectedProfileId = optionIdFromExecutionProfile(planningProfiles[key], models);
                return (
                  <div key={key} className="rounded-xl border border-border bg-surface p-3">
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
                        setPlanningProfiles((current) => ({
                          ...current,
                          [key]: profile,
                        }));
                      }}
                      className="w-full rounded-lg border border-border bg-card px-2 py-1.5 text-xs text-text outline-none focus:border-amber"
                      ariaLabel={`${label} execution profile`}
                    />
                  </div>
                );
              })}
            </div>
          </div>

          <div className="mt-5 flex items-center justify-between gap-3">
            <span className="text-[11px] text-dim">
              {loadingModels ? "Loading models..." : `${PLANNING_PROFILE_KEYS.length} execution profile(s) armed`}
            </span>
            <button
              type="button"
              disabled={!canCreateDraft || creatingDraft}
              className="inline-flex items-center rounded-full border border-amber/35 bg-amber/10 px-4 py-2 text-sm font-semibold text-amber transition-colors hover:bg-amber/15 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => {
                void handleCreateDraft();
              }}
            >
              {creatingDraft ? "Opening..." : "Open Black Hole"}
            </button>
          </div>
        </section>
      ) : (
        <div className="space-y-5">
          <BlackHoleHero
            campaignState={campaign?.status ?? "orbit_ready"}
            campaignStatus={campaign?.status}
            loopNumber={campaign?.current_loop ?? 0}
            metricLabel={metricLabel}
            metricBefore={blackHoleMetricValue(configDraft, latestLoop?.metric_before as Record<string, unknown> | undefined)}
            metricAfter={blackHoleMetricValue(
              configDraft,
              ((campaign?.last_metric as Record<string, unknown> | undefined) ?? (latestLoop?.metric_after as Record<string, unknown> | undefined)),
            )}
            title="Black Hole Campaign Telemetry"
            description={blackHoleHeroDescription(configDraft, campaign)}
          />

          {preflightPending ? (
            <PreflightQuestionsPanel
              draft={draft}
              answers={preflightAnswers}
              submitting={submittingPreflight}
              submitLabel="Unlock Campaign"
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

          {!preflightPending && repairPending ? (
            <PreflightQuestionsPanel
              draft={{
                ...draft,
                preflight_questions: draft.repair_questions,
              }}
              answers={repairAnswers}
              submitting={submittingRepair}
              title="Repair Questions"
              description={draft.repair_context?.gate_reason || "Answer these questions so the campaign can repair the child plan and continue the locked loop."}
              submitLabel="Resume Locked Loop"
              onAnswerChange={(questionId, answer) => {
                setRepairAnswers((current) => ({
                  ...current,
                  [questionId]: answer,
                }));
              }}
              onSubmit={() => {
                void handleSubmitRepair();
              }}
              onSkip={() => {
                void handleSubmitRepair();
              }}
            />
          ) : null}

          {!preflightPending && !repairPending && (draft.planning_follow_ups?.length ?? 0) > 0 ? (
            <PlanningFollowUpPanel
              followUps={draft.planning_follow_ups ?? []}
              description="Black Hole converted these planning questions into execution-owned child-mission work instead of reopening the campaign planning loop."
            />
          ) : null}

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(16rem,0.95fr)]">
            {configDraft ? (
              <BlackHoleConfigPanel
                config={configDraft}
                campaign={campaign}
                busy={syncingCampaign || submittingPreflight || submittingRepair}
                onChange={setConfigDraft}
                onStart={() => {
                  void handleStartCampaign();
                }}
                onPause={() => {
                  void handlePauseCampaign();
                }}
                onResume={() => {
                  void handleResumeCampaign();
                }}
                onStop={() => {
                  void handleStopCampaign();
                }}
              />
            ) : (
              <div className="rounded-[1.15rem] border border-border bg-card p-5 text-sm text-dim">
                Loading campaign configuration…
              </div>
            )}
            <BlackHoleLedger campaign={campaign} loops={loops} />
          </div>

          <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
            <div className="rounded-[1.15rem] border border-border bg-card p-5">
              <h2 className="section-title">Campaign Brief</h2>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div className="rounded-xl border border-border bg-surface px-4 py-4">
                  <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Original Prompt</div>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-text">
                    {firstTurnPrompt(draft) || "No original prompt stored."}
                  </p>
                </div>
                <div className="rounded-xl border border-border bg-surface px-4 py-4">
                  <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Objective</div>
                  <p className="mt-2 text-sm leading-7 text-text">
                    {configDraft?.objective || draft.draft_spec.goal}
                  </p>
                </div>
              </div>
            </div>
            <div className="rounded-[1.15rem] border border-border bg-card p-5">
              <h2 className="section-title">Campaign Footprint</h2>
              <div className="mt-4 flex flex-wrap gap-2">
                <span className="rounded-full border border-border bg-surface px-3 py-1 font-mono text-[11px] text-dim">
                  {draft.workspace_paths.length} workspace{draft.workspace_paths.length === 1 ? "" : "s"}
                </span>
                <span className="rounded-full border border-border bg-surface px-3 py-1 font-mono text-[11px] text-dim">
                  {PLANNING_PROFILE_KEYS.length} planning profiles
                </span>
                <span className="rounded-full border border-border bg-surface px-3 py-1 font-mono text-[11px] text-dim">
                  {campaign?.current_loop ?? 0} loop{campaign?.current_loop === 1 ? "" : "s"}
                </span>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
