interface ValidationBoardProps {
  conflictMessage: string | null;
  summaryIssues: string[];
  advisoryIssues: string[];
}

export default function ValidationBoard({ conflictMessage, summaryIssues, advisoryIssues }: ValidationBoardProps) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="section-title">Validation Board</h2>
      <div className="mt-4 space-y-2">
        {conflictMessage ? (
          <div className="rounded-lg border border-amber/30 bg-amber-bg px-3 py-3 text-sm text-amber">
            {conflictMessage}
          </div>
        ) : null}
        {summaryIssues.length === 0 ? (
          <div className="rounded-lg border border-green/20 bg-green-bg px-3 py-3 text-sm text-green">
            Draft passes the visible cockpit checks.
          </div>
        ) : null}
        {summaryIssues.map((issue) => (
          <div key={issue} className="rounded-lg border border-red/20 bg-red-bg px-3 py-3 text-sm text-red">
            {issue}
          </div>
        ))}
        {advisoryIssues.length > 0 ? (
          <div className="rounded-lg border border-amber/20 bg-amber-bg px-3 py-3 text-sm text-amber">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em]">
              Advisory Flight Checks
            </div>
            <ul className="space-y-1">
              {advisoryIssues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}
