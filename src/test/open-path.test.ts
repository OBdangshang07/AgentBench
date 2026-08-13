import { afterEach, describe, expect, it, vi } from "vitest";
import { openFolder } from "../lib/openPath";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

describe("openFolder", () => {
  afterEach(() => {
    invoke.mockReset();
    delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
  });

  it("uses the validated desktop command for a local directory", async () => {
    (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
    invoke.mockResolvedValue(undefined);

    await expect(openFolder(" D:\\AgentBench\\workspace ")).resolves.toEqual({ ok: true });
    expect(invoke).toHaveBeenCalledWith("open_workspace_folder", { path: "D:\\AgentBench\\workspace" });
  });

  it("returns the desktop error so the UI can explain a missing folder", async () => {
    (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
    invoke.mockRejectedValue("Workspace path does not exist or cannot be accessed");

    await expect(openFolder("D:\\missing")).resolves.toEqual({
      ok: false,
      error: "Workspace path does not exist or cannot be accessed",
    });
  });

  it("reports the browser fallback instead of silently doing nothing", async () => {
    await expect(openFolder("D:\\AgentBench\\workspace")).resolves.toEqual({
      ok: false,
      error: "只能在 AgentBench 桌面客户端中打开本地工作区",
    });
    expect(invoke).not.toHaveBeenCalled();
  });
});
