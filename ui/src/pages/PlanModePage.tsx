import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import FileBrowser from '../components/FileBrowser';
import ModelSelector from '../components/ModelSelector';
import Terminal from '../components/Terminal';
import { createMission, getModels } from '../lib/api';
import type { Model } from '../lib/types';
import { parseMissionPlanYaml, serializeMissionPlanYaml, type EditableMissionPlan } from '../lib/planYaml';

type Step = 'compose' | 'generating' | 'review';

interface PlanTaskState {
  expanded: boolean;
}

interface EditablePlanState extends EditableMissionPlan {
  tasks: (EditableMissionPlan['tasks'][number] & PlanTaskState)[];
}

function createBlankTask(index: number, model: string): EditablePlanState['tasks'][number] {
  return {
    id: `task-${index + 1}`,
    title: '',
    description: '',
    acceptance_criteria: [''],
    model,
    expanded: index === 0,
  };
}

function normalizePlan(plan: EditableMissionPlan, approvedModels: string[]): EditablePlanState {
  const fallbackModel = approvedModels[0] ?? '';

  return {
    ...plan,
    tasks: plan.tasks.length > 0
      ? plan.tasks.map((task, index) => ({
          ...task,
          acceptance_criteria: task.acceptance_criteria.length > 0 ? task.acceptance_criteria : [''],
          model: approvedModels.includes(task.model) ? task.model : fallbackModel,
          expanded: index === 0,
        }))
      : [createBlankTask(0, fallbackModel)],
  };
}

function buildApprovedPlan(plan: EditablePlanState): EditableMissionPlan {
  return {
    name: plan.name,
    goal: plan.goal,
    working_dir: plan.working_dir,
    definition_of_done: plan.definition_of_done,
    tasks: plan.tasks.map(({ expanded, ...task }) => task),
  };
}

function validatePlan(plan: EditablePlanState): string | null {
  if (plan.name.trim() === '') {
    return 'Mission name is required.';
  }
  if (plan.goal.trim() === '') {
    return 'Goal is required.';
  }
  if (plan.definition_of_done.some((criterion) => criterion.trim() === '')) {
    return 'Remove empty DoD criteria before launching.';
  }
  if (plan.tasks.length === 0) {
    return 'Add at least one task.';
  }
  for (const task of plan.tasks) {
    if (task.id.trim() === '' || task.title.trim() === '' || task.description.trim() === '') {
      return 'Every task needs an id, title, and description.';
    }
    if (task.acceptance_criteria.some((criterion) => criterion.trim() === '')) {
      return `Task ${task.id} has an empty acceptance criterion.`;
    }
    if (task.model.trim() === '') {
      return `Task ${task.id} needs an approved model.`;
    }
  }

  return null;
}

