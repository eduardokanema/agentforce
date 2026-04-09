import { useEffect, useRef, useState } from 'react';
import { getTask, getTaskOutput } from '../lib/api';
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

    // Load status from task state, and historical output from the stream log file.
    // worker_output in the state is not updated during execution, so we read
    // the raw stream log directly via the /output endpoint.
    const taskStatusPromise = getTask(missionId, taskId)
      .then((task) => { if (active) setDone(isTerminalStatus(task.status)); })
      .catch(() => undefined);

    const taskOutputPromise = getTaskOutput(missionId, taskId)
      .then(({ lines: logLines }) => {
        if (!active || logLines.length === 0) return;
        setLines((current) => {
          // WS lines may have already arrived; append log lines before them
          if (current.length === 0) return logLines;
          return logLines.concat(current);
        });
      })
      .catch(() => undefined);

    void Promise.all([taskStatusPromise, taskOutputPromise]);

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
