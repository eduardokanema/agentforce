import type { MissionDraft } from './types';

const THINKING_LEVELS = new Set(['low', 'medium', 'high', 'xhigh']);

function normalizeConfiguredModelId(model: string | null | undefined): string | null {
  if (!model) {
    return null;
  }
  const trimmed = model.trim();
  if (!trimmed) {
    return null;
  }
  const firstColon = trimmed.indexOf(':');
  const lastColon = trimmed.lastIndexOf(':');
  if (firstColon <= 0 || lastColon <= firstColon + 1 || lastColon >= trimmed.length - 1) {
    return trimmed;
  }
  const thinking = trimmed.slice(lastColon + 1).trim().toLowerCase();
  if (!THINKING_LEVELS.has(thinking)) {
    return trimmed;
  }
  return trimmed.slice(firstColon + 1, lastColon).trim() || trimmed;
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

  const checkProfile = (model: string | null | undefined, label: string): void => {
    const normalizedModel = normalizeConfiguredModelId(model);
    if (!normalizedModel) {
      return;
    }
    if (!activeModelIds.has(normalizedModel)) {
      warnings.push(`${label} uses inactive model ${normalizedModel}.`);
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
