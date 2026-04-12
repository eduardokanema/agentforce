import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_LABS_CONFIG, type BlackHoleCampaignState, type MissionDraft, type Model } from "../lib/types";
import BlackHoleModePage from "./BlackHoleModePage";

function flushPromises(): Promise<void> {
  return act(async () => {
    await Promise.resolve();
  });
}

function makeDraft(overrides: Partial<MissionDraft> = {}): MissionDraft {
  return {
    id: "draft-123",
    revision: 3,
    status: "draft",
    draft_kind: "black_hole",
    draft_spec: {
      name: "Black Hole Campaign",
      goal: "Refactor the repository recursively",
      definition_of_done: [],
      caps: {
        max_tokens_per_task: 100000,
        max_retries_global: 3,
        max_retries_per_task: 3,
        max_wall_time_minutes: 120,
        max_human_interventions: 2,
        max_cost_usd: null,
        max_concurrent_workers: 3,
      },
      tasks: [],
    },
    turns: [
      { role: "user", content: "Refactor until no Python function exceeds 300 lines." },
      { role: "assistant", content: "Black hole draft initialized." },
    ],
    validation: {
      draft_kind: "black_hole",
      summary: ["Ready to arm"],
      issues: [],
    },
    activity_log: [],
    approved_models: ["claude-sonnet-4-5", "claude-haiku-4-5"],
    workspace_paths: ["/workspace/app"],
    companion_profile: {
      id: "planner",
      label: "Planner",
      model: "claude-opus-4-5",
    },
    draft_notes: [],
    ...overrides,
  };
}

function makeBlackHoleState(): BlackHoleCampaignState {
  return {
    draft_id: "draft-123",
    draft_kind: "black_hole",
    config: {
      mode: "black_hole",
      objective: "Refactor until no Python function exceeds 300 lines.",
      analyzer: "python_fn_length",
      scope: "repo",
      global_acceptance: [],
      loop_limits: {
        max_loops: 8,
        max_no_progress: 2,
        function_line_limit: 300,
      },
      gate_policy: {
        require_test_delta: true,
        public_surface_policy: "justify",
      },
      docs_manifest_path: null,
      notes: "",
    },
    campaign: {
      id: "campaign-1",
      draft_id: "draft-123",
      status: "child_mission_running",
      created_at: "2026-04-11T00:00:00Z",
      updated_at: "2026-04-11T00:10:00Z",
      current_loop: 2,
      max_loops: 8,
      max_no_progress: 2,
      no_progress_count: 0,
      active_child_mission_id: "mission-1",
      active_plan_run_id: "run-99",
      last_metric: {
        threshold: 300,
        violations: 4,
      },
      last_delta: 34,
      stop_reason: "",
      config_snapshot: {},
      tokens_in: 1200,
      tokens_out: 3400,
      cost_usd: 0.221,
    },
    loops: [
      {
        campaign_id: "campaign-1",
        loop_no: 2,
        status: "launched",
        created_at: "2026-04-11T00:05:00Z",
        candidate_id: "app.py:big_fn:12",
        candidate_summary: "app.py:12-355 spans 344 lines",
        metric_before: { violations: 5, max_line_count: 344 },
        metric_after: { violations: 4, max_line_count: 330 },
        normalized_delta: 22,
        plan_run_id: "run-1",
        plan_version_id: "version-1",
        mission_id: "mission-1",
        review_summary: "Child mission completed with all tasks review-approved.",
      },
    ],
  };
}

function renderPage(
  fetchMock: ReturnType<typeof vi.fn>,
  initialEntry = "/black-hole",
): { container: HTMLDivElement; root: Root } {
  vi.stubGlobal("fetch", fetchMock);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/black-hole" element={<BlackHoleModePage />} />
          <Route path="/black-hole/:id" element={<BlackHoleModePage />} />
          <Route path="/plan/:id" element={<div data-testid="plan-route">Plan route</div>} />
        </Routes>
      </MemoryRouter>,
    );
  });

  return { container, root };
}

const models: Model[] = [
  {
    id: "claude-opus-4-5",
    name: "Claude Opus 4.5",
    provider: "Anthropic",
    cost_per_1k_input: 0.015,
    cost_per_1k_output: 0.075,
    latency_label: "Powerful",
  },
  {
    id: "claude-sonnet-4-5",
    name: "Claude Sonnet 4.5",
    provider: "Anthropic",
    cost_per_1k_input: 0.003,
    cost_per_1k_output: 0.015,
    latency_label: "Standard",
  },
];

