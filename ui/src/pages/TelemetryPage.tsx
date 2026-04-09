import { useEffect, useRef, useState } from 'react';
import { getTelemetry } from '../lib/api';
import { useInterval } from '../hooks/useInterval';
import type { TelemetryData, TelemetryCostPoint } from '../lib/types';

const NUMBER_FORMATTER = new Intl.NumberFormat('en-US');
const REFETCH_MS = 30_000;

function formatCurrency(value: number): string {
  return `$${value.toFixed(4)}`;
}

function formatTokens(tokensIn: number, tokensOut: number): string {
  return `${NUMBER_FORMATTER.format(tokensIn)} in / ${NUMBER_FORMATTER.format(tokensOut)} out`;
}

function formatTimestamp(isoString: string | null): string {
  if (!isoString) {
    return '—';
  }

  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }

  return date.toLocaleString();
}

function formatRetryLabel(retryLabel: string): string {
  if (retryLabel === '1') {
    return '1 retry';
  }

  if (retryLabel === '2+') {
    return '2+ retries';
  }

  return '0 retries';
}

function downloadTelemetryJson(data: TelemetryData): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement('a');

  anchor.href = url;
  anchor.download = 'agentforce-telemetry.json';
  anchor.rel = 'noreferrer';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

function TelemetryStats({ telemetry }: { telemetry: TelemetryData }) {
  const stats = [
    { label: 'Total Missions', value: telemetry.total_missions },
    { label: 'Total Tasks', value: telemetry.total_tasks },
    { label: 'Total Cost', value: formatCurrency(telemetry.total_cost_usd) },
    { label: 'Total Tokens', value: formatTokens(telemetry.total_tokens_in, telemetry.total_tokens_out) },
  ];

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {stats.map((stat) => (
        <article key={stat.label} className="rounded-lg border border-border bg-card px-4 py-3">
          <div className="text-label text-dim">{stat.label}</div>
          <div className="mt-1 text-hero text-text">{stat.value}</div>
        </article>
      ))}
    </div>
  );
}

function RetryDistributionChart({ retryDistribution }: { retryDistribution: TelemetryData['retry_distribution'] }) {
  const bars = [
    { label: '0 retries', key: '0' },
    { label: '1 retry', key: '1' },
    { label: '2+ retries', key: '2+' },
  ].map((item) => ({
    ...item,
    count: Number(retryDistribution[item.key] ?? 0),
  }));
  const maxCount = Math.max(1, ...bars.map((bar) => bar.count));
  const chartWidth = 300;
  const chartHeight = 140;
  const baselineY = 108;

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-3 text-[12px] font-semibold uppercase tracking-[0.09em] text-muted">
        Retry Distribution
      </h3>
      <svg
        aria-label="Retry Distribution"
        className="block h-[140px] w-full"
        data-testid="retry-distribution"
        viewBox={`0 0 ${chartWidth} ${chartHeight}`}
        role="img"
      >
        {bars.map((bar, index) => {
          const height = Math.round((bar.count / maxCount) * 100);
          const barWidth = 56;
          const x = 34 + index * 96;
          const y = baselineY - height;

          return (
            <g key={bar.key}>
              <text
                className="fill-dim text-[11px] font-semibold"
                textAnchor="middle"
                x={x + barWidth / 2}
                y={Math.max(16, y - 6)}
              >
                {bar.count}
              </text>
              <rect
                data-bar
                fill="#4d94ff"
                height={height}
                rx="6"
                x={x}
                y={y}
                width={barWidth}
              />
              <text className="fill-text text-[11px]" textAnchor="middle" x={x + barWidth / 2} y={131}>
                {bar.label}
              </text>
            </g>
          );
        })}
      </svg>
    </section>
  );
}

function buildCostLinePoints(costOverTime: TelemetryCostPoint[]): { points: string; dots: Array<{ x: number; y: number; key: string }> } {
  if (costOverTime.length === 0) {
    return { points: '', dots: [] };
  }

  const chartWidth = 300;
  const chartHeight = 120;
  const paddingX = 20;
  const paddingY = 20;
  const innerWidth = chartWidth - paddingX * 2;
  const innerHeight = chartHeight - paddingY * 2;
  const costs = costOverTime.map((point) => point.cumulative_cost);
  const minCost = Math.min(...costs);
  const maxCost = Math.max(...costs);
  const span = Math.max(1, maxCost - minCost);

  if (costOverTime.length === 1) {
    const y = paddingY + innerHeight / 2;
    return {
      points: `${paddingX},${y} ${chartWidth - paddingX},${y}`,
      dots: [{ x: chartWidth / 2, y, key: costOverTime[0].mission_name }],
    };
  }

  const dots = costOverTime.map((point, index) => {
    const x = paddingX + (index / (costOverTime.length - 1)) * innerWidth;
    const normalized = (point.cumulative_cost - minCost) / span;
    const y = paddingY + (1 - normalized) * innerHeight;
    return { x, y, key: point.mission_name };
  });

  return {
    points: dots.map((dot) => `${dot.x},${dot.y}`).join(' '),
    dots,
  };
}

