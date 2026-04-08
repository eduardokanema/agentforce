import { useEffect, useRef } from 'react';

export interface TerminalPanelProps {
  lines: string[];
  className?: string;
}

export default function TerminalPanel({ lines, className = '' }: TerminalPanelProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [lines.length]);

  return (
    <div
      className={[
        'max-h-[500px] overflow-y-auto rounded-lg border border-border bg-[#050810] px-4 py-4 font-mono text-[12px] leading-6 text-[#9ab0c6] whitespace-pre-wrap break-words',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {lines.map((line, index) => (
        <div key={`${index}-${line}`}>{line}</div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
