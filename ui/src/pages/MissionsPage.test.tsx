import { createRoot } from "react-dom/client";
import { act } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MissionSummary } from "../lib/types";
import { discardPlanDraft, restartMission, stopMission } from "../lib/api";

const useMissionListMock = vi.hoisted(() => vi.fn());
const useElapsedTimeMock = vi.hoisted(() => vi.fn());
const useToastMock = vi.hoisted(() => ({
  addToast: vi.fn(),
  removeToast: vi.fn(),
  toasts: [],
}));

vi.mock("../hooks/useMissionList", () => ({
  useMissionList: useMissionListMock,
}));

vi.mock("../hooks/useElapsedTime", () => ({
  useElapsedTime: useElapsedTimeMock,
}));

vi.mock("../hooks/useToast", () => ({
  useToast: () => useToastMock,
}));

vi.mock("../lib/api", () => ({
  archiveMission: vi.fn(),
  deleteMission: vi.fn(),
  unarchiveMission: vi.fn(),
  stopMission: vi.fn(),
  restartMission: vi.fn(),
  discardPlanDraft: vi.fn(),
}));

import MissionsPage from "./MissionsPage";

function renderPage(): HTMLDivElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <MemoryRouter>
        <MissionsPage />
      </MemoryRouter>,
    );
  });

  return container;
}

