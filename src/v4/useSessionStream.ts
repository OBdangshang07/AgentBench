import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";
import type { StudioEvent } from "./types";

export function useSessionStream(sessionId: string | undefined) {
  const [events, setEvents] = useState<StudioEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    setEvents([]);
    setConnected(false);
    if (!sessionId) return;
    const source = new EventSource(`${API_BASE}/sessions/${sessionId}/events/stream?after=0`);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as StudioEvent;
        setEvents((current) => current.some((item) => item.seq === event.seq)
          ? current
          : [...current.slice(-299), event]);
      } catch {
        // Ignore a malformed transport frame; persisted events remain available by polling.
      }
    };
    return () => source.close();
  }, [sessionId]);

  return { events, connected };
}
