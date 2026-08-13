import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import FrontendPortfolio from "../pages/FrontendPortfolio";
import RunDetailPage from "../pages/RunDetail";
import type { FrontendPortfolio as Portfolio, ManualReview, RunDetail } from "../types";

const review: ManualReview = {
  id: "review-1",
  run_id: "run-front",
  status: "draft",
  rubric_version: "1.0",
  reviewer: "本机用户",
  dimension_scores: {},
  checklist: {},
  critical_defects: [],
  comment: "",
  evidence: [],
  updated_at: "2026-08-13T08:00:00Z",
};

const run: RunDetail = {
  id: "run-front",
  experiment_id: "exp-front",
  test_case_id: "case-front",
  model_id: "model-1",
  runner_id: "runner-1",
  test_title: "2048 × Roguelike 网页游戏",
  category: "frontend-games",
  model_name: "DeepSeek V4 Flash",
  runner_name: "Reasonix CLI",
  lane: "native",
  repetition: 1,
  status: "needs_review",
  score: null,
  tokens_input: 1000,
  tokens_output: 500,
  cost_usd: 0,
  cost_source: "reported",
  duration_ms: 90_000,
  steps: 12,
  attempt_count: 1,
  passed: null,
  workspace_path: "C:/AgentBench/data/frontend-portfolios/exp-front/project",
  created_at: "2026-08-13T08:00:00Z",
  events: [],
  validators: [],
  score_dimensions: [],
  artifacts: [],
  attempts: [],
  judge_reviews: [],
  runner_type: "reasonix_cli",
  test_definition: { instruction: "实现完整网页游戏。", tools: [], validators: [], limits: {}, tags: [] },
  materials: [],
  frontend: {
    difficulty: 4,
    source_repository: "https://github.com/Xnmk029/Xnmk_Library",
    source_commit: "2b03bc0f39f4a1e912816d5a8f752f6d1fd985eb",
    source_path: "L2_Intermediate/2048/PROJECT_PROMPT.md",
    suite_revision: "2026.08-r1",
    preview_entry: "index.html",
    review,
    rubric: {
      mode: "manual",
      version: "1.0",
      dimensions: [{ key: "functionality", label: "功能完成度", max_score: 35, criteria: "功能形成闭环" }],
      checklist: [{ key: "check-1", label: "可以独立启动" }],
      critical_defects: [{ key: "cannot_launch", label: "无法启动" }],
    },
  },
};

function json(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("Xnmk frontend suite UI", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("shows the fixed offline portfolio and keeps unreviewed work scoreless", async () => {
    const portfolio: Portfolio = {
      experiment_id: "exp-front",
      root_path: "C:/AgentBench/data/frontend-portfolios/exp-front",
      metadata: { kind: "frontend", suite_revision: "2026.08-r1", source_commit: "2b03bc0f39f4a1e912816d5a8f752f6d1fd985eb" },
      score: { reviewed_runs: 0, unreviewed_runs: 1, review_progress: 0, reviewed_weighted_score: null, frontend_weighted_score: null },
      runs: [{
        id: run.id, model_id: run.model_id, runner_id: run.runner_id, repetition: 1,
        status: "needs_review", score: null, workspace_path: run.workspace_path,
        duration_ms: run.duration_ms, tokens_input: run.tokens_input, tokens_output: run.tokens_output,
        cost_usd: 0, model_name: run.model_name, runner_name: run.runner_name,
        title: run.test_title, slug: "frontend.xnmk-2048", difficulty: 4,
        preview: { available: true, kind: "static", entry: "index.html" }, review,
      }],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.0" });
      return json(portfolio);
    }));
    render(<MemoryRouter initialEntries={["/experiments/exp-front/portfolio"]}><Routes><Route path="/experiments/:experimentId/portfolio" element={<FrontendPortfolio />} /></Routes></MemoryRouter>);

    expect(await screen.findByText("前端作品集")).toBeInTheDocument();
    expect(screen.getByText(/不在运行时访问远程仓库/)).toBeInTheDocument();
    expect(screen.getByText("评分草稿")).toBeInTheDocument();
    expect(screen.queryByText("0.0 分")).not.toBeInTheDocument();
  });

  it("uploads screenshot evidence from the manual rubric workbench", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.0" });
      if (url.includes("manual-review/evidence?")) return json({ ...review, evidence: [{ name: "proof.png", path: "evidence.png", size: 8 }] });
      if (url.includes("/runs?experiment_id=")) return json([run]);
      return json(run);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/runs/run-front"]}><Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "开始人工评分" }));
    const input = screen.getByText("添加截图").closest("label")?.querySelector("input[type=file]") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["png"], "proof.png", { type: "image/png" })] } });

    expect(await screen.findByText("proof.png")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("manual-review/evidence?filename=proof.png"), expect.objectContaining({ method: "POST" })));
  });
});
