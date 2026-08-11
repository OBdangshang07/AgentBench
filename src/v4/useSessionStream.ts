import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";
import type { StudioEvent } from "./types";

export function useSessionStream(sessionId: string | undefined, persistedSequence = 0, active = true) {
  const [events, setEvents] = useState<StudioEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const sequenceRef = useRef(0);
  const reconnectRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    sequenceRef.current = persistedSequence;
    setEvents([]);
    setConnected(false);
  }, [sessionId]);

  useEffect(() => {
    sequenceRef.current = Math.max(sequenceRef.current, persistedSequence);
  }, [persistedSequence]);

  useEffect(() => {
    if (!sessionId || !active) {
      setConnected(false);
      return;
    }
    let disposed = false;
    let source: EventSource | null = null;
    let retry = 800;

    const connect = () => {
      if (disposed) return;
      source = new EventSource(`${API_BASE}/sessions/${sessionId}/events/stream?after=${sequenceRef.current}`);
      source.onopen = () => {
        retry = 800;
        setConnected(true);
      };
      source.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as StudioEvent;
          sequenceRef.current = Math.max(sequenceRef.current, event.seq);
          setEvents((current) => current.some((item) => item.seq === event.seq)
            ? current
            : [...current.slice(-999), event]);
        } catch {
          // Persisted events remain available through the session detail endpoint.
        }
      };
      source.onerror = () => {
        setConnected(false);
        source?.close();
        source = null;
        if (!disposed) {
          reconnectRef.current = window.setTimeout(connect, retry);
          retry = Math.min(8_000, Math.round(retry * 1.7));
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      setConnected(false);
      source?.close();
      if (reconnectRef.current !== undefined) window.clearTimeout(reconnectRef.current);
    };
  }, [active, sessionId]);

  return { events, connected, lastSequence: sequenceRef.current };
}
