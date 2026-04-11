import type { BlackHoleCampaign, BlackHoleConfig } from "../../lib/types";

interface BlackHoleConfigPanelProps {
  config: BlackHoleConfig;
  campaign?: BlackHoleCampaign | null;
  busy?: boolean;
  onChange: (next: BlackHoleConfig) => void;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
}

function setLoopLimit(config: BlackHoleConfig, key: keyof BlackHoleConfig["loop_limits"], value: number): BlackHoleConfig {
  return {
    ...config,
    loop_limits: {
      ...config.loop_limits,
      [key]: value,
    },
  };
}

export default function BlackHoleConfigPanel({
  config,
  campaign,
  busy = false,
  onChange,
  onStart,
  onPause,
  onResume,
  onStop,
}: BlackHoleConfigPanelProps) {
  const campaignStatus = campaign?.status ?? "idle";
  const running = campaignStatus === "child_mission_running" || campaignStatus === "evaluating_workspace" || campaignStatus === "candidate_locked";
  const resumable = campaignStatus === "paused" || campaignStatus === "waiting_human";
  const stopped = campaignStatus === "cancelled";

  return (
    <section className="rounded-[1.15rem] border border-border bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-amber">
            Black Hole Campaign
          </div>
          <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em] text-text">
            Recursive single-slice planning loop
          </h2>
          <p className="mt-2 max-w-[64ch] text-sm leading-7 text-dim">
            One candidate at a time, bounded by explicit loop limits, with a live accretion-disk hero tracking campaign state.
          </p>
        </div>
        <div className="rounded-full border border-border bg-surface px-3 py-1 font-mono text-[11px] text-dim">
          {campaign ? `Status ${campaignStatus}` : "Not started"}
        </div>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <label className="block text-sm font-medium text-text">
          Objective
          <textarea
            rows={4}
            className="mt-2 w-full rounded-lg border border-border bg-surface p-3 text-sm text-text outline-none focus:border-amber"
            value={config.objective}
            onChange={(event) => onChange({ ...config, objective: event.currentTarget.value })}
          />
        </label>

        <div className="grid gap-4">
          <label className="block text-sm font-medium text-text">
            Analyzer
            <select
              className="mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-amber"
              value={config.analyzer}
              onChange={(event) => onChange({ ...config, analyzer: event.currentTarget.value })}
            >
              <option value="python_fn_length">Python function length</option>
              <option value="docs_section_coverage">Docs section coverage</option>
            </select>
          </label>

          <label className="block text-sm font-medium text-text">
            Manifest path
            <input
              className="mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-amber"
              value={config.docs_manifest_path ?? ""}
              placeholder="docs/manifest.yaml"
              onChange={(event) => onChange({ ...config, docs_manifest_path: event.currentTarget.value || null })}
            />
          </label>
        </div>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <label className="block text-sm font-medium text-text">
          Max loops
          <input
            type="number"
            min={1}
            className="mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-amber"
            value={config.loop_limits.max_loops}
            onChange={(event) => onChange(setLoopLimit(config, "max_loops", Number(event.currentTarget.value) || 1))}
          />
        </label>
        <label className="block text-sm font-medium text-text">
          No-progress limit
          <input
            type="number"
            min={1}
            className="mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-amber"
            value={config.loop_limits.max_no_progress}
            onChange={(event) => onChange(setLoopLimit(config, "max_no_progress", Number(event.currentTarget.value) || 1))}
          />
        </label>
        <label className="block text-sm font-medium text-text">
          Function line limit
          <input
            type="number"
            min={50}
            className="mt-2 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-amber"
            value={config.loop_limits.function_line_limit ?? 300}
            onChange={(event) => onChange(setLoopLimit(config, "function_line_limit", Number(event.currentTarget.value) || 300))}
          />
        </label>
      </div>

      <label className="mt-5 block text-sm font-medium text-text">
        Notes
        <textarea
          rows={3}
          className="mt-2 w-full rounded-lg border border-border bg-surface p-3 text-sm text-text outline-none focus:border-amber"
          value={config.notes ?? ""}
          onChange={(event) => onChange({ ...config, notes: event.currentTarget.value })}
        />
      </label>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2 text-[11px] text-dim">
          <span className="rounded-full border border-border bg-surface px-3 py-1">
            Single-task child missions
          </span>
          <span className="rounded-full border border-border bg-surface px-3 py-1">
            Public surface stays constrained
          </span>
          <span className="rounded-full border border-border bg-surface px-3 py-1">
            Tests required when feasible
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {!campaign || stopped ? (
            <button
              type="button"
              className="rounded-full border border-amber/35 bg-amber/10 px-4 py-2 text-sm font-semibold text-amber transition-colors hover:bg-amber/15 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={busy}
              onClick={onStart}
            >
              {busy ? "Arming..." : "Arm Campaign"}
            </button>
          ) : null}
          {running ? (
            <button
              type="button"
              className="rounded-full border border-border bg-surface px-4 py-2 text-sm font-semibold text-dim transition-colors hover:bg-card-hover hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
              disabled={busy}
              onClick={onPause}
            >
              Pause
            </button>
          ) : null}
          {resumable ? (
            <button
              type="button"
              className="rounded-full border border-cyan/35 bg-cyan/10 px-4 py-2 text-sm font-semibold text-cyan transition-colors hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={busy}
              onClick={onResume}
            >
              Resume
            </button>
          ) : null}
          {campaign && !stopped ? (
            <button
              type="button"
              className="rounded-full border border-red/25 bg-red/10 px-4 py-2 text-sm font-semibold text-red transition-colors hover:bg-red/15 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={busy}
              onClick={onStop}
            >
              Stop
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