async function readSseStream(
  response: Response,
  onEvent: (payload: string) => boolean | void,
): Promise<void> {
  if (!response.body) {
    throw new Error('Plan stream is empty.');
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

    return onEvent(dataLines.join('\n')) !== false;
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

  const trailing = buffer.trim();
  if (trailing !== '') {
    const shouldContinue = handleBlock(trailing.replace(/\r/g, ''));
    if (!shouldContinue) {
      await reader.cancel().catch(() => {});
      return;
    }
  }
}

export default function PlanModePage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>('compose');
  const [prompt, setPrompt] = useState('');
  const [workspaces, setWorkspaces] = useState<string[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [plan, setPlan] = useState<EditablePlanState | null>(null);
  const [yaml, setYaml] = useState('');
  const [streamLines, setStreamLines] = useState<string[]>([]);
  const [streamDone, setStreamDone] = useState(true);
  const [loadingModels, setLoadingModels] = useState(true);
  const [composeError, setComposeError] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const effectiveSelectedModels = useMemo(() => (
    selectedModels.length > 0 ? selectedModels : models.map((model) => model.id)
  ), [models, selectedModels]);

  useEffect(() => {
    let cancelled = false;

    const loadModels = async (): Promise<void> => {
      setLoadingModels(true);

      try {
        const data = await getModels();
        if (cancelled) {
          return;
        }

        setModels(data);
        setSelectedModels((current) => {
          if (current.length > 0) {
            const filtered = current.filter((id) => data.some((model) => model.id === id));
            return filtered.length > 0 ? filtered : data.map((model) => model.id);
          }

          return data.map((model) => model.id);
        });
      } catch (caught) {
        if (!cancelled) {
          setComposeError(caught instanceof Error ? caught.message : 'Failed to load models.');
        }
      } finally {
        if (!cancelled) {
          setLoadingModels(false);
        }
      }
    };

    void loadModels();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!plan) {
      return;
    }

    if (expandedTaskId && plan.tasks.some((task) => task.id === expandedTaskId)) {
      return;
    }

    setExpandedTaskId(plan.tasks[0]?.id ?? null);
  }, [expandedTaskId, plan]);

  useEffect(() => {
    if (!plan || effectiveSelectedModels.length === 0) {
      return;
    }

    setPlan((current) => {
      if (!current) {
        return current;
      }

      let changed = false;
      const fallbackModel = effectiveSelectedModels[0];
      const next = {
        ...current,
        tasks: current.tasks.map((task) => {
          if (effectiveSelectedModels.includes(task.model)) {
            return task;
          }

          changed = true;
          return { ...task, model: fallbackModel };
        }),
      };

      return changed ? next : current;
    });
  }, [effectiveSelectedModels, plan]);

  const canGenerate = useMemo(() => (
    prompt.trim() !== ''
    && workspaces.length > 0
    && effectiveSelectedModels.length > 0
  ), [effectiveSelectedModels.length, prompt, workspaces.length]);

  const updatePlan = (updater: (current: EditablePlanState) => EditablePlanState): void => {
    setPlan((current) => {
      if (!current) {
        return current;
      }

      const next = updater(current);
      setYaml(serializeMissionPlanYaml(buildApprovedPlan(next)));
      return next;
    });
  };

  const startGeneration = async (): Promise<void> => {
    setComposeError(null);
    setLaunchError(null);
    setStreamLines([]);
    setStreamDone(false);

    try {
      const response = await fetch('/api/plan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
          body: JSON.stringify({
            prompt,
            approved_models: effectiveSelectedModels,
            workspaces,
          }),
        });

      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status} ${response.statusText}`);
      }

      let finalYaml = '';

      await readSseStream(response, (payload) => {
        if (payload === '[DONE]') {
          return false;
        }

        finalYaml += `${payload}\n`;
        setStreamLines((current) => [...current, ...payload.split('\n')]);
      });

      setYaml(finalYaml);
      const parsed = normalizePlan(parseMissionPlanYaml(finalYaml), effectiveSelectedModels);
      setPlan(parsed);
      setExpandedTaskId(parsed.tasks[0]?.id ?? null);
      setStep('review');
    } catch (caught) {
      setComposeError(caught instanceof Error ? caught.message : 'Plan generation failed.');
      setStep('compose');
    } finally {
      setStreamDone(true);
    }
  };

  const handleGenerate = (): void => {
    if (!canGenerate) {
      return;
    }

    setPlan(null);
    setStep('generating');
    void startGeneration();
  };

  const handleLaunch = async (): Promise<void> => {
    if (!plan) {
      setLaunchError('Plan is not ready yet.');
      return;
    }

    const validationError = validatePlan(plan);
    if (validationError) {
      setLaunchError(validationError);
      return;
    }

    setLaunchError(null);
    const assembledYaml = serializeMissionPlanYaml(buildApprovedPlan(plan));
    setYaml(assembledYaml);

    try {
      const response = await createMission(assembledYaml);
      navigate(`/mission/${response.id}`);
    } catch (caught) {
      setLaunchError(caught instanceof Error ? caught.message : 'Failed to launch mission.');
    }
  };

  const addCriterion = (index: number): void => {
    updatePlan((current) => {
      const definition_of_done = current.definition_of_done.slice();
      definition_of_done.splice(index + 1, 0, '');
      return { ...current, definition_of_done };
    });
  };

  const removeCriterion = (index: number): void => {
    updatePlan((current) => ({
      ...current,
      definition_of_done: current.definition_of_done.filter((_, itemIndex) => itemIndex !== index),
    }));
  };

  const addTask = (): void => {
    updatePlan((current) => {
      const tasks = current.tasks.map((task) => ({ ...task, expanded: false }));
      tasks.push(createBlankTask(tasks.length, effectiveSelectedModels[0] ?? ''));
      return { ...current, tasks };
    });
    setExpandedTaskId(`task-${(plan?.tasks.length ?? 0) + 1}`);
  };

  const removeTask = (taskId: string): void => {
    updatePlan((current) => {
      const tasks = current.tasks.filter((task) => task.id !== taskId);
      return {
        ...current,
        tasks: tasks.map((task, index) => ({ ...task, expanded: index === 0 })),
      };
    });
  };

  if (step === 'compose') {
    return (
      <div className="flex flex-col gap-5">
        <header className="page-head">
          <h1 className="text-3xl font-semibold tracking-tight">Plan Mode</h1>
          <p className="mt-1 text-sm text-dim">Compose a mission prompt, choose models, and generate a launch-ready YAML plan.</p>
        </header>

        {composeError ? (
          <div className="rounded-lg border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
            {composeError}
          </div>
        ) : null}

        <section className="rounded-lg border border-border bg-card p-4">
          <label className="block text-sm font-medium text-text" htmlFor="plan-prompt">
            Mission prompt
          </label>
          <textarea
            id="plan-prompt"
            rows={10}
            className="mt-2 w-full rounded-lg border border-border bg-surface p-3 font-sans text-[14px] text-text outline-none transition-colors placeholder:text-dim focus:border-cyan"
            placeholder="Describe what you want to build..."
            value={prompt}
            onInput={(event) => setPrompt(event.currentTarget.value)}
          />
          <div className="mt-1 text-right text-[11px] text-dim">{prompt.length} chars</div>

          <div className="mt-4">
            <label className="block text-sm font-medium text-text">
              Working directories
            </label>
            <div className="mt-2">
              <FileBrowser selected={workspaces} onSelect={setWorkspaces} />
            </div>
          </div>

          <div className="mt-4">
            <div className="mb-2 text-sm font-medium text-text">Approved models</div>
            <ModelSelector
              models={models}
              selected={effectiveSelectedModels}
              onChange={setSelectedModels}
            />
          </div>

          <div className="mt-5 flex items-center justify-between gap-3">
            <span className="text-[11px] text-dim">
              {loadingModels ? 'Loading models...' : `${effectiveSelectedModels.length} approved model(s) selected`}
            </span>
            <button
              type="button"
              disabled={!canGenerate}
              className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={handleGenerate}
            >
              Generate Plan →
            </button>
          </div>
        </section>
      </div>
    );
  }

  if (step === 'generating') {
    return (
      <div className="flex flex-col gap-5">
        <header className="page-head">
          <h1 className="text-3xl font-semibold tracking-tight">Plan Mode</h1>
          <p className="mt-1 text-sm text-dim">Generating a mission plan from your prompt and approved models.</p>
        </header>

        {composeError ? (
          <div className="rounded-lg border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
            {composeError}
          </div>
        ) : null}

        <Terminal lines={streamLines} done={streamDone} className="rounded-lg border border-border bg-card p-4" />
      </div>
    );
  }

  if (!plan) {
    return (
      <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-dim">
        Loading plan...
      </div>
    );
  }

  const approvedPlan = buildApprovedPlan(plan);

  return (
    <div className="flex flex-col gap-5">
      <header className="page-head">
        <h1 className="text-3xl font-semibold tracking-tight">Plan Review</h1>
        <p className="mt-1 text-sm text-dim">Edit the generated YAML, tune task ownership, and launch the mission.</p>
      </header>

      {launchError ? (
        <div className="rounded-lg border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
          {launchError}
        </div>
      ) : null}

      <section className="rounded-lg border border-border bg-card p-4">
        <div className="grid gap-4">
          <div>
            <label className="block text-sm font-medium text-text" htmlFor="mission-name">
              Mission name
            </label>
              <input
                id="mission-name"
                aria-label="Mission name"
                className="mt-2 w-full border-b border-border bg-transparent px-0 py-1 text-title font-semibold outline-none placeholder:text-dim focus:border-cyan"
                value={plan.name}
              onInput={(event) => updatePlan((current) => ({ ...current, name: event.currentTarget.value }))}
              />
          </div>

          <div>
            <label className="block text-sm font-medium text-text" htmlFor="mission-goal">
              Goal
            </label>
            <textarea
              id="mission-goal"
              rows={3}
              className="mt-2 w-full rounded-lg border border-border bg-surface p-3 text-sm text-text outline-none placeholder:text-dim focus:border-cyan"
              value={plan.goal}
              onInput={(event) => updatePlan((current) => ({ ...current, goal: event.currentTarget.value }))}
            />
          </div>

          <div>
            <div className="mb-2 text-sm font-medium text-text">DoD</div>
            <div className="space-y-2">
              {plan.definition_of_done.map((criterion, index) => (
                <div key={`${index}-${criterion}`} className="flex items-center gap-2">
                  <input
                    className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                    value={criterion}
                    onInput={(event) => updatePlan((current) => ({
                      ...current,
                      definition_of_done: current.definition_of_done.map((item, itemIndex) => (
                        itemIndex === index ? event.currentTarget.value : item
                      )),
                    }))}
                  />
                  <button
                    type="button"
                    className="rounded border border-border px-2 py-1 text-[11px] text-dim hover:bg-surface"
                    onClick={() => removeCriterion(index)}
                  >
                    [x]
                  </button>
                </div>
              ))}
            </div>
            <button
              type="button"
              className="mt-3 inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-surface"
              onClick={() => addCriterion(plan.definition_of_done.length - 1)}
            >
              + Add criterion
            </button>
          </div>

          <div className="space-y-3">
            <div className="text-sm font-medium text-text">Tasks</div>
            {plan.tasks.map((task, index) => {
              const isOpen = expandedTaskId === task.id;

              return (
                <article key={task.id} className="overflow-hidden rounded-lg border border-border bg-surface">
                  <button
                    type="button"
                    className="flex w-full items-center gap-3 border-b border-border px-4 py-3 text-left"
                    onClick={() => setExpandedTaskId(isOpen ? null : task.id)}
                  >
                    <span className="rounded-full border border-cyan/30 bg-cyan-bg px-2 py-0.5 text-[10px] font-semibold text-cyan">
                      {task.id}
                    </span>
                    <span className="flex-1 text-sm font-semibold text-text">
                      {task.title || `Task ${index + 1}`}
                    </span>
                    <span className="text-[11px] text-dim">{isOpen ? 'Collapse' : 'Expand'}</span>
                  </button>

                  {isOpen ? (
                    <div className="space-y-4 p-4">
                      <div>
                        <label className="block text-[11px] font-medium uppercase tracking-[0.08em] text-dim">
                          Title
                        </label>
                        <input
                          className="mt-1 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                          value={task.title}
                          onInput={(event) => updatePlan((current) => ({
                            ...current,
                            tasks: current.tasks.map((item) => (
                              item.id === task.id ? { ...item, title: event.currentTarget.value } : item
                            )),
                          }))}
                        />
                      </div>

                      <div>
                        <label className="block text-[11px] font-medium uppercase tracking-[0.08em] text-dim">
                          Description
                        </label>
                        <textarea
                          rows={3}
                          className="mt-1 w-full rounded-lg border border-border bg-card p-3 text-sm text-text outline-none focus:border-cyan"
                          value={task.description}
                          onInput={(event) => updatePlan((current) => ({
                            ...current,
                            tasks: current.tasks.map((item) => (
                              item.id === task.id ? { ...item, description: event.currentTarget.value } : item
                            )),
                          }))}
                        />
                      </div>

                      <div>
                        <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.08em] text-dim">
                          Acceptance criteria
                        </div>
                        <div className="space-y-2">
                          {task.acceptance_criteria.map((criterion, criterionIndex) => (
                            <div key={`${task.id}-${criterionIndex}`} className="flex items-center gap-2">
                              <input
                                className="flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                                value={criterion}
                                onInput={(event) => updatePlan((current) => ({
                                  ...current,
                                  tasks: current.tasks.map((item) => (
                                    item.id === task.id
                                      ? {
                                          ...item,
                                          acceptance_criteria: item.acceptance_criteria.map((value, valueIndex) => (
                                            valueIndex === criterionIndex ? event.currentTarget.value : value
                                          )),
                                        }
                                      : item
                                  )),
                                }))}
                              />
                              <button
                                type="button"
                                className="rounded border border-border px-2 py-1 text-[11px] text-dim hover:bg-surface"
                                onClick={() => updatePlan((current) => ({
                                  ...current,
                                  tasks: current.tasks.map((item) => (
                                    item.id === task.id
                                      ? {
                                          ...item,
                                          acceptance_criteria: item.acceptance_criteria.filter((_, valueIndex) => valueIndex !== criterionIndex),
                                        }
                                      : item
                                  )),
                                }))}
                              >
                                [x]
                              </button>
                            </div>
                          ))}
                        </div>
                        <button
                          type="button"
                          className="mt-3 inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-surface"
                          onClick={() => updatePlan((current) => ({
                            ...current,
                            tasks: current.tasks.map((item) => (
                              item.id === task.id
                                ? { ...item, acceptance_criteria: [...item.acceptance_criteria, ''] }
                                : item
                            )),
                          }))}
                        >
                          + Add criterion
                        </button>
                      </div>

                      <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
                        <label className="block">
                          <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.08em] text-dim">
                            Model
                          </span>
                          <select
                            aria-label="Task model"
                            className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                            value={task.model}
                            onChange={(event) => updatePlan((current) => ({
                              ...current,
                              tasks: current.tasks.map((item) => (
                                item.id === task.id ? { ...item, model: event.target.value } : item
                              )),
                            }))}
                          >
                            {effectiveSelectedModels.map((modelId) => {
                              const model = models.find((entry) => entry.id === modelId);
                              return (
                                <option key={modelId} value={modelId}>
                                  {model ? `${model.name} (${model.provider})` : modelId}
                                </option>
                              );
                            })}
                          </select>
                        </label>

                        <button
                          type="button"
                          className="inline-flex items-center justify-center rounded-full border border-red/30 bg-red/10 px-3 py-1.5 text-[11px] font-semibold text-red transition-colors hover:bg-red/15"
                          onClick={() => removeTask(task.id)}
                        >
                          Remove task
                        </button>
                      </div>
                    </div>
                  ) : null}
                </article>
              );
            })}
            <button
              type="button"
              className="inline-flex items-center rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-surface"
              onClick={addTask}
            >
              Add Task
            </button>
          </div>

          <details className="rounded-lg border border-border bg-surface px-4 py-3">
            <summary className="cursor-pointer text-sm font-medium text-text">Raw YAML</summary>
            <textarea
              aria-label="Raw YAML"
              rows={20}
              className="mt-3 w-full rounded-lg border border-border bg-card p-3 font-mono text-[12px] text-text outline-none focus:border-cyan"
              value={yaml || serializeMissionPlanYaml(approvedPlan)}
              onInput={(event) => {
                const nextYaml = event.currentTarget.value;
                setYaml(nextYaml);
                const parsed = normalizePlan(parseMissionPlanYaml(nextYaml), effectiveSelectedModels);
                setPlan(parsed);
                setExpandedTaskId(parsed.tasks[0]?.id ?? null);
              }}
            />
          </details>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              className="inline-flex items-center rounded-full border border-border px-4 py-2 text-sm font-semibold text-text transition-colors hover:bg-surface"
              onClick={() => {
                setStep('compose');
              }}
            >
              ← Back
            </button>
            <button
              type="button"
              className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={validatePlan(plan) !== null}
              onClick={() => {
                void handleLaunch();
              }}
            >
              Launch Mission →
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
