import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RadarChart from "../components/RadarChart";
import { EvaluationOverview } from "../v4/EvaluationOverview";
import type { Experiment, RunSummary } from "../types";

const state = vi.hoisted(() => ({ data: [] as unknown[], error: null as string | null, loading: false, refresh: vi.fn() }));
vi.mock("../lib/useApi", () => ({ useApi: () => state }));
const base: Experiment = { id: "active", name: "正在运行的评测", suite_id: "suite", suite_name: "测试套件", participants: [{ model_id: "model", runner_id: "runner" }], repetitions: 1, concurrency: 2, status: "running", created_at: "2026-09-01T12:00:00Z", run_count: 4, finished_count: 2 };

describe("Fieldnotes evaluation evidence", () => {
  beforeEach(() => { state.data = []; state.error = null; });

  it("prioritizes active work over a more recent completed experiment and counts terminal outcomes", () => {
    state.data = ["completed", "failed", "running", "queued"].map((status, index) => ({ id: String(index), model_id: "model", runner_id: "runner", model_name: "测试模型", runner_name: "测试 Agent", status } as RunSummary));
    render(<MemoryRouter><EvaluationOverview experiments={[{ ...base, id: "new", name: "已完成的新评测", status: "completed", created_at: "2026-09-02T12:00:00Z" }, base]} loading={false} error={null} retry={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "正在运行的评测" })).toBeVisible();
    expect(screen.queryByText("已完成的新评测")).not.toBeInTheDocument();
    expect(screen.getAllByRole("progressbar").map(item => item.getAttribute("aria-valuenow"))).toEqual(["50", "50"]);
    expect(screen.getByRole("link", { name: /打开评测详情/ })).toHaveAttribute("href", "/experiments/active");
  });

  it("shows a retryable data error without claiming there are no evaluations", () => {
    render(<MemoryRouter><EvaluationOverview experiments={null} loading={false} error="服务已断开" retry={vi.fn()} /></MemoryRouter>);
    expect(screen.getByText("服务已断开")).toBeVisible();
    expect(screen.getByRole("button", { name: "重试" })).toBeVisible();
    expect(screen.queryByText("准备开始第一次评测")).not.toBeInTheDocument();
  });

  it("explains truncated participant evidence while keeping the aggregate progress", () => {
    state.data = [{ model_id: "model", runner_id: "runner", model_name: "模型", runner_name: "Agent", status: "completed" }];
    render(<MemoryRouter><EvaluationOverview experiments={[base]} loading={false} error={null} retry={vi.fn()} /></MemoryRouter>);
    expect(screen.getByText(/参测明细显示已读取的 1 项测试/)).toBeVisible();
    expect(screen.getAllByRole("progressbar")[0]).toHaveAttribute("aria-valuenow", "50");
  });

  it("keeps unscored radar axes empty instead of plotting a zero score", () => {
    const { container } = render(<RadarChart data={[{ label: "前端", value: null }, { label: "后端", value: 82 }, { label: "研究", value: 68 }]} />);
    expect(container.querySelector(".radar-data")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".radar-vertex")).toHaveLength(2);
    expect(container.querySelector("title")).toHaveTextContent("前端：待评分；后端：82.0；研究：68.0");
  });
});
