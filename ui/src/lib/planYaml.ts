import type { Caps, ExecutionConfig, ExecutionProfile, MissionSpec, TaskSpec } from './types';

export interface EditableTaskPlan {
  id: string;
  title: string;
  description: string;
  acceptance_criteria: string[];
  model: string;
}

export interface EditableMissionPlan {
  name: string;
  goal: string;
  definition_of_done: string[];
  tasks: EditableTaskPlan[];
  working_dir?: string;
}

function yamlScalar(value: unknown): string {
  if (value === null || value === undefined) {
    return 'null';
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(String(value));
}

function pushExecutionProfile(lines: string[], indent: string, label: string, profile?: ExecutionProfile | null): void {
  if (!profile) {
    return;
  }
  lines.push(`${indent}${label}:`);
  if (profile.agent !== undefined && profile.agent !== null) {
    lines.push(`${indent}  agent: ${yamlScalar(profile.agent)}`);
  }
  if (profile.model !== undefined && profile.model !== null) {
    lines.push(`${indent}  model: ${yamlScalar(profile.model)}`);
  }
  if (profile.thinking !== undefined && profile.thinking !== null) {
    lines.push(`${indent}  thinking: ${yamlScalar(profile.thinking)}`);
  }
}

function pushExecutionConfig(lines: string[], indent: string, key: string, execution?: ExecutionConfig | null): void {
  if (!execution) {
    return;
  }
  const hasWorker = Boolean(execution.worker);
  const hasReviewer = Boolean(execution.reviewer);
  if (!hasWorker && !hasReviewer) {
    return;
  }
  lines.push(`${indent}${key}:`);
  pushExecutionProfile(lines, `${indent}  `, 'worker', execution.worker);
  pushExecutionProfile(lines, `${indent}  `, 'reviewer', execution.reviewer);
}

function pushTask(lines: string[], task: TaskSpec): void {
  lines.push(`  - id: ${yamlScalar(task.id)}`);
  lines.push(`    title: ${yamlScalar(task.title)}`);
  lines.push(`    description: ${yamlScalar(task.description)}`);
  lines.push('    acceptance_criteria:');
  for (const criterion of task.acceptance_criteria) {
    lines.push(`      - ${yamlScalar(criterion)}`);
  }
  if (task.dependencies.length > 0) {
    lines.push('    dependencies:');
    for (const dependency of task.dependencies) {
      lines.push(`      - ${yamlScalar(dependency)}`);
    }
  }
  if (task.working_dir) {
    lines.push(`    working_dir: ${yamlScalar(task.working_dir)}`);
  }
  lines.push(`    max_retries: ${task.max_retries}`);
  if (task.output_artifacts.length > 0) {
    lines.push('    output_artifacts:');
    for (const artifact of task.output_artifacts) {
      lines.push(`      - ${yamlScalar(artifact)}`);
    }
  }
  if (task.tdd) {
    lines.push('    tdd:');
    if (task.tdd.test_file !== undefined && task.tdd.test_file !== null) {
      lines.push(`      test_file: ${yamlScalar(task.tdd.test_file)}`);
    }
    if (task.tdd.test_command !== undefined && task.tdd.test_command !== null) {
      lines.push(`      test_command: ${yamlScalar(task.tdd.test_command)}`);
    }
    lines.push(`      tests_must_pass: ${task.tdd.tests_must_pass}`);
    if (task.tdd.coverage_threshold !== undefined && task.tdd.coverage_threshold !== null) {
      lines.push(`      coverage_threshold: ${task.tdd.coverage_threshold}`);
    }
  }
  pushExecutionConfig(lines, '    ', 'execution', task.execution);
}

function pushCaps(lines: string[], caps: Caps): void {
  lines.push('caps:');
  lines.push(`  max_tokens_per_task: ${caps.max_tokens_per_task}`);
  lines.push(`  max_retries_global: ${caps.max_retries_global}`);
  lines.push(`  max_retries_per_task: ${caps.max_retries_per_task}`);
  lines.push(`  max_wall_time_minutes: ${caps.max_wall_time_minutes}`);
  lines.push(`  max_human_interventions: ${caps.max_human_interventions}`);
  lines.push(`  max_cost_usd: ${yamlScalar(caps.max_cost_usd)}`);
  lines.push(`  max_concurrent_workers: ${caps.max_concurrent_workers}`);
  if (caps.review !== undefined) {
    lines.push(`  review: ${yamlScalar(caps.review)}`);
  }
}

function parseScalar(value: string): string {
  const trimmed = value.trim();

  if (trimmed === '') {
    return '';
  }

  if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return trimmed.slice(1, -1);
    }
  }

  if (trimmed.startsWith('\'') && trimmed.endsWith('\'')) {
    return trimmed.slice(1, -1).replace(/''/g, '\'');
  }

  return trimmed;
}

