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
import YamlDrawer from '../components/planning/YamlDrawer';
import {
  createPlanDraft,
  startPlanDraft,
  getModels,
  getPlanDraft,
  importPlanDraftYaml,
  patchPlanDraftSpec,
  sendPlanDraftMessage,
} from '../lib/api';
import { collectAdvisoryFlightChecks } from '../lib/planChecks';
import { serializeMissionPlanYaml } from '../lib/planYaml';
import type { MissionDraft, MissionSpec, Model } from '../lib/types';

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

async function readPlannerStream(
  response: Response,
  onEvent: (event: PlannerStreamEventView) => void,
): Promise<void> {
  if (!response.body) {
    throw new Error('Planner stream is empty.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const handleBlock = (block: string): boolean => {
    const dataLines = block
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).replace(/^ /, ''));
    if (dataLines.length === 0) {
      return true;
    }

    const payload = dataLines.join('\n');
    if (payload === '[DONE]') {
      return false;
    }

    const parsed = JSON.parse(payload) as PlannerStreamEventView;
    onEvent(parsed);
    return true;
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? undefined, { stream: !done });

    let boundaryIndex = buffer.indexOf('\n\n');
    while (boundaryIndex !== -1) {
      const block = buffer.slice(0, boundaryIndex).replace(/\r/g, '');
      buffer = buffer.slice(boundaryIndex + 2);
      if (!handleBlock(block)) {
        await reader.cancel().catch(() => {});
        return;
      }
      boundaryIndex = buffer.indexOf('\n\n');
    }

    if (done) {
      break;
    }
  }
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
  const [streamEvents, setStreamEvents] = useState<PlannerStreamEventView[]>([]);
  const [loadingModels, setLoadingModels] = useState(true);
  const [loadingDraft, setLoadingDraft] = useState(false);
  const [creatingDraft, setCreatingDraft] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [importingYaml, setImportingYaml] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);

  const effectiveSelectedModels = useMemo(() => (
    selectedModels.length > 0 ? selectedModels : models.map((model) => model.id)
  ), [models, selectedModels]);

  const loadDraft = async (id: string): Promise<void> => {
    setLoadingDraft(true);
    setPageError(null);
    try {
      const loaded = await getPlanDraft(id);
      setDraft(loaded);
      setFollowUpMessage('');
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
        setSelectedModels((current) => current.length > 0 ? current : loadedModels.map((model) => model.id));
        setCompanionModel((current) => current || loadedModels[0]?.id || '');
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
      return;
    }
    void loadDraft(draftId);
  }, [draftId]);

  const canCreateDraft = prompt.trim() !== ''
    && workspaces.length > 0
    && effectiveSelectedModels.length > 0
    && companionModel.trim() !== '';

  const updateCurrentDraft = (updater: (current: MissionDraft) => MissionDraft): void => {
    setDraft((current) => current ? updater(current) : current);
  };

  const persistDraftSpec = async (): Promise<void> => {
    if (!draft) {
      return;
    }
    setSavingDraft(true);
    setConflictMessage(null);
    setPageError(null);
    try {
      const response = await patchPlanDraftSpec(draft.id, draft.revision, draft.draft_spec);
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
      await loadDraft(created.id);
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
    setStreamEvents([]);

    try {
      const response = await sendPlanDraftMessage(draft.id, followUpMessage);
      await readPlannerStream(response, (event) => {
        setStreamEvents((current) => current.concat(event));
      });
      await loadDraft(draft.id);
      setFollowUpMessage('');
    } catch (caught) {
      setPageError(caught instanceof Error ? caught.message : 'Planner turn failed.');
    } finally {
      setStreaming(false);
    }
  };

  const handleImportYaml = async (yaml: string): Promise<void> => {
    if (!draft) return;
    setImportingYaml(true);
    try {
      const result = await importPlanDraftYaml(draft.id, draft.revision, yaml);
      setDraft((current) => current ? {
        ...current,
        revision: result.revision,
        draft_spec: result.draft_spec,
      } : current);
    } finally {
      setImportingYaml(false);
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

  const validationIssues = draftValidationIssues(draft);
  const advisoryIssues = useMemo(
    () => (loadingModels ? [] : collectAdvisoryFlightChecks(draft, models.map((model) => model.id))),
    [draft, loadingModels, models],
  );

  if (!draftId) {
    return (
      <div className="flex flex-col gap-5">
        <header className="page-head">
          <h1 className="text-3xl font-semibold tracking-tight">Flight Director Cockpit</h1>
          <p className="mt-1 text-sm text-dim">Create a planning draft from prompt, workspaces, approved models, and a companion model.</p>
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
            busy={streaming}
            onMessageChange={setFollowUpMessage}
            onSend={() => {
              void handleFollowUp();
            }}
          />
          <PlannerStreamPanel events={streamEvents} busy={streaming} />
        </div>

        <aside className="space-y-5">
          <section className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="section-title">Engineering Controls</h2>
                <p className="mt-1 text-xs text-dim">Mission summary, task timeline, validation, execution, and launch.</p>
              </div>
              <button
                type="button"
                className="rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={launching || validationIssues.length > 0}
                onClick={() => {
                  void handleLaunch();
                }}
              >
                Launch Mission
              </button>
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

          <ValidationBoard
            conflictMessage={conflictMessage}
            summaryIssues={validationIssues}
            advisoryIssues={advisoryIssues}
          />

          <YamlDrawer
            yamlText={serializeMissionPlanYaml(draft.draft_spec)}
            importing={importingYaml}
            onApplyImport={handleImportYaml}
          />

        </aside>
      </div>
    </div>
  );
}