describe("BlackHoleModePage", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("creates black-hole drafts without auto-starting a simple plan run", async () => {
    window.localStorage.setItem("agentforce-black-hole-workspaces-v1", JSON.stringify(["/workspace/app"]));
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/models") {
        return new Response(JSON.stringify(models), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/config") {
        return new Response(JSON.stringify({
          filesystem: { allowed_base_paths: ["/workspace"] },
          default_caps: { max_concurrent_workers: 2, max_retries_per_task: 2, max_wall_time_minutes: 60, max_cost_usd: 0 },
          labs: { ...DEFAULT_LABS_CONFIG, black_hole_enabled: true },
        }), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.startsWith("/api/filesystem")) {
        return new Response(JSON.stringify({
          path: "/workspace",
          entries: [{ name: "app", path: "/workspace/app", is_dir: true }],
          parent: null,
        }), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/plan/drafts") {
        const body = JSON.parse(String(init?.body || "{}"));
        expect(body.auto_start).toBe(false);
        expect(body.validation.draft_kind).toBe("black_hole");
        return new Response(JSON.stringify({ id: "draft-123", revision: 1 }), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/plan/drafts/draft-123") {
        return new Response(JSON.stringify(makeDraft()), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/plan/drafts/draft-123/black-hole") {
        return new Response(JSON.stringify({ draft_id: "draft-123", draft_kind: "black_hole", campaign: null, config: null, loops: [] }), {
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock);
    await flushPromises();

    const prompt = container.querySelector("#black-hole-prompt") as HTMLTextAreaElement;
    await act(async () => {
      prompt.value = "Refactor recursively";
      prompt.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const openButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Open Black Hole"),
    ) as HTMLButtonElement | undefined;

    await act(async () => {
      openButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/plan/drafts", expect.anything());

    act(() => {
      root.unmount();
    });
  });

  it("renders the black-hole hero, config panel, and ledger on the dedicated route", async () => {
    const blackHoleState = makeBlackHoleState();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/models") {
        return new Response(JSON.stringify(models), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/plan/drafts/draft-123") {
        return new Response(JSON.stringify(makeDraft({
          validation: {
            ...makeDraft().validation,
            black_hole_config: blackHoleState.config,
          },
        })), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/plan/drafts/draft-123/black-hole") {
        return new Response(JSON.stringify(blackHoleState), {
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock, "/black-hole/draft-123");
    await flushPromises();

    expect(container.textContent).toContain("Black Hole Campaign Telemetry");
    expect(container.textContent).toContain("Black Hole Campaign");
    expect(container.textContent).toContain("Loop Ledger");
    expect(container.textContent).toContain("Candidate-by-candidate provenance");

    act(() => {
      root.unmount();
    });
  });

  it("redirects simple-plan drafts back to plan mode", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/models") {
        return new Response(JSON.stringify(models), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/plan/drafts/draft-123") {
        return new Response(JSON.stringify(makeDraft({
          draft_kind: "simple_plan",
          validation: { summary: ["Ready to refine"], issues: [] },
        })), {
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock, "/black-hole/draft-123");
    await flushPromises();

    expect(container.textContent).toContain("Plan route");

    act(() => {
      root.unmount();
    });
  });

  it("renders repair questions and resumes the locked loop after submission", async () => {
    const blackHoleState = makeBlackHoleState();
    let repairSubmitted = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/models") {
        return new Response(JSON.stringify(models), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/plan/drafts/draft-123") {
        return new Response(JSON.stringify(makeDraft({
          revision: repairSubmitted ? 5 : 4,
          validation: {
            ...makeDraft().validation,
            black_hole_config: blackHoleState.config,
          },
          repair_status: repairSubmitted ? "not_needed" : "pending",
          repair_questions: repairSubmitted ? [] : [
            {
              id: "repair_desc",
              prompt: "Allow the planner to update the description?",
              options: ["Accept proposed change", "Decline proposed change", "Edit manually"],
              preview: {
                before_text: "Current description",
                proposed_text: "Proposed description",
                why_required: "The repair pass needs a coherent description to proceed.",
              },
            },
          ],
          repair_answers: {},
          repair_context: {
            loop_no: 2,
            repair_round: 1,
            source_version_id: "version-1",
            gate_reason: "Answer repair questions before the loop can continue.",
          },
        })), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/plan/drafts/draft-123/black-hole") {
        return new Response(JSON.stringify(blackHoleState), {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/plan/drafts/draft-123/black-hole/repair") {
        repairSubmitted = true;
        const body = JSON.parse(String(init?.body || "{}"));
        expect(body.loop_no).toBe(2);
        expect(body.repair_round).toBe(1);
        expect(body.source_version_id).toBe("version-1");
        return new Response(JSON.stringify({ draft_id: "draft-123", revision: 5, status: "queued", campaign_id: "campaign-1" }), {
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock, "/black-hole/draft-123");
    await flushPromises();

    expect(container.textContent).toContain("Repair Questions");
    expect(container.textContent).toContain("Proposed description");

    const acceptOption = Array.from(container.querySelectorAll("label")).find((label) =>
      label.textContent?.includes("Accept proposed change"),
    );
    expect(acceptOption).toBeTruthy();

    await act(async () => {
      acceptOption?.querySelector("input")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const reviewButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Review Answers"),
    );
    expect(reviewButton).toBeTruthy();

    await act(async () => {
      reviewButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const resumeButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Resume Locked Loop"),
    );
    expect(resumeButton).toBeTruthy();

    await act(async () => {
      resumeButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/plan/drafts/draft-123/black-hole/repair", expect.anything());

    act(() => {
      root.unmount();
    });
  });
});
