import type { StreamEventRecord } from "./ws";

export interface SupportActivitySource {
  status?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  summary?: string | null;
  message?: string | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  cost_usd?: number | null;
  metadata?: Record<string, unknown> | null;
}

export interface SupportActivityFinding {
  id: string;
  severity: string;
  title: string;
  detail?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function orbitEvent(
  seq: number,
  sourceId: string,
  kind: StreamEventRecord["kind"],
  timestamp: string,
  payload: Record<string, unknown>,
  extra: Partial<StreamEventRecord> = {},
): StreamEventRecord {
  return {
    seq,
    timestamp,
    mission_id: "plan",
    task_id: sourceId,
    provider: typeof extra.provider === "string" ? extra.provider : "orbit-agent",
    role: typeof extra.role === "string" ? extra.role : "system",
    kind,
    payload,
    raw_line: typeof extra.raw_line === "string" ? extra.raw_line : undefined,
  };
}

function isStreamEventRecordLike(value: unknown): value is StreamEventRecord {
  return isRecord(value)
    && typeof value.seq === "number"
    && typeof value.timestamp === "string"
    && typeof value.mission_id === "string"
    && typeof value.task_id === "string"
    && typeof value.provider === "string"
    && typeof value.role === "string"
    && typeof value.kind === "string"
    && isRecord(value.payload);
}

export function supportActivityMetadata(source: SupportActivitySource | null | undefined): Record<string, unknown> {
  return isRecord(source?.metadata) ? source.metadata : {};
}

export function formatExecutionProfile(value: unknown): string | null {
  if (!isRecord(value)) {
    return null;
  }
  const agent = typeof value.agent === "string" && value.agent.trim() !== ""
    ? value.agent.trim()
    : null;
  const model = typeof value.model === "string" && value.model.trim() !== ""
    ? value.model.trim()
    : null;
  const thinking = typeof value.thinking === "string" && value.thinking.trim() !== ""
    ? value.thinking.trim()
    : null;
  const parts = [agent, model, thinking].filter(Boolean);
  return parts.length > 0 ? parts.join(" / ") : null;
}

export function formatSupportActivityDateTime(value: string | null | undefined): string {
  if (!value) {
    return "Pending";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function formatSupportActivityCurrency(value: number | undefined | null): string {
  return `$${(value ?? 0).toFixed(4)}`;
}

export function supportActivityEvents(
  sourceId: string,
  label: string,
  source: SupportActivitySource | null,
): StreamEventRecord[] {
  const metadata = supportActivityMetadata(source);
  const persisted = metadata.stream_events;
  if (Array.isArray(persisted)) {
    const valid = persisted.filter(isStreamEventRecordLike);
    if (valid.length > 0) {
      return valid;
    }
  }

  if (!source) {
    return [
      orbitEvent(1, sourceId, "warning", new Date(0).toISOString(), {
        message: "No persisted agent payload yet.",
      }),
    ];
  }

  let seq = 1;
  const events: StreamEventRecord[] = [];
  const startedAt = source.started_at || source.completed_at || new Date(0).toISOString();
  const completedAt = source.completed_at || source.started_at || startedAt;
  const summary = typeof source.summary === "string" ? source.summary.trim() : "";
  const message = typeof source.message === "string" ? source.message.trim() : "";

  events.push(
    orbitEvent(seq++, sourceId, "status", startedAt, {
      state: source.status === "running" || source.status === "started" ? "running" : "started",
      message: message || `Started ${label}`,
    }),
  );

  if (summary) {
    events.push(
      orbitEvent(
        seq++,
        sourceId,
        "text_delta",
        completedAt,
        { text: summary },
        { role: "assistant", provider: "planner" },
      ),
    );
  } else if (message && message !== summary) {
    events.push(
      orbitEvent(
        seq++,
        sourceId,
        "text_delta",
        completedAt,
        { text: message },
        { role: "assistant", provider: "planner" },
      ),
    );
  }

  if (
    typeof source.tokens_in === "number"
    || typeof source.tokens_out === "number"
    || typeof source.cost_usd === "number"
  ) {
    events.push(
      orbitEvent(seq++, sourceId, "usage", completedAt, {
        tokens_in: source.tokens_in ?? 0,
        tokens_out: source.tokens_out ?? 0,
        cost_usd: source.cost_usd ?? 0,
      }),
    );
  }

  const issueLikeValues = [
    ...(Array.isArray(metadata.issues) ? metadata.issues : []),
    ...(Array.isArray(metadata.warnings) ? metadata.warnings : []),
    ...(Array.isArray(metadata.blocking_issues) ? metadata.blocking_issues : []),
  ];
  for (const issue of issueLikeValues) {
    if (typeof issue === "string" && issue.trim()) {
      events.push(
        orbitEvent(seq++, sourceId, "warning", completedAt, {
          message: issue.trim(),
        }),
      );
      continue;
    }
    if (isRecord(issue)) {
      const title = typeof issue.title === "string" ? issue.title.trim() : "";
      const reason = typeof issue.reason === "string" ? issue.reason.trim() : "";
      const fix = typeof issue.fix === "string" ? issue.fix.trim() : "";
      const parts = [title, reason, fix].filter(Boolean);
      if (parts.length > 0) {
        events.push(
          orbitEvent(seq++, sourceId, "warning", completedAt, {
            message: parts.join("\n"),
          }),
        );
      }
    }
  }

  if (source.status !== "running" && source.status !== "started") {
    events.push(
      orbitEvent(seq++, sourceId, "status", completedAt, {
        state: source.status ?? "completed",
        message: message || summary || `${label} finished.`,
      }),
    );
  }

  return events;
}

export function supportActivityFindings(
  source: SupportActivitySource | null,
): SupportActivityFinding[] {
  const metadata = supportActivityMetadata(source);
  const findings: SupportActivityFinding[] = [];
  let index = 0;

  const addFinding = (severity: string, title: string, detail?: string): void => {
    const normalizedTitle = title.trim();
    const normalizedDetail = detail?.trim();
    if (!normalizedTitle && !normalizedDetail) {
      return;
    }
    findings.push({
      id: `finding-${index++}`,
      severity,
      title: normalizedTitle || normalizedDetail || "Untitled note",
      detail: normalizedTitle && normalizedDetail ? normalizedDetail : undefined,
    });
  };

  const structuredIssues = Array.isArray(metadata.structured_issues) ? metadata.structured_issues : [];
  for (const issue of structuredIssues) {
    if (!isRecord(issue)) {
      continue;
    }
    const severity = issue.blocking ? "high" : "medium";
    const title = typeof issue.reason === "string" ? issue.reason : String(issue.kind ?? "Validation issue");
    const detailParts = [
      typeof issue.task_id === "string" && issue.task_id ? `Task ${issue.task_id}` : "",
      typeof issue.original_text === "string" ? issue.original_text : "",
    ].filter(Boolean);
    addFinding(severity, title, detailParts.join(" · "));
  }

  const issues = Array.isArray(metadata.issues) ? metadata.issues : [];
  for (const issue of issues) {
    if (typeof issue === "string") {
      addFinding("high", issue);
      continue;
    }
    if (!isRecord(issue)) {
      continue;
    }
    const severity = typeof issue.severity === "string" ? issue.severity : "high";
    const title = typeof issue.title === "string" ? issue.title : String(issue.reason ?? "Issue");
    const detail = typeof issue.fix === "string"
      ? issue.fix
      : typeof issue.reason === "string" && issue.reason !== title
        ? issue.reason
        : "";
    addFinding(severity, title, detail);
  }

  const warnings = Array.isArray(metadata.warnings) ? metadata.warnings : [];
  for (const warning of warnings) {
    if (typeof warning === "string") {
      addFinding("warning", warning);
    }
  }

  const suggestions = Array.isArray(metadata.suggestions) ? metadata.suggestions : [];
  for (const suggestion of suggestions) {
    if (typeof suggestion === "string") {
      addFinding("suggestion", suggestion);
    }
  }

  return findings;
}
