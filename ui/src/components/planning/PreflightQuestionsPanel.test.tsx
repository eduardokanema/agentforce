import { act, useState, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MissionDraft, PreflightAnswer } from "../../lib/types";
import PreflightQuestionsPanel from "./PreflightQuestionsPanel";

function makeDraft(overrides: Partial<MissionDraft> = {}): MissionDraft {
  return {
    id: "draft-123",
    revision: 3,
    status: "draft",
    draft_spec: {
      name: "Calculator Mission",
      goal: "Build a calculator cockpit",
      definition_of_done: ["Planner summary is current"],
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
    turns: [],
    validation: {},
    activity_log: [],
    approved_models: [],
    workspace_paths: [],
    companion_profile: {},
    draft_notes: [],
    ...overrides,
  };
}

function renderPanel(element: ReactElement): { container: HTMLDivElement; root: Root } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(element);
  });

  return { container, root };
}

function Harness({
  draft,
  onSubmit,
  onSkip,
}: {
  draft: MissionDraft;
  onSubmit: () => void;
  onSkip: () => void;
}): ReactElement {
  const [answers, setAnswers] = useState<Record<string, PreflightAnswer>>({});

  return (
    <PreflightQuestionsPanel
      draft={draft}
      answers={answers}
      submitting={false}
      submitLabel="Start Planning"
      onAnswerChange={(questionId, answer) => {
        setAnswers((current) => ({
          ...current,
          [questionId]: answer,
        }));
      }}
      onSubmit={onSubmit}
      onSkip={onSkip}
    />
  );
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("PreflightQuestionsPanel", () => {
  it("walks one question at a time, shows review, and submits from the final step", () => {
    const onSubmit = vi.fn();
    const onSkip = vi.fn();
    const draft = makeDraft({
      preflight_questions: [
        {
          id: "question-1",
          prompt: "How should the mission be verified?",
          options: ["Use a specific command", "Use a concrete artifact"],
          reason: "The current answer is too vague.",
        },
        {
          id: "question-2",
          prompt: "What output should be recorded?",
          options: ["A file path", "A log message"],
        },
      ],
    });

    const { container, root } = renderPanel(
      <Harness draft={draft} onSubmit={onSubmit} onSkip={onSkip} />,
    );

    expect(container.textContent).toContain("Question 1 of 2");
    expect(container.textContent).toContain("How should the mission be verified?");
    expect(container.textContent).not.toContain("What output should be recorded?");

    const firstAnswer = Array.from(container.querySelectorAll("label")).find((label) =>
      label.textContent?.includes("Use a specific command"));
    expect(firstAnswer).toBeTruthy();

    act(() => {
      firstAnswer?.querySelector("input")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const nextButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Next"));
    expect(nextButton).toBeTruthy();

    act(() => {
      nextButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.textContent).toContain("Question 2 of 2");
    expect(container.textContent).toContain("What output should be recorded?");
    expect(container.textContent).not.toContain("How should the mission be verified?");

    const secondAnswer = Array.from(container.querySelectorAll("label")).find((label) =>
      label.textContent?.includes("A file path"));
    expect(secondAnswer).toBeTruthy();

    act(() => {
      secondAnswer?.querySelector("input")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const reviewButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.trim() === "Next");
    expect(reviewButton).toBeTruthy();

    act(() => {
      reviewButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.textContent).toContain("Review");
    expect(container.textContent).toContain("Use a specific command");
    expect(container.textContent).toContain("A file path");
    expect(container.textContent).not.toContain("Edit");

    const submitButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Start Planning"));
    expect(submitButton).toBeTruthy();

    act(() => {
      submitButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSkip).not.toHaveBeenCalled();

    act(() => {
      root.unmount();
    });
  });

  it("keeps skip available without coupling it to repair semantics", () => {
    const onSubmit = vi.fn();
    const onSkip = vi.fn();
    const draft = makeDraft({
      preflight_questions: [
        {
          id: "repair-1",
          prompt: "How should the repair be made measurable?",
          options: ["Add a verification command", "Add an artifact path"],
        },
      ],
    });

    const { container, root } = renderPanel(
      <Harness draft={draft} onSubmit={onSubmit} onSkip={onSkip} />,
    );

    const skipButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Skip For Now"));
    expect(skipButton).toBeTruthy();

    act(() => {
      skipButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();

    act(() => {
      root.unmount();
    });
  });

  it("resets to the first question when the question set changes", () => {
    const onSubmit = vi.fn();
    const onSkip = vi.fn();
    const initialDraft = makeDraft({
      preflight_questions: [
        {
          id: "preflight-1",
          prompt: "Initial question?",
          options: ["First answer", "Second answer"],
        },
      ],
    });
    const nextDraft = makeDraft({
      preflight_questions: [
        {
          id: "repair-1",
          prompt: "Replacement repair question?",
          options: ["Repair answer", "Another repair answer"],
        },
      ],
    });

    const { container, root } = renderPanel(
      <Harness draft={initialDraft} onSubmit={onSubmit} onSkip={onSkip} />,
    );

    const firstAnswer = Array.from(container.querySelectorAll("label")).find((label) =>
      label.textContent?.includes("First answer"));
    expect(firstAnswer).toBeTruthy();

    act(() => {
      firstAnswer?.querySelector("input")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const reviewButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.trim() === "Next");
    expect(reviewButton).toBeTruthy();

    act(() => {
      reviewButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.textContent).toContain("Review");

    act(() => {
      root.render(<Harness draft={nextDraft} onSubmit={onSubmit} onSkip={onSkip} />);
    });

    expect(container.textContent).toContain("Question 1 of 1");
    expect(container.textContent).toContain("Replacement repair question?");
    expect(container.textContent).not.toContain("Initial question?");

    act(() => {
      root.unmount();
    });
  });
});
