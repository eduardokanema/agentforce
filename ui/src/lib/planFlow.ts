import type { MissionDraft, PlanRun, PlanStep, PlanVersion } from './types';

export type CockpitPhaseId =
  | 'briefing'
  | 'preflight'
  | 'draft'
  | 'stress_test'
  | 'finalize'
  | 'launch';

export type CockpitPhaseStatus =
  | 'complete'
  | 'current'
  | 'up_next'
  | 'locked'
  | 'blocked'
  | 'unknown';

export type PlanningSubstepId =
  | 'planner_synthesis'
  | 'mission_plan_pass'
  | 'technical_critic'
  | 'practical_critic'
  | 'resolver';

export interface PlanningSubstepState {
  id: PlanningSubstepId;
  label: string;
  status: 'idle' | 'running' | 'complete' | 'failed' | 'stale';
  summary?: string;
  timestamp?: string | null;
}

export interface CockpitPhaseState {
  id: CockpitPhaseId;
  label: string;
  status: CockpitPhaseStatus;
  summary: string;
  railSummary?: string | null;
  timestamp?: string | null;
  blocker?: string | null;
  available: boolean;
}

export interface LaunchReadinessState {
  ready: boolean;
  blockers: string[];
  summary: string;
}

export interface PlanFlowState {
  currentPhaseId: CockpitPhaseId;
  currentRun: PlanRun | null;
  latestVersion: PlanVersion | null;
  launchReadiness: LaunchReadinessState;
  phases: CockpitPhaseState[];
  substeps: PlanningSubstepState[];
  nextAction: string;
  activeSummary: string;
  latestRunIssue: string | null;
  unknownState: boolean;
}

const PHASE_ORDER: CockpitPhaseId[] = [
  'briefing',
  'preflight',
  'draft',
  'stress_test',
  'finalize',
  'launch',
];

const SUBSTEP_LABELS: Record<PlanningSubstepId, string> = {
  planner_synthesis: 'Planner Synthesis',
  mission_plan_pass: 'Mission Plan Pass',
  technical_critic: 'Technical Critic',
  practical_critic: 'Practical Critic',
  resolver: 'Resolver',
};

function normalizedText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function latestRun(draft: MissionDraft | null): PlanRun | null {
  return draft?.plan_runs?.[0] ?? null;
}

function latestVersion(draft: MissionDraft | null): PlanVersion | null {
  return draft?.plan_versions?.[0] ?? null;
}

function latestStep(run: PlanRun | null): PlanStep | null {
  if (!run || run.steps.length === 0) {
    return null;
  }
  return run.steps[run.steps.length - 1] ?? null;
}

function latestFailedStep(run: PlanRun | null): PlanStep | null {
  if (!run) {
    return null;
  }
  return [...run.steps]
    .reverse()
    .find((step) => step.status === 'failed' || step.status === 'stale')
    ?? null;
}

function stepFailureLabel(step: PlanStep | null): string | null {
  if (!step || (step.status !== 'failed' && step.status !== 'stale')) {
    return null;
  }
  const label = SUBSTEP_LABELS[step.name as PlanningSubstepId] ?? step.name.replace(/_/g, ' ');
  const detail = step.summary || step.message || '';
  const interventionRequired = Boolean(
    step.human_intervention_needed
      || step.metadata?.human_intervention_needed
      || step.metadata?.intervention_required
      || step.metadata?.requires_human_intervention,
  );
  const suffix = interventionRequired ? ' Intervention required.' : '';
  return detail ? `${label} ${step.status === 'stale' ? 'went stale' : 'failed'}: ${detail}${suffix}` : `${label} ${step.status === 'stale' ? 'went stale' : 'failed'}.${suffix}`;
}

function phaseIndex(id: CockpitPhaseId): number {
  return PHASE_ORDER.indexOf(id);
}

function isStressStep(stepName: string | null | undefined): boolean {
  return stepName === 'technical_critic'
    || stepName === 'practical_critic'
    || stepName === 'resolver';
}

