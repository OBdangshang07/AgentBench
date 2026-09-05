import {
  Brain,
  Check,
  ChevronDown,
  Code2,
  Copy,
  FileDiff,
  GitFork,
  Paperclip,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  User,
} from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { copyText } from "../../lib/clipboard";
import type { StudioEvent, StudioMessage } from "../types";

export function formatStudioTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function formatStudioDuration(ms: number) {
  if (!ms) return "0s";
  if (ms < 60_000) return `${Math.max(1, Math.round(ms / 1000))}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round(ms % 60_000 / 1000)}s`;
}

export function studioEventTitle(event: StudioEvent) {
  const payload = event.payload;
  switch (event.event_type) {
    case "turn.queued": return "任务已进入队列";
    case "turn.started": return "开始处理任务";
    case "native_cli.started": return "运行环境已就绪";
    case "live.phase": return String(payload.summary ?? "正在推进任务");
    case "live.heartbeat": return String(payload.summary ?? "正在持续运行");
    case "live.message": return payload.status === "streaming" ? "正在整理进展" : "进展说明";
    case "live.tool": return `${payload.status === "completed" ? "工具已完成" : payload.status === "preparing" ? "准备使用工具" : "正在使用工具"} · ${String(payload.tool ?? "工具")}`;
    case "live.command": return "执行命令";
    case "live.test": return payload.status === "completed" ? "验证已完成" : "运行验证";
    case "live.file_change": return `${String(payload.change ?? "修改")}文件 · ${String(payload.path ?? "工作区文件")}`;
    case "tool.requested": return `调用工具 · ${String(payload.name ?? "工具")}`;
    case "tool.completed": return `工具完成 · ${String(payload.name ?? "工具")}`;
    case "file.changed": return `${String(payload.change_type ?? "修改")}文件 · ${String(payload.path ?? "")}`;
    case "native_cli.event": return String(payload.summary ?? "Agent 产生新活动");
    case "assistant.message": return "结果已生成";
    case "turn.completed": return "任务已完成";
    case "turn.cancelled": return "任务已取消";
    case "session.cancel_requested": return "正在安全停止";
    case "session.cancelled": return "Agent 已停止";
    case "session.created": return "会话已创建";
    case "session.updated": return "会话配置已更新";
    case "live.activity": return String(payload.summary ?? "正在处理任务");
    case "turn.failed": return `执行失败 · ${String(payload.error_code ?? "runtime_error")}`;
    case "approval.requested": return `等待审批 · ${String(payload.title ?? "受保护操作")}`;
    case "usage.updated": return "用量已更新";
    default: return "运行状态已更新";
  }
}

function studioEventDetail(event: StudioEvent) {
  const payload = event.payload;
  if (event.event_type === "live.message") return String(payload.text ?? "");
  if (event.event_type === "live.tool") return String(payload.detail ?? "");
  if (["live.command", "live.test"].includes(event.event_type)) return [payload.command, payload.detail].filter(Boolean).join("\n");
  if (event.event_type === "live.phase") return String(payload.detail ?? "");
  if (event.event_type === "live.heartbeat" && payload.phase) return `阶段：${String(payload.phase)}`;
  if (event.event_type === "live.file_change" && payload.size_delta !== undefined) return `${Number(payload.size_delta) >= 0 ? "+" : ""}${String(payload.size_delta)} B`;
  if (event.event_type === "tool.requested") return JSON.stringify(payload.arguments ?? {}, null, 2);
  if (event.event_type === "tool.completed") return JSON.stringify(payload.result ?? {}, null, 2);
  if (event.event_type === "turn.completed") return `${String(payload.steps ?? 0)} 个步骤 · ${formatStudioDuration(Number(payload.duration_ms ?? 0))}`;
  if (["turn.failed", "turn.cancelled"].includes(event.event_type)) return String(payload.message ?? "");
  return "";
}

function studioEventCategory(event: StudioEvent) {
  if (event.event_type === "live.message") return "说明";
  if (event.event_type.includes("tool")) return "工具";
  if (event.event_type.includes("command")) return "命令";
  if (event.event_type.includes("test")) return "验证";
  if (event.event_type.includes("file")) return "文件";
  if (event.event_type.includes("approval")) return "审批";
  return "进度";
}

function studioEventTone(event: StudioEvent) {
  if (event.event_type.includes("failed") || event.event_type.includes("cancelled")) return "failed";
  if (event.payload.status === "completed" || event.event_type.includes("completed")) return "done";
  if (event.event_type === "live.message") return "message";
  if (event.event_type.includes("tool") || event.event_type.includes("command") || event.event_type.includes("test")) return "action";
  return "running";
}

function StudioEventIcon({ event }: { event: StudioEvent }) {
  if (event.event_type === "live.message") return <Sparkles size={15} />;
  if (event.event_type.includes("command") || event.event_type.includes("test")) return <TerminalSquare size={15} />;
  if (event.event_type.includes("file")) return <FileDiff size={15} />;
  if (event.event_type.includes("approval")) return <ShieldCheck size={15} />;
  if (event.event_type.includes("tool")) return <Code2 size={15} />;
  if (studioEventTone(event) === "done") return <Check size={15} />;
  return <Brain size={15} />;
}

