import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Experiments from "../pages/Experiments";

function json(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("benchmark reasoning policy", () => {
  afterEach(() => vi.restoreAllMocks());

  it("defaults Ultra to MAX and persists participant and judge conditions", async () => {
    const bodies: Record<string, unknown>[] = [];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.3" });
      if (url.endsWith("/models")) return json([{ id: "model-1", name: "DeepSeek V4 Pro", enabled: true }]);
      if (url.endsWith("/runners")) return json([{ id: "runner-1", name: "DeepSeek Harness", runner_type: "deepseek_harness", enabled: true, capability: { installed: true }, adapter: { reasoning_control: { supported: true, verified: true, maximum: "max", note: "Harness 实际使用 MAX 档" } } }]);
      if (url.endsWith("/suites")) return json([{ id: "ultra", name: "Ultra 极限挑战", version: "3", case_count: 2, difficulty_min: 6, difficulty_max: 6 }]);
      if (url.endsWith("/system/status")) return json({ settings: {} });
      if (url.endsWith("/experiments") && init?.method === "POST") {
        bodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return json({ id: "experiment-1" });
      }
      if (url.endsWith("/experiments/experiment-1/start")) return json({ id: "experiment-1" });
      if (url.endsWith("/experiments")) return json([]);
      return json({});
    });

    render(<MemoryRouter initialEntries={["/experiments"]}><Routes><Route path="/experiments" element={<Experiments />} /><Route path="/experiments/:id" element={<div>experiment</div>} /></Routes></MemoryRouter>);

    await waitFor(() => expect(screen.getByRole("combobox", { name: "测评思考策略" })).toHaveValue("maximum"));
    fireEvent.change(screen.getByRole("combobox", { name: "参测者 1 模型" }), { target: { value: "model-1" } });
    fireEvent.change(screen.getByRole("combobox", { name: "参测者 1 Agent" }), { target: { value: "runner-1" } });
    fireEvent.change(screen.getByRole("combobox", { name: "匿名裁判思考强度" }), { target: { value: "xhigh" } });
    fireEvent.click(screen.getByRole("button", { name: /验证并开始本地评测/ }));

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({
      reasoning_policy: "maximum",
      reasoning_effort: "high",
      strict_fairness: true,
      judge_reasoning_effort: "xhigh",
    });
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/experiments/experiment-1/start"))).toBe(true);
  });
});
