import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import RunDetailPage from "../pages/RunDetail";
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
      value = { name: "AgentBench Desktop", version: "3.0.0" };
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
});