function stringifyScalar(value: string): string {
  return JSON.stringify(value);
}

export function parseMissionPlanYaml(yaml: string): EditableMissionPlan {
  const lines = yaml.replace(/\r\n/g, '\n').split('\n');
  const plan: EditableMissionPlan = {
    name: '',
    goal: '',
    definition_of_done: [],
    tasks: [],
  };

  let section: 'root' | 'dod' | 'tasks' = 'root';
  let currentTask: EditableTaskPlan | null = null;
  let collectingCriteria = false;

  const finishTask = (): void => {
    if (currentTask) {
      plan.tasks.push(currentTask);
    }

    currentTask = null;
    collectingCriteria = false;
  };

  for (const rawLine of lines) {
    if (rawLine.trim() === '' || rawLine.trim().startsWith('#')) {
      continue;
    }

    const indent = rawLine.match(/^ */)?.[0].length ?? 0;
    const line = rawLine.trim();

    if (indent === 0) {
      finishTask();
      collectingCriteria = false;

      if (line.startsWith('definition_of_done:')) {
        section = 'dod';
        continue;
      }

      if (line.startsWith('tasks:')) {
        section = 'tasks';
        continue;
      }

      const colonIndex = line.indexOf(':');
      if (colonIndex === -1) {
        continue;
      }

      const key = line.slice(0, colonIndex).trim();
      const value = parseScalar(line.slice(colonIndex + 1));

      if (key === 'name') {
        plan.name = value;
      } else if (key === 'goal') {
        plan.goal = value;
      } else if (key === 'working_dir') {
        plan.working_dir = value;
      }

      section = 'root';
      continue;
    }

    if (section === 'dod') {
      if (line.startsWith('- ')) {
        plan.definition_of_done.push(parseScalar(line.slice(2)));
      }
      continue;
    }

    if (section !== 'tasks') {
      continue;
    }

    if (line.startsWith('- id:')) {
      finishTask();
      currentTask = {
        id: parseScalar(line.slice(5)),
        title: '',
        description: '',
        acceptance_criteria: [],
        model: '',
      };
      collectingCriteria = false;
      continue;
    }

    if (!currentTask) {
      continue;
    }

    if (line.startsWith('acceptance_criteria:')) {
      collectingCriteria = true;
      continue;
    }

    if (collectingCriteria && line.startsWith('- ')) {
      currentTask.acceptance_criteria.push(parseScalar(line.slice(2)));
      continue;
    }

    const colonIndex = line.indexOf(':');
    if (colonIndex === -1) {
      continue;
    }

    const key = line.slice(0, colonIndex).trim();
    const value = parseScalar(line.slice(colonIndex + 1));

    if (key === 'title') {
      currentTask.title = value;
    } else if (key === 'description') {
      currentTask.description = value;
    } else if (key === 'model') {
      currentTask.model = value;
    }
  }

  finishTask();

  return plan;
}

export function serializeMissionPlanYaml(plan: MissionSpec): string {
  const lines: string[] = [];

  lines.push(`name: ${stringifyScalar(plan.name)}`);
  lines.push(`goal: ${stringifyScalar(plan.goal)}`);

  if (plan.working_dir) {
    lines.push(`working_dir: ${stringifyScalar(plan.working_dir)}`);
  }

  if (plan.project_memory_file) {
    lines.push(`project_memory_file: ${stringifyScalar(plan.project_memory_file)}`);
  }

  lines.push('definition_of_done:');
  for (const criterion of plan.definition_of_done) {
    lines.push(`  - ${stringifyScalar(criterion)}`);
  }

  pushCaps(lines, plan.caps);

  if (plan.execution_defaults) {
    pushExecutionConfig(lines, '', 'execution_defaults', plan.execution_defaults);
  }

  lines.push('tasks:');
  for (const task of plan.tasks) {
    pushTask(lines, task);
  }

  return `${lines.join('\n')}\n`;
}
