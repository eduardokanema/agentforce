import { useEffect, useRef, useState } from "react";
import type { MissionDraft, PreflightAnswer, PreflightQuestion } from "../../lib/types";

interface PreflightQuestionsPanelProps {
  draft: MissionDraft;
  answers: Record<string, PreflightAnswer>;
  submitting: boolean;
  title?: string;
  description?: string;
  submitLabel?: string;
  onAnswerChange: (questionId: string, answer: PreflightAnswer) => void;
  onSubmit: () => void;
  onSkip: () => void;
}

function answerSummary(answer: PreflightAnswer | undefined): string {
  if (!answer) {
    return "No answer recorded yet.";
  }

  return answer.custom_answer?.trim()
    || answer.selected_option
    || "No answer recorded yet.";
}

function QuestionPreview({ question }: { question: PreflightQuestion }) {
  return question.preview ? (
    <div className="mt-3 grid gap-2 rounded-lg border border-amber/20 bg-amber/5 p-3 text-xs text-dim">
      {question.preview.why_required ? (
        <div>{question.preview.why_required}</div>
      ) : null}
      {question.preview.before_text ? (
        <div>
          <div className="font-semibold uppercase tracking-[0.08em] text-muted">Current</div>
          <div className="mt-1 whitespace-pre-wrap rounded-md border border-border bg-card px-2 py-2 text-text">
            {question.preview.before_text}
          </div>
        </div>
      ) : null}
      {question.preview.proposed_text ? (
        <div>
          <div className="font-semibold uppercase tracking-[0.08em] text-muted">Proposed</div>
          <div className="mt-1 whitespace-pre-wrap rounded-md border border-cyan/20 bg-cyan/5 px-2 py-2 text-text">
            {question.preview.proposed_text}
          </div>
        </div>
      ) : null}
    </div>
  ) : null;
}

