import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export function useApi<T>(path: string | null, refreshMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!path) return;
    try {
      setError(null);
      const result = await api<T>(path);
      setData(result);
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法连接本地服务");
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void refresh();
    if (!refreshMs || !path) return;
    const handle = window.setInterval(() => void refresh(), refreshMs);
    return () => window.clearInterval(handle);
  }, [path, refresh, refreshMs]);

  return { data, loading, error, refresh, setData };
}
