import { useEffect, useState } from 'react';

function parseStartedAt(startedAt: string | null | undefined): number | null {
  if (!startedAt) {
    return null;
  }

  const parsed = Date.parse(startedAt);
  return Number.isNaN(parsed) ? null : parsed;
}

function formatElapsed(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) {
    return '0s';
  }

  const totalSeconds = Math.floor(ms / 1000);
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }

  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) {
    return `${totalMinutes}m`;
  }

  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`;
}

export function useElapsedTime(startedAt: string | null | undefined): string {
  const [elapsed, setElapsed] = useState(() => {
    const startedMs = parseStartedAt(startedAt);
    return startedMs === null ? '—' : formatElapsed(Date.now() - startedMs);
  });

  useEffect(() => {
    const startedMs = parseStartedAt(startedAt);

    if (startedMs === null) {
      setElapsed('—');
      return;
    }

    const update = () => {
      setElapsed(formatElapsed(Date.now() - startedMs));
    };

    update();
    const timer = window.setInterval(update, 5000);

    return () => {
      window.clearInterval(timer);
    };
  }, [startedAt]);

  return elapsed;
}
