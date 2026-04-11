import type { MissionDraft, PreflightAnswer } from "../../lib/types";

export default function PreflightQuestionsPanel({
  draft,
  answers,
  submitting,
  submitLabel = "Start Planning",
  onAnswerChange,
  onSubmit,
  onSkip,
}: {
  draft: MissionDraft;
  answers: Record<string, PreflightAnswer>;
  submitting: boolean;
  submitLabel?: string;
  onAnswerChange: (questionId: string, answer: PreflightAnswer) => void;
  onSubmit: () => void;
  onSkip: () => void;
}) {
  const questions = draft.preflight_questions ?? [];

  return (
    <section className="rounded-[1.15rem] border border-amber/30 bg-[radial-gradient(circle_at_top,rgba(251,191,36,0.12),transparent_62%),var(--color-card)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">Preflight Questions</h2>
          <p className="mt-1 text-xs text-dim">
            Clarify only what changes structure, dependencies, or acceptance criteria.
          </p>
        </div>
        <div className="rounded-full border border-amber/30 bg-amber/10 px-3 py-1 font-mono text-[11px] text-amber">
          {questions.length} pending
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {questions.map((question, index) => {
          const answer = answers[question.id] ?? {};
          return (
            <article
              key={question.id}
              className="rounded-xl border border-border bg-surface p-3"
            >
              <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                Question {index + 1}
              </div>
              <div className="mt-2 text-sm font-semibold text-text">
                {question.prompt}
              </div>
              {question.reason ? (
                <p className="mt-1 text-xs text-dim">{question.reason}</p>
              ) : null}
              <div className="mt-3 grid gap-2">
                {question.options.map((option) => (
                  <label
                    key={`${question.id}-${option}`}
                    className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-text"
                  >
                    <input
                      type="radio"
                      name={`preflight-${question.id}`}
                      checked={answer.selected_option === option}
                      onChange={() =>
                        onAnswerChange(question.id, {
                          ...answer,
                          selected_option: option,
                        })}
                    />
                    <span>{option}</span>
                  </label>
                ))}
                {question.allow_custom !== false ? (
                  <input
                    className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-text outline-none focus:border-cyan"
                    placeholder="Custom reply"
                    value={answer.custom_answer ?? ""}
                    onChange={(event) =>
                      onAnswerChange(question.id, {
                        ...answer,
                        custom_answer: event.currentTarget.value,
                      })}
                  />
                ) : null}
              </div>
            </article>
          );
        })}
      </div>

      <div className="mt-4 flex flex-wrap justify-end gap-2">
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
          disabled={submitting}
          onClick={onSubmit}
        >
          {submitLabel}
        </button>
      </div>
    </section>
  );
}
