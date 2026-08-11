import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import AgentFlow from "../v4/AgentFlow";
import ToolsMcp from "../v4/ToolsMcp";

const now = "2026-08-10T10:00:00.000Z";

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

const flow = {
  id: "flow-1",
  project_id: "project-1",
  project_name: "AgentBench",
  name: "Release flow",
  description: "",
  status: "draft",
  node_count: 2,
  settings: { max_retries: 1, max_concurrency: 2, max_runtime_seconds: 2700, max_cost_usd: 3, max_tokens: 500000 },
  nodes: [
    { id: "node-a", node_type: "agent", name: "Plan", position_x: 50, position_y: 80, config: { prompt: "Plan" }, status: "pending", attempts: 0, error_message: null, output: {}, session_id: null },
    { id: "node-b", node_type: "approval", name: "Review", position_x: 350, position_y: 80, config: {}, status: "pending", attempts: 0, error_message: null, output: {}, session_id: null },
  ],
  edges: [{ id: "edge-1", source_node_id: "node-a", target_node_id: "node-b", edge_type: "default", condition: {} }],
  created_at: now,
  updated_at: now,
};

afterEach(() => vi.restoreAllMocks());

describe("real Flow and tool management workbenches", () => {
  it("adds a Flow node and persists the edited graph", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.0.0" });
      if (url.endsWith("/flows/flow-1") && init?.method === "PATCH") return json(flow);
      if (url.endsWith("/flows/flow-1")) return json(flow);
      if (url.endsWith("/flows")) return json([flow]);
      if (url.endsWith("/projects")) return json([{ id: "project-1", name: "AgentBench" }]);
      if (url.endsWith("/mcp-servers")) return json([]);
      return json([]);
    });
    render(<MemoryRouter><AgentFlow /></MemoryRouter>);

    expect(await screen.findByText("Release flow")).toBeInTheDocument();
    expect(await screen.findByText(/2 NODES/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /条件分支/ }));
    expect(await screen.findByText(/3 NODES/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /保存/ }));

    await waitFor(() => {
      const request = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith("/flows/flow-1") && init?.method === "PATCH");
      expect(request).toBeDefined();
      expect(JSON.parse(String(request?.[1]?.body)).nodes).toHaveLength(3);
    });
  });

  it("validates, dry-runs, and locally undoes Flow edits without invoking an Agent", async () => {
    const validation = {
      valid: true,
      errors: [],
      warnings: [],
      roots: ["node-a"],
      topological_order: ["node-a", "node-b"],
      levels: [["node-a"], ["node-b"]],
      node_count: 2,
      edge_count: 1,
    };
    const dryRun = {
      id: "run-1",
      graph_id: "flow-1",
      version_no: 1,
      status: "completed",
      dry_run: true,
      retry_node_id: null,
      error_message: "",
      result: { validation, steps: [] },
      usage: {},
      started_at: now,
      completed_at: now,
      created_at: now,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.0.0" });
      if (url.endsWith("/flows/validate") && init?.method === "POST") return json(validation);
      if (url.endsWith("/flows/flow-1/dry-run") && init?.method === "POST") return json(dryRun, 201);
      if (url.includes("/flows/flow-1/runs")) return json([]);
      if (url.endsWith("/flows/flow-1/versions")) return json([]);
      if (url.endsWith("/flows/flow-1")) return json(flow);
      if (url.endsWith("/flows")) return json([flow]);
      if (url.endsWith("/projects")) return json([{ id: "project-1", name: "AgentBench" }]);
      if (url.endsWith("/mcp-servers")) return json([]);
      return json([]);
    });
    render(<MemoryRouter><AgentFlow /></MemoryRouter>);

    expect(await screen.findByText(/2 NODES/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /条件分支/ }));
    expect(await screen.findByText(/3 NODES/)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("撤销 Ctrl+Z"));
    expect(await screen.findByText(/2 NODES/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dry Run" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith("/flows/validate") && init?.method === "POST")).toBe(true);
      expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith("/flows/flow-1/dry-run") && init?.method === "POST")).toBe(true);
    });
  });

  it("edits persisted MCP servers and exposes the real browser console", async () => {
    const server = { id: "mcp-1", name: "Playwright MCP", transport: "stdio", command: "npx", args: ["playwright"], url: null, env_keys: ["API_KEY"], tools: [], health_status: "unknown", last_error: null, last_checked_at: null, enabled: true, builtin: false, created_at: now, updated_at: now };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.0.0" });
      if (url.endsWith("/mcp-servers/mcp-1") && init?.method === "PATCH") return json(server);
      if (url.endsWith("/mcp-servers")) return json([server]);
      if (url.endsWith("/tools/status")) return json([
        { id: "filesystem", name: "Filesystem", status: "online", detail: "Real filesystem" },
        { id: "browser", name: "Browser", status: "approval", detail: "Microsoft Edge detected" },
      ]);
      if (url.endsWith("/skill-packs")) return json([{ id: "skill-1", name: "代码审查", description: "真实能力包", content: "Review", tools: ["search"], permission_profile: "readonly", builtin: true, created_at: now, updated_at: now }]);
      if (url.endsWith("/browser/status")) return json({ installed: true, running: false, executable: "msedge.exe", engine: "Microsoft Edge / Chromium CDP", profile_path: "profile", page_count: 0, pages: [], manual_takeover: false });
      if (url.endsWith("/runners")) return json([]);
      return json([]);
    });
    render(<MemoryRouter><ToolsMcp /></MemoryRouter>);

    expect(await screen.findByText("Playwright MCP")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "配置" }));
    expect(screen.getByText("配置 MCP Server")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "Browser MCP" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 Server" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith("/mcp-servers/mcp-1") && init?.method === "PATCH")).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "打开浏览器" }));
    expect(screen.getByText("内置浏览器控制台")).toBeInTheDocument();
    expect(screen.getByText(/独立配置文件/)).toBeInTheDocument();
  });
});
