import {
  Activity,
  AlertTriangle,
  Bot,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  CircleStop,
  Clock3,
  Code2,
  Cpu,
  File,
  FileCode2,
  FileDiff,
  FileSearch,
  Folder,
  FolderOpen,
  Gauge,
  GitBranch,
  Paperclip,
  PanelBottomClose,
  PanelBottomOpen,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Play,
  Plus,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Upload,
  User,
  X,
} from "lucide-react";
import { open } from "@tauri-apps/plugin-dialog";
import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { ModelConfig, Runner } from "../types";
import type {
  AgentSession,
  AgentSessionDetail,
  ApprovalRequest,
  FileChange,
  PermissionProfile,
  Project,
  ProjectFileSearch,
  ProjectTree,
  ReasoningEffort,
  SessionAttachment,
  StudioEvent,
} from "./types";
import { useSessionStream } from "./useSessionStream";
import { TerminalView } from "./TerminalView";

const activeStatuses = new Set(["queued", "preparing", "running", "waiting_approval"]);

function time(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function duration(ms: number) {
  if (!ms) return "0s";
  if (ms < 60_000) return `${Math.max(1, Math.round(ms / 1000))}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round(ms % 60_000 / 1000)}s`;
}

function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const permissionLabels: Record<PermissionProfile, string> = {
  readonly: "只读",
  workspace: "工作区",
  standard: "标准开发",
  full: "完全访问",
};

const effortLabels: Record<ReasoningEffort, string> = {
  low: "低",
  medium: "中",
  high: "高",
  xhigh: "极高",
  max: "最大",
};

const statusLabels: Record<string, string> = {
  idle: "就绪",
  queued: "排队中",
  preparing: "准备中",
  running: "执行中",
  waiting_approval: "等待审批",
  completed: "已完成",
  failed: "失败",
  cancelled: "已停止",
  interrupted: "已中断",
};

function eventTitle(event: StudioEvent) {
  const payload = event.payload;
  switch (event.event_type) {
    case "turn.queued": return "任务已进入 Agent 队列";
    case "turn.started": return "Agent 开始执行本轮任务";
    case "tool.requested": return `调用工具 · ${String(payload.name ?? "tool")}`;
    case "tool.completed": return `工具完成 · ${String(payload.name ?? "tool")}`;
    case "file.changed": return `${String(payload.change_type ?? "修改")}文件 · ${String(payload.path ?? "")}`;
    case "native_cli.event": return String(payload.summary ?? "原生 Agent 产生新活动");
    case "assistant.message": return "Agent 已提交结果";
    case "turn.completed": return "本轮任务已完成";
    case "turn.cancelled": return "本轮任务已取消";
    case "turn.failed": return `执行失败 · ${String(payload.error_code ?? "runtime_error")}`;
    case "approval.requested": return `等待审批 · ${String(payload.title ?? "受保护操作")}`;
    case "usage.updated": return "额度消耗已更新";
    default: return event.event_type.replaceAll(".", " · ");
  }
}

function eventDetail(event: StudioEvent) {
  const payload = event.payload;
  if (event.event_type === "tool.requested") return JSON.stringify(payload.arguments ?? {}, null, 2);
  if (event.event_type === "tool.completed") return JSON.stringify(payload.result ?? {}, null, 2);
  if (event.event_type === "turn.completed") return `${String(payload.steps ?? 0)} steps · ${duration(Number(payload.duration_ms ?? 0))}`;
  if (event.event_type === "turn.failed" || event.event_type === "turn.cancelled") return String(payload.message ?? "");
  return "";
}

interface SessionForm {
  project_id: string;
  title: string;
  runner_id: string;
  model_id: string;
  permission_profile: PermissionProfile;
  reasoning_effort: ReasoningEffort;
}

interface StudioPickerOption {
  value: string;
  label: string;
  description: string;
  disabled?: boolean;
}

interface StudioLayoutState {
  left: boolean;
  right: boolean;
  dock: boolean;
}

const studioLayoutKey = "agentbench.studio.layout.v1";

function initialStudioLayout(): StudioLayoutState {
  try {
    const stored = window.localStorage.getItem(studioLayoutKey);
    if (stored) return { left: true, right: true, dock: true, ...JSON.parse(stored) };
  } catch {
    // A locked-down WebView may deny storage; the defaults remain fully usable.
  }
  return { left: true, right: true, dock: true };
}

function StudioPicker({
  ariaLabel,
  caption,
  icon,
  value,
  options,
  disabled = false,
  onChange,
}: {
  ariaLabel: string;
  caption: string;
  icon: ReactNode;
  value: string;
  options: StudioPickerOption[];
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const selected = options.find((option) => option.value === value);
  const needle = query.trim().toLowerCase();
  const visibleOptions = options.filter((option) => (
    !needle || `${option.label} ${option.description}`.toLowerCase().includes(needle)
  ));

  useEffect(() => {
    if (!open) return;
    setQuery("");
    const focusTimer = window.setTimeout(() => searchRef.current?.focus(), 0);
    function dismiss(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", dismiss);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("mousedown", dismiss);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  return (
    <div className={`v4-studio-picker ${open ? "open" : ""}`} ref={rootRef}>
      <button
        className="v4-studio-picker-trigger"
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="v4-picker-icon">{icon}</span>
        <span className="v4-picker-value"><small>{caption}</small><strong>{selected?.label ?? "请选择"}</strong></span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="v4-studio-picker-menu">
          <header><span>{caption}</span><b>{options.length} 项</b></header>
          {options.length > 6 && (
            <label><Search size={14} /><input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`搜索${caption}`} /></label>
          )}
          <div role="listbox" aria-label={ariaLabel}>
            {visibleOptions.map((option) => (
              <button
                type="button"
                role="option"
                aria-selected={option.value === value}
                key={option.value}
                disabled={option.disabled}
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                }}
              >
                <span className="v4-picker-radio">{option.value === value && <Check size={12} />}</span>
                <span><strong>{option.label}</strong><small>{option.disabled ? "未安装 · " : ""}{option.description}</small></span>
                {!option.disabled && <i />}
              </button>
            ))}
            {!visibleOptions.length && <p>没有匹配项</p>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function AgentStudio() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { data: sessions, refresh: refreshSessions } = useApi<AgentSession[]>("/sessions", 3_000);
  const { data: projects } = useApi<Project[]>("/projects");
  const { data: runners } = useApi<Runner[]>("/runners");
  const { data: models } = useApi<ModelConfig[]>("/models");
  const { data: detail, loading, error, refresh } = useApi<AgentSessionDetail>(
    sessionId ? `/sessions/${sessionId}` : null,
    (current) => current && activeStatuses.has(current.status) ? 750 : 2_500,
  );
  const [treePath, setTreePath] = useState(".");
  const { data: tree } = useApi<ProjectTree>(detail ? `/projects/${detail.project_id}/files?path=${encodeURIComponent(treePath)}` : null, 4_000);
  const [railMode, setRailMode] = useState<"files" | "search">("files");
  const [fileQuery, setFileQuery] = useState("");
  const normalizedFileQuery = fileQuery.trim();
  const { data: searchResult, loading: searchLoading, error: searchError } = useApi<ProjectFileSearch>(
    detail && railMode === "search" && normalizedFileQuery.length >= 2
      ? `/projects/${detail.project_id}/files/search?query=${encodeURIComponent(normalizedFileQuery)}&limit=120`
      : null,
  );
  const { events: streamedEvents, connected } = useSessionStream(sessionId);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ path: string; content: string } | null>(null);
  const [dock, setDock] = useState<"activity" | "terminal" | "file" | "changes">("activity");
  const [changePreview, setChangePreview] = useState<{
    id: string; path: string; change_type: string; status: string; diff: string;
    current_content: string; can_restore: boolean;
  } | null>(null);
  const [changeEdit, setChangeEdit] = useState("");
  const [terminal, setTerminal] = useState<{ id: string; running: boolean; cursor: number } | null>(null);
  const [terminalText, setTerminalText] = useState("");
  const [terminalInput, setTerminalInput] = useState("");
  const [attachments, setAttachments] = useState<SessionAttachment[]>([]);
  const [attachmentBusy, setAttachmentBusy] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState<string | null>(null);
  const [configBusy, setConfigBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [sessionForm, setSessionForm] = useState<SessionForm>({ project_id: "", title: "新 Agent 会话", runner_id: "", model_id: "", permission_profile: "workspace", reasoning_effort: "medium" });
  const [studioLayout, setStudioLayout] = useState<StudioLayoutState>(initialStudioLayout);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileSearchRef = useRef<HTMLInputElement>(null);
  const terminalCursorRef = useRef(0);
  const terminalWriteChainRef = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    if (!sessionId && sessions?.length) navigate(`/studio/${sessions[0].id}`, { replace: true });
  }, [navigate, sessionId, sessions]);

  useEffect(() => {
    setTreePath(".");
    setPreview(null);
    setRailMode("files");
    setFileQuery("");
  }, [detail?.project_id]);

  useEffect(() => {
    setAttachments([]);
    setTerminal(null);
    setTerminalText("");
    setTerminalInput("");
    terminalCursorRef.current = 0;
  }, [sessionId]);

  useEffect(() => {
    try {
      window.localStorage.setItem(studioLayoutKey, JSON.stringify(studioLayout));
    } catch {
      // Layout persistence is a convenience, not a runtime requirement.
    }
  }, [studioLayout]);

  useEffect(() => {
    if (railMode !== "search") return;
    const timer = window.setTimeout(() => fileSearchRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [railMode]);

  useEffect(() => {
    function handleWorkbenchShortcuts(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.shiftKey && event.key.toLowerCase() === "f") {
        event.preventDefault();
        setStudioLayout((current) => ({ ...current, left: true }));
        setRailMode("search");
      } else if (!event.shiftKey && event.key.toLowerCase() === "b") {
        event.preventDefault();
        setStudioLayout((current) => ({ ...current, left: !current.left }));
      } else if (!event.shiftKey && event.key.toLowerCase() === "j") {
        event.preventDefault();
        setStudioLayout((current) => ({ ...current, dock: !current.dock }));
      }
    }
    window.addEventListener("keydown", handleWorkbenchShortcuts);
    return () => window.removeEventListener("keydown", handleWorkbenchShortcuts);
  }, []);

  const events = useMemo(() => {
    const bySequence = new Map<number, StudioEvent>();
    detail?.events.forEach((event) => bySequence.set(event.seq, event));
    streamedEvents.forEach((event) => bySequence.set(event.seq, event));
    return [...bySequence.values()].sort((left, right) => left.seq - right.seq);
  }, [detail?.events, streamedEvents]);
  const pendingApprovals = useMemo(
    () => detail?.approvals.filter((item) => item.status === "pending") ?? [],
    [detail?.approvals],
  );

  const runnerOptions = useMemo<StudioPickerOption[]>(() => (runners ?? [])
    .filter((runner) => runner.enabled)
    .map((runner) => ({
      value: runner.id,
      label: runner.name,
      description: runner.capability.version ?? runner.runner_type.replaceAll("_", " "),
      disabled: !runner.capability.installed,
    })), [runners]);
  const modelOptions = useMemo<StudioPickerOption[]>(() => (models ?? [])
    .filter((model) => model.enabled)
    .map((model) => ({
      value: model.id,
      label: model.name,
      description: `${model.provider} · ${model.model_name}`,
    })), [models]);
  const liveUsage = useMemo(() => {
    if (!activeStatuses.has(detail?.status ?? "")) return { input: 0, output: 0 };
    const activeTurn = [...(detail?.turns ?? [])].reverse().find((turn) => activeStatuses.has(turn.status));
    if (!activeTurn) return { input: 0, output: 0 };
    let deltaInput = 0;
    let deltaOutput = 0;
    let absoluteInput = 0;
    let absoluteOutput = 0;
    for (const event of events) {
      if (event.turn_id !== activeTurn.id || event.event_type !== "usage.updated") continue;
      const usage = event.payload.usage as Record<string, unknown> | undefined;
      const input = Number(usage?.input_tokens ?? 0);
      const output = Number(usage?.output_tokens ?? 0);
      if (event.payload.mode === "delta") {
        deltaInput += input;
        deltaOutput += output;
      } else {
        absoluteInput = Math.max(absoluteInput, input);
        absoluteOutput = Math.max(absoluteOutput, output);
      }
    }
    return {
      input: Math.max(deltaInput, absoluteInput),
      output: Math.max(deltaOutput, absoluteOutput),
    };
  }, [detail?.status, detail?.turns, events]);
  const quotaTokens = (detail?.tokens_input ?? 0) + (detail?.tokens_output ?? 0) + liveUsage.input + liveUsage.output;
  const quotaCost = useMemo(() => {
    const selected = models?.find((model) => model.id === detail?.model_id);
    const liveCost = selected
      ? (liveUsage.input * selected.input_price + liveUsage.output * selected.output_price) / 1_000_000
      : 0;
    return (detail?.cost_usd ?? 0) + liveCost;
  }, [detail?.cost_usd, detail?.model_id, liveUsage.input, liveUsage.output, models]);

  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [detail?.messages.length, events.length]);

  useEffect(() => {
    if (!sessionId || !terminal?.id || !terminal.running) return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      try {
        const value = await api<{ id: string; running: boolean; cursor: number; chunks: Array<{ data: string }> }>(
          `/sessions/${sessionId}/terminals/${terminal.id}?after=${terminalCursorRef.current}`,
        );
        if (stopped) return;
        if (value.chunks.length) setTerminalText((current) => (current + value.chunks.map((item) => item.data).join("")).slice(-300_000));
        terminalCursorRef.current = value.cursor;
        setTerminal({ id: value.id, running: value.running, cursor: value.cursor });
      } catch (value) {
        if (!stopped) {
          setTerminal((current) => current ? { ...current, running: false } : current);
          setActionError(value instanceof Error ? value.message : "终端连接已中断");
        }
      }
    }, 450);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [sessionId, terminal?.id, terminal?.running]);

  function openCreate() {
    const project = projects?.[0];
    setSessionForm({
      project_id: project?.id ?? "",
      title: project ? `${project.name} Agent 会话` : "新 Agent 会话",
      runner_id: project?.default_runner_id ?? runners?.find((item) => item.enabled)?.id ?? "",
      model_id: project?.default_model_id ?? models?.find((item) => item.enabled)?.id ?? "",
      permission_profile: project?.permission_profile ?? "workspace",
      reasoning_effort: "medium",
    });
    setCreateOpen(true);
  }

  async function createSession(event: FormEvent) {
    event.preventDefault();
    setActionError(null);
    try {
      const created = await api<AgentSession>("/sessions", { method: "POST", body: JSON.stringify(sessionForm) });
      setCreateOpen(false);
      await refreshSessions();
      navigate(`/studio/${created.id}`);
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "无法创建会话");
    }
  }

  async function sendTurn(event: FormEvent) {
    event.preventDefault();
    if (!sessionId || !message.trim() || sending || activeStatuses.has(detail?.status ?? "")) return;
    setSending(true);
    setActionError(null);
    try {
      const context: Array<Record<string, unknown>> = [];
      if (preview) context.push({ type: "file", path: preview.path });
      context.push(...attachments.map((item) => ({
        type: "attachment",
        artifact_id: item.id,
      })));
      await api(`/sessions/${sessionId}/turns`, {
        method: "POST",
        body: JSON.stringify({ message: message.trim(), context }),
      });
      setMessage("");
      setAttachments([]);
      await Promise.all([refresh(), refreshSessions()]);
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "发送失败");
    } finally {
      setSending(false);
    }
  }

  async function cancel() {
    if (!sessionId) return;
    await api(`/sessions/${sessionId}/cancel`, { method: "POST" });
    await refresh();
  }

  async function updateSession(changes: Record<string, unknown>) {
    if (!sessionId) return;
    setActionError(null);
    try {
      await api(`/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify(changes) });
      await refresh();
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "更新会话失败");
    }
  }

  async function updateRuntimeSetting(changes: Record<string, unknown>) {
    setConfigBusy(true);
    try {
      await updateSession(changes);
    } finally {
      setConfigBusy(false);
    }
  }

  async function decide(approval: ApprovalRequest, decision: "allow_once" | "allow_session" | "allow_project" | "deny") {
    setApprovalBusy(approval.id);
    setActionError(null);
    try {
      await api(`/approvals/${approval.id}/decision`, { method: "POST", body: JSON.stringify({ decision, reason: "在 Agent Studio 中处理" }) });
      await Promise.all([refresh(), refreshSessions()]);
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "无法处理审批");
    } finally {
      setApprovalBusy(null);
    }
  }

  async function attachFiles() {
    if (!sessionId || attachmentBusy || attachments.length >= 10) return;
    setActionError(null);
    try {
      const selected = await open({
        multiple: true,
        directory: false,
        title: "选择要发送给 Agent 的图片或文件",
      });
      const paths = Array.isArray(selected) ? selected : selected ? [selected] : [];
      if (!paths.length) return;
      setAttachmentBusy(true);
      const imported = await api<SessionAttachment[]>(`/sessions/${sessionId}/attachments`, {
        method: "POST",
        body: JSON.stringify({ paths: paths.slice(0, Math.max(0, 10 - attachments.length)) }),
      });
      setAttachments((current) => [...current, ...imported].slice(0, 10));
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "无法添加附件");
    } finally {
      setAttachmentBusy(false);
    }
  }

  async function removeAttachment(attachment: SessionAttachment) {
    if (!sessionId) return;
    setAttachments((current) => current.filter((item) => item.id !== attachment.id));
    try {
      await api(`/sessions/${sessionId}/attachments/${attachment.id}`, { method: "DELETE" });
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "无法移除附件");
    }
  }

  async function openEntry(entry: ProjectTree["entries"][number]) {
    if (!detail) return;
    if (entry.kind === "directory") {
      setTreePath(entry.path);
      return;
    }
    try {
      const file = await api<{ path: string; content: string }>(`/projects/${detail.project_id}/file?path=${encodeURIComponent(entry.path)}`);
      setPreview(file);
      setDock("file");
      setStudioLayout((current) => ({ ...current, dock: true }));
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "无法打开文件");
    }
  }

  function openSearchEntry(entry: ProjectTree["entries"][number]) {
    if (entry.kind === "directory") {
      setTreePath(entry.path);
      setRailMode("files");
      return;
    }
    void openEntry(entry);
  }

  async function openChange(change: FileChange) {
    if (!sessionId) return;
    setActionError(null);
    try {
      const value = await api<typeof changePreview & Record<string, unknown>>(
        `/sessions/${sessionId}/changes/${change.id}`,
      );
      setChangePreview(value);
      setChangeEdit(String(value?.current_content ?? ""));
      setDock("changes");
      setStudioLayout((current) => ({ ...current, dock: true }));
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "无法读取变更 Diff");
    }
  }

  async function reviewChange(action: "accept" | "reject" | "apply_content") {
    if (!changePreview) return;
    setActionError(null);
    try {
      const value = await api<typeof changePreview>(`/file-changes/${changePreview.id}/review`, {
        method: "POST",
        body: JSON.stringify({ action, content: action === "apply_content" ? changeEdit : null }),
      });
      setChangePreview(value);
      setChangeEdit(value.current_content);
      await refresh();
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "无法处理文件变更");
    }
  }

  async function startInteractiveTerminal() {
    if (!sessionId) return;
    setActionError(null);
    try {
      const value = await api<{ id: string; running: boolean; cursor: number; chunks: Array<{ data: string }> }>(`/sessions/${sessionId}/terminals`, {
        method: "POST",
        body: JSON.stringify({ shell: "powershell.exe", columns: 120, rows: 30 }),
      });
      setTerminal({ id: value.id, running: value.running, cursor: value.cursor });
      terminalCursorRef.current = value.cursor;
      setTerminalText(value.chunks.map((item) => item.data).join(""));
      setDock("terminal");
      setStudioLayout((current) => ({ ...current, dock: true }));
      if (!value.running) setActionError("终端进程未能保持运行，请点击“重新启动”重试。");
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "无法启动交互终端");
    }
  }

  async function sendTerminalInput(event: FormEvent) {
    event.preventDefault();
    if (!sessionId || !terminal?.id || !terminalInput) return;
    const data = terminalInput + "\r";
    setTerminalInput("");
    await writeTerminalData(data);
  }

  function writeTerminalData(data: string): Promise<void> {
    if (!sessionId || !terminal?.id || !terminal.running || !data) return Promise.resolve();
    const currentSessionId = sessionId;
    const currentTerminalId = terminal.id;
    terminalWriteChainRef.current = terminalWriteChainRef.current
      .catch(() => undefined)
      .then(async () => {
        try {
          await api(`/sessions/${currentSessionId}/terminals/${currentTerminalId}/input`, {
            method: "POST", body: JSON.stringify({ data }),
          });
        } catch (value) {
          setActionError(value instanceof Error ? value.message : "终端输入失败");
          setTerminal((current) => current ? { ...current, running: false } : current);
          throw value;
        }
      });
    return terminalWriteChainRef.current;
  }

  async function resizeTerminal(columns: number, rows: number) {
    if (!sessionId || !terminal?.id || !terminal.running) return;
    try {
      await api(`/sessions/${sessionId}/terminals/${terminal.id}/resize`, {
        method: "POST", body: JSON.stringify({ columns, rows }),
      });
    } catch {
      // A resize failure should not interrupt typing; the next fit can retry.
    }
  }

  function openTerminalPanel() {
    setDock("terminal");
    setStudioLayout((current) => ({ ...current, dock: true }));
    if ((!terminal || !terminal.running) && (detail?.permission_profile === "standard" || detail?.permission_profile === "full")) {
      void startInteractiveTerminal();
    }
  }

  async function closeInteractiveTerminal() {
    if (!sessionId || !terminal?.id) return;
    await api(`/sessions/${sessionId}/terminals/${terminal.id}`, { method: "DELETE" });
    setTerminal((current) => current ? { ...current, running: false } : current);
  }

  function renderApproval(approval: ApprovalRequest, inline = false) {
    const busy = approvalBusy === approval.id;
    const requestText = String(
      approval.request.command
      ?? approval.request.path
      ?? approval.request.runner_name
      ?? approval.request_type,
    );
    return (
      <article className={inline ? "v4-inline-approval" : "v4-inspector-approval"} key={approval.id}>
        <AlertTriangle size={inline ? 18 : 16} />
        <div className="v4-approval-copy">
          <header><strong>{approval.title}</strong><span>{approval.risk_level.toUpperCase()}</span></header>
          <p>{approval.description}</p>
          <code title={requestText}>{requestText}</code>
        </div>
        <div className="v4-approval-actions">
          <button type="button" disabled={busy} onClick={() => void decide(approval, "deny")}>拒绝</button>
          <button type="button" disabled={busy} onClick={() => void decide(approval, "allow_once")}>仅允许一次</button>
          <button type="button" disabled={busy} onClick={() => void decide(approval, "allow_session")}>本会话允许</button>
          {inline && <button type="button" disabled={busy} onClick={() => void decide(approval, "allow_project")}>此项目允许</button>}
        </div>
      </article>
    );
  }

  if (!sessionId && !sessions?.length) {
    return (
      <div className="v4-studio-empty">
        <span><Sparkles size={28} /></span><h1>Agent Studio</h1><p>选择一个已授权项目，建立可持续、多轮且可审计的 Agent 会话。</p>
        {projects?.length ? <button className="v4-button primary" type="button" onClick={openCreate}><Plus size={16} />新建 Agent 会话</button> : <Link className="v4-button primary" to="/projects"><FolderOpen size={16} />先添加项目</Link>}
        {createOpen && renderCreateModal()}
      </div>
    );
  }

  function renderCreateModal() {
    return (
      <div className="v4-modal-backdrop" onMouseDown={() => setCreateOpen(false)}>
        <form className="v4-modal small" onSubmit={createSession} onMouseDown={(event) => event.stopPropagation()}>
          <header><div><strong>新建 Agent 会话</strong><small>选择项目、Agent、模型和权限配置</small></div><button type="button" onClick={() => setCreateOpen(false)}><X size={18} /></button></header>
          <div className="v4-form-grid">
            <label className="full"><span>项目</span><select required value={sessionForm.project_id} onChange={(event) => {
              const project = projects?.find((item) => item.id === event.target.value);
              setSessionForm({ ...sessionForm, project_id: event.target.value, runner_id: project?.default_runner_id ?? sessionForm.runner_id, model_id: project?.default_model_id ?? sessionForm.model_id, permission_profile: project?.permission_profile ?? sessionForm.permission_profile });
            }}>{projects?.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
            <label className="full"><span>会话标题</span><input required value={sessionForm.title} onChange={(event) => setSessionForm({ ...sessionForm, title: event.target.value })} /></label>
            <label><span>Agent</span><select required value={sessionForm.runner_id} onChange={(event) => setSessionForm({ ...sessionForm, runner_id: event.target.value })}>{runners?.filter((runner) => runner.enabled).map((runner) => <option key={runner.id} value={runner.id}>{runner.name}</option>)}</select></label>
            <label><span>模型</span><select required value={sessionForm.model_id} onChange={(event) => setSessionForm({ ...sessionForm, model_id: event.target.value })}>{models?.filter((model) => model.enabled).map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
            <label><span>权限</span><select value={sessionForm.permission_profile} onChange={(event) => setSessionForm({ ...sessionForm, permission_profile: event.target.value as PermissionProfile })}><option value="readonly">只读</option><option value="workspace">工作区读写</option><option value="standard">标准开发</option><option value="full">完全访问</option></select></label>
            <label><span>思考强度</span><select value={sessionForm.reasoning_effort} onChange={(event) => setSessionForm({ ...sessionForm, reasoning_effort: event.target.value as ReasoningEffort })}><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">极高</option><option value="max">最大</option></select></label>
          </div>
          {actionError && <div className="v4-error">{actionError}</div>}
          <footer><button className="v4-button secondary" type="button" onClick={() => setCreateOpen(false)}>取消</button><button className="v4-button primary" type="submit"><Sparkles size={16} />创建会话</button></footer>
        </form>
      </div>
    );
  }

  return (
    <div className={`v4-studio-workbench ${studioLayout.left ? "" : "left-collapsed"} ${studioLayout.right ? "" : "right-collapsed"} ${studioLayout.dock ? "" : "dock-collapsed"}`}>
      <aside className="v4-studio-rail">
        <header>{detail ? <><span className="v4-project-logo">{detail.project_name.slice(0, 2).toUpperCase()}</span><div><strong>{detail.project_name}</strong><small title={detail.workspace_path}><GitBranch size={11} /> {detail.workspace_path}</small></div></> : <span>加载项目…</span>}</header>
        <div className="v4-rail-tabs"><button className={railMode === "files" ? "active" : ""} type="button" onClick={() => setRailMode("files")}><Folder size={13} />文件</button><button className={railMode === "search" ? "active" : ""} type="button" onClick={() => setRailMode("search")}><Search size={13} />搜索</button></div>
        {railMode === "files" ? (
          <section className="v4-file-tree">
            <button className="v4-tree-up" type="button" disabled={treePath === "."} onClick={() => setTreePath(treePath.includes("/") ? treePath.slice(0, treePath.lastIndexOf("/")) : ".")}><ChevronDown size={14} />WORKSPACE · {treePath}</button>
            {tree?.entries.map((entry) => <button key={entry.path} title={entry.path} type="button" onClick={() => void openEntry(entry)}>{entry.kind === "directory" ? <Folder size={15} /> : <FileCode2 size={15} />}<span>{entry.name}</span>{entry.kind === "directory" && <ChevronRight size={13} />}</button>)}
            {!tree?.entries.length && <small>目录为空或正在读取…</small>}
          </section>
        ) : (
          <section className="v4-file-search">
            <div className="v4-file-search-box"><Search size={15} /><input ref={fileSearchRef} aria-label="搜索项目文件" value={fileQuery} onChange={(event) => setFileQuery(event.target.value)} placeholder="输入文件名或路径" />{fileQuery && <button type="button" aria-label="清除文件搜索" onClick={() => setFileQuery("")}><X size={13} /></button>}</div>
            <header><span>WORKSPACE SEARCH</span>{normalizedFileQuery.length >= 2 && <b>{searchResult?.entries.length ?? 0} 结果</b>}</header>
            <div className="v4-file-search-results">
              {normalizedFileQuery.length < 2 && <div className="v4-search-hint"><FileSearch size={23} /><strong>搜索整个项目</strong><p>至少输入 2 个字符，也可按 Ctrl Shift F 聚焦。</p></div>}
              {normalizedFileQuery.length >= 2 && searchLoading && <div className="v4-search-hint"><RefreshCw className="spin" size={20} /><strong>正在扫描项目…</strong></div>}
              {searchError && <div className="v4-search-hint error"><AlertTriangle size={20} /><strong>搜索失败</strong><p>{searchError}</p></div>}
              {!searchLoading && normalizedFileQuery.length >= 2 && !searchError && searchResult?.entries.map((entry) => <button key={entry.path} type="button" title={entry.path} onClick={() => openSearchEntry(entry)}>{entry.kind === "directory" ? <Folder size={15} /> : <FileCode2 size={15} />}<span><strong>{entry.name}</strong><small>{entry.path}</small></span>{entry.kind === "directory" && <ChevronRight size={13} />}</button>)}
              {!searchLoading && normalizedFileQuery.length >= 2 && !searchError && searchResult && !searchResult.entries.length && <div className="v4-search-hint"><FileSearch size={21} /><strong>没有匹配文件</strong><p>尝试缩短关键词或搜索路径片段。</p></div>}
            </div>
            {searchResult && <footer>已扫描 {searchResult.scanned.toLocaleString()} 项{searchResult.truncated ? " · 已达到结果上限" : ""}</footer>}
          </section>
        )}
        <section className="v4-session-list"><header><span>RECENT SESSIONS</span><button type="button" onClick={openCreate}><Plus size={14} /></button></header>{sessions?.slice(0, 8).map((session) => <button key={session.id} className={session.id === sessionId ? "active" : ""} type="button" onClick={() => navigate(`/studio/${session.id}`)}><i className={activeStatuses.has(session.status) ? "live" : ""} /><span><strong>{session.title}</strong><small>{session.runner_name} · {statusLabels[session.status] ?? session.status}</small></span></button>)}</section>
      </aside>

      <section className="v4-conversation">
        <header className="v4-conversation-head">
          <button className={`v4-pane-toggle with-label ${studioLayout.left ? "active" : ""}`} type="button" aria-label={studioLayout.left ? "收起项目侧栏" : "展开项目侧栏"} title={`${studioLayout.left ? "收起" : "展开"}项目侧栏 · Ctrl B`} onClick={() => setStudioLayout((current) => ({ ...current, left: !current.left }))}>{studioLayout.left ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}<span>项目栏</span></button>
          <div className="v4-conversation-title"><strong>{detail?.title ?? "正在加载会话"}</strong><small title={detail?.workspace_path}>SESSION / {sessionId?.slice(0, 8)} · {detail?.workspace_path}</small></div>
          <span className={`v4-status ${activeStatuses.has(detail?.status ?? "") ? "green" : ""}`}><i />{detail ? statusLabels[detail.status] ?? detail.status : "加载中"}</span>
          <StudioPicker ariaLabel="选择 Agent" caption="AGENT" icon={<Bot size={15} />} disabled={activeStatuses.has(detail?.status ?? "")} value={detail?.runner_id ?? ""} options={runnerOptions} onChange={(runnerId) => void updateSession({ runner_id: runnerId })} />
          <StudioPicker ariaLabel="选择模型" caption="MODEL" icon={<Cpu size={15} />} disabled={activeStatuses.has(detail?.status ?? "")} value={detail?.model_id ?? ""} options={modelOptions} onChange={(modelId) => void updateSession({ model_id: modelId })} />
          <button className="v4-pane-toggle" type="button" onClick={() => void refresh()} title="刷新会话"><RefreshCw className={loading ? "spin" : ""} size={16} /></button>
          <button className={`v4-pane-toggle with-label ${studioLayout.right ? "active" : ""}`} type="button" aria-label={studioLayout.right ? "收起会话侧栏" : "展开会话侧栏"} title={`${studioLayout.right ? "收起" : "展开"}会话上下文`} onClick={() => setStudioLayout((current) => ({ ...current, right: !current.right }))}>{studioLayout.right ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}<span>上下文</span></button>
        </header>

        <div className="v4-conversation-scroll" ref={scrollRef}>
          {loading && <div className="v4-empty compact"><RefreshCw className="spin" size={22} /><strong>正在恢复会话上下文</strong></div>}
          {detail?.messages.map((item) => <article key={item.id} className={`v4-message ${item.role}`}><span>{item.role === "user" ? <User size={16} /> : <Sparkles size={16} />}</span><div><header><strong>{item.role === "user" ? "你" : detail.runner_name}</strong><time>{time(item.created_at)}</time></header><p>{item.content}</p>{item.metadata.context?.length ? <footer><Paperclip size={13} />已附加 {item.metadata.context.length} 项上下文</footer> : null}</div></article>)}
          {!!events.length && <section className="v4-inline-activity"><header><TerminalSquare size={15} /><strong>可验证执行活动</strong><span>{connected ? "LIVE" : "PERSISTED"}</span></header>{events.slice(-8).map((event) => <article key={event.seq} className={event.event_type.includes("failed") ? "failed" : event.event_type.includes("completed") ? "done" : ""}><i /><div><strong>{eventTitle(event)}</strong>{eventDetail(event) && <pre>{eventDetail(event)}</pre>}<small>{time(event.created_at)} · EVENT {event.seq}</small></div></article>)}</section>}
          {pendingApprovals.length > 0 && <section className="v4-approval-gate"><header><ShieldCheck size={16} /><div><strong>Agent 正在等待你的审批</strong><small>选择后任务会自动继续，无需重新发送消息</small></div><b>{pendingApprovals.length}</b></header>{pendingApprovals.map((approval) => renderApproval(approval, true))}</section>}
          {error && <div className="v4-error">{error}</div>}
        </div>

        <form className="v4-composer" onSubmit={sendTurn}>
          {(preview || attachments.length > 0) && <div className="v4-composer-context">
            {preview && <div className="v4-context-chip"><File size={13} /><span>{preview.path}</span><button type="button" aria-label="移除文件上下文" onClick={() => setPreview(null)}><X size={12} /></button></div>}
            {attachments.map((attachment) => <div className="v4-context-chip attachment" key={attachment.id}><Paperclip size={13} /><span>{attachment.name}<small>{fileSize(attachment.size)}</small></span><button type="button" aria-label={`移除附件 ${attachment.name}`} onClick={() => void removeAttachment(attachment)}><X size={12} /></button></div>)}
          </div>}
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder={pendingApprovals.length ? "请先处理上方审批；仍可调整权限、思考强度或准备下一条消息" : "继续告诉 Agent 要做什么… Enter 发送，Shift + Enter 换行"}
            disabled={activeStatuses.has(detail?.status ?? "") && detail?.status !== "waiting_approval"}
          />
          <footer className="v4-composer-toolbar">
            <button className="v4-composer-tool" type="button" onClick={() => void attachFiles()} disabled={attachmentBusy || attachments.length >= 10} title="添加图片或文件（单个最大 50 MB）"><Upload size={14} /><span>{attachmentBusy ? "添加中" : "附件"}</span></button>
            <label className="v4-composer-select" title="运行中的权限变更会安全地用于后续操作；切换为完全访问会继续当前待审批操作"><ShieldCheck size={14} /><span>权限</span><select aria-label="会话访问权限" value={detail?.permission_profile ?? "workspace"} disabled={configBusy} onChange={(event) => void updateRuntimeSetting({ permission_profile: event.target.value as PermissionProfile })}><option value="readonly">只读</option><option value="workspace">工作区</option><option value="standard">标准开发</option><option value="full">完全访问</option></select></label>
            <label className="v4-composer-select" title="不同 Agent 会映射到其原生 effort、variant 或 reasoning 设置"><Brain size={14} /><span>思考</span><select aria-label="思考强度" value={detail?.reasoning_effort ?? "medium"} disabled={configBusy} onChange={(event) => void updateRuntimeSetting({ reasoning_effort: event.target.value as ReasoningEffort })}><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">极高</option><option value="max">最大</option></select></label>
            <span className="v4-quota" title={`输入 ${(detail?.tokens_input ?? 0) + liveUsage.input} · 输出 ${(detail?.tokens_output ?? 0) + liveUsage.output} · 预计费用 $${quotaCost.toFixed(4)}`}><Gauge size={14} /><span>{quotaTokens.toLocaleString()} Tokens{activeStatuses.has(detail?.status ?? "") && (liveUsage.input + liveUsage.output > 0) ? " · LIVE" : ""}</span><b>${quotaCost.toFixed(3)}</b></span>
            {activeStatuses.has(detail?.status ?? "") ? <button className="cancel" type="button" onClick={() => void cancel()}><CircleStop size={16} />停止</button> : <button className="send" type="submit" aria-label="发送消息" title="发送 · Enter" disabled={!message.trim() || sending}><Send size={16} /></button>}
          </footer>
          {actionError && <div className="v4-composer-error"><AlertTriangle size={14} />{actionError}</div>}
        </form>
      </section>

      <aside className="v4-inspector">
        <header><div><strong>会话上下文</strong><small>{connected ? "LIVE EVENT STREAM" : "PERSISTED EVENTS"}</small></div><span><i className={connected ? "live" : ""} /></span></header>
        <section><label>ACTIVE AGENT</label><div className="v4-agent-profile"><span>{detail?.runner_name?.slice(0, 2).toUpperCase()}</span><div><strong>{detail?.runner_name}</strong><small>{detail?.model_name} · {detail?.runner_type}</small></div></div><div className="v4-profile-tags"><span>原生恢复</span><span>MCP</span><span>结构化事件</span></div></section>
        <section><label>PERMISSION REQUESTS <b>{pendingApprovals.length} PENDING</b></label>{pendingApprovals.map((approval) => renderApproval(approval))}{!pendingApprovals.length && <p className="v4-inspector-empty"><Check size={15} />没有待处理操作</p>}</section>
        <section><label>LIVE TELEMETRY</label><dl className="v4-telemetry"><div><dt>输入 Token</dt><dd>{((detail?.tokens_input ?? 0) + liveUsage.input).toLocaleString()}</dd></div><div><dt>输出 Token</dt><dd>{((detail?.tokens_output ?? 0) + liveUsage.output).toLocaleString()}</dd></div><div><dt>预计费用</dt><dd>${quotaCost.toFixed(3)}</dd></div><div><dt>累计用时</dt><dd>{duration(detail?.duration_ms ?? 0)}</dd></div></dl></section>
        <section><label>SESSION CONTEXT</label><div className="v4-context-list"><span><FolderOpen size={14} />{detail?.project_name}</span><span><ShieldCheck size={14} />{permissionLabels[detail?.permission_profile ?? "workspace"]}</span><span><Brain size={14} />{effortLabels[detail?.reasoning_effort ?? "medium"]}思考强度</span><span><FileDiff size={14} />{detail?.file_changes.length ?? 0} 个文件变更</span></div></section>
      </aside>

      <section className="v4-studio-dock">
        <nav><button type="button" className={studioLayout.dock && dock === "activity" ? "active" : ""} onClick={() => { setDock("activity"); setStudioLayout((current) => ({ ...current, dock: true })); }}><Activity size={14} />活动日志 <b>{events.length}</b></button><button type="button" className={studioLayout.dock && dock === "terminal" ? "active" : ""} onClick={openTerminalPanel}><TerminalSquare size={14} />交互终端 <i className={terminal?.running ? "live" : ""} /></button><button type="button" className={studioLayout.dock && dock === "file" ? "active" : ""} onClick={() => { setDock("file"); setStudioLayout((current) => ({ ...current, dock: true })); }}><Code2 size={14} />文件预览</button><button type="button" className={studioLayout.dock && dock === "changes" ? "active" : ""} onClick={() => { setDock("changes"); setStudioLayout((current) => ({ ...current, dock: true })); }}><FileDiff size={14} />变更 <b>{detail?.file_changes.length ?? 0}</b></button><span className="v4-dock-summary">{terminal?.running ? "TERMINAL LIVE · 点击终端区域直接输入" : `${events.length} EVENTS`}</span><button className="v4-dock-toggle" type="button" aria-label={studioLayout.dock ? "隐藏底部面板" : "展开底部面板"} title={`${studioLayout.dock ? "隐藏" : "展开"}底部面板 · Ctrl J`} onClick={() => setStudioLayout((current) => ({ ...current, dock: !current.dock }))}>{studioLayout.dock ? <PanelBottomClose size={16} /> : <PanelBottomOpen size={16} />}{studioLayout.dock ? "隐藏" : "展开"}</button></nav>
        {studioLayout.dock && dock === "activity" && <div className="v4-terminal"><header><span>可验证 Agent 活动</span><small>此处为只读事件日志，命令请在“交互终端”输入</small></header>{events.slice(-16).map((event) => <div key={event.seq}><time>{time(event.created_at)}</time><span>{eventTitle(event)}</span></div>)}{!events.length && <span>等待 Agent 活动…</span>}</div>}
        {studioLayout.dock && dock === "terminal" && (terminal?.running ? <div className="v4-interactive-terminal"><header><span><i className="live" />ConPTY · PowerShell <small>点击下方终端即可直接键入</small></span><button type="button" onClick={() => void closeInteractiveTerminal()}>关闭终端</button></header><TerminalView content={terminalText} onData={(data) => void writeTerminalData(data)} onResize={(columns, rows) => void resizeTerminal(columns, rows)} /><form onSubmit={sendTerminalInput}><span>快速命令 ›</span><input aria-label="终端快速命令" value={terminalInput} onChange={(event) => setTerminalInput(event.target.value)} placeholder="也可在上方终端内直接输入" autoComplete="off" /><button type="submit" disabled={!terminalInput}>运行</button></form></div> : <div className="v4-terminal-empty"><TerminalSquare size={26} /><strong>{terminal ? "终端已退出" : "启动项目交互终端"}</strong><p>{detail?.permission_profile === "standard" || detail?.permission_profile === "full" ? "终端将在当前项目目录打开，支持直接键盘输入、快捷键与命令历史。" : "交互终端需要“标准开发”或“完全访问”权限。可在上方输入框工具栏随时切换。"}</p>{detail?.permission_profile === "standard" || detail?.permission_profile === "full" ? <button type="button" onClick={() => void startInteractiveTerminal()}><TerminalSquare size={14} />{terminal ? "重新启动终端" : "启动终端"}</button> : <button type="button" onClick={() => void updateRuntimeSetting({ permission_profile: "standard" })}><ShieldCheck size={14} />切换到标准开发</button>}</div>)}
        {studioLayout.dock && dock === "file" && <pre className="v4-file-preview">{preview ? preview.content : "从左侧项目树选择一个 UTF-8 文本文件。"}</pre>}
        {studioLayout.dock && dock === "changes" && <div className="v4-change-review"><div className="v4-change-list">{detail?.file_changes.map((change) => <button className={change.id === changePreview?.id ? "active" : ""} type="button" key={change.id} onClick={() => void openChange(change)}><span className={change.change_type}>{change.change_type.slice(0, 1).toUpperCase()}</span><code>{change.path}</code><small>{change.status} · {change.size_delta >= 0 ? "+" : ""}{change.size_delta} B</small></button>)}{!detail?.file_changes.length && <span>本会话尚未修改文件。</span>}</div>{changePreview && <section className="v4-diff-review"><header><strong>{changePreview.path}</strong><span>{changePreview.status}</span><div><button type="button" onClick={() => void reviewChange("reject")} disabled={!changePreview.can_restore || changePreview.status !== "observed"}>拒绝并还原</button><button type="button" onClick={() => void reviewChange("apply_content")} disabled={changePreview.status !== "observed"}>应用编辑内容</button><button className="accept" type="button" onClick={() => void reviewChange("accept")} disabled={changePreview.status !== "observed"}>接受变更</button></div></header><div><pre>{changePreview.diff || "此文件没有可显示的文本 Diff。"}</pre><textarea aria-label="编辑后的文件内容" value={changeEdit} onChange={(event) => setChangeEdit(event.target.value)} /></div></section>}</div>}
      </section>
      {createOpen && renderCreateModal()}
    </div>
  );
}
