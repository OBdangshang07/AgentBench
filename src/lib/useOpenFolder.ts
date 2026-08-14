import { useCallback } from "react";
import { useWorkspaceUx } from "../components/WorkspaceUx";
import { openFolder } from "./openPath";

export function useOpenFolder() {
  const { notify } = useWorkspaceUx();

  return useCallback(async (path: string, label = "工作区") => {
    const result = await openFolder(path);
    if (result.ok) {
      notify({ kind: "success", title: `已打开${label}`, message: path });
      return true;
    }
    notify({
      kind: "error",
      title: `无法打开${label}`,
      message: result.error ?? "请检查目录是否仍然存在，以及当前账户是否有访问权限。",
      duration: 0,
    });
    return false;
  }, [notify]);
}
