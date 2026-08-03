export const statusLabel: Record<string, string> = {
  draft: "待启动",
  queued: "排队中",
  preparing: "准备环境",
  running: "执行中",
  validating: "验证中",
  judging: "AI 评分",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "被中断",
  environment_unavailable: "缺少沙箱",
  needs_review: "待复核",
};

export function formatDate(value?: string) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function formatDuration(ms?: number) {
  if (!ms) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

export function formatNumber(value?: number | null, digits = 0) {
  if (value == null) return "—";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: digits }).format(value);
}

export function statusTone(status: string) {
  if (status === "completed") return "success";
  if (["failed", "cancelled"].includes(status)) return "danger";
  if (["running", "validating", "judging", "preparing"].includes(status)) return "active";
  if (["needs_review", "environment_unavailable", "interrupted"].includes(status)) return "warning";
  return "neutral";
}
