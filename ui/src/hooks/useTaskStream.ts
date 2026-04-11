import { useEffect, useRef, useState } from 'react';
import { getTask, getTaskOutput, getTaskStreamEvents } from '../lib/api';
import {
  wsClient,
  type StreamEventRecord,
  type StreamLineEvent,
  type TaskAttemptStartEvent,
  type TaskStreamDoneEvent,
  type TaskStreamEvent,
  type TaskStreamLineEvent,
} from '../lib/ws';
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
  events: StreamEventRecord[];
  done: boolean;
  flush: () => void;
} {
  const [lines, setLines] = useState<string[]>([]);
  const [events, setEvents] = useState<StreamEventRecord[]>([]);
  const [done, setDone] = useState(false);
  const pendingLinesRef = useRef<string[]>([]);
  const flushTimerRef = useRef<number | null>(null);
  const lastSeqRef = useRef(0);
  const seenEventSeqRef = useRef<Set<number>>(new Set());

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

    const resetStreamState = (): void => {
      pendingLinesRef.current = [];
      lastSeqRef.current = 0;
      seenEventSeqRef.current = new Set();
      setLines([]);
      setEvents([]);
      setDone(false);
      if (flushTimerRef.current !== null) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    };

    resetStreamState();

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

    const taskEventsPromise = getTaskStreamEvents(missionId, taskId)
      .then(({ events: initialEvents, done: initialDone, last_seq }) => {
        if (!active) return;
        seenEventSeqRef.current = new Set(initialEvents.map((event) => event.seq));
        lastSeqRef.current = last_seq;
        setEvents(initialEvents);
        if (initialDone) {
          setDone(true);
        }
      })
      .catch(() => undefined);

    void Promise.all([taskStatusPromise, taskOutputPromise, taskEventsPromise]);

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

    const mergeEvents = (nextEvents: StreamEventRecord[]): void => {
      if (nextEvents.length === 0) {
        return;
      }
      setEvents((current) => {
        const merged = current.slice();
        for (const event of nextEvents) {
          if (seenEventSeqRef.current.has(event.seq)) {
            continue;
          }
          seenEventSeqRef.current.add(event.seq);
          merged.push(event);
          lastSeqRef.current = Math.max(lastSeqRef.current, event.seq);
        }
        merged.sort((a, b) => a.seq - b.seq);
        return merged;
      });
    };

    const recoverGap = async (): Promise<void> => {
      const { events: backfill, done: recoveredDone } = await getTaskStreamEvents(missionId, taskId, lastSeqRef.current);
      if (!active) {
        return;
      }
      mergeEvents(backfill);
      if (recoveredDone) {
        setDone(true);
      }
    };

    const handler = (event: StreamLineEvent | TaskStreamLineEvent | TaskStreamDoneEvent | TaskStreamEvent): void => {
      if (!active || event.mission_id !== missionId || event.task_id !== taskId) {
        return;
      }

      if (event.type === 'task_stream_done') {
        setDone(true);
        return;
      }

      if (event.type === 'task_stream_event') {
        const seq = event.event.seq;
        if (seq > lastSeqRef.current + 1) {
          void recoverGap().then(() => {
            if (!seenEventSeqRef.current.has(seq)) {
              mergeEvents([event.event]);
            }
          }).catch(() => undefined);
          return;
        }
        mergeEvents([event.event]);
        return;
      }

      pendingLinesRef.current.push(event.line);
      if (event.done) {
        setDone(true);
      }
      scheduleFlush();
    };

    const handleTaskAttemptStart = (event: TaskAttemptStartEvent): void => {
      if (!active || event.mission_id !== missionId || event.task_id !== taskId) {
        return;
      }

      resetStreamState();
      void getTaskOutput(missionId, taskId)
        .then(({ lines: outputLines }) => {
          if (active) {
            setLines(outputLines);
          }
        })
        .catch(() => undefined);
    };

    wsClient.subscribe(missionId);
    wsClient.on('stream_line', handler);
    wsClient.on('task_stream_line', handler);
    wsClient.on('task_stream_done', handler);
    wsClient.on('task_stream_event', handler);
    wsClient.on('task_attempt_start', handleTaskAttemptStart);

    return () => {
      active = false;
      wsClient.off('stream_line', handler);
      wsClient.off('task_stream_line', handler);
      wsClient.off('task_stream_done', handler);
      wsClient.off('task_stream_event', handler);
      wsClient.off('task_attempt_start', handleTaskAttemptStart);
      if (flushTimerRef.current !== null) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    };
  }, [missionId, taskId]);

  return { lines, events, done, flush };
}
