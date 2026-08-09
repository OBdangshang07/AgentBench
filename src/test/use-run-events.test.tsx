import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useRunEvents } from "../lib/useRunEvents";
import type { RunEvent } from "../types";

function event(seq: number, summary: string): RunEvent {
  return { id: seq, seq, event_type: "live.activity", payload: { summary }, created_at: "2026-08-09T10:00:00Z" };
}

describe("useRunEvents", () => {
  it("drops the previous run event buffer when the live focus changes", async () => {
    const first = [event(1, "first run"), event(9, "old high cursor")];
    const second = [event(1, "second run")];
    const { result, rerender } = renderHook(
      ({ runId, initial }) => useRunEvents(runId, initial, false),
      { initialProps: { runId: "run-1", initial: first } },
    );
    expect(result.current.events.map((item) => item.payload.summary)).toContain("old high cursor");

    rerender({ runId: "run-2", initial: second });

    await waitFor(() => expect(result.current.events).toHaveLength(1));
    expect(result.current.events[0].payload.summary).toBe("second run");
  });
});
