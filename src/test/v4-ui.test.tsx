import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { useWorkspaceUx, WorkspaceUxProvider } from "../components/WorkspaceUx";

const systemStatus = {
  version: "5.1.0",
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
  active_tasks_list: [{ id: "task-live", title: "完善 Studio", status: "running", priority: "high", session_id: "session-live", updated_at: "2026-08-11T09:00:00Z", project_id: "project-1", project_name: "AgentBench" }],
  active_flows_list: [],
  activity: [{ id: "task:1", source_type: "task", source_id: "task-live", source_title: "完善 Studio", project_id: "project-1", project_name: "AgentBench", event_type: "task.running", summary: "任务开始执行", status: "running", payload: {}, href: "/tasks/task-live", created_at: "2026-08-11T09:00:00Z" }],
  pending_approvals_list: [],
  recent_projects: [],
  recent_failures: [],
  runtime_health: { models_enabled: 1, runners_enabled: 1, mcp_enabled: 0, mcp_healthy: 0, mcp_error: 0 },
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

const task = {
  id: "task-1",
  project_id: "project-1",
  project_name: "AgentBench",
  title: "完善任务中心",
  description: "实现独立详情与批量操作",
  status: "backlog" as const,
  priority: "high" as const,
  runner_id: "runner-1",
  runner_name: "Codex",
  model_id: "model-1",
  model_name: "GPT-5.6 Sol",
  session_id: null,
  due_at: null,
  tags: ["frontend"],
  depends_on: [],
  acceptance_criteria: [
    { text: "详情页可以直接打开", completed: false },
    { text: "活动记录按时间展示", completed: true },
  ],
  result_summary: "任务界面已完成并通过测试。",
  retry_of: null,
  archived: false,
  cancelled_at: null,
  created_at: "2026-08-11T08:00:00Z",
  updated_at: "2026-08-11T09:00:00Z",
  completed_at: null,
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

function NotificationSeed() {
  const ux = useWorkspaceUx();
  return <button type="button" onClick={() => ux.notify({ title: "任务已完成", message: "结果已保存到本地" })}>生成通知</button>;
}

describe("AgentBench V4 application shell", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    delete document.documentElement.dataset.agentbenchDensity;
  });

  it("renders the real Agent operations navigation and control center", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.1.0" });
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
    expect(screen.getByText("统一活动流")).toBeInTheDocument();
    expect(screen.getByText("任务开始执行")).toBeInTheDocument();
    expect(screen.getByText("当前工作队列")).toBeInTheDocument();
  });

  it("creates an authorized local project through the V4 form", async () => {
    let posted: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.1.0" });
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

  it("persists workspace density, collapses navigation, runs commands and keeps notifications", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.1.0" });
      if (url.endsWith("/system/status")) return json(systemStatus);
      if (url.endsWith("/studio/dashboard")) return json(studioDashboard);
      if (url.endsWith("/projects")) return json([{ id: "project-1", name: "AgentBench", root_path: "D:/AgentBench" }]);
      return json([]);
    });

    render(<WorkspaceUxProvider><NotificationSeed /><MemoryRouter initialEntries={["/"]}><App /></MemoryRouter></WorkspaceUxProvider>);

    const shell = (await screen.findByRole("heading", { name: "控制中心" })).closest(".v4-shell");
    fireEvent.click(screen.getByRole("button", { name: "收起主导航" }));
    expect(shell).toHaveClass("sidebar-collapsed");
    expect(window.localStorage.getItem("agentbench.workspace.sidebar.v1")).toBe("collapsed");

    fireEvent.click(screen.getByTitle("切换为紧凑密度"));
    await waitFor(() => expect(document.documentElement.dataset.agentbenchDensity).toBe("compact"));
    expect(window.localStorage.getItem("agentbench.workspace.density.v1")).toBe("compact");

    fireEvent.click(screen.getByRole("button", { name: "生成通知" }));
    fireEvent.click(screen.getByRole("button", { name: /通知中心，1 条未读/ }));
    expect(screen.getByRole("complementary", { name: "通知中心" })).toHaveTextContent("任务已完成");

    fireEvent.click(screen.getByRole("button", { name: /搜索项目、会话或运行命令/ }));
    const palette = document.querySelector(".v4-palette");
    expect(palette).not.toBeNull();
    expect(within(palette as HTMLElement).getByText("新建 Agent 会话")).toBeInTheDocument();
    expect(within(palette as HTMLElement).getByText("新建 Agent Flow")).toBeInTheDocument();
  });

  it("opens the real task detail route and updates acceptance evidence", async () => {
    let acceptanceUpdate: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.1.0" });
      if (url.endsWith("/system/status")) return json(systemStatus);
      if (url.endsWith("/studio/dashboard")) return json(studioDashboard);
      if (url.endsWith("/projects")) return json([{ id: "project-1", name: "AgentBench", root_path: "D:/AgentBench" }]);
      if (url.endsWith("/tasks/task-1") && init?.method === "PATCH") {
        acceptanceUpdate = JSON.parse(String(init.body));
        return json({ ...task, ...(acceptanceUpdate as object) });
      }
      if (url.endsWith("/tasks/task-1")) return json({
        ...task,
        dependencies: [],
        events: [
          { id: 1, task_id: "task-1", event_type: "task.created", payload: {}, created_at: task.created_at },
          { id: 2, task_id: "task-1", event_type: "task.completed", payload: {}, created_at: task.updated_at },
        ],
      });
      return json([]);
    });

    render(<MemoryRouter initialEntries={["/tasks/task-1"]}><App /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "完善任务中心" })).toBeInTheDocument();
    expect(screen.getByText("活动时间线")).toBeInTheDocument();
    expect(screen.getByText("Agent 结果摘要")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /详情页可以直接打开/ }));
    await waitFor(() => expect(acceptanceUpdate).not.toBeNull());
    expect(acceptanceUpdate).toMatchObject({
      acceptance_criteria: [
        { text: "详情页可以直接打开", completed: true },
        { text: "活动记录按时间展示", completed: true },
      ],
    });
  });

  it("switches task views and sends one bulk action for selected tasks", async () => {
    let bulkPayload: Record<string, unknown> | null = null;
    const secondTask = { ...task, id: "task-2", title: "验证批量操作", priority: "normal" as const };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.1.0" });
      if (url.endsWith("/system/status")) return json(systemStatus);
      if (url.endsWith("/studio/dashboard")) return json(studioDashboard);
      if (url.endsWith("/projects")) return json([{ id: "project-1", name: "AgentBench", root_path: "D:/AgentBench" }]);
      if (url.endsWith("/runners")) return json([runner]);
      if (url.endsWith("/models")) return json([model]);
      if (url.endsWith("/tasks/bulk") && init?.method === "POST") {
        bulkPayload = JSON.parse(String(init.body));
        return json({ requested: 2, updated: [task, secondTask], errors: [] });
      }
      if (url.endsWith("/tasks")) return json([task, secondTask]);
      return json([]);
    });

    render(<MemoryRouter initialEntries={["/tasks"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "任务中心" })).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("列表视图"));
    expect(screen.getByText("验证批量操作")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "选择 完善任务中心" }));
    fireEvent.click(screen.getByRole("button", { name: "选择 验证批量操作" }));
    const bulkbar = document.querySelector(".v5-task-bulkbar") as HTMLElement;
    fireEvent.click(within(bulkbar).getByRole("button", { name: "复制" }));
    await waitFor(() => expect(bulkPayload).not.toBeNull());
    expect(bulkPayload).toMatchObject({ task_ids: ["task-1", "task-2"], action: "duplicate" });
  });
});
