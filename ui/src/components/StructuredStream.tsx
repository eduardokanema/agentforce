import { useEffect, useMemo, useRef, useState } from 'react';
import type { StreamEventRecord } from '../lib/ws';

type ResponseBlock = {
  type: 'response';
  key: string;
  role: string;
  provider: string;
  text: string;
  startSeq: number;
  endSeq: number;
  startedAt: string;
  endedAt: string;
};

type ActionBlock = {
  type: 'action';
  key: string;
  title: string;
  label: string;
  command?: string;
  provider: string;
  role: string;
  callId: string;
  outputs: string[];
  running: boolean;
  success?: boolean;
  exitCode?: number | null;
  startedAt: string;
  endedAt: string;
};

type SystemBlock = {
  type: 'system';
  key: string;
  kind: string;
  label: string;
  role: string;
  provider: string;
  message: string;
  at: string;
};

type Block = ResponseBlock | ActionBlock | SystemBlock;

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function formatClock(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatEventLabel(event: StreamEventRecord): string {
  if (event.kind === 'status') {
    const state = stringValue(event.payload.state);
    if (state) {
      return state.replace(/_/g, ' ');
    }
  }

  if (event.kind === 'raw_line') {
    const providerEventType = stringValue((event.payload.meta as Record<string, unknown> | undefined)?.provider_event_type);
    if (providerEventType === 'thread.started') {
      return 'thread started';
    }
    if (providerEventType === 'turn.started') {
      return 'turn started';
    }
    if (providerEventType === 'non_json') {
      return 'raw output';
    }
  }

  return event.kind.replace(/_/g, ' ');
}

function formatSystemMessage(event: StreamEventRecord): string {
  const providerEventType = stringValue((event.payload.meta as Record<string, unknown> | undefined)?.provider_event_type);

  if (event.kind === 'status') {
    return stringValue(event.payload.message) || formatEventLabel(event);
  }
  if (event.kind === 'user_instruction') {
    return stringValue(event.payload.message);
  }
  if (event.kind === 'warning' || event.kind === 'error') {
    return stringValue(event.payload.message);
  }
  if (event.kind === 'usage') {
    const tokensIn = typeof event.payload.tokens_in === 'number' ? event.payload.tokens_in.toLocaleString() : '0';
    const tokensOut = typeof event.payload.tokens_out === 'number' ? event.payload.tokens_out.toLocaleString() : '0';
    const cost = typeof event.payload.cost_usd === 'number' ? `$${event.payload.cost_usd.toFixed(4)}` : '$0.0000';
    return `↓ ${tokensIn} in\n↑ ${tokensOut} out\n${cost}`;
  }
  if (event.kind === 'raw_line') {
    if (providerEventType === 'thread.started') {
      const threadId = stringValue((event.payload.meta as Record<string, unknown> | undefined)?.thread_id);
      return threadId ? `Thread ready\n${threadId}` : 'Thread ready';
    }
    if (providerEventType === 'turn.started') {
      return 'New model turn started';
    }
    return stringValue(event.payload.text) || event.raw_line || '';
  }
  return stringValue(event.payload.message) || stringValue(event.payload.text) || event.raw_line || JSON.stringify(event.payload);
}

export default function StructuredStream({ events, done }: { events: StreamEventRecord[]; done: boolean }) {
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const blocks = useMemo<Block[]>(() => {
    const next: Block[] = [];
    const actionIndex = new Map<string, number>();

    for (const event of events) {
      if (event.kind === 'text_delta') {
        const text = stringValue(event.payload.text);
        const current = next[next.length - 1];
        if (current?.type === 'response' && current.role === event.role && current.provider === event.provider) {
          current.text += text;
          current.endSeq = event.seq;
          current.endedAt = event.timestamp;
        } else {
          next.push({
            type: 'response',
            key: `response-${event.seq}`,
            role: event.role,
            provider: event.provider,
            text,
            startSeq: event.seq,
            endSeq: event.seq,
            startedAt: event.timestamp,
            endedAt: event.timestamp,
          });
        }
        continue;
      }

      if (event.kind === 'tool_start') {
        const callId = stringValue(event.payload.call_id) || `tool-${event.seq}`;
        actionIndex.set(callId, next.length);
        next.push({
          type: 'action',
          key: `action-${callId}-${event.seq}`,
          title: stringValue(event.payload.title) || stringValue(event.payload.command) || 'action',
          label: 'tool run',
          command: stringValue(event.payload.command) || undefined,
          provider: event.provider,
          role: event.role,
          callId,
          outputs: [],
          running: true,
          startedAt: event.timestamp,
          endedAt: event.timestamp,
        });
        continue;
      }

      if (event.kind === 'tool_output' || event.kind === 'tool_end') {
        const callId = stringValue(event.payload.call_id);
        const index = actionIndex.get(callId);
        const block = index !== undefined ? next[index] : null;
        if (block && block.type === 'action') {
          if (event.kind === 'tool_output') {
            const text = stringValue(event.payload.text);
            if (text) {
              block.outputs.push(text);
            }
          } else {
            block.running = false;
            block.success = typeof event.payload.success === 'boolean' ? event.payload.success : undefined;
            block.exitCode = typeof event.payload.exit_code === 'number' ? event.payload.exit_code : null;
          }
          block.endedAt = event.timestamp;
          continue;
        }
      }

      next.push({
        type: 'system',
        key: `system-${event.seq}`,
        kind: event.kind,
        label: formatEventLabel(event),
        role: event.role,
        provider: event.provider,
        message: formatSystemMessage(event),
        at: event.timestamp,
      });
    }

    return next;
  }, [events]);

  useEffect(() => {
    if (!autoScroll) {
      return;
    }
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [autoScroll, blocks.length]);

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2">
        <div className="text-[11px] uppercase tracking-[0.08em] text-dim">
          Structured activity
        </div>
        <button
          type="button"
          className={[
            'rounded border px-2 py-0.5 font-mono text-[11px] transition-colors',
            autoScroll ? 'border-cyan/30 bg-cyan/10 text-cyan' : 'border-border text-dim hover:bg-surface',
          ].join(' ')}
          onClick={() => setAutoScroll((current) => !current)}
        >
          {autoScroll ? '↓ Auto' : '↑ Manual'}
        </button>
      </div>
      <div ref={scrollRef} className="max-h-[560px] overflow-y-auto px-4 py-4">
        <div className="space-y-3">
          {blocks.length === 0 ? (
            <div className="rounded-lg border border-border bg-surface px-4 py-3 text-sm text-dim">
              No structured events yet.
            </div>
          ) : null}

          {blocks.map((block) => {
            if (block.type === 'response') {
              const isLive = !done && block.endSeq === events[events.length - 1]?.seq;
              return (
                <article key={block.key} className="rounded-lg border border-cyan/20 bg-cyan/5 p-4">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full border border-cyan/30 bg-cyan/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-cyan">
                        response
                      </span>
                      <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-cyan">
                        {block.role} · {block.provider}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-dim">
                        {formatClock(block.startedAt)}
                        {block.startedAt !== block.endedAt ? ` → ${formatClock(block.endedAt)}` : ''}
                      </span>
                      {isLive ? (
                        <div className="rounded-full border border-cyan/30 bg-cyan/10 px-2 py-0.5 text-[10px] text-cyan">live</div>
                      ) : null}
                    </div>
                  </div>
                  <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-6 text-text">{block.text}</pre>
                </article>
              );
            }

            if (block.type === 'action') {
              return (
                <article key={block.key} className="rounded-lg border border-amber/20 bg-amber/5 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full border border-amber/30 bg-amber/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-amber">
                          {block.label}
                        </span>
                        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-amber">
                          {block.provider}
                        </span>
                      </div>
                      <div className="mt-1 font-mono text-sm text-text">{block.title}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-dim">
                        {formatClock(block.startedAt)}
                        {block.startedAt !== block.endedAt ? ` → ${formatClock(block.endedAt)}` : ''}
                      </span>
                      <div className={`rounded-full border px-2 py-0.5 text-[10px] ${
                        block.running
                          ? 'border-amber/30 bg-amber/10 text-amber'
                          : block.success
                            ? 'border-green/30 bg-green/10 text-green'
                            : 'border-red/30 bg-red/10 text-red'
                      }`}>
                        {block.running ? 'running' : block.success ? 'ok' : `exit ${block.exitCode ?? '?'}`}
                      </div>
                    </div>
                  </div>
                  {block.command ? (
                    <div className="mt-3 rounded border border-border bg-card px-3 py-2 font-mono text-[12px] text-text">
                      {block.command}
                    </div>
                  ) : null}
                  {block.outputs.length > 0 ? (
                    <details className="mt-3" open={block.running}>
                      <summary className="cursor-pointer text-[11px] uppercase tracking-[0.08em] text-dim">
                        Output ({block.outputs.length})
                      </summary>
                      <pre className="mt-2 whitespace-pre-wrap break-words rounded border border-border bg-card px-3 py-2 font-mono text-[12px] leading-6 text-text">
                        {block.outputs.join('\n')}
                      </pre>
                    </details>
                  ) : null}
                </article>
              );
            }

            const tone =
              block.kind === 'error'
                ? 'border-red/20 bg-red/5 text-red'
                : block.kind === 'warning'
                  ? 'border-amber/20 bg-amber/5 text-amber'
                  : block.kind === 'user_instruction'
                    ? 'border-blue/20 bg-blue/5 text-blue'
                    : block.kind === 'usage'
                      ? 'border-emerald-400/20 bg-[linear-gradient(135deg,rgba(16,185,129,0.12),rgba(16,185,129,0.04))] text-green'
                      : block.label === 'thread started'
                        ? 'border-violet-400/20 bg-[linear-gradient(135deg,rgba(139,92,246,0.12),rgba(139,92,246,0.04))] text-violet-200'
                        : block.label === 'turn started'
                          ? 'border-sky-400/20 bg-[linear-gradient(135deg,rgba(56,189,248,0.12),rgba(56,189,248,0.04))] text-sky-100'
                      : 'border-border bg-surface text-dim';

            return (
              <article key={block.key} className={`rounded-lg border p-4 ${tone}`}>
                <div className="flex items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-current/20 bg-black/5 px-2 py-0.5 text-[10px] uppercase tracking-[0.08em]">
                      {block.label}
                    </span>
                    <span className="text-[11px] font-semibold uppercase tracking-[0.08em]">
                      {block.provider}
                    </span>
                  </div>
                  <span className="font-mono text-[11px] text-dim">{formatClock(block.at)}</span>
                </div>
                {block.kind === 'usage' ? (
                  <div className="mt-3 grid gap-2 sm:grid-cols-3">
                    {block.message.split('\n').map((part) => (
                      <div key={part} className="rounded border border-current/10 bg-black/10 px-3 py-2 font-mono text-[12px] text-text">
                        {part}
                      </div>
                    ))}
                  </div>
                ) : block.label === 'thread started' ? (
                  <div className="mt-3">
                    <div className="text-sm font-semibold text-text">Thread ready</div>
                    {block.message.includes('\n') ? (
                      <div className="mt-2 rounded border border-current/10 bg-black/10 px-3 py-2 font-mono text-[12px] text-text">
                        {block.message.split('\n')[1]}
                      </div>
                    ) : null}
                  </div>
                ) : block.label === 'turn started' ? (
                  <div className="mt-3 text-sm font-semibold text-text">New model turn started</div>
                ) : (
                  <pre className="mt-2 whitespace-pre-wrap break-words font-mono text-[12px] leading-6 text-text">{block.message}</pre>
                )}
              </article>
            );
          })}
        </div>
      </div>
    </div>
  );
}
