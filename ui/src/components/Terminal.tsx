import { useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/virtual';
import { parseAnsi } from '../lib/ansi';
import { LINE_CLASSES, parseStreamLine } from '../lib/streamParser';

export interface TerminalProps {
  lines: string[];
  done: boolean;
  className?: string;
}

export default function Terminal({ lines, done, className = '' }: TerminalProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);

  const filteredLines = useMemo(() => {
    if (searchQuery === '') {
      return lines;
    }

    const query = searchQuery.toLowerCase();
    return lines.filter((line) => line.toLowerCase().includes(query));
  }, [lines, searchQuery]);

  const virtualizer = useVirtualizer({
    count: filteredLines.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 20,
    overscan: 30,
  });

  const totalSize = virtualizer.getTotalSize();

  useEffect(() => {
    if (!autoScroll) {
      return;
    }

    const scrollable = parentRef.current as { scrollTo?: (x: number, y: number) => void } | null;
    if (typeof scrollable?.scrollTo === 'function') {
      scrollable.scrollTo(0, totalSize);
    }
  }, [autoScroll, lines.length, totalSize]);

  const handleCopy = async (): Promise<void> => {
    const text = lines.join('\n');

    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    document.execCommand('copy');
    textarea.remove();
  };

  return (
    <div className={className}>
      <div className="mb-1 flex items-center gap-2 text-[11px]">
        <input
          className="flex-1 rounded border border-border bg-surface px-2 py-0.5 font-mono text-[11px] text-text"
          placeholder="Filter output..."
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
        <button
          type="button"
          className={[
            'rounded border border-border px-2 py-0.5 font-mono text-[11px]',
            autoScroll ? 'bg-cyan/10 text-cyan' : 'text-dim',
          ]
            .filter(Boolean)
            .join(' ')}
          onClick={() => setAutoScroll((next) => !next)}
        >
          {autoScroll ? '↓ Auto' : '↑ Manual'}
        </button>
        <button
          type="button"
          className="rounded border border-border px-2 py-0.5 font-mono text-[11px] text-text"
          onClick={() => {
            void handleCopy();
          }}
        >
          ⎘ Copy
        </button>
      </div>

      <div
        ref={parentRef}
        className="bg-[#050810] text-[#dde6f0] rounded-lg border border-border font-mono text-[12px] leading-5 overflow-auto"
        style={{ height: '480px' }}
      >
        {searchQuery !== '' && filteredLines.length === 0 ? (
          <div className="px-3 py-3 text-[12px] text-dim">No matches for '{searchQuery}'</div>
        ) : (
          <div style={{ height: totalSize, position: 'relative' }}>
            {virtualizer.getVirtualItems().map((item) => {
              const line = filteredLines[item.index] ?? '';
              const { type } = parseStreamLine(line);
              const spans = parseAnsi(line);

              return (
                <div
                  key={item.key}
                  style={{ position: 'absolute', top: item.start, left: 0, right: 0 }}
                  className={`px-3 ${LINE_CLASSES[type]}`}
                >
                  {type === 'inject' ? (
                    <span className="text-[10px] font-bold mr-2 text-amber bg-amber/20 rounded px-1">
                      [USER]
                    </span>
                  ) : null}
                  {spans.map((span, index) => (
                    <span key={index} style={span.style}>
                      {span.text}
                    </span>
                  ))}
                  {!done && item.index === filteredLines.length - 1 ? (
                    <span className="animate-[data-blink_1s_step-end_infinite]">_</span>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
