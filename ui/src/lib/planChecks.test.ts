import { describe, expect, it } from 'vitest';
import { collectAdvisoryFlightChecks } from './planChecks';
import type { MissionDraft } from './types';

function makeDraft(overrides: Partial<MissionDraft> = {}): MissionDraft {
  return {
    id: 'draft-123',
    revision: 1,
    status: 'draft',
    draft_spec: {
      name: 'Legacy Profile Draft',
      goal: 'Keep advisory checks aligned with active models',
      definition_of_done: [],
      caps: {
        max_tokens_per_task: 100000,
        max_retries_global: 3,
        max_retries_per_task: 3,
        max_wall_time_minutes: 60,
        max_human_interventions: 2,
        max_cost_usd: null,
        max_concurrent_workers: 2,
      },
      execution_defaults: {
        worker: {
          agent: 'codex',
          model: 'gpt-5.4',
          thinking: 'medium',
        },
        reviewer: {
          agent: 'codex',
          model: 'codex:gpt-5.4:medium',
          thinking: 'medium',
        },
      },
      tasks: [],
    },
    turns: [],
    validation: {},
    activity_log: [],
    approved_models: ['gpt-5.4'],
    workspace_paths: [],
    companion_profile: {},
    draft_notes: [],
    ...overrides,
  };
}

describe('collectAdvisoryFlightChecks', () => {
  it('treats legacy execution profile ids as active when the underlying model is active', () => {
    const warnings = collectAdvisoryFlightChecks(makeDraft(), ['gpt-5.4']);

    expect(warnings).not.toContain('Reviewer defaults uses inactive model gpt-5.4.');
    expect(warnings.some((warning) => warning.includes('inactive model'))).toBe(false);
  });

  it('still warns when the underlying model is inactive', () => {
    const warnings = collectAdvisoryFlightChecks(makeDraft(), ['gpt-5.4-mini']);

    expect(warnings).toContain('Reviewer defaults uses inactive model gpt-5.4.');
  });
});
