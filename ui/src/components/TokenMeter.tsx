export interface TokenMeterProps {
  tokensIn: number;
  tokensOut: number;
  costUsd: number;
  label?: string;
}

function Chip({ children, className = '' }: { children: string; className?: string }) {
  return (
    <span
      className={['bg-surface border border-border rounded-full px-3 py-0.5 font-mono text-[11px]', className]
        .filter(Boolean)
        .join(' ')}
    >
      {children}
    </span>
  );
}

export default function TokenMeter({ tokensIn, tokensOut, costUsd, label }: TokenMeterProps) {
  const wrapperProps = label ? { 'aria-label': label, title: label } : {};

  return (
    <div className="flex flex-wrap gap-2" {...wrapperProps}>
      <Chip>{`↓ ${tokensIn.toLocaleString()} in`}</Chip>
      <Chip>{`↑ ${tokensOut.toLocaleString()} out`}</Chip>
      <Chip className={costUsd > 0 ? 'text-green' : ''}>{`$${costUsd.toFixed(4)}`}</Chip>
    </div>
  );
}