function stepToPhase(stepName: string | null | undefined): CockpitPhaseId {
  return isStressStep(stepName) ? 'stress_test' : 'draft';
}

function buildSubsteps(run: PlanRun | null): PlanningSubstepState[] {
  const stepsById = new Map<string, PlanStep>(
    (run?.steps ?? []).map((step) => [step.name, step]),
  );

  return (Object.keys(SUBSTEP_LABELS) as PlanningSubstepId[]).map((id) => {
    const step = stepsById.get(id);
    if (!step) {
      return {
        id,
        label: SUBSTEP_LABELS[id],
        status: 'idle',
      };
    }

    let status: PlanningSubstepState['status'] = 'idle';
    if ((step.status === 'started' || step.status === 'running') && run?.status === 'failed') {
      status = 'failed';
    } else if ((step.status === 'started' || step.status === 'running') && run?.status === 'stale') {
      status = 'stale';
    } else if (step.status === 'started' || step.status === 'running') {
      status = 'running';
    } else if (step.status === 'failed') {
      status = 'failed';
    } else if (step.status === 'stale') {
      status = 'stale';
    } else {
      status = 'complete';
    }

    return {
      id,
      label: SUBSTEP_LABELS[id],
      status,
      summary: step.summary || step.message || undefined,
      timestamp: step.completed_at || step.started_at || null,
    };
  });
}

function phaseLabel(id: CockpitPhaseId): string {
  switch (id) {
    case 'briefing':
      return 'Briefing';
    case 'preflight':
      return 'Preflight';
    case 'draft':
      return 'Draft';
    case 'stress_test':
      return 'Stress Test';
    case 'finalize':
      return 'Finalize';
    case 'launch':
      return 'Launch Window';
  }
}

