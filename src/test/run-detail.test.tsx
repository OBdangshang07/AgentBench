import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import RunDetailPage from "../pages/RunDetail";
import { WorkspaceUxProvider } from "../components/WorkspaceUx";
import type { RunDetail } from "../types";

function makeRun(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "run-1",
    experiment_id: "exp-1",
    test_case_id: "case-1",
    model_id: "model-1",
    runner_id: "runner-1",
    test_title: "NCRE 表格题",
    category: "ncre",
    model_name: "Mock Model",
    runner_name: "Mock Runner",
    lane: "unified",
    repetition: 1,
    status: "completed",
    score: 88,
    tokens_input: 100,
    tokens_output: 50,
    cost_usd: 0,
    cost_source: "unpriced",
    duration_ms: 12_000,
    steps: 4,
    attempt_count: 1,
    passed: true,
    workspace_path: "C:/AgentBench/workspaces/run-1",
    created_at: "2026-08-06T10:00:00Z",
    final_answer: "已完成",
    events: [],
    validators: [],
    score_dimensions: [],
    artifacts: [],
    attempts: [],
    judge_reviews: [],
    test_definition: { instruction: "", tools: [], validators: [], limits: {}, tags: [] },
    runner_type: "unified",
    ...overrides,
  };
}

function renderRunPage(run: RunDetail) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    let value: unknown = {};
    if (url.endsWith("/health")) {
        value = { name: "AgentBench Desktop", version: "5.2.3" };
    } else if (url.includes("/runs?experiment_id=")) {
      value = [run];
    } else if (url.includes("/runs/run-1")) {
      value = run;
    }
    return { ok: true, status: 200, json: async () => value } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MemoryRouter initialEntries={["/runs/run-1"]}>
      <Routes>
        <Route path="/runs/:runId" element={<RunDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
  return fetchMock;
}

function renderRunPageWithNotifications(run: RunDetail) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const value = url.includes("/runs?experiment_id=") ? [run] : url.includes("/runs/run-1") ? run : { name: "AgentBench Desktop", version: "5.2.3" };
    return { ok: true, status: 200, json: async () => value } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <WorkspaceUxProvider>
      <MemoryRouter initialEntries={["/runs/run-1"]}>
        <Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes>
      </MemoryRouter>
    </WorkspaceUxProvider>,
  );
}

describe("RunDetail exam question card", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("renders instruction text and material download links for an office-exam run", async () => {
    renderRunPage(makeRun({
      test_definition: {
        instruction: "打开素材中的销售表，将合计列填充为求和公式。",
        tools: [],
        validators: [],
        limits: {},
        tags: [],
      },
      materials: [
        { name: "销售表 2026.xlsx", size_bytes: 20480 },
        { name: "requirements.txt", size_bytes: 128 },
      ],
    }));

    expect(await screen.findByText("打开素材中的销售表，将合计列填充为求和公式。")).toBeInTheDocument();
    expect(screen.getByText("EXAM QUESTION")).toBeInTheDocument();

    const xlsxLink = screen.getByRole("link", { name: /销售表 2026\.xlsx/ });
    expect(xlsxLink).toHaveAttribute("href", expect.stringContaining(`/runs/run-1/materials/${encodeURIComponent("销售表 2026.xlsx")}`));
    expect(xlsxLink).toHaveTextContent("20,480 bytes");

    const txtLink = screen.getByRole("link", { name: /requirements\.txt/ });
    expect(txtLink).toHaveAttribute("href", expect.stringContaining("/runs/run-1/materials/requirements.txt"));
  });

  it("does not render the question card when instruction is missing and materials are empty", async () => {
    renderRunPage(makeRun({ test_definition: { instruction: "", tools: [], validators: [], limits: {}, tags: [] }, materials: [] }));

    await screen.findByText("NCRE 表格题");
    expect(screen.queryByText("EXAM QUESTION")).not.toBeInTheDocument();
    expect(screen.queryByText("题目")).not.toBeInTheDocument();
  });

  it("shows a clear message when a workspace cannot be opened", async () => {
    renderRunPageWithNotifications(makeRun());
    fireEvent.click(await screen.findByRole("button", { name: /打开工作区/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("无法打开工作区");
    expect(screen.getByRole("alert")).toHaveTextContent("只能在 AgentBench 桌面客户端中打开本地工作区");
  });

  it("always exposes a return-to-experiment link", async () => {
    renderRunPage(makeRun());

    const returnLinks = await screen.findAllByRole("link", { name: /返回实验/ });
    expect(returnLinks.length).toBeGreaterThan(0);
    expect(returnLinks[0]).toHaveAttribute("href", "/experiments/exp-1");
  });

  it("keeps the return link in the active single-run broadcast", async () => {
    renderRunPage(makeRun({ status: "running", completed_at: null }));

    expect(await screen.findByRole("link", { name: /返回实验/ })).toHaveAttribute("href", "/experiments/exp-1");
    expect(screen.getByText("单任务追踪")).toBeInTheDocument();
  });

  it("shows the frozen runtime condition and treats missing telemetry as N/A", async () => {
    renderRunPage(makeRun({
      requested_reasoning_effort: "max",
      effective_reasoning_effort: "high",
      effort_source: "mapped",
      effort_verified: true,
      telemetry_status: "unavailable",
      tokens_input: 0,
      tokens_output: 0,
      runtime_identity: {
        agent_provider: "deepseek-pro",
        model_name: "deepseek-pro",
        runner_version: "1.2.3",
      },
    }));

    expect(await screen.findByText("MAX → HIGH")).toBeInTheDocument();
    expect(screen.getByText("deepseek-pro / deepseek-pro")).toBeInTheDocument();
    expect(screen.getByText(/Agent 未上报/)).toBeInTheDocument();
    expect(screen.getAllByText("N/A").length).toBeGreaterThan(0);
  });
});
