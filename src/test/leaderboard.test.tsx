import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Leaderboard from "../pages/Leaderboard";

function json(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
}

function installApiMock() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/health")) return json({ name: "AgentBench Desktop", version: "5.2.2" });
    if (url.includes("/leaderboard/exams/math-2025")) return json([]);
    if (url.includes("/leaderboard/exams/ncre")) return json([]);
    if (url.includes("/leaderboard?lane=")) return json([]);
    return json([]);
  });
}

describe("Leaderboard boards", () => {
  afterEach(() => vi.restoreAllMocks());

  it("keeps both official exams independent from the existing two boards", async () => {
    const fetchMock = installApiMock();
    render(<Leaderboard />);

    expect(screen.getByRole("button", { name: /统一 Agent 模型榜/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /原生 Agent 系统榜/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /2025 考研数学（一）榜/ }));
    expect(await screen.findByRole("group", { name: "考研数学榜模式" })).toBeInTheDocument();
    expect(screen.getByText(/完整 22 题/)).toBeInTheDocument();
    expect(screen.getByText(/官方 150 分结构/)).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/leaderboard/exams/math-2025?mode=closed-book"))).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "工具增强" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("mode=tool-augmented"))).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: /NCRE 二级榜/ }));
    expect(await screen.findByText(/选择题与 Word、Excel、PowerPoint/)).toBeInTheDocument();
    expect(screen.getByText(/完整四部分/)).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/leaderboard/exams/ncre"))).toBe(true));
  });
});
