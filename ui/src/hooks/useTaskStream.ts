import { useEffect, useRef, useState } from 'react';
import { getTask } from '../lib/api';
import { wsClient, type StreamLineEvent, type TaskStreamDoneEvent, type TaskStreamLineEvent } from '../lib/ws';
import type { TaskStatus } from '../lib/types';

const TERMINAL_STATUSES: readonly TaskStatus[] = [
  'completed',
  'review_approved',
  'review_rejected',
  'failed',
  'needs_human',
  'blocked',
];

function isTerminalStatus(status: TaskStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

function splitWorkerOutput(output: string): string[] {
  if (!output) {
    return [];
  }

  const normalized = output.replace(/\r\n/g, '\n');
  const lines = normalized.split('\n');
  if (lines.length > 0 && lines[lines.length - 1] === '') {
    lines.pop();
  }
  return lines;
}

export function useTaskStream(
  missionId: string,
  taskId: string,
): {
  lines: string[];
  done: boolean;
  flush: () => void;
} {
  const [lines, setLines] = useState<string[]>([]);
  const [done, setDone] = useState(false);
  const pendingLinesRef = useRef<string[]>([]);
  const flushTimerRef = useRef<number | null>(null);

  const flush = (): void => {
    if (pendingLinesRef.current.length === 0) {
      return;
    }

    const nextLines = pendingLinesRef.current;
    pendingLinesRef.current = [];
    setLines((current) => current.concat(nextLines));
  };

  useEffect(() => {
    let active = true;

    pendingLinesRef.current = [];
    if (flushTimerRef.current !== null) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    setLines([]);
    setDone(false);

    void getTask(missionId, taskId)
      .then((task) => {
        if (!active) {
          return;
        }

        const initialLines = splitWorkerOutput(task.worker_output ?? '');
        setLines((current) => {
          if (current.length === 0) {
            return initialLines;
          }

          if (initialLines.length === 0) {
            return current;
          }

          return initialLines.concat(current);
        });
        setDone(isTerminalStatus(task.status));
      })
      .catch(() => {
        if (active) {
          setDone(false);
        }
      });

    const scheduleFlush = (): void => {
      if (flushTimerRef.current !== null) {
        return;
      }

      flushTimerRef.current = setTimeout(() => {
        flushTimerRef.current = null;
        if (active) {
          flush();
        }
      }, 0);
    };

    const handler = (event: StreamLineEvent | TaskStreamLineEvent | TaskStreamDoneEvent): void => {
      if (!active || event.mission_id !== missionId || event.task_id !== taskId) {
        return;
      }

      if (event.type === 'task_stream_done') {
        setDone(true);
        return;
      }

      pendingLinesRef.current.push(event.line);
      if (event.done) {
        setDone(true);
      }
      scheduleFlush();
    };

    wsClient.subscribe(missionId);
    wsClient.on('stream_line', handler);
    wsClient.on('task_stream_line', handler);
    wsClient.on('task_stream_done', handler);

    return () => {
      active = false;
      wsClient.off('stream_line', handler);
      wsClient.off('task_stream_line', handler);
      wsClient.off('task_stream_done', handler);
      if (flushTimerRef.current !== null) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    };
  }, [missionId, taskId]);

  return { lines, done, flush };
}