function countLabel(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

function buildPhaseCopy(
  phaseId: CockpitPhaseId,
  draft: MissionDraft,
  run: PlanRun | null,
  version: PlanVersion | null,
  validationIssues: string[],
): { summary: string; railSummary: string; timestamp?: string | null } {
  const step = latestStep(run);
  const missionName = normalizedText(draft.draft_spec.name);
  const workspaceCount = draft.workspace_paths.length;
  const planningProfiles = Object.values((draft.validation?.planning_profiles as Record<string, unknown> | undefined) ?? {})
    .filter((value): value is { model?: string | null } => Boolean(value) && typeof value === 'object')
    .filter((value) => typeof value.model === 'string' && value.model.trim() !== '');
  const profileCount = planningProfiles.length;

  switch (phaseId) {
    case 'briefing':
      return {
        summary: missionName
          ? `${missionName} is staged with ${countLabel(workspaceCount, 'workspace')} and ${countLabel(profileCount, 'planning profile')}.`
          : 'Mission brief configured and ready for the first planning pass.',
        railSummary: missionName ? 'Mission brief locked' : 'Brief pending',
      };
    case 'preflight':
      if (draft.preflight_status === 'pending') {
        return {
          summary: `${countLabel(draft.preflight_questions?.length ?? 0, 'clarification question')} still gate the first planning pass.`,
          railSummary: countLabel(draft.preflight_questions?.length ?? 0, 'question'),
        };
      }
      if (draft.repair_status === 'pending') {
        return {
          summary: `${countLabel(draft.repair_questions?.length ?? 0, 'repair question')} must be answered before planning can continue.`,
          railSummary: countLabel(draft.repair_questions?.length ?? 0, 'repair'),
        };
      }
      if (draft.repair_status === 'manual_edit_required') {
        return {
          summary: draft.repair_context?.gate_reason || 'Repair rounds are exhausted. Manual edits are required before planning can continue.',
          railSummary: 'Manual repair',
        };
      }
      return {
        summary: draft.preflight_status === 'skipped'
          ? 'Preflight was skipped. Planning can proceed, but the mission may be carrying unanswered assumptions.'
          : 'Preflight answers are recorded and the planner can continue.',
        railSummary: draft.preflight_status === 'skipped' ? 'Skipped' : 'Resolved',
      };
    case 'draft':
      return {
        summary: step?.summary || step?.message || 'Planner is shaping the mission structure and drafting the initial flight plan.',
        railSummary: run
          ? (step?.name ? SUBSTEP_LABELS[step.name as PlanningSubstepId] ?? 'Planner active' : 'Planner active')
          : 'Awaiting first pass',
        timestamp: step?.completed_at || step?.started_at || null,
      };
    case 'stress_test':
      return {
        summary: step?.summary || 'Critics and resolver are pressure-testing the plan before launch.',
        railSummary: run?.status === 'failed'
          ? 'Issue detected'
          : run?.status === 'stale'
            ? 'Run went stale'
            : 'Stress test active',
        timestamp: step?.completed_at || step?.started_at || null,
      };
    case 'finalize':
      return {
        summary: validationIssues.length > 0
          ? `${countLabel(validationIssues.length, 'launch blocker')} still need attention before the mission can enter the launch window.`
          : 'Reviewed draft is ready for final inspection before commitment.',
        railSummary: validationIssues.length > 0 ? countLabel(validationIssues.length, 'blocker') : 'Inspection ready',
        timestamp: version?.created_at || null,
      };
    case 'launch':
      return {
        summary: version
          ? `Reviewed version ${version.id} is armed for launch. Confirm readiness and commit the mission.`
          : 'No promoted version is armed for launch yet.',
        railSummary: version ? 'Launch ready' : 'Awaiting version',
        timestamp: version?.created_at || null,
      };
  }
}

function buildLaunchReadiness(
  draft: MissionDraft,
  run: PlanRun | null,
  version: PlanVersion | null,
  validationIssues: string[],
  conflictMessage: string | null,
): LaunchReadinessState {
  const blockers: string[] = [];

  if (draft.preflight_status === 'pending') {
    blockers.push('Preflight questions still need answers.');
  }
  if (!version) {
    blockers.push('No reviewed plan version is promoted yet.');
  }
  if (validationIssues.length > 0) {
    blockers.push(...validationIssues);
  }
  if (conflictMessage) {
    blockers.push(conflictMessage);
  }
  if (run?.status === 'queued' || run?.status === 'running') {
    blockers.push('A newer planning run is still in progress.');
  }
  if (run?.status === 'failed') {
    blockers.push(run.error_message || 'Newest planning run failed and must be resolved.');
  }
  if (run?.status === 'stale') {
    blockers.push('Newest planning run went stale and must be resolved.');
  }

  if (blockers.length > 0) {
    return {
      ready: false,
      blockers,
      summary: blockers[0],
    };
  }

  return {
    ready: true,
    blockers: [],
    summary: 'Launch window clear. Mission can be started now.',
  };
}

export function derivePlanFlow(
  draft: MissionDraft | null,
  options?: {
    conflictMessage?: string | null;
    validationIssues?: string[];
  },
): PlanFlowState {
  const validationIssues = options?.validationIssues ?? [];
  const conflictMessage = options?.conflictMessage ?? null;

  if (!draft) {
    return {
      currentPhaseId: 'briefing',
      currentRun: null,
      latestVersion: null,
      launchReadiness: {
        ready: false,
        blockers: ['Create a planning draft first.'],
        summary: 'Mission brief not created yet.',
      },
      phases: PHASE_ORDER.map((id, index) => ({
        id,
        label: phaseLabel(id),
        status: index === 0 ? 'current' : 'locked',
        summary: index === 0 ? 'Define mission brief, workspace, and planning stack.' : 'Locked until prior phases complete.',
        available: index === 0,
      })),
      substeps: buildSubsteps(null),
      nextAction: 'Define the mission brief and open a flight plan.',
      activeSummary: 'Mission brief not created yet.',
      latestRunIssue: null,
      unknownState: false,
    };
  }

  const run = latestRun(draft);
  const version = latestVersion(draft);
  const readiness = buildLaunchReadiness(draft, run, version, validationIssues, conflictMessage);
  const preflightPending = draft.preflight_status === 'pending'
    && (draft.preflight_questions?.length ?? 0) > 0;
  const repairPending = draft.repair_status === 'pending'
    && (draft.repair_questions?.length ?? 0) > 0;

  let currentPhaseId: CockpitPhaseId = 'briefing';
  let latestRunIssue: string | null = null;
  let unknownState = false;

  if (preflightPending || repairPending || draft.repair_status === 'manual_edit_required') {
    currentPhaseId = 'preflight';
  } else if (run?.status === 'queued' || run?.status === 'running') {
    currentPhaseId = stepToPhase(run.current_step);
  } else if (run?.status === 'failed' || run?.status === 'stale') {
    currentPhaseId = stepToPhase(run.current_step || latestStep(run)?.name);
    latestRunIssue = stepFailureLabel(latestFailedStep(run))
      || run.error_message
      || (run.status === 'stale'
        ? 'Latest run became stale.'
        : 'Latest run failed.');
  } else if (version) {
    currentPhaseId = readiness.ready ? 'launch' : 'finalize';
  } else if (run) {
    currentPhaseId = stepToPhase(run.current_step || latestStep(run)?.name);
    unknownState = true;
  } else {
    currentPhaseId = 'draft';
  }

  const phases = PHASE_ORDER.map((id) => {
    const summary = buildPhaseCopy(id, draft, run, version, validationIssues);
    const idIndex = phaseIndex(id);
    const currentIndex = phaseIndex(currentPhaseId);

    let status: CockpitPhaseStatus = 'locked';
    if (id === currentPhaseId) {
      status = latestRunIssue && (id === 'draft' || id === 'stress_test')
        ? 'blocked'
        : 'current';
    } else if (idIndex < currentIndex) {
      status = 'complete';
    } else if (idIndex === currentIndex + 1) {
      status = 'up_next';
    }

    if (id === 'launch' && !readiness.ready && status === 'locked' && version) {
      status = 'up_next';
    }

    return {
      id,
      label: phaseLabel(id),
      status,
      summary: summary.summary,
      railSummary: summary.railSummary,
      timestamp: summary.timestamp ?? null,
      blocker: id === 'launch' ? readiness.summary : id === currentPhaseId ? latestRunIssue : null,
      available: status === 'complete' || status === 'current' || status === 'blocked',
    };
  });

  let nextAction = 'Review the current stage.';
  if (currentPhaseId === 'briefing') {
    nextAction = 'Open the first flight plan.';
  } else if (currentPhaseId === 'preflight') {
    nextAction = 'Answer or skip the preflight clarifications.';
  } else if (currentPhaseId === 'draft') {
    nextAction = latestRunIssue
      ? 'Resolve the latest planning issue or retry the run.'
      : run
        ? 'Monitor planner synthesis and mission-plan checks.'
        : 'Send the first planner guidance or refine the engineering controls.';
  } else if (currentPhaseId === 'stress_test') {
    nextAction = latestRunIssue ? 'Resolve the latest critic or resolver issue.' : 'Wait for the critics and resolver to finish.';
  } else if (currentPhaseId === 'finalize') {
    nextAction = readiness.summary;
  } else if (currentPhaseId === 'launch') {
    nextAction = 'Launch the mission or inspect prior phases before committing.';
  }

  return {
    currentPhaseId,
    currentRun: run,
    latestVersion: version,
    launchReadiness: readiness,
    phases,
    substeps: buildSubsteps(run),
    nextAction,
    activeSummary: phases[phaseIndex(currentPhaseId)]?.summary ?? 'Planning state updated.',
    latestRunIssue,
    unknownState,
  };
}
