import { useCallback, useEffect, useState, useSyncExternalStore, type SetStateAction } from "react";

export function useMediaQuery(query: string) {
  const subscribe = useCallback((notify: () => void) => {
    const media = window.matchMedia?.(query);
    media?.addEventListener("change", notify);
    return () => media?.removeEventListener("change", notify);
  }, [query]);
  const snapshot = useCallback(() => window.matchMedia?.(query).matches ?? false, [query]);
  return useSyncExternalStore(subscribe, snapshot, () => false);
}

/** Compact panes are temporary; resizing never overwrites the desktop layout. */
export function useResponsiveLayout<T extends object>(
  initial: () => T, storageKey: string, mode: string, collapsed: Partial<T>,
): [T, (action: SetStateAction<T>) => void] {
  const [state, setState] = useState(() => ({ desktop: initial(), overlay: {} as Partial<T>, mode }));
  if (state.mode !== mode) setState({ ...state, overlay: {}, mode });
  const overlay = state.mode === mode ? state.overlay : {};
  const visible = { ...state.desktop, ...collapsed, ...overlay };
  const collapsedKeys = JSON.stringify(Object.keys(collapsed).sort());
  const setLayout = useCallback((action: SetStateAction<T>) => {
    setState(current => {
      const base = { ...current.desktop, ...collapsed, ...(current.mode === mode ? current.overlay : {}) };
      const next = typeof action === "function" ? (action as (value: T) => T)(base) : action;
      const desktop = { ...next };
      const overlay: Partial<T> = {};
      for (const key of JSON.parse(collapsedKeys) as Array<keyof T>) {
        desktop[key] = current.desktop[key];
        overlay[key] = next[key];
      }
      return { desktop, overlay, mode };
    });
  // Presets contain fixed values; their keys and mode identify a breakpoint.
  }, [mode, collapsedKeys]);
  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify(state.desktop)); } catch { /* optional preference */ }
  }, [storageKey, state.desktop]);
  return [visible, setLayout];
}
