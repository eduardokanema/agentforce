import { describe, expect, it } from "vitest";
import { derivePlanFlow } from "./planFlow";
import type { MissionDraft, PlanRun, PlanVersion } from "./types";

function makeRun(overrides: Partial<PlanRun> = {}): PlanRun {
  return {
    id: "run-1",
    draft_id: "draft-1",
    base_revision: 1,
    head_revision_seen: 1,
    status: "queued",
    trigger_kind: "auto",
    trigger_message: "Initial run",
    created_at: "2026-04-11T00:00:00Z",
    steps: [],
    cost_usd: 0,
    ...overrides,
  };
}

function makeVersion(overrides: Partial<PlanVersion> = {}): PlanVersion {
  return {
    id: "version-1",
    draft_id: "draft-1",
    source_run_id: "run-1",
    revision_base: 1,
    created_at: "2026-04-11T00:05:00Z",
    draft_spec_snapshot: makeDraft().draft_spec,
    changelog: ["Resolver promoted the reviewed plan."],
    validation: {},
    ...overrides,
  };
}

function makeDraft(overrides: Partial<MissionDraft> = {}): MissionDraft {
  return {
    id: "draft-1",
    revision: 1,
    status: "draft",
    draft_spec: {
      name: "Flight Director",
      goal: "Ship the new cockpit",
      definition_of_done: ["Phase flow works"],
      caps: {
        max_tokens_per_task: 100000,
        max_retries_global: 3,
        max_retries_per_task: 3,
        max_wall_time_minutes: 120,
        max_human_interventions: 2,
        max_cost_usd: null,
        max_concurrent_workers: 3,
      },
      execution_defaults: {
        worker: {
          agent: "codex",
          model: "gpt-5.4",
          thinking: "medium",
        },
        reviewer: {
          agent: "codex",
          model: "gpt-5.4",
          thinking: "medium",
        },
      },
      tasks: [
        {
          id: "01",
          title: "Build shell",
          description: "Implement the cockpit shell.",
          acceptance_criteria: ["Phase rail renders"],
          dependencies: [],
          max_retries: 3,
          output_artifacts: [],
        },
      ],
    },
    turns: [{ role: "user", content: "Build the cockpit" }],
    validation: {
      summary: [],
      issues: [],
    },
    activity_log: [],
    approved_models: ["gpt-5.4"],
    workspace_paths: ["/workspace/app"],
    companion_profile: {
      id: "planner",
      label: "Planner",
      agent: "codex",
      model: "gpt-5.4",
      thinking: "medium",
    },
    draft_notes: [],
    preflight_status: "answered",
    preflight_questions: [],
    preflight_answers: {},
    plan_runs: [],
    plan_versions: [],
    ...overrides,
  };
}

describe("derivePlanFlow", () => {
  it("defaults a created brief with no runs to the draft phase", () => {
    const flow = derivePlanFlow(makeDraft());

    expect(flow.currentPhaseId).toBe("draft");
    expect(flow.nextAction).toContain("planner guidance");
    expect(flow.phases.find((phase) => phase.id === "briefing")?.status).toBe("complete");
    expect(flow.phases.find((phase) => phase.id === "draft")?.railSummary).toBe("Awaiting first pass");
  });

  it("moves to preflight when clarifications are pending", () => {
    const flow = derivePlanFlow(
      makeDraft({
        preflight_status: "pending",
        preflight_questions: [
          {
            id: "scope",
            prompt: "Confirm the scope",
            options: ["Small", "Large"],
            allow_custom: true,
          },
        ],
      }),
    );

    expect(flow.currentPhaseId).toBe("preflight");
    expect(flow.nextAction).toContain("Answer or skip");
  });

  it("uses the active run step to focus stress test work", () => {
    const flow = derivePlanFlow(
      makeDraft({
        plan_runs: [
          makeRun({
            status: "running",
            current_step: "technical_critic",
            steps: [
              {
                name: "technical_critic",
                status: "running",
                started_at: "2026-04-11T00:01:00Z",
                summary: "Critic is reviewing the plan.",
              },
            ],
          }),
        ],
      }),
    );

    expect(flow.currentPhaseId).toBe("stress_test");
    expect(flow.substeps.find((step) => step.id === "technical_critic")?.status).toBe("running");
  });

  it("keeps launch blocked when the newest run failed even if a version exists", () => {
    const flow = derivePlanFlow(
      makeDraft({
        plan_runs: [
          makeRun({
            id: "run-latest",
            status: "failed",
            current_step: "resolver",
            error_message: "Resolver could not reconcile critic feedback.",
            steps: [
              {
                name: "resolver",
                status: "failed",
                started_at: "2026-04-11T00:02:00Z",
                completed_at: "2026-04-11T00:03:00Z",
                summary: "Resolver failed.",
              },
            ],
          }),
        ],
        plan_versions: [makeVersion()],
      }),
    );

    expect(flow.currentPhaseId).toBe("stress_test");
    expect(flow.launchReadiness.ready).toBe(false);
    expect(flow.launchReadiness.summary).toContain("Resolver could not reconcile critic feedback.");
    expect(flow.phases.find((phase) => phase.id === "launch")?.status).toBe("up_next");
  });

  it("surfaces failed step details and intervention guidance for a failed run", () => {
    const flow = derivePlanFlow(
      makeDraft({
        plan_runs: [
          makeRun({
            status: "failed",
            current_step: "technical_critic",
            error_message: "codex planning step failed",
            steps: [
              {
                name: "technical_critic",
                status: "failed",
                started_at: "2026-04-11T00:01:00Z",
                completed_at: "2026-04-11T00:02:00Z",
                summary: "Planner response was incomplete.",
                metadata: {
                  human_intervention_needed: true,
                },
              },
            ],
          }),
        ],
      }),
    );

    expect(flow.currentPhaseId).toBe("stress_test");
    expect(flow.latestRunIssue).toContain("Technical Critic failed");
    expect(flow.latestRunIssue).toContain("Intervention required");
  });

  it("handles drafts with missing name and goal fields without crashing", () => {
    const flow = derivePlanFlow(
      makeDraft({
        draft_spec: {
          ...makeDraft().draft_spec,
          name: undefined as unknown as string,
          goal: undefined as unknown as string,
        },
      }),
    );

    expect(flow.currentPhaseId).toBe("draft");
    expect(flow.phases.find((phase) => phase.id === "briefing")?.summary).toContain("Mission brief configured");
  });

  it("opens the launch window only when a reviewed version exists and blockers are clear", () => {
    const flow = derivePlanFlow(
      makeDraft({
        plan_runs: [
          makeRun({
            status: "completed",
            current_step: "resolver",
            steps: [
              {
                name: "resolver",
                status: "completed",
                started_at: "2026-04-11T00:02:00Z",
                completed_at: "2026-04-11T00:03:00Z",
                summary: "Resolver completed.",
              },
            ],
          }),
        ],
        plan_versions: [makeVersion()],
      }),
    );

    expect(flow.currentPhaseId).toBe("launch");
    expect(flow.launchReadiness.ready).toBe(true);
    expect(flow.phases.find((phase) => phase.id === "launch")?.status).toBe("current");
    expect(flow.phases.find((phase) => phase.id === "launch")?.railSummary).toBe("Launch ready");
  });
});
