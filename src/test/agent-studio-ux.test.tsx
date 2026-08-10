import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AgentStudio from "../v4/AgentStudio";
import type { AgentSession, AgentSessionDetail, ApprovalRequest } from "../v4/types";

const terminalHarness = vi.hoisted(() => ({
  onData: null as ((data: string) => void) | null,
}));

vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    cols = 120;
    rows = 30;
    loadAddon() {}
    open() {}
    write() {}
    reset() {}
    dispose() {}
    onData(callback: (data: string) => void) {
      terminalHarness.onData = callback;
      return { dispose() {} };
    }
  },
}));

vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class {
    fit() {}
  },
}));

const now = "2026-08-10T02:00:00.000Z";

const session: AgentSession = {
  id: "session-1",
  project_id: "project-1",
  project_name: "AgentBench",
  title: "视觉体验巡查",
  runner_id: "runner-1",
  runner_name: "Codex",
  runner_type: "codex_cli",
  model_id: "model-1",
  model_name: "GPT-5.6 Sol",
  status: "completed",
  permission_profile: "workspace",
  reasoning_effort: "medium",
  native_session_id: null,
  workspace_path: "D:/AI_project/AI_test",
  summary: "",
  tokens_input: 1200,
  tokens_output: 800,
  cost_usd: 0.02,
  duration_ms: 42_000,
  turn_count: 1,
  pending_approvals: 0,
  archived: false,
  created_at: now,
  updated_at: now,
  started_at: now,
  completed_at: now,
};

const detail: AgentSessionDetail = {
  ...session,
  messages: [],
  events: [],
  approvals: [],
  turns: [],
  file_changes: [],
  artifacts: [],
};

const project = {
  id: "project-1",
  name: "AgentBench",
  description: "",
  default_runner_id: "runner-1",
  default_model_id: "model-1",
  permission_profile: "workspace",
  pinned: true,
  archived: false,
  root_path: "D:/AI_project/AI_test",
  branch: "codex/agentbench-4.0",
  session_count: 1,
  active_sessions: 0,
  pending_approvals: 0,
  created_at: now,
  updated_at: now,
  last_opened_at: now,
};

const runners = Array.from({ length: 7 }, (_, index) => ({
  id: `runner-${index + 1}`,
  name: index === 0 ? "Codex" : index === 1 ? "Reasonix" : `Agent ${index + 1}`,
  runner_type: index === 1 ? "reasonix_cli" : "codex_cli",
  executable: "agent",
  args: [],
  env: {},
  tools: [],
  limits: {},
  model_override_supported: true,
  enabled: true,
  builtin: true,
  capability: { installed: index !== 6, version: `1.${index}.0` },
  install: { supported: true, available: true },
}));

const models = Array.from({ length: 7 }, (_, index) => ({
  id: `model-${index + 1}`,
  name: index === 0 ? "GPT-5.6 Sol" : index === 1 ? "DeepSeek V4 Flash" : `Model ${index + 1}`,
  provider: index === 1 ? "deepseek-responses" : "codex-cli",
  model_name: index === 1 ? "deepseek-v4-flash" : `model-${index + 1}`,
  api_style: "responses",
  settings: {},
  input_price: 0,
  output_price: 0,
  enabled: true,
  builtin: true,
  has_secret: true,
}));

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

function installApiMock(
  currentDetail: AgentSessionDetail = detail,
  currentSession: AgentSession = session,
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "4.1.1" });
    if (url.endsWith("/sessions")) return json([currentSession]);
    if (url.endsWith("/sessions/session-1") && init?.method === "PATCH") return json({ ...currentDetail, ...JSON.parse(String(init.body)) });
    if (url.endsWith("/sessions/session-1")) return json(currentDetail);
    if (url.endsWith("/sessions/session-1/terminals") && init?.method === "POST") {
      return json({ id: "terminal-1", running: true, cursor: 0, chunks: [] }, 201);
    }
    if (url.includes("/sessions/session-1/terminals/terminal-1/input")) {
      return json({ id: "terminal-1", running: true, cursor: 0, chunks: [] });
    }
    if (url.includes("/sessions/session-1/terminals/terminal-1?")) {
      return json({ id: "terminal-1", running: true, cursor: 0, chunks: [] });
    }
    if (url.includes("/approvals/") && url.endsWith("/decision")) return json({ status: "approved" });
    if (url.endsWith("/projects")) return json([project]);
    if (url.endsWith("/runners")) return json(runners);
    if (url.endsWith("/models")) return json(models);
    if (url.includes("/projects/project-1/files/search?")) return json({
      project_id: "project-1",
      root_path: project.root_path,
      query: "read",
      entries: [{ name: "README.md", path: "docs/README.md", kind: "file", size: 1200, modified_ns: 1 }],
      scanned: 86,
      truncated: false,
    });
    if (url.includes("/projects/project-1/files?")) return json({ project_id: "project-1", root_path: project.root_path, path: ".", entries: [] });
    return json([]);
  });
}

