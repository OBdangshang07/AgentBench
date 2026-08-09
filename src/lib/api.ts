const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:43765/api/v1";
export const APP_VERSION = "3.0.0";

let compatibleBackend = false;
let compatibilityCheck: Promise<void> | null = null;

async function ensureCompatibleBackend(): Promise<void> {
  if (compatibleBackend) return;
  if (!compatibilityCheck) {
    compatibilityCheck = (async () => {
      const response = await fetch(`${API_BASE}/health`);
      if (!response.ok) throw new ApiError(response.status, "本地后台健康检查失败");
      const health = await response.json() as { name?: string; version?: string };
      if (health.name !== "AgentBench Desktop") {
        throw new Error("端口 43765 上的服务不是 AgentBench 后台，请关闭冲突程序后重启客户端。");
      }
      if (health.version !== APP_VERSION) {
        throw new Error(`客户端 ${APP_VERSION} 与本地后台 ${health.version ?? "未知"} 版本不一致，请完全退出旧版 AgentBench 后重启。`);
      }
      compatibleBackend = true;
    })().catch((error) => {
      compatibilityCheck = null;
      throw error;
    });
  }
  await compatibilityCheck;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (path !== "/health") await ensureCompatibleBackend();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, body.detail ?? "请求失败");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function apiUpload<T>(path: string, body: BodyInit, contentType: string): Promise<T> {
  await ensureCompatibleBackend();
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": contentType },
    body,
  });
  if (!response.ok) {
    const value = await response.json().catch(() => ({ detail: response.statusText })) as { detail?: string };
    throw new ApiError(response.status, value.detail ?? "上传失败");
  }
  return response.json() as Promise<T>;
}

export function downloadUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export { API_BASE };