describe("MissionsPage", () => {
  beforeEach(() => {
    useMissionListMock.mockReset();
    useElapsedTimeMock.mockReset();
    vi.mocked(stopMission).mockReset();
    vi.mocked(restartMission).mockReset();
    vi.mocked(discardPlanDraft).mockReset();
    useToastMock.addToast.mockReset();
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("renders a loading skeleton while the initial fetch is in flight", () => {
    useMissionListMock.mockReturnValue({
      missions: [],
      loading: true,
      error: null,
      refresh: vi.fn(),
    });

    const container = renderPage();

    expect(container.textContent).toContain("AgentForce Missions");
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(3);
    expect(container.textContent).not.toContain("No missions yet");
  });

  it("renders an empty state when no missions are available", () => {
    useMissionListMock.mockReturnValue({
      missions: [],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });

    const container = renderPage();

    expect(container.textContent).toContain(
      "No missions yet. Launch one with Plan Mode →",
    );
    expect(container.querySelector('a[href="/plan"]')).toBeTruthy();
  });

  it("renders mission cards with all requested fields", () => {
    const missions: MissionSummary[] = [
      {
        mission_id: "mission-123",
        name: "Backfill pipeline",
        status: "active",
        done_tasks: 3,
        total_tasks: 5,
        pct: 60,
        duration: "1h 20m",
        worker_agent: "worker-a",
        worker_model: "gpt-5.4",
        started_at: "2026-04-08T00:00:00Z",
        cost_usd: 1.23,
        tokens_in: 120,
        tokens_out: 80,
        workspace: "/Users/eduardo/Projects/agentforce",
        models: ["gpt-5.4", "gpt-4.1"],
      },
    ];
    useMissionListMock.mockReturnValue({
      missions,
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    useElapsedTimeMock.mockReturnValue("1h 20m");

    const container = renderPage();

    const link = container.querySelector('a[href="/mission/mission-123"]');

    expect(link?.textContent).toContain("Backfill pipeline");
    expect(container.textContent).toContain("active");
    expect(container.textContent).toContain("3/5 tasks");
    expect(container.textContent).toContain("0 retries");
    expect(container.textContent).toContain("$1.2300");
    expect(container.textContent).toContain("1h 20m");
    expect(container.textContent).toContain("Total: 1");
    expect(container.textContent).toContain("Running: 1");
    expect(container.textContent).toContain("Done: 0");
    expect(container.textContent).toContain("Cost: $1.23");
    expect(container.textContent).toContain("Tokens: 200");
    expect(container.textContent).toContain(
      "/Users/eduardo/Projects/agentforce",
    );
    expect(container.textContent).toContain("gpt-5.4");
    expect(container.textContent).toContain("gpt-4.1");
    expect(container.querySelector('a[href="/plan"]')).toBeTruthy();
  });

  it("confirms and calls the stop and restart APIs from the mission card", async () => {
    const missions: MissionSummary[] = [
      {
        mission_id: "mission-123",
        name: "Backfill pipeline",
        status: "active",
        done_tasks: 3,
        total_tasks: 5,
        pct: 60,
        duration: "1h 20m",
        worker_agent: "worker-a",
        worker_model: "gpt-5.4",
        started_at: "2026-04-08T00:00:00Z",
        cost_usd: 1.23,
      },
    ];
    const refresh = vi.fn();
    useMissionListMock.mockReturnValue({
      missions,
      loading: false,
      error: null,
      refresh,
    });
    useElapsedTimeMock.mockReturnValue("1h 20m");
    vi.mocked(stopMission).mockResolvedValue(undefined);
    vi.mocked(restartMission).mockResolvedValue(undefined);

    const container = renderPage();
    const [stopButton, restartButton] = Array.from(
      container.querySelectorAll("button"),
    ) as HTMLButtonElement[];

    await act(async () => {
      stopButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.textContent).toContain(
      'Stop mission "Backfill pipeline"?',
    );
    const confirmStop = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Stop Mission",
    ) as HTMLButtonElement;
    expect(confirmStop).toBeTruthy();

    await act(async () => {
      confirmStop.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(vi.mocked(stopMission)).toHaveBeenCalledWith("mission-123");
    expect(useToastMock.addToast).toHaveBeenCalledWith(
      "Mission stopped",
      "success",
    );
    expect(refresh).toHaveBeenCalled();

    await act(async () => {
      restartButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.textContent).toContain(
      'Restart mission "Backfill pipeline"?',
    );
    const confirmRestart = Array.from(
      container.querySelectorAll("button"),
    ).find(
      (button) => button.textContent === "Restart Mission",
    ) as HTMLButtonElement;
    expect(confirmRestart).toBeTruthy();

    await act(async () => {
      confirmRestart.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(vi.mocked(restartMission)).toHaveBeenCalledWith("mission-123");
    expect(useToastMock.addToast).toHaveBeenCalledWith(
      "Mission restarted",
      "success",
    );
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("discards drafts from Mission Control through the draft API", async () => {
    const missions: MissionSummary[] = [
      {
        mission_id: "draft-123",
        name: "Draft mission",
        status: "draft",
        done_tasks: 0,
        total_tasks: 0,
        pct: 0,
        duration: "0m",
        worker_agent: "",
        worker_model: "",
        started_at: "2026-04-08T00:00:00Z",
        cost_usd: 0,
      },
    ];
    const refresh = vi.fn();
    useMissionListMock.mockReturnValue({
      missions,
      loading: false,
      error: null,
      refresh,
    });
    useElapsedTimeMock.mockReturnValue("0m");
    vi.mocked(discardPlanDraft).mockResolvedValue(undefined);

    const container = renderPage();
    const discardButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Discard"),
    ) as HTMLButtonElement;

    await act(async () => {
      discardButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.textContent).toContain('Discard draft "Draft mission"?');

    const confirmDiscard = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Discard Draft",
    ) as HTMLButtonElement;
    expect(confirmDiscard).toBeTruthy();

    await act(async () => {
      confirmDiscard.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(vi.mocked(discardPlanDraft)).toHaveBeenCalledWith("draft-123");
    expect(useToastMock.addToast).toHaveBeenCalledWith("Draft discarded", "info");
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("keeps the page copy limited to the requested mission list surface", () => {
    useMissionListMock.mockReturnValue({
      missions: [],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });

    const container = renderPage();

    expect(container.textContent).not.toContain("Live mission dashboard");
    expect(container.textContent).not.toContain("No refresh required");
  });
});