function renderStudio() {
  return render(
    <MemoryRouter initialEntries={["/studio/session-1"]}>
      <Routes><Route path="/studio/:sessionId" element={<AgentStudio />} /></Routes>
    </MemoryRouter>,
  );
}

describe("Agent Studio visual workspace controls", () => {
  beforeEach(() => {
    terminalHarness.onData = null;
    window.localStorage.clear();
    vi.stubGlobal("EventSource", class {
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      close = vi.fn();
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("searches the real project tree and persists collapsible panels", async () => {
    const fetchMock = installApiMock();
    const { container } = renderStudio();

    expect((await screen.findAllByText("视觉体验巡查")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    fireEvent.change(screen.getByRole("textbox", { name: "搜索项目文件" }), { target: { value: "read" } });

    expect(await screen.findByText("README.md")).toBeInTheDocument();
    expect(screen.getByText("docs/README.md")).toBeInTheDocument();
    expect(screen.getByText(/已扫描 86 项/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("files/search?query=read"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "收起项目侧栏" }));
    fireEvent.click(screen.getByRole("button", { name: "收起会话侧栏" }));
    fireEvent.click(screen.getByRole("button", { name: "隐藏底部面板" }));

    const workbench = container.querySelector(".v4-studio-workbench");
    expect(workbench).toHaveClass("left-collapsed", "right-collapsed", "dock-collapsed");
    await waitFor(() => expect(JSON.parse(window.localStorage.getItem("agentbench.studio.layout.v1") ?? "{}")).toEqual({ left: false, right: false, dock: false }));
  });

  it("filters custom Agent and model menus and applies a selected option", async () => {
    const fetchMock = installApiMock();
    renderStudio();

    const agentPicker = await screen.findByRole("button", { name: "选择 Agent" });
    fireEvent.click(agentPicker);
    fireEvent.change(screen.getByPlaceholderText("搜索AGENT"), { target: { value: "Reasonix" } });
    fireEvent.click(screen.getByRole("option", { name: /Reasonix/ }));

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith("/sessions/session-1") && init?.method === "PATCH");
      expect(patch).toBeDefined();
      expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ runner_id: "runner-2" });
    });

    fireEvent.click(screen.getByRole("button", { name: "选择模型" }));
    fireEvent.change(screen.getByPlaceholderText("搜索MODEL"), { target: { value: "DeepSeek" } });
    expect(screen.getByRole("option", { name: /DeepSeek V4 Flash/ })).toBeInTheDocument();
  });

  it("keeps approval, runtime controls, quota and the real terminal discoverable", async () => {
    const approval: ApprovalRequest = {
      id: "approval-1",
      session_id: session.id,
      turn_id: "turn-1",
      request_type: "native_agent",
      status: "pending",
      title: "允许 Reasonix CLI 操作项目",
      description: "批准后本轮任务会自动继续。",
      risk_level: "medium",
      request: { runner_name: "Reasonix CLI" },
      decision: {},
      created_at: now,
      resolved_at: null,
    };
    const waitingSession = { ...session, status: "waiting_approval", pending_approvals: 1 };
    const fetchMock = installApiMock({ ...detail, ...waitingSession, approvals: [approval] }, waitingSession);
    renderStudio();

    expect(await screen.findByText("Agent 正在等待你的审批")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "仅允许一次" }).length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole("button", { name: "仅允许一次" })[0]);
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/approvals/approval-1/decision"))).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "会话访问权限" }));
    fireEvent.click(screen.getByRole("option", { name: /完全访问/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith("/sessions/session-1") && init?.method === "PATCH" && String(init.body).includes("permission_profile"))).toBe(true));
    await waitFor(() => expect(screen.getByRole("button", { name: "思考强度" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "思考强度" }));
    fireEvent.click(screen.getByRole("option", { name: /高.*复杂任务/ }));
    expect(screen.getByRole("button", { name: /附件/ })).toBeInTheDocument();
    expect(screen.getByText("2,000 Tokens")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /交互终端/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /活动日志/ })).toBeInTheDocument();
  });

  it("turns streamed model output into a readable and deduplicated process timeline", async () => {
    const processDetail: AgentSessionDetail = {
      ...detail,
      events: [
        { id: 1, session_id: session.id, turn_id: "turn-1", seq: 1, event_type: "turn.started", visibility: "recording_safe", payload: {}, created_at: now },
        { id: 2, session_id: session.id, turn_id: "turn-1", seq: 2, event_type: "live.message", visibility: "recording_safe", payload: { stream_id: "native-message-0", text: "正在读取", status: "streaming" }, created_at: now },
        { id: 3, session_id: session.id, turn_id: "turn-1", seq: 3, event_type: "live.message", visibility: "recording_safe", payload: { stream_id: "native-message-0", text: "正在读取 package.json 以确认版本。", status: "completed" }, created_at: now },
        { id: 4, session_id: session.id, turn_id: "turn-1", seq: 4, event_type: "live.tool", visibility: "recording_safe", payload: { tool_id: "call-1", tool: "read_file", status: "preparing" }, created_at: now },
        { id: 5, session_id: session.id, turn_id: "turn-1", seq: 5, event_type: "live.tool", visibility: "recording_safe", payload: { tool_id: "call-1", tool: "read_file", status: "completed", detail: '{"path":"package.json"}' }, created_at: now },
        { id: 6, session_id: session.id, turn_id: "turn-1", seq: 6, event_type: "live.activity", visibility: "recording_safe", payload: { kind: "activity", summary: "Agent 产生新的可验证进度" }, created_at: now },
        { id: 7, session_id: session.id, turn_id: "turn-1", seq: 7, event_type: "live.heartbeat", visibility: "recording_safe", payload: { elapsed_ms: 12_000, line_count: 91 }, created_at: now },
        { id: 8, session_id: session.id, turn_id: "turn-1", seq: 8, event_type: "usage.updated", visibility: "recording_safe", payload: { usage: { input_tokens: 120, output_tokens: 17 }, mode: "delta" }, created_at: now },
      ],
    };
    installApiMock(processDetail, session);
    const { container } = renderStudio();

    expect(await screen.findByText("Agent 执行过程")).toBeInTheDocument();
    const processList = container.querySelector(".v4-process-list");
    expect(processList).not.toBeNull();
    expect(processList?.querySelectorAll("article")).toHaveLength(3);
    expect(processList).toHaveTextContent("正在读取 package.json 以确认版本。");
    expect(processList).toHaveTextContent("工具完成 · read_file");
    expect(processList).not.toHaveTextContent("Agent 产生新的可验证进度");
    expect(container.querySelector(".v4-inline-activity > footer")).toHaveTextContent("5 条");
  });

  it("forwards direct xterm keyboard input to the interactive terminal in order", async () => {
    const standardSession: AgentSession = { ...session, permission_profile: "standard" };
    const standardDetail: AgentSessionDetail = {
      ...detail,
      ...standardSession,
      permission_profile: "standard",
    };
    const fetchMock = installApiMock(standardDetail, standardSession);
    renderStudio();

    fireEvent.click(await screen.findByRole("button", { name: /交互终端/ }));
    await waitFor(() => expect(terminalHarness.onData).not.toBeNull());
    terminalHarness.onData?.("Write-Output 'DIRECT_INPUT_OK'\r");

    await waitFor(() => {
      const write = fetchMock.mock.calls.find(([input]) =>
        String(input).includes("/sessions/session-1/terminals/terminal-1/input"),
      );
      expect(write).toBeDefined();
      expect(JSON.parse(String(write?.[1]?.body))).toEqual({
        data: "Write-Output 'DIRECT_INPUT_OK'\r",
      });
    });
  });
});
