/** 在 Tauri 桌面环境下打开本地文件夹；浏览器/vitest 环境优雅降级返回 false。 */
export async function openFolder(path: string): Promise<boolean> {
  try {
    if (!path) return false;
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return false;
    const { openPath } = await import("@tauri-apps/plugin-opener");
    await openPath(path);
    return true;
  } catch {
    return false;
  }
}
