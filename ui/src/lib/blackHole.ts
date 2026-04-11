import type { BlackHoleCampaignState, BlackHoleConfig, MissionDraft } from "./types";

export function firstTurnPrompt(draft: MissionDraft | null): string {
  if (!draft) {
    return "";
  }
  const firstUserTurn = draft.turns.find((turn) => turn.role === "user");
  return firstUserTurn?.content ?? "";
}

export function defaultBlackHoleConfig(draft: MissionDraft): BlackHoleConfig {
  return {
    mode: "black_hole",
    objective:
      draft.draft_spec.goal
      || firstTurnPrompt(draft)
      || "Iteratively improve the repository until the acceptance criteria is satisfied.",
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
  };
}

export function normalizeBlackHoleConfig(value: unknown, draft: MissionDraft): BlackHoleConfig {
  const defaults = defaultBlackHoleConfig(draft);
  if (!value || typeof value !== "object") {
    return defaults;
  }
  const candidate = value as Record<string, unknown>;
  const loopLimits = candidate.loop_limits && typeof candidate.loop_limits === "object"
    ? candidate.loop_limits as Record<string, unknown>
    : {};
  const gatePolicy = candidate.gate_policy && typeof candidate.gate_policy === "object"
    ? candidate.gate_policy as Record<string, unknown>
    : {};
  return {
    ...defaults,
    mode: "black_hole",
    objective: typeof candidate.objective === "string" && candidate.objective.trim() ? candidate.objective : defaults.objective,
    analyzer: typeof candidate.analyzer === "string" && candidate.analyzer.trim() ? candidate.analyzer : defaults.analyzer,
    scope: typeof candidate.scope === "string" && candidate.scope.trim() ? candidate.scope : defaults.scope,
    global_acceptance: Array.isArray(candidate.global_acceptance) ? candidate.global_acceptance.map(String) : defaults.global_acceptance,
    loop_limits: {
      max_loops: typeof loopLimits.max_loops === "number" ? loopLimits.max_loops : defaults.loop_limits.max_loops,
      max_no_progress: typeof loopLimits.max_no_progress === "number" ? loopLimits.max_no_progress : defaults.loop_limits.max_no_progress,
      function_line_limit: typeof loopLimits.function_line_limit === "number"
        ? loopLimits.function_line_limit
        : defaults.loop_limits.function_line_limit,
    },
    gate_policy: {
      require_test_delta: typeof gatePolicy.require_test_delta === "boolean"
        ? gatePolicy.require_test_delta
        : defaults.gate_policy?.require_test_delta,
      public_surface_policy: typeof gatePolicy.public_surface_policy === "string"
        ? gatePolicy.public_surface_policy
        : defaults.gate_policy?.public_surface_policy,
    },
    docs_manifest_path: typeof candidate.docs_manifest_path === "string" && candidate.docs_manifest_path.trim()
      ? candidate.docs_manifest_path
      : null,
    notes: typeof candidate.notes === "string" ? candidate.notes : defaults.notes,
  };
}

export function blackHoleMetricLabel(config: BlackHoleConfig | null): string {
  if (!config) {
    return "Campaign metric";
  }
  if (config.analyzer === "docs_section_coverage") {
    return "Missing manifest paths";
  }
  return `Functions > ${config.loop_limits.function_line_limit ?? 300} lines`;
}

export function blackHoleMetricValue(
  config: BlackHoleConfig | null,
  metric: Record<string, unknown> | undefined,
): string | number {
  if (!metric) {
    return "—";
  }
  if (config?.analyzer === "docs_section_coverage") {
    const missing = metric.missing_paths;
    return typeof missing === "number" ? missing : "—";
  }
  const violations = metric.violations;
  return typeof violations === "number" ? violations : "—";
}

export function blackHoleHeroDescription(
  config: BlackHoleConfig | null,
  campaign: BlackHoleCampaignState["campaign"],
): string {
  if (campaign?.stop_reason) {
    return campaign.stop_reason;
  }
  if (!config) {
    return "The accretion disk stays alive between loops so the current campaign state is always visible.";
  }
  if (config.analyzer === "docs_section_coverage") {
    return "The lensed arcs track documentation coverage gaps while the central ring reflects the currently targeted section.";
  }
  return "The crescent brightens as the campaign burns down oversize Python functions one slice at a time.";
}
