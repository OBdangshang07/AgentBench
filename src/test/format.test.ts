import { describe, expect, it } from "vitest";
import { formatDuration, statusLabel, statusTone } from "../lib/format";

describe("display formatting", () => {
  it("keeps evaluation statuses explicit", () => {
    expect(statusLabel.environment_unavailable).toBe("缺少沙箱");
    expect(statusTone("needs_review")).toBe("warning");
    expect(statusTone("completed")).toBe("success");
  });

  it("formats run duration", () => {
    expect(formatDuration(950)).toBe("950 ms");
    expect(formatDuration(12_500)).toBe("12.5 s");
    expect(formatDuration(125_000)).toBe("2m 5s");
  });
});
