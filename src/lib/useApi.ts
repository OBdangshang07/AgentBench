import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

interface CacheEntry {
  data: unknown;
  updatedAt: number;
}

const responseCache = new Map<string, CacheEntry>();
const INVALIDATE_EVENT = "agentbench:api-invalidate";

export function invalidateApi(match?: string | RegExp) {
  for (const path of responseCache.keys()) {
    if (!match || (typeof match === "string" ? path.startsWith(match) : match.test(path))) {
      responseCache.delete(path);
    }
  }
  window.dispatchEvent(new CustomEvent(INVALIDATE_EVENT, { detail: match }));
}

function matchesInvalidation(path: string, match: unknown) {
  if (!match) return true;
  if (typeof match === "string") return path.startsWith(match);
  return match instanceof RegExp ? match.test(path) : false;
}

export function useApi<T>(path: string | null, refreshMs?: number | ((data: T | null) => number | undefined)) {
  const cached = path ? responseCache.get(path) : undefined;
  const [data, setDataState] = useState<T | null>((cached?.data as T | undefined) ?? null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const requestRef = useRef<AbortController | null>(null);
  const runningRef = useRef(false);

  const setData = useCallback((value: T | null | ((current: T | null) => T | null)) => {
    setDataState((current) => {
      const next = typeof value === "function" ? (value as (current: T | null) => T | null)(current) : value;
      if (path && next !== null) responseCache.set(path, { data: next, updatedAt: Date.now() });
      return next;
    });
  }, [path]);

  const refresh = useCallback(async () => {
    if (!path || runningRef.current) return;
    runningRef.current = true;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    try {
      setError(null);
      const result = await api<T>(path, { signal: controller.signal });
      if (!mountedRef.current || controller.signal.aborted) return;
      responseCache.set(path, { data: result, updatedAt: Date.now() });
      setDataState(result);
    } catch (value) {
      if (controller.signal.aborted || !mountedRef.current) return;
      setError(value instanceof Error ? value.message : "无法连接本地服务");
    } finally {
      if (mountedRef.current && !controller.signal.aborted) setLoading(false);
      if (requestRef.current === controller) {
        requestRef.current = null;
        runningRef.current = false;
      }
    }
  }, [path]);

  const interval = typeof refreshMs === "function" ? refreshMs(data) : refreshMs;

  useEffect(() => {
    mountedRef.current = true;
    const current = path ? responseCache.get(path) : undefined;
    if (current) {
      setDataState(current.data as T);
      setLoading(false);
    } else {
      setDataState(null);
      setLoading(Boolean(path));
    }
    void refresh();
    let handle: number | undefined;
    if (interval && path) {
      const schedule = () => {
        const delay = document.visibilityState === "hidden" ? Math.max(interval * 4, 15_000) : interval;
        handle = window.setTimeout(async () => {
          await refresh();
          schedule();
        }, delay);
      };
      schedule();
    }
    const onInvalidate = (event: Event) => {
      const match = (event as CustomEvent).detail;
      if (path && matchesInvalidation(path, match)) void refresh();
    };
    window.addEventListener(INVALIDATE_EVENT, onInvalidate);
    return () => {
      mountedRef.current = false;
      if (handle !== undefined) window.clearTimeout(handle);
      if (requestRef.current) {
        requestRef.current.abort();
        requestRef.current = null;
        runningRef.current = false;
      }
      window.removeEventListener(INVALIDATE_EVENT, onInvalidate);
    };
  }, [path, refresh, interval]);

  return { data, loading, error, refresh, setData };
}
