import { useEffect, useRef } from 'react';

export function useInterval(callback: () => void, delayMs: number | null): void {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (delayMs === null) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      savedCallback.current();
    }, delayMs);

    return () => {
      window.clearInterval(timer);
    };
  }, [delayMs]);
}
