import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Layout from "../components/Layout";
import TestLibrary from "../pages/TestLibrary";

const health = { name: "AgentBench Desktop", version: "4.1.0" };
const systemStatus = {
  version: "4.1.0",
  data_dir: "C:/AgentBench",
  database: { path: "C:/AgentBench/agentbench.db", ready: true },
  docker: { installed: true, available: true, executable: "docker" },
  native_cli_enabled: true,
  settings: { default_concurrency: 2, default_max_runtime_seconds: 0 },
  runners: [{ id: "runner-1", name: "Codex", capability: { installed: true } }],
};

function response(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200 });
}

describe("V3 evaluation OS information architecture", () => {
  afterEach(() => vi.restoreAllMocks());

  it("uses the v2 titlebar, tool rail and operational command palette", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/health")) return response(health);
      if (url.endsWith("/system/status")) return response(systemStatus);
      return response({ total_runs: 0, active_runs: 0, models: 1, test_cases: 214, recent_experiments: [], categories: [] });
    });
    render(<MemoryRouter initialEntries={["/"]}><Routes><Route element={<Layout />}><Route index element={<div>dashboard</div>} /></Route></Routes></MemoryRouter>);

    expect(await screen.findByText("EVALUATION OS")).toBeInTheDocument();
    expect(screen.getByText("Local Lab")).toBeInTheDocument();
    expect(screen.getByText("控制台")).toBeInTheDocument();
    expect(screen.getByText("编排")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(await screen.findByText("NAVIGATE")).toBeInTheDocument();
  });

  it("shows the built-in 2025 math paper lanes before the task list", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/health")) return response(health);
      if (url.includes("/test-cases?")) return response([{ id: "case-1", slug: "reasoning.one", version: "1", category: "reasoning", title: "推理样例", description: "示例", builtin: true, difficulty: 4 }]);
      if (url.endsWith("/suites")) return response([
        { id: "suite-1", name: "高难推理套件", description: "经过校准的推理测试", version: "3.0", case_count: 1, builtin: 1, difficulty_min: 4, difficulty_max: 5, category_count: 1 },
        { id: "math-closed", name: "2025 考研数学（一）· 闭卷推理", description: "22 题、150 分", version: "2025.1", case_count: 22, builtin: 1, difficulty_min: 4, difficulty_max: 5 },
        { id: "math-tools", name: "2025 考研数学（一）· 工具增强", description: "22 题、150 分", version: "2025.1", case_count: 22, builtin: 1, difficulty_min: 4, difficulty_max: 5 },
      ]);
      return response({});
    });
    render(<MemoryRouter initialEntries={["/library"]}><TestLibrary /></MemoryRouter>);

    expect(await screen.findByText("高难推理套件")).toBeInTheDocument();
    expect(screen.getByText("2025 考研数学（一）")).toBeInTheDocument();
    expect(screen.getByText("闭卷推理")).toBeInTheDocument();
    expect(screen.getByText("工具增强")).toBeInTheDocument();
    expect(screen.queryByText("导入 PDF")).not.toBeInTheDocument();
    expect((await screen.findAllByText("推理样例")).length).toBeGreaterThan(0);
    expect(screen.getByText("COLLECTIONS")).toBeInTheDocument();
    expect(screen.getByText("VALIDATOR MAP")).toBeInTheDocument();
  });
});
