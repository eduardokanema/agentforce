import type { ReactNode } from 'react';

export interface StatItem {
  label: string;
  value: ReactNode;
}

export interface StatsBarProps {
  stats: StatItem[];
  className?: string;
}

export default function StatsBar({ stats, className = '' }: StatsBarProps) {
  return (
    <div className={['flex flex-wrap gap-2', className].filter(Boolean).join(' ')}>
      {stats.map((stat) => (
        <div key={stat.label} className="min-w-[86px] rounded-lg border border-border bg-card px-4 py-3">
          <div className="mb-1 text-[10px] uppercase tracking-[0.07em] text-muted">{stat.label}</div>
          <div className="text-xl font-bold leading-none text-text">{stat.value}</div>
        </div>
      ))}
    </div>
  );
}
