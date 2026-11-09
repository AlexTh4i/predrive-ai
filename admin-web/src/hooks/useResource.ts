import { useEffect, useState } from 'react';
import { ApiError } from '../api/contract';

export function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return 'Không thể tải dữ liệu. Vui lòng kiểm tra kết nối và thử lại.';
}

export function useResource<T>(load: (signal: AbortSignal) => Promise<T>, refreshKey = 0) {
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<{ load: typeof load; version: number; data?: T; error?: string }>();
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setResult({ load, version, data }); },
      (error: unknown) => {
        if (!controller.signal.aborted) setResult({ load, version, error: errorMessage(error) });
      },
    );
    return () => controller.abort();
  }, [load, version, refreshKey]);
  const current = result?.load === load && result.version === version ? result : undefined;
  return { data: current?.data, error: current?.error, loading: !current, retry: () => setVersion((value) => value + 1) };
}
