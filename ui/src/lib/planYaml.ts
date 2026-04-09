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

export function serializeMissionPlanYaml(plan: EditableMissionPlan): string {
  const lines: string[] = [];

  lines.push(`name: ${stringifyScalar(plan.name)}`);
  lines.push(`goal: ${stringifyScalar(plan.goal)}`);

  if (plan.working_dir) {
    lines.push(`working_dir: ${stringifyScalar(plan.working_dir)}`);
  }

  lines.push('definition_of_done:');
  for (const criterion of plan.definition_of_done) {
    lines.push(`  - ${stringifyScalar(criterion)}`);
  }

  lines.push('tasks:');
  for (const task of plan.tasks) {
    lines.push(`  - id: ${stringifyScalar(task.id)}`);
    lines.push(`    title: ${stringifyScalar(task.title)}`);
    lines.push(`    description: ${stringifyScalar(task.description)}`);
    lines.push('    acceptance_criteria:');
    for (const criterion of task.acceptance_criteria) {
      lines.push(`      - ${stringifyScalar(criterion)}`);
    }
    if (task.model) {
      lines.push(`    model: ${stringifyScalar(task.model)}`);
    }
  }

  return `${lines.join('\n')}\n`;
}