export default function PreflightQuestionsPanel({
  draft,
  answers,
  submitting,
  title = "Preflight Questions",
  description = "Clarify only what changes structure, dependencies, or acceptance criteria.",
  submitLabel = "Start Planning",
  onAnswerChange,
  onSubmit,
  onSkip,
}: PreflightQuestionsPanelProps) {
  const questions = draft.preflight_questions ?? [];
  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const questionCount = questions.length;
  const reviewStepIndex = questionCount;
  const questionSignature = questions.map((question) => question.id).join("|");
  const lastQuestionSignature = useRef(questionSignature);
  const isReviewStep = questionCount > 0 && activeStepIndex >= reviewStepIndex;
  const currentQuestionIndex = questionCount === 0
    ? 0
    : Math.min(activeStepIndex, reviewStepIndex);
  const currentQuestion = !isReviewStep ? questions[currentQuestionIndex] : null;

  useEffect(() => {
    if (lastQuestionSignature.current !== questionSignature) {
      lastQuestionSignature.current = questionSignature;
      setActiveStepIndex(0);
      return;
    }

    setActiveStepIndex((current) => {
      if (questionCount === 0) {
        return 0;
      }
      return Math.min(current, reviewStepIndex);
    });
  }, [questionCount, questionSignature, reviewStepIndex]);

  const goPrevious = (): void => {
    setActiveStepIndex((current) => Math.max(current - 1, 0));
  };

  const goNext = (): void => {
    setActiveStepIndex((current) => Math.min(current + 1, reviewStepIndex));
  };

  return (
    <section className="rounded-[1.15rem] border border-amber/30 bg-[radial-gradient(circle_at_top,rgba(251,191,36,0.12),transparent_62%),var(--color-card)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">{title}</h2>
          <p className="mt-1 text-xs text-dim">{description}</p>
        </div>
        <div className="rounded-full border border-amber/30 bg-amber/10 px-3 py-1 font-mono text-[11px] text-amber">
          {questionCount === 0
            ? "No questions"
            : isReviewStep
              ? "Review"
              : `Question ${currentQuestionIndex + 1} / ${questionCount}`}
        </div>
      </div>

      {questionCount === 0 ? (
        <div className="mt-4 rounded-xl border border-border bg-surface p-4 text-sm text-dim">
          No clarification questions are pending right now.
        </div>
      ) : !isReviewStep && currentQuestion ? (
        <article className="mt-4 rounded-xl border border-border bg-surface p-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            Question {currentQuestionIndex + 1} of {questionCount}
          </div>
          <div className="mt-2 text-sm font-semibold text-text">
            {currentQuestion.prompt}
          </div>
          {currentQuestion.reason ? (
            <p className="mt-1 text-xs text-dim">{currentQuestion.reason}</p>
          ) : null}
          <QuestionPreview question={currentQuestion} />
          <div className="mt-3 grid gap-2">
            {currentQuestion.options.map((option) => (
              <label
                key={`${currentQuestion.id}-${option}`}
                className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-text"
              >
                <input
                  type="radio"
                  name={`preflight-${currentQuestion.id}`}
                  checked={answers[currentQuestion.id]?.selected_option === option}
                  onChange={() =>
                    onAnswerChange(currentQuestion.id, {
                      ...answers[currentQuestion.id],
                      selected_option: option,
                    })}
                />
                <span>{option}</span>
              </label>
            ))}
            {currentQuestion.allow_custom !== false ? (
              <input
                className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                placeholder="Custom reply"
                value={answers[currentQuestion.id]?.custom_answer ?? ""}
                onChange={(event) =>
                  onAnswerChange(currentQuestion.id, {
                    ...answers[currentQuestion.id],
                    custom_answer: event.currentTarget.value,
                  })}
              />
            ) : null}
          </div>
        </article>
      ) : (
        <div className="mt-4 space-y-3">
          <div className="rounded-xl border border-border bg-surface p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
              Review
            </div>
            <p className="mt-2 text-sm text-dim">
              Confirm the recorded answers before you submit the flow.
            </p>
          </div>
          <div className="space-y-3">
            {questions.map((question, index) => {
              const answer = answers[question.id];
              return (
                <article key={question.id} className="rounded-xl border border-border bg-surface p-3">
                  <div>
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                        Question {index + 1} of {questionCount}
                      </div>
                      <div className="mt-2 text-sm font-semibold text-text">
                        {question.prompt}
                      </div>
                    </div>
                  </div>
                  {question.reason ? (
                    <p className="mt-1 text-xs text-dim">{question.reason}</p>
                  ) : null}
                  <div className="mt-3 rounded-lg border border-border bg-card px-3 py-2 text-sm text-text">
                    {answerSummary(answer)}
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-full border border-border px-4 py-2 text-sm font-semibold text-dim transition-colors hover:bg-card-hover disabled:cursor-not-allowed disabled:opacity-50"
            disabled={submitting || questionCount === 0 || activeStepIndex === 0}
            onClick={goPrevious}
          >
            Previous
          </button>
          {!isReviewStep && questionCount > 0 ? (
            <button
              type="button"
            className="rounded-full border border-border px-4 py-2 text-sm font-semibold text-dim transition-colors hover:bg-card-hover disabled:cursor-not-allowed disabled:opacity-50"
            disabled={submitting || activeStepIndex >= reviewStepIndex}
            onClick={goNext}
          >
              Next
          </button>
        ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-full border border-border px-4 py-2 text-sm font-semibold text-dim transition-colors hover:bg-card-hover disabled:cursor-not-allowed disabled:opacity-50"
            disabled={submitting}
            onClick={onSkip}
          >
            Skip For Now
          </button>
          <button
            type="button"
            className="rounded-full border border-cyan/30 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={submitting || questionCount === 0 || !isReviewStep}
            onClick={onSubmit}
          >
            {submitLabel}
          </button>
        </div>
      </div>
    </section>
  );
}
