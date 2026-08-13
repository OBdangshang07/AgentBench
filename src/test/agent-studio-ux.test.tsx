import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AgentStudio from "../v4/AgentStudio";
import type { AgentSession, AgentSessionDetail, ApprovalRequest } from "../v4/types";

const terminalHarness = vi.hoisted(() => ({
  onData: null as ((data: string) => void) | null,
}));

const eventStreamHarness = {
  current: null as { onmessage: ((event: MessageEvent) => void) | null } | null,
};

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
  skill_pack_id: null,
  skill_pack_name: null,
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
  message_count: 0,
  messages_truncated: false,
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
  let terminalSequence = 0;
  const liveTerminals: Array<{ id: string; title: string; shell: string; running: boolean; cursor: number; chunks: Array<{ data: string }> }> = [];
  let browserSequence = 1;
  let browserPages = [{ id: "page-1", title: "Example", url: "https://example.com", type: "page" }];
  const browserStatus = () => ({
    installed: true,
    running: true,
    executable: "msedge.exe",
    engine: "chromium",
    profile_path: "D:/AgentBench/browser",
    page_count: browserPages.length,
    pages: browserPages,
    manual_takeover: true,
  });
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.0" });
    if (url.endsWith("/sessions")) return json([currentSession]);
    if (url.endsWith("/sessions/session-1") && init?.method === "PATCH") return json({ ...currentDetail, ...JSON.parse(String(init.body)) });
    if (url.includes("/sessions/session-1?message_limit=")) return json(currentDetail);
    if (url.endsWith("/sessions/session-1/turns") && init?.method === "POST") return json({ id: "queued-turn-new", status: "queued", queued_behind_active: true }, 202);
    if (url.includes("/sessions/session-1/turns/") && init?.method === "DELETE") return json({ ...currentDetail, removed_turn_id: "turn-2" });
    if (url.endsWith("/sessions/session-1/terminals") && init?.method === "POST") {
      terminalSequence += 1;
      const terminal = { id: `terminal-${terminalSequence}`, title: `PowerShell ${terminalSequence}`, shell: "powershell.exe", running: true, cursor: 0, chunks: [] };
      liveTerminals.push(terminal);
      return json(terminal, 201);
    }
    if (url.endsWith("/sessions/session-1/terminals") && !init?.method) return json(liveTerminals);
    if (url.includes("/sessions/session-1/terminals/") && url.endsWith("/input")) {
      const id = url.split("/terminals/")[1].split("/")[0];
      return json({ id, running: true, cursor: 0, chunks: [] });
    }
    if (url.includes("/sessions/session-1/terminals/") && url.includes("?after=")) {
      const id = url.split("/terminals/")[1].split("?")[0];
      return json({ id, running: true, cursor: 0, chunks: [] });
    }
    if (url.includes("/sessions/session-1/terminals/") && init?.method === "DELETE") {
      const id = url.split("/terminals/")[1].split("?")[0];
      const index = liveTerminals.findIndex((item) => item.id === id);
      if (index >= 0) liveTerminals.splice(index, 1);
      return json({ id, running: false });
    }
    if (url.includes("/approvals/") && url.endsWith("/decision")) return json({ status: "approved" });
    if (url.endsWith("/projects")) return json([project]);
    if (url.endsWith("/runners")) return json(runners);
    if (url.endsWith("/models")) return json(models);
    if (url.endsWith("/browser/status")) return json(browserStatus());
    if (url.endsWith("/browser/launch")) return json(browserStatus());
    if (url.endsWith("/browser/pages") && init?.method === "POST") {
      browserSequence += 1;
      const page = { id: `page-${browserSequence}`, title: `New tab ${browserSequence}`, url: "about:blank", type: "page" };
      browserPages = [...browserPages, page];
      return json(page);
    }
    if (url.includes("/browser/pages/") && init?.method === "DELETE") {
      const id = url.split("/browser/pages/")[1];
      browserPages = browserPages.filter((item) => item.id !== id);
      return json({ pages: browserPages });
    }
    if (url.includes("/browser/snapshot?")) {
      const pageId = new URL(url, "http://localhost").searchParams.get("page_id");
      const page = browserPages.find((item) => item.id === pageId) ?? browserPages[0];
      return json({ title: page?.title ?? "", url: page?.url ?? "about:blank", text: "Example", links: [], controls: [] });
    }
    if (url.includes("/browser/screenshots?")) return json({ id: "screenshot-1" });
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
    eventStreamHarness.current = null;
    window.localStorage.clear();
    vi.stubGlobal("EventSource", class {
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      close = vi.fn();
      constructor() {
        eventStreamHarness.current = this;
      }
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
    fireEvent.change(await screen.findByRole("textbox", { name: "搜索项目文件" }), { target: { value: "read" } });

    expect(await screen.findByText("README.md")).toBeInTheDocument();
    expect(screen.getByText("docs/README.md")).toBeInTheDocument();
    expect(screen.getByText(/已扫描 86 项/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("files/search?query=read"))).toBe(true);

    fireEvent.keyDown(screen.getByRole("separator", { name: "调整导航侧栏宽度" }), { key: "ArrowRight" });
    expect(container.querySelector(".v4-studio-workbench")).toHaveStyle({ "--studio-left": "302px" });

    fireEvent.click(screen.getByRole("button", { name: "收起导航侧栏" }));

    const workbench = container.querySelector(".v4-studio-workbench");
    expect(workbench).toHaveClass("left-collapsed", "right-collapsed", "dock-collapsed");
    await waitFor(() => expect(JSON.parse(window.localStorage.getItem("agentbench.studio.layout.v2") ?? "{}")).toMatchObject({
      left: false,
      right: false,
      dock: false,
      dockExpanded: false,
      leftWidth: 302,
      rightWidth: 520,
      dockHeight: 246,
    }));
  });

  it("filters custom Agent and model menus and applies a selected option", async () => {
    const fetchMock = installApiMock();
    renderStudio();

    fireEvent.click(await screen.findAllByRole("button", { name: "打开运行配置" }).then((items) => items[0]));
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

    fireEvent.click(screen.getAllByRole("button", { name: "打开运行配置" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "会话访问权限" }));
    fireEvent.click(screen.getByRole("option", { name: /完全访问/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith("/sessions/session-1") && init?.method === "PATCH" && String(init.body).includes("permission_profile"))).toBe(true));
    await waitFor(() => expect(screen.getByRole("button", { name: "思考强度" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "思考强度" }));
    fireEvent.click(screen.getByRole("option", { name: /高.*复杂任务/ }));
    expect(screen.getByRole("button", { name: /附件/ })).toBeInTheDocument();
    expect(document.querySelector(".v5-runtime-config-popover > footer")).toHaveTextContent("2,000 Tokens");
    expect(screen.getByRole("button", { name: /交互终端/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /活动详情/ })).toBeInTheDocument();
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
    const operations = container.querySelector(".v4-process-operations");
    expect(operations).not.toHaveAttribute("open");
    expect(operations).toHaveTextContent("1 个工具");
    expect(processList).toHaveTextContent("正在读取 package.json 以确认版本。");
    expect(processList).toHaveTextContent("工具完成 · read_file");
    expect(processList).not.toHaveTextContent("Agent 产生新的可验证进度");
    expect(container.querySelector(".v4-inline-activity > footer")).toHaveTextContent("5 条");
  });

  it("stops following new events as soon as the user scrolls upward", async () => {
    installApiMock({
      ...detail,
      events: [
        { id: 1, session_id: session.id, turn_id: "turn-1", seq: 1, event_type: "turn.started", visibility: "recording_safe", payload: {}, created_at: now },
      ],
    }, session);
    const { container } = renderStudio();

    expect(await screen.findByText("Agent 执行过程")).toBeInTheDocument();
    const scroller = container.querySelector<HTMLElement>(".v4-conversation-scroll");
    expect(scroller).not.toBeNull();
    Object.defineProperties(scroller!, {
      scrollHeight: { configurable: true, value: 1_000 },
      clientHeight: { configurable: true, value: 400 },
    });
    scroller!.scrollTop = 600;
    fireEvent.scroll(scroller!);
    scroller!.scrollTop = 599;
    fireEvent.scroll(scroller!);

    expect(screen.getByRole("button", { name: "返回最新内容" })).toBeInTheDocument();
    act(() => {
      eventStreamHarness.current?.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({
          id: 2,
          session_id: session.id,
          turn_id: "turn-1",
          seq: 2,
          event_type: "live.message",
          visibility: "recording_safe",
          payload: { stream_id: "message-2", text: "新的公开进度", status: "completed" },
          created_at: now,
        }),
      }));
    });

    expect(await screen.findByText("新的公开进度")).toBeInTheDocument();
    expect(scroller!.scrollTop).toBe(599);
    fireEvent.click(screen.getByRole("button", { name: "返回最新内容" }));
    expect(scroller!.scrollTop).toBe(1_000);
    expect(screen.queryByRole("button", { name: "返回最新内容" })).not.toBeInTheDocument();
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

  it("keeps three independent terminal tabs and closes only the selected process", async () => {
    const standardSession: AgentSession = { ...session, permission_profile: "standard" };
    const fetchMock = installApiMock(
      { ...detail, ...standardSession, permission_profile: "standard" },
      standardSession,
    );
    renderStudio();

    fireEvent.click(await screen.findByRole("button", { name: /交互终端/ }));
    expect(await screen.findByText("PowerShell 1")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("新建终端"));
    expect(await screen.findByText("PowerShell 2")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("新建终端"));
    expect(await screen.findByText("PowerShell 3")).toBeInTheDocument();
    expect(screen.getByTitle("新建终端")).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "关闭终端 PowerShell 2" }));
    await waitFor(() => expect(screen.queryByText("PowerShell 2")).not.toBeInTheDocument());
    expect(screen.getByText("PowerShell 1")).toBeInTheDocument();
    expect(screen.getByText("PowerShell 3")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input, init]) =>
      String(input).endsWith("/terminals/terminal-2") && init?.method === "DELETE"
    )).toBe(true);
  });

  it("creates, switches and closes real visible-browser tabs", async () => {
    const fetchMock = installApiMock();
    renderStudio();

    fireEvent.click(await screen.findByRole("button", { name: /浏览器/ }));
    expect(await screen.findByText("Example")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("新建浏览器标签"));
    expect((await screen.findAllByText("New tab 2")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Example"));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) =>
      String(input).includes("/browser/snapshot?page_id=page-1")
    )).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "关闭浏览器标签 Example" }));
    await waitFor(() => expect(screen.queryByText("Example")).not.toBeInTheDocument());
    expect(screen.getAllByText("New tab 2").length).toBeGreaterThan(0);
    expect(fetchMock.mock.calls.some(([input, init]) =>
      String(input).endsWith("/browser/pages/page-1") && init?.method === "DELETE"
    )).toBe(true);
  });

  it("restores session drafts, adds @file context and manages follow-up instructions", async () => {
    const runningSession: AgentSession = { ...session, status: "running" };
    const queuedTurn = {
      id: "turn-2",
      session_id: session.id,
      turn_no: 2,
      status: "queued",
      user_message: "稍后检查发布说明",
      final_answer: null,
      tokens_input: 0,
      tokens_output: 0,
      cost_usd: 0,
      duration_ms: 0,
      steps: 0,
      error_code: null,
      error_message: null,
      created_at: now,
      started_at: null,
      completed_at: null,
    };
    const runningDetail: AgentSessionDetail = {
      ...detail,
      ...runningSession,
      turns: [queuedTurn],
      messages: [{ id: "queued-message", turn_id: queuedTurn.id, role: "user", content: queuedTurn.user_message, metadata: {}, created_at: now }],
      message_count: 1,
    };
    window.localStorage.setItem("agentbench.studio.draft.v1.session-1", JSON.stringify({
      message: "继续审查 @read",
      context_files: ["src/main.ts"],
    }));
    const fetchMock = installApiMock(runningDetail, runningSession);
    renderStudio();

    const composer = await screen.findByPlaceholderText(/输入后续要求/);
    expect(composer).toHaveValue("继续审查 @read");
    expect(screen.getByText("src/main.ts")).toBeInTheDocument();
    expect(await screen.findByText("README.md")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /README\.md/ }));
    expect(screen.getByText("docs/README.md")).toBeInTheDocument();
    expect(screen.getByText(/后续指令队列/)).toBeInTheDocument();
    expect(screen.getByText("稍后检查发布说明")).toBeInTheDocument();

    fireEvent.change(composer, { target: { value: "排队执行最终检查" } });
    fireEvent.click(screen.getByRole("button", { name: "加入后续指令队列" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith("/sessions/session-1/turns") && init?.method === "POST")).toBe(true));
    await waitFor(() => expect(window.localStorage.getItem("agentbench.studio.draft.v1.session-1")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: /移除排队指令/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => String(input).includes("/sessions/session-1/turns/turn-2") && init?.method === "DELETE")).toBe(true));
  });
});
