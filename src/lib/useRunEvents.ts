import { useEffect, useRef, useState } from "react";
import type { RunEvent } from "../types";
import { API_BASE } from "./api";

export type StreamState = "idle" | "connecting" | "live" | "reconnecting";

export function useRunEvents(runId: string, initial: RunEvent[], active: boolean) {
  const [events, setEvents] = useState<RunEvent[]>(initial);
  const [streamState, setStreamState] = useState<StreamState>(active ? "connecting" : "idle");
  const cursor = useRef(initial.at(-1)?.seq ?? 0);

  useEffect(() => {
    setEvents((current) => {
      const merged = new Map(current.map((event) => [event.seq, event]));
      for (const event of initial) merged.set(event.seq, event);
      const next = [...merged.values()].sort((left, right) => left.seq - right.seq);
      cursor.current = next.at(-1)?.seq ?? 0;
      if (next.length === current.length && next.every((event, index) => event === current[index])) {
        return current;
      }
      return next;
    });
  }, [initial]);

  useEffect(() => {
    if (!active || !runId || typeof EventSource === "undefined") {
      setStreamState("idle");
      return undefined;
    }
    let disposed = false;
    let source: EventSource | null = null;
    let retryTimer: number | undefined;

    const connect = () => {
      if (disposed) return;
      setStreamState((current) => current === "live" ? "reconnecting" : "connecting");
      source = new EventSource(
        `${API_BASE}/runs/${encodeURIComponent(runId)}/events/stream?after=${cursor.current}`,
      );
      source.onopen = () => setStreamState("live");
      source.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as RunEvent;
          cursor.current = Math.max(cursor.current, event.seq);
          setEvents((current) => {
            if (current.some((item) => item.seq === event.seq)) return current;
            return [...current, event].sort((left, right) => left.seq - right.seq);
          });
        } catch {
          // Ignore malformed display messages; the authoritative run is still polled.
        }
      };
      source.onerror = () => {
        source?.close();
        source = null;
        if (!disposed) {
          setStreamState("reconnecting");
          retryTimer = window.setTimeout(connect, 1_500);
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      source?.close();
    };
  }, [active, runId]);

  return { events, streamState };
}
