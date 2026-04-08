export interface AgentChipProps {
  agent: string;
  model?: string | null;
  className?: string;
}

export default function AgentChip({ agent, model, className = '' }: AgentChipProps) {
  const label = model ? `${agent} · ${model}` : agent;

  return (
    <span
      className={[
        'inline-flex items-center gap-1 rounded-full border border-border bg-surface px-2 py-0.5 text-[11px] text-dim',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <span aria-hidden="true">🤖</span>
      <span>{label}</span>
    </span>
  );
}
