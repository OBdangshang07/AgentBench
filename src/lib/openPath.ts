export interface OpenFolderResult {
  ok: boolean;
  error?: string;
}

/**
 * Open an existing local directory in Windows Explorer.
 *
 * The Rust command validates the path before launching Explorer, so callers get
 * an actionable error instead of a silent no-op. Browser and test environments
 * return an explicit unsupported result without attempting a system launch.
 */
export async function openFolder(path: string): Promise<OpenFolderResult> {
  const normalized = path.trim();
  if (!normalized) return { ok: false, error: "工作区路径为空" };
  if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) {
    return { ok: false, error: "只能在 AgentBench 桌面客户端中打开本地工作区" };
  }
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("open_workspace_folder", { path: normalized });
    return { ok: true };
  } catch (value) {
    return {
      ok: false,
      error: typeof value === "string"
        ? value
        : value instanceof Error
          ? value.message
          : "Windows 无法打开这个工作区",
    };
  }
}
