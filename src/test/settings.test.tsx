import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "../pages/Settings";
import { WorkspaceUxProvider } from "../components/WorkspaceUx";

const status = {
  version: "5.5.1",
  data_dir: "C:/AgentBench",
  database: { path: "C:/AgentBench/agentbench.db", ready: true },
  docker: { installed: true, available: true, executable: "docker" },
  native_cli_enabled: true,
  settings: { judge_model_id: "model-1", judge_runner_id: "runner-1", default_concurrency: 2, default_max_runtime_seconds: 7200 },
  runners: [],
};

describe("settings", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("persists judge selection immediately", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return new Response(JSON.stringify({ name: "AgentBench Desktop", version: "5.5.1" }), { status: 200 });
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
    fireEvent.click(await screen.findByRole("button", { name: /评测默认值/ }));
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

  it("migrates the legacy theme and persists density without changing the settings route", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/models") || url.endsWith("/runners")) return new Response("[]", { status: 200 });
      return new Response(JSON.stringify(status), { status: 200 });
    });

    window.localStorage.setItem("agentbench.workspace.theme.v1", "acid-terminal");
    window.localStorage.setItem("agentbench.workspace.color-mode.v1", "dark");
    window.location.hash = "/settings";
    render(<WorkspaceUxProvider><SettingsPage /></WorkspaceUxProvider>);
    expect(await screen.findByText("浅色专业工具")).toBeVisible();
    expect(document.documentElement.dataset.agentbenchTheme).toBe("fieldnotes");
    expect(document.documentElement.dataset.agentbenchColorMode).toBe("light");
    expect(window.localStorage.getItem("agentbench.workspace.theme.v1")).toBe("fieldnotes");
    fireEvent.click(screen.getByRole("button", { name: "紧凑" }));
    await waitFor(() => expect(window.localStorage.getItem("agentbench.workspace.density.v1")).toBe("compact"));
    fireEvent.click(screen.getByRole("button", { name: /数据与诊断/ }));
    expect(screen.getByRole("heading", { name: "备份与迁移" })).toBeVisible();
    expect(screen.getByText("浅色专业工具")).not.toBeVisible();
    expect(window.location.hash).toBe("#/settings");
  });
});
