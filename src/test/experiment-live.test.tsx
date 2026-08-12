import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import ExperimentDetail from "../pages/ExperimentDetail";
import type { Experiment, RunDetail, RunSummary } from "../types";

const experiment: Experiment = {
  id: "exp-live",
  name: "2025 考研数学（一）· 工具增强",
  suite_id: "suite-math",
  suite_name: "2025 考研数学（一）· 工具增强",
  participants: [{ model_id: "model-1", runner_id: "runner-1" }],
  repetitions: 1,
  concurrency: 1,
  status: "running",
  created_at: "2026-08-09T10:00:00Z",
  summary: { total: 10, completed: 9, failed: 0, blocked: 0 },
};

function run(number: number, status: string): RunSummary {
  return {
    id: `run-${number}`,
    experiment_id: "exp-live",
    test_case_id: `case-${number}`,
    model_id: "model-1",
    runner_id: "runner-1",
    test_title: `2025 数学一 · 第 ${number} 题 · 工具增强`,
    category: "postgraduate-math",
    model_name: "DeepSeek V4 Flash",
    runner_name: "Reasonix CLI",
    lane: "native",
    repetition: 1,
    status,
    score: status === "completed" ? 99.5 : null,
    tokens_input: 100,
    tokens_output: 20,
    cost_usd: 0,
    cost_source: "reported",
    duration_ms: number * 1000,
    steps: 1,
    attempt_count: 1,
    passed: status === "completed",
    created_at: `2026-08-09T10:${String(number).padStart(2, "0")}:00Z`,
    completed_at: status === "completed" ? `2026-08-09T10:${String(number).padStart(2, "0")}:30Z` : null,
  };
}

const runs = Array.from({ length: 10 }, (_, index) => run(index + 1, index === 0 ? "running" : "completed"));

function runDetail(summary: RunSummary): RunDetail {
  return {
    ...summary,
    runner_type: "reasonix_cli",
    final_answer: "",
    events: [{ id: 1, seq: 1, event_type: "live.activity", payload: { summary: "正在计算公开题目" }, created_at: summary.created_at }],
    validators: [],
    score_dimensions: [],
    artifacts: [],
    attempts: [],
    judge_reviews: [],
    test_definition: { instruction: "计算本题并提交结构化答案。", tools: [], validators: [], limits: {}, tags: [] },
    materials: [],
  };
}

function response(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200 });
}

describe("experiment live queue", () => {
  afterEach(() => vi.restoreAllMocks());

  it("can reveal every run while keeping the current run on the live stage", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/health")) return response({ name: "AgentBench Desktop", version: "5.1.0" });
      if (url.includes("/experiments/exp-live")) return response(experiment);
      if (url.includes("/runs?experiment_id=exp-live")) return response(runs);
      if (url.includes("/runs/run-1")) return response(runDetail(runs[0]));
      return response({});
    });
    render(<MemoryRouter initialEntries={["/experiments/exp-live"]}><Routes><Route path="/experiments/:experimentId" element={<ExperimentDetail />} /></Routes></MemoryRouter>);

    expect(await screen.findByText("数学答题通道")).toBeInTheDocument();
    expect(screen.getByText("全部 10")).toBeInTheDocument();
    expect(screen.queryByText("2025 数学一 · 第 2 题 · 工具增强")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "全部 10" }));

    expect(await screen.findByText("2025 数学一 · 第 2 题 · 工具增强")).toBeInTheDocument();
    expect(screen.getByText("2025 数学一 · 第 10 题 · 工具增强")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "详情" })).toHaveLength(10);
  });
});
