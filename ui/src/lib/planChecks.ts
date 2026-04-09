import type { MissionDraft } from './types';

const VAGUE_PHRASES = new Set([
  'it works',
  'works correctly',
  'works properly',
  'works well',
  'done',
  'complete',
  'completed',
  'finished',
  'implemented',
  'fully implemented',
  'properly implemented',
  'feature complete',
]);

const TESTABLE_PATTERNS = [
  /\b[1-5]\d{2}\b/,
  /[<>]=?|==|!=/,
  /["'].+["']/,
  /[\w./]+\/[\w./]+/,
  /\b(pytest|npm test|make test|go test|cargo test|assert)\b/i,
];

function normalize(value: string): string {
  return value.replace(/[^\w\s]/g, ' ').trim().toLowerCase();
}

function isVagueStatement(value: string): boolean {
  if (value.trim() === '') {
    return true;
  }
  const normalized = normalize(value);
  if (VAGUE_PHRASES.has(normalized)) {
    return true;
  }
  const hasSignal = TESTABLE_PATTERNS.some((pattern) => pattern.test(value));
  return !hasSignal;
}

function collectVagueIssues(label: string, values: string[]): string[] {
  if (values.length === 0) {
    return [`${label} is missing.`];
  }

  const issues: string[] = [];
  for (const value of values) {
    if (isVagueStatement(value)) {
      issues.push(`${label} item is too vague: ${value.trim() || '(empty)'}`);
    }
  }
  return issues;
}

function collectDependencyWarnings(tasks: MissionDraft['draft_spec']['tasks']): string[] {
  const warnings: string[] = [];
  const taskIds = new Set(tasks.map((task) => task.id));

  for (const task of tasks) {
    for (const dependency of task.dependencies) {
      if (!taskIds.has(dependency)) {
        warnings.push(`Task ${task.id} depends on unknown task ${dependency}.`);
      }
    }
  }

  const state = new Map<string, 'unvisited' | 'visiting' | 'visited'>();
  const visit = (taskId: string, path: string[]): boolean => {
    const current = state.get(taskId) ?? 'unvisited';
    if (current === 'visiting') {
      const cycleStart = path.indexOf(taskId);
      const cyclePath = cycleStart >= 0 ? path.slice(cycleStart).concat(taskId) : path.concat(taskId);
      warnings.push(`Dependency cycle detected: ${cyclePath.join(' -> ')}.`);
      return true;
    }
    if (current === 'visited') {
      return false;
    }

    state.set(taskId, 'visiting');
    const task = tasks.find((entry) => entry.id === taskId);
    if (task) {
      for (const dependency of task.dependencies) {
        if (taskIds.has(dependency) && visit(dependency, path.concat(taskId))) {
          return true;
        }
      }
    }
    state.set(taskId, 'visited');
    return false;
  };

  for (const task of tasks) {
    if (visit(task.id, [])) {
      break;
    }
  }

  return warnings;
}

function collectModelWarnings(draft: MissionDraft, activeModelIds: Set<string>): string[] {
  const warnings: string[] = [];
  const approvedModels = new Set(draft.approved_models);
  const allowedModels = new Set([...approvedModels].filter((model) => activeModelIds.has(model)));

  const checkProfile = (model: string | null | undefined, label: string): void => {
    if (!model) {
      return;
    }
    if (!allowedModels.has(model)) {
      warnings.push(`${label} uses model ${model} outside the approved active set.`);
    }
  };

  checkProfile(draft.draft_spec.execution_defaults?.worker?.model ?? null, 'Worker defaults');
  checkProfile(draft.draft_spec.execution_defaults?.reviewer?.model ?? null, 'Reviewer defaults');

  for (const task of draft.draft_spec.tasks) {
    checkProfile(task.execution?.worker?.model ?? null, `Task ${task.id} worker execution`);
    checkProfile(task.execution?.reviewer?.model ?? null, `Task ${task.id} reviewer execution`);
  }

  return warnings;
}

export function collectAdvisoryFlightChecks(draft: MissionDraft | null, activeModelIds: string[]): string[] {
  if (!draft) {
    return [];
  }

  const warnings: string[] = [];
  warnings.push(...collectVagueIssues('Definition of Done', draft.draft_spec.definition_of_done));
  for (const task of draft.draft_spec.tasks) {
    warnings.push(...collectVagueIssues(`Task ${task.id} acceptance criteria`, task.acceptance_criteria));
  }

  if (draft.draft_spec.tasks.length > 7) {
    warnings.push(`Draft has ${draft.draft_spec.tasks.length} tasks; keep the launchable spec to 7 or fewer.`);
  }

  if (!draft.draft_spec.execution_defaults?.worker) {
    warnings.push('Worker execution settings are missing.');
  }
  if (!draft.draft_spec.execution_defaults?.reviewer) {
    warnings.push('Reviewer execution settings are missing.');
  }

  warnings.push(...collectDependencyWarnings(draft.draft_spec.tasks));
  warnings.push(...collectModelWarnings(draft, new Set(activeModelIds)));

  return warnings;
}
