import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "../pages/Settings";

const status = {
  version: "5.2.0",
  data_dir: "C:/AgentBench",
  database: { path: "C:/AgentBench/agentbench.db", ready: true },
  docker: { installed: true, available: true, executable: "docker" },
  native_cli_enabled: true,
  settings: { judge_model_id: "model-1", judge_runner_id: "runner-1", default_concurrency: 2, default_max_runtime_seconds: 7200 },
  runners: [],
};

describe("judge settings", () => {
  afterEach(() => vi.restoreAllMocks());

  it("persists judge selection immediately", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return new Response(JSON.stringify({ name: "AgentBench Desktop", version: "5.2.0" }), { status: 200 });
      if (init?.method === "PATCH") return new Response(JSON.stringify(status), { status: 200 });
      if (url.endsWith("/models")) {
        return new Response(JSON.stringify([
          { id: "model-1", name: "Model One" },
          { id: "model-2", name: "Model Two" },
        ]), { status: 200 });
      }
      if (url.endsWith("/runners")) {
        return new Response(JSON.stringify([{ id: "runner-1", name: "Runner One" }]), { status: 200 });
      }
      return new Response(JSON.stringify(status), { status: 200 });
    });

    render(<SettingsPage />);
    const select = await screen.findByLabelText("裁判模型");
    fireEvent.change(select, { target: { value: "model-2" } });

    await screen.findByText("已自动保存");
    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
      expect(patchCall).toBeDefined();
      expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({
        judge_model_id: "model-2",
        judge_runner_id: "runner-1",
      });
    });
  });
});
