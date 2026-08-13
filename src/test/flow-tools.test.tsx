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

const flowTemplates = [
  {
    id: "single-delivery",
    name: "单 Agent 交付",
    description: "从执行到人工验收",
    category: "DELIVERY",
    settings: { max_retries: 1, max_concurrency: 1 },
    nodes: [{ id: "worker", node_type: "agent", name: "执行", x: 60, y: 80, config: { prompt: "完成任务" } }],
    edges: [],
  },
  {
    id: "parallel-review",
    name: "并行复核",
    description: "两个 Agent 独立检查后汇总",
    category: "REVIEW",
    settings: { max_retries: 2, max_concurrency: 3 },
    nodes: [
      { id: "work", node_type: "agent", name: "实现", x: 40, y: 80, config: { prompt: "实现" } },
      { id: "review", node_type: "agent", name: "复核", x: 330, y: 80, config: { prompt: "复核" } },
    ],
    edges: [{ source: "work", target: "review" }],
  },
];

afterEach(() => vi.restoreAllMocks());

describe("real Flow and tool management workbenches", () => {
  it("creates a Flow from the selected template instead of a static default", async () => {
    const created = { ...flow, id: "flow-created", name: "并行发布检查" };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.0" });
      if (url.endsWith("/flow-templates")) return json(flowTemplates);
      if (url.endsWith("/flows") && init?.method === "POST") return json(created, 201);
      if (url.endsWith("/flows/flow-1")) return json(flow);
      if (url.endsWith("/flows")) return json([flow]);
      if (url.endsWith("/projects")) return json([{ id: "project-1", name: "AgentBench" }]);
      if (url.endsWith("/mcp-servers")) return json([]);
      return json([]);
    });
    render(<MemoryRouter><AgentFlow /></MemoryRouter>);

    fireEvent.click(await screen.findByTitle("新建工作流"));
    fireEvent.click(await screen.findByRole("button", { name: /并行复核/ }));
    fireEvent.change(screen.getByPlaceholderText("例如：版本发布前复核"), { target: { value: "并行发布检查" } });
    fireEvent.click(screen.getByRole("button", { name: /使用模板创建/ }));

    await waitFor(() => {
      const request = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith("/flows") && init?.method === "POST");
      expect(request).toBeDefined();
      const body = JSON.parse(String(request?.[1]?.body));
      expect(body.settings).toMatchObject({ max_retries: 2, max_concurrency: 3 });
      expect(body.nodes).toHaveLength(2);
      expect(body.edges).toEqual(flowTemplates[1].edges);
    });
  });

  it("connects node ports with a default structured binding", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.0" });
      if (url.endsWith("/flow-templates")) return json(flowTemplates);
      if (url.endsWith("/flows/flow-1") && init?.method === "PATCH") return json(flow);
      if (url.endsWith("/flows/flow-1")) return json(flow);
      if (url.endsWith("/flows")) return json([flow]);
      if (url.endsWith("/projects")) return json([{ id: "project-1", name: "AgentBench" }]);
      if (url.endsWith("/mcp-servers")) return json([]);
      return json([]);
    });
    render(<MemoryRouter><AgentFlow /></MemoryRouter>);

    expect(await screen.findByText(/2 NODES/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /条件分支/ }));
    fireEvent.pointerDown(screen.getByRole("button", { name: "从 Plan 创建连接" }));
    fireEvent.pointerUp(screen.getByRole("button", { name: "连接到 条件分支" }));
    fireEvent.click(screen.getByRole("button", { name: /保存/ }));

    await waitFor(() => {
      const request = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith("/flows/flow-1") && init?.method === "PATCH");
      const body = JSON.parse(String(request?.[1]?.body));
      const target = body.nodes.find((node: { name: string }) => node.name === "条件分支");
      expect(body.edges).toEqual(expect.arrayContaining([expect.objectContaining({ source: "node-a", target: target.id })]));
      expect(target.config.input_bindings).toEqual([{ source_node_id: "node-a", path: "summary", target: "source" }]);
    });
  });

  it("persists node failure controls and starts an isolated node test", async () => {
    let tested = false;
    const nodeTestRun = {
      id: "run-node-test", graph_id: "flow-1", version_no: 2, status: "completed", dry_run: false,
      retry_node_id: "node-a", error_message: "", result: { node_test: true }, usage: {},
      started_at: now, completed_at: now, created_at: now,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.0" });
      if (url.endsWith("/flow-templates")) return json(flowTemplates);
      if (url.endsWith("/flows/flow-1/nodes/node-a/test") && init?.method === "POST") { tested = true; return json(nodeTestRun, 202); }
      if (url.includes("/flows/flow-1/runs")) return json(tested ? [nodeTestRun] : []);
      if (url.endsWith("/flows/flow-1") && init?.method === "PATCH") return json(flow);
      if (url.endsWith("/flows/flow-1")) return json(flow);
      if (url.endsWith("/flows")) return json([flow]);
      if (url.endsWith("/projects")) return json([{ id: "project-1", name: "AgentBench" }]);
      if (url.endsWith("/mcp-servers")) return json([]);
      return json([]);
    });
    render(<MemoryRouter><AgentFlow /></MemoryRouter>);

    expect(await screen.findByText(/2 NODES/)).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("终止整个 Flow"), { target: { value: "continue" } });
    fireEvent.change(screen.getByDisplayValue("重试 1 次"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /测试节点/ }));

    await waitFor(() => expect(tested).toBe(true));
    const saveRequest = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith("/flows/flow-1") && init?.method === "PATCH");
    const saved = JSON.parse(String(saveRequest?.[1]?.body)).nodes.find((node: { id: string }) => node.id === "node-a");
    expect(saved.config).toMatchObject({ error_strategy: "continue", retry_count: 3 });
    expect(await screen.findByText("单节点测试")).toBeInTheDocument();
  });

  it("adds a Flow node and persists the edited graph", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.0" });
      if (url.endsWith("/flows/flow-1") && init?.method === "PATCH") return json(flow);
      if (url.endsWith("/flows/flow-1")) return json(flow);
      if (url.endsWith("/flows")) return json([flow]);
      if (url.endsWith("/projects")) return json([{ id: "project-1", name: "AgentBench" }]);
      if (url.endsWith("/mcp-servers")) return json([]);
      return json([]);
    });
    render(<MemoryRouter><AgentFlow /></MemoryRouter>);

    expect((await screen.findAllByText("Release flow")).length).toBeGreaterThan(0);
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
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.0" });
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
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.0" });
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

  it("builds MCP arguments from nested JSON Schema fields and keeps advanced JSON in sync", async () => {
    const server = {
      id: "mcp-schema",
      name: "Issue MCP",
      transport: "stdio",
      command: "issue-mcp",
      args: [],
      url: null,
      env_keys: [],
      tools: [{
        name: "create_issue",
        description: "Create an issue",
        inputSchema: {
          type: "object",
          required: ["title"],
          properties: {
            title: { type: "string", title: "Issue title" },
            priority: { type: "string", title: "Priority", enum: ["low", "high"] },
            estimate: { type: "integer", title: "Estimate" },
            notify: { type: "boolean", title: "Notify owner" },
            labels: { type: "array", title: "Labels", items: { type: "string" } },
            metadata: {
              type: "object",
              title: "Metadata",
              properties: { owner: { type: "string", title: "Owner" } },
            },
          },
        },
      }],
      health_status: "online",
      last_error: null,
      last_checked_at: now,
      enabled: true,
      builtin: false,
      created_at: now,
      updated_at: now,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.0" });
      if (url.endsWith("/mcp-servers/mcp-schema/tools/call") && init?.method === "POST") return json({ ok: true });
      if (url.endsWith("/mcp-servers")) return json([server]);
      if (url.endsWith("/tools/status") || url.endsWith("/skill-packs") || url.endsWith("/runners") || url.endsWith("/runtime-profiles")) return json([]);
      if (url.endsWith("/browser/status")) return json({ installed: true, running: false, executable: "msedge.exe", engine: "Chromium", profile_path: "profile", page_count: 0, pages: [], manual_takeover: false });
      return json([]);
    });
    render(<MemoryRouter><ToolsMcp /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /测试工具/ }));
    fireEvent.change(screen.getByLabelText(/Issue title/), { target: { value: "Ship V5" } });
    fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "high" } });
    fireEvent.change(screen.getByLabelText("Estimate"), { target: { value: "8" } });
    fireEvent.click(screen.getByLabelText(/Notify owner/));
    fireEvent.change(screen.getByLabelText("Labels"), { target: { value: '["release","desktop"]' } });
    fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "agentbench" } });
    fireEvent.click(screen.getByRole("button", { name: /调用工具/ }));

    await waitFor(() => {
      const request = fetchMock.mock.calls.find(([input, init]) =>
        String(input).endsWith("/mcp-servers/mcp-schema/tools/call") && init?.method === "POST"
      );
      expect(JSON.parse(String(request?.[1]?.body))).toEqual({
        tool_name: "create_issue",
        arguments: {
          title: "Ship V5",
          priority: "high",
          estimate: 8,
          notify: true,
          labels: ["release", "desktop"],
          metadata: { owner: "agentbench" },
        },
      });
    });
  });
});
