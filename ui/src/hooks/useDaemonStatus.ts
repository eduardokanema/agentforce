import { useCallback, useEffect, useState } from 'react';
import { getDaemonStatus } from '../lib/api';
import type { DaemonStatus } from '../lib/types';

export function useDaemonStatus() {
  const [status, setStatus] = useState<DaemonStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      const data = await getDaemonStatus();
      setStatus(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
    const id = setInterval(refetch, 3000);
    return () => clearInterval(id);
  }, [refetch]);

  return { status, loading, error, refetch };
}