export function isSecondaryStudioOperation(event: StudioEvent) {
  return ["live.tool", "live.command", "live.test", "live.file_change", "tool.requested", "tool.completed", "file.changed"].includes(event.event_type)
    && studioEventTone(event) !== "failed";
}

export function isStudioRuntimeNoise(event: StudioEvent) {
  const path = String(event.payload.path ?? event.payload.detail ?? "").replaceAll("\\", "/").toLowerCase();
  return [
    "/node_modules/", "/.git/", "/__pycache__/", "/.venv/", "/.packaging-venv/",
    "/browser-profile/", "/guide-browser-profile/", "/cache/", "/code cache/",
    "/gpu cache/", "/session storage/", "/safe browsing/", "/gcm store/",
  ].some((fragment) => path.includes(fragment));
}

function MarkdownMessage({ content }: { content: string }) {
  const [copied, setCopied] = useState<string | null>(null);

  async function copyCode(value: string) {
    if (!await copyText(value)) return;
    setCopied(value);
    window.setTimeout(() => setCopied((current) => current === value ? null : current), 1600);
  }

  return (
    <div className="v5-markdown ab-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
        pre: ({ children }) => <>{children}</>,
        code: ({ className, children, ...props }) => {
          const value = String(children).replace(/\n$/, "");
          const block = Boolean(className) || value.includes("\n");
          if (!block) return <code className={className} {...props}>{children}</code>;
          const language = className?.replace("language-", "") || "text";
          return <section className="v5-code-block"><header><span>{language}</span><button type="button" onClick={() => void copyCode(value)}>{copied === value ? <Check size={13} /> : <Copy size={13} />}{copied === value ? "已复制" : "复制"}</button></header><pre><code className={className} {...props}>{children}</code></pre></section>;
        },
        a: ({ href, children }) => <a href={href} target={href?.startsWith("http") ? "_blank" : undefined} rel="noreferrer">{children}</a>,
      }}>{content}</ReactMarkdown>
    </div>
  );
}

export function StudioMessageCard({ message, runnerName, onFork }: { message: StudioMessage; runnerName?: string; onFork: () => void }) {
  return (
    <article className={`v4-message ab-message ${message.role}`}>
      <span className="ab-message-avatar">{message.role === "user" ? <User size={16} /> : <Sparkles size={16} />}</span>
      <div className="ab-message-body">
        <header><strong>{message.role === "user" ? "你" : runnerName}</strong><time>{formatStudioTime(message.created_at)}</time><button className="v5-message-action" type="button" title="从这里创建会话分支" aria-label="从这条消息创建会话分支" onClick={onFork}><GitFork size={13} /></button></header>
        <MarkdownMessage content={message.content} />
        {message.metadata.context?.length ? <footer><Paperclip size={13} />已附加 {message.metadata.context.length} 项上下文</footer> : null}
      </div>
    </article>
  );
}

export function ExecutionTimeline({ events, label = "执行轨迹", active, expanded, onToggle }: { events: StudioEvent[]; label?: string; active: boolean; expanded: boolean; onToggle: () => void }) {
  const readable = events.filter((event) => !isStudioRuntimeNoise(event));
  const shown = expanded ? readable.slice(-30) : readable.slice(-4);
  const toolCount = readable.filter(isSecondaryStudioOperation).length;
  const completedCount = readable.filter((event) => ["completed", "success", "done"].includes(String(event.payload.status ?? ""))).length;
  return (
    <section className={`v4-inline-activity ab-execution ${expanded ? "expanded" : ""}`}>
      <button className="ab-execution-summary" type="button" aria-expanded={expanded} onClick={onToggle}>
        <span className="ab-execution-mark"><Brain size={16} /></span>
        <span className="ab-execution-copy"><strong>{label}</strong><small>公开计划、工具与验证，不包含模型私有思维链</small></span>
        <span className="ab-execution-metrics"><em>{readable.length} 步</em>{toolCount > 0 && <em>{toolCount} 次操作</em>}{completedCount > 0 && <em>{completedCount} 项完成</em>}</span>
        <b className={active ? "live" : ""}><i />{active ? "进行中" : "已完成"}</b>
        <ChevronDown className="ab-execution-chevron" size={15} />
      </button>
      {expanded && <div className="ab-execution-list">
        {shown.map((event) => <article key={`${event.event_type}-${event.seq}`} className={studioEventTone(event)}><span><StudioEventIcon event={event} /></span><div><header><strong>{studioEventTitle(event)}</strong><em>{studioEventCategory(event)}</em><time>{formatStudioTime(event.created_at)}</time></header>{studioEventDetail(event) && (event.event_type === "live.message" ? <p>{studioEventDetail(event)}</p> : <pre>{studioEventDetail(event)}</pre>)}</div></article>)}
        {!shown.length && <div className="ab-execution-waiting"><Brain size={18} /><span><strong>正在分析任务</strong><small>可公开的计划与操作会显示在这里。</small></span></div>}
      </div>}
      {!expanded && readable.length > 0 && <footer>{studioEventTitle(readable.at(-1) as StudioEvent)}</footer>}
    </section>
  );
}
