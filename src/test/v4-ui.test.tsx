import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";

const systemStatus = {
  version: "5.0.0",
  data_dir: "C:/AgentBench",
  database: { path: "C:/AgentBench/agentbench.db", ready: true },
  docker: { installed: true, available: true, executable: "docker" },
  native_cli_enabled: true,
  settings: { default_concurrency: 2, default_max_runtime_seconds: 0 },
  runners: [{ id: "runner-1", name: "Codex", enabled: true, capability: { installed: true } }],
};

const studioDashboard = {
  project_count: 1,
  session_count: 2,
  active_sessions: 1,
  pending_approvals: 0,
  completed_tasks: 4,
  open_tasks: 2,
  total_tokens: 428_000,
  total_cost: 1.84,
  active_sessions_list: [],
  pending_approvals_list: [],
  recent_projects: [],
};

const runner = {
  id: "runner-1",
  name: "Codex",
  runner_type: "codex_cli",
  executable: "codex",
  args: [],
  env: {},
  tools: [],
  limits: {},
  model_override_supported: true,
  enabled: true,
  builtin: true,
  capability: { installed: true },
  install: { supported: true, available: true },
};

const model = {
  id: "model-1",
  name: "GPT-5.6 Sol",
  provider: "codex-cli",
  model_name: "gpt-5.6-sol",
  api_style: "mock",
  settings: {},
  input_price: 0,
  output_price: 0,
  enabled: true,
  builtin: true,
  has_secret: false,
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

describe("AgentBench V4 application shell", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders the real Agent operations navigation and control center", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.0.0" });
      if (url.endsWith("/system/status")) return json(systemStatus);
      if (url.endsWith("/studio/dashboard")) return json(studioDashboard);
      return json([]);
    });

    render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "控制中心" })).toBeInTheDocument();
    expect(screen.getByText("Agent Studio")).toBeInTheDocument();
    expect(screen.getByText("Agent Flow")).toBeInTheDocument();
    expect(screen.getByText("工具与 MCP")).toBeInTheDocument();
    expect(screen.getByText(/把所有 Agent 放进一个/)).toBeInTheDocument();
    expect(await screen.findByText(/42\.8万|428K/)).toBeInTheDocument();
  });

  it("creates an authorized local project through the V4 form", async () => {
    let posted: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.0.0" });
      if (url.endsWith("/system/status")) return json(systemStatus);
      if (url.endsWith("/studio/dashboard")) return json(studioDashboard);
      if (url.endsWith("/runners")) return json([runner]);
      if (url.endsWith("/models")) return json([model]);
      if (url.endsWith("/projects") && init?.method === "POST") {
        posted = JSON.parse(String(init.body));
        return json({ id: "project-1", ...posted }, 201);
      }
      if (url.endsWith("/projects")) return json([]);
      return json([]);
    });

    render(<MemoryRouter initialEntries={["/projects"]}><App /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /新建项目/ }));
    fireEvent.change(screen.getByLabelText("项目名称"), { target: { value: "Local Workbench" } });
    fireEvent.change(screen.getByLabelText(/项目根目录/), { target: { value: "D:\\Projects\\Workbench" } });
    fireEvent.click(screen.getByRole("button", { name: /创建并授权/ }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).toMatchObject({
      name: "Local Workbench",
      root_path: "D:\\Projects\\Workbench",
      default_runner_id: "runner-1",
      default_model_id: "model-1",
      permission_profile: "workspace",
    });
  });
});