function CumulativeCostChart({ costOverTime }: { costOverTime: TelemetryData['cost_over_time'] }) {
  const { points, dots } = buildCostLinePoints(costOverTime);

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-3 text-[12px] font-semibold uppercase tracking-[0.09em] text-muted">
        Cumulative Cost
      </h3>
      <svg
        aria-label="Cumulative Cost"
        className="block h-[120px] w-full"
        data-testid="cumulative-cost"
        viewBox="0 0 300 120"
        role="img"
      >
        {costOverTime.length === 0 ? (
          <text className="fill-dim text-[12px]" dominantBaseline="middle" textAnchor="middle" x="50%" y="50%">
            No data yet
          </text>
        ) : (
          <>
            <polyline fill="none" points={points} stroke="#22d3ee" strokeWidth="2" />
            {dots.map((dot) => (
              <circle key={dot.key} cx={dot.x} cy={dot.y} fill="#22d3ee" r="3" />
            ))}
          </>
        )}
      </svg>
    </section>
  );
}

function LoadingState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="animate-pulse space-y-3">
        <div className="h-4 w-44 rounded bg-surface" />
        <div className="h-3 w-60 rounded bg-surface" />
        <div className="h-3 w-32 rounded bg-surface" />
      </div>
      <p className="mt-3 text-dim">{message}</p>
    </div>
  );
}

function TelemetryTableSection({
  title,
  columns,
  rows,
  emptyMessage,
}: {
  title: string;
  columns: string[];
  rows: Array<Array<string | number>>;
  emptyMessage: string;
}) {
  return (
    <section className="sec">
      <h2 className="section-title">{title}</h2>
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-surface text-left text-[10px] font-semibold uppercase tracking-[0.09em] text-muted">
              {columns.map((column) => (
                <th key={column} className="border-b border-border px-4 py-2">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td className="px-4 py-3 text-dim" colSpan={columns.length}>
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              rows.map((row, index) => (
                <tr key={`${title}-${index}`} className="border-b border-border last:border-b-0">
                  {row.map((cell, cellIndex) => (
                    <td key={`${title}-${index}-${cellIndex}`} className="px-4 py-2 align-middle text-[12px] text-text">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function TelemetryPage() {
  const [telemetry, setTelemetry] = useState<TelemetryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    void getTelemetry()
      .then((data) => {
        if (cancelled || !mountedRef.current) {
          return;
        }

        setTelemetry(data);
        setError(null);
        setLastUpdatedAt(new Date().toISOString());
      })
      .catch((err: unknown) => {
        if (cancelled || !mountedRef.current) {
          return;
        }

        setError(err instanceof Error ? err.message : 'Failed to load telemetry');
      })
      .finally(() => {
        if (!cancelled && mountedRef.current) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [refreshIndex]);

  useInterval(() => {
    setRefreshIndex((current) => current + 1);
  }, REFETCH_MS);

  const handleRefresh = (): void => {
    setRefreshIndex((current) => current + 1);
  };

  const handleExport = (): void => {
    if (!telemetry) {
      return;
    }

    downloadTelemetryJson(telemetry);
  };

  const missionRows = (telemetry?.missions_by_cost ?? []).slice(0, 5).map((mission) => [
    mission.name,
    formatCurrency(mission.cost_usd),
    NUMBER_FORMATTER.format(mission.tokens_in),
    NUMBER_FORMATTER.format(mission.tokens_out),
    mission.duration,
    mission.retries,
  ]);

  const taskRows = (telemetry?.tasks_by_cost ?? []).slice(0, 5).map((task) => [
    task.task,
    task.mission,
    task.model || '—',
    formatCurrency(task.cost_usd),
    task.retries,
  ]);

  return (
    <div>
      <div className="page-head flex-wrap justify-between">
        <div>
          <h1>Telemetry</h1>
          <p className="text-[12px] text-dim">
            Last updated: {formatTimestamp(lastUpdatedAt)}{loading ? ' · loading' : ''}
          </p>
          {error ? <p className="mt-1 text-[12px] text-red">{error}</p> : null}
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-full border border-border px-3 py-1.5 text-[11px] font-semibold text-text transition-colors hover:bg-card-hover hover:no-underline"
            onClick={handleRefresh}
          >
            Refresh
          </button>
          <button
            type="button"
            className="rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 hover:no-underline disabled:cursor-not-allowed disabled:opacity-40"
            disabled={!telemetry}
            onClick={handleExport}
          >
            Export JSON
          </button>
        </div>
      </div>

      {loading && !telemetry ? <LoadingState message="Loading telemetry..." /> : null}

      {telemetry ? (
        <>
          <section className="sec">
            <TelemetryStats telemetry={telemetry} />
          </section>

          <section className="sec grid gap-4 xl:grid-cols-2">
            <TelemetryTableSection
              columns={['Mission Name', 'Cost', 'Tokens In', 'Tokens Out', 'Duration', 'Retries']}
              emptyMessage="No missions yet."
              rows={missionRows}
              title="Top Missions by Cost"
            />
            <TelemetryTableSection
              columns={['Task', 'Mission', 'Model', 'Cost', 'Retries']}
              emptyMessage="No tasks yet."
              rows={taskRows}
              title="Top Tasks by Cost"
            />
          </section>

          <section className="sec">
            <RetryDistributionChart retryDistribution={telemetry.retry_distribution} />
          </section>

          <section className="sec">
            <CumulativeCostChart costOverTime={telemetry.cost_over_time} />
          </section>
        </>
      ) : null}
    </div>
  );
}

export { downloadTelemetryJson };
