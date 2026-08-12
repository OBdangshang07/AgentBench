import {
  Activity,
  Archive,
  ArrowLeft,
  Bot,
  CalendarClock,
  Check,
  CheckCircle2,
  CircleStop,
  Clock3,
  Copy,
  ExternalLink,
  FolderKanban,
  GitFork,
  Pencil,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Tag,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useWorkspaceUx } from "../components/WorkspaceUx";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { StudioTaskDetail, TaskEvent } from "./types";

const activeStatuses = ["queued", "running", "approval"];

function statusLabel(status: StudioTaskDetail["status"]) {
  return ({
    backlog: "待处理",
    queued: "排队中",
    running: "执行中",
    approval: "等待审批",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  })[status];
}

function priorityLabel(priority: StudioTaskDetail["priority"]) {
  return ({ low: "低优先级", normal: "普通优先级", high: "高优先级", urgent: "紧急" })[priority];
}

function dateTime(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function eventPresentation(event: TaskEvent) {
  const values: Record<string, { label: string; detail: string; tone: string }> = {
    "task.created": { label: "任务已创建", detail: "任务进入待处理队列", tone: "neutral" },
    "task.updated": { label: "任务信息已更新", detail: "配置或验收标准发生变化", tone: "neutral" },
    "task.status_changed": { label: "任务状态已调整", detail: `${String(event.payload.from ?? "—")} → ${String(event.payload.to ?? "—")}`, tone: "neutral" },
    "task.queued": { label: "已提交给 Agent", detail: "运行环境正在排队准备", tone: "active" },
    "task.running": { label: "Agent 开始执行", detail: "已创建隔离的关联会话", tone: "active" },
    "task.awaiting_approval": { label: "等待人工审批", detail: String(event.payload.title ?? "Agent 请求额外权限"), tone: "warning" },
    "task.approval_resolved": { label: "审批已处理", detail: String(event.payload.status ?? "已处理"), tone: "active" },
    "task.completed": { label: "任务执行完成", detail: "结果与会话记录已保存", tone: "success" },
    "task.failed": { label: "任务执行失败", detail: String(event.payload.message ?? "请检查关联会话"), tone: "danger" },
    "task.cancelled": { label: "任务已取消", detail: "Agent 收到停止信号", tone: "warning" },
    "task.interrupted": { label: "任务被应用重启中断", detail: "可检查记录后重新启动", tone: "danger" },
    "task.duplicated": { label: "从已有任务复制", detail: "验收标准与配置已保留", tone: "neutral" },
  };
  return values[event.event_type] ?? { label: event.event_type, detail: "任务活动已记录", tone: "neutral" };
}

export default function TaskDetail() {
  const { taskId = "" } = useParams();
  const navigate = useNavigate();
  const ux = useWorkspaceUx();
  const { data: task, loading, error, refresh } = useApi<StudioTaskDetail>(taskId ? `/tasks/${taskId}` : null, 2_500);
  const [busy, setBusy] = useState(false);
  const completedCriteria = task?.acceptance_criteria.filter((item) => item.completed).length ?? 0;
  const progress = task?.acceptance_criteria.length ? Math.round(completedCriteria / task.acceptance_criteria.length * 100) : 0;
  const pendingDependencies = useMemo(() => task?.dependencies.filter((item) => item.status !== "completed") ?? [], [task]);

  async function perform(action: "start" | "cancel" | "duplicate" | "archive") {
    if (!task) return;
    if (action === "cancel") {
      const approved = await ux.confirm({ title: "停止正在执行的任务？", message: "关联会话与已产生的文件变更会保留。", confirmLabel: "停止任务", tone: "danger", detail: task.title });
      if (!approved) return;
    }
    if (action === "archive") {
      const approved = await ux.confirm({ title: "归档这个任务？", message: "任务、时间线与关联会话不会被删除。", confirmLabel: "归档", detail: task.title });
      if (!approved) return;
    }
    setBusy(true);
    try {
      if (action === "start") await api(`/tasks/${task.id}/start`, { method: "POST" });
      if (action === "cancel") await api(`/tasks/${task.id}/cancel`, { method: "POST" });
      if (action === "duplicate") {
        const created = await api<StudioTaskDetail>(`/tasks/${task.id}/duplicate`, { method: "POST" });
        ux.notify({ kind: "success", title: "任务副本已创建", message: created.title });
        navigate(`/tasks/${created.id}`);
        return;
      }
      if (action === "archive") {
        await api(`/tasks/${task.id}`, { method: "DELETE" });
        ux.notify({ kind: "success", title: "任务已归档", message: task.title });
        navigate("/tasks");
        return;
      }
      await refresh();
      ux.notify({ kind: action === "cancel" ? "warning" : "success", title: action === "cancel" ? "任务已取消" : "任务已提交", message: task.title });
    } catch (value) {
      ux.notify({ kind: "error", title: "任务操作失败", message: value instanceof Error ? value.message : "未知错误" });
    } finally {
      setBusy(false);
    }
  }

  async function toggleCriterion(index: number) {
    if (!task || activeStatuses.includes(task.status)) return;
    const criteria = task.acceptance_criteria.map((item, itemIndex) => itemIndex === index ? { ...item, completed: !item.completed } : item);
    setBusy(true);
    try {
      await api(`/tasks/${task.id}`, { method: "PATCH", body: JSON.stringify({ acceptance_criteria: criteria }) });
      await refresh();
    } catch (value) {
      ux.notify({ kind: "error", title: "无法更新验收状态", message: value instanceof Error ? value.message : "未知错误" });
    } finally {
      setBusy(false);
    }
  }

  if (loading && !task) return <div className="v5-task-detail-state"><RefreshCw className="spin" size={22} /><strong>正在载入任务记录</strong></div>;
  if (error || !task) return <div className="v5-task-detail-state error"><TriangleAlert size={25} /><strong>无法打开任务</strong><p>{error || "任务不存在或已不可用"}</p><Link className="v4-button secondary" to="/tasks"><ArrowLeft size={15} />返回任务中心</Link></div>;

  return (
    <div className="v4-page v5-task-detail-page">
      <nav className="v5-task-breadcrumb"><button type="button" onClick={() => navigate(-1)}><ArrowLeft size={15} />返回</button><span>/</span><Link to="/tasks">任务中心</Link><span>/</span><strong>{task.id.slice(0, 8).toUpperCase()}</strong></nav>

      <header className="v5-task-detail-hero">
        <div>
          <span className={`v5-task-status ${task.status}`}><i />{statusLabel(task.status)}</span>
          <span className={`v5-task-priority ${task.priority}`}>{priorityLabel(task.priority)}</span>
          <h1>{task.title}</h1>
          <p>{task.description || "这个任务还没有补充说明。"}</p>
          <div className="v5-task-detail-tags">{task.tags.map((item) => <span key={item}><Tag size={11} />{item}</span>)}</div>
        </div>
        <section className="v5-task-detail-actions">
          {(task.status === "backlog" || task.status === "failed" || task.status === "cancelled") && <button className="v4-button primary" type="button" disabled={busy || pendingDependencies.length > 0} onClick={() => void perform("start")}>{task.status === "backlog" ? <Play size={15} /> : <RotateCcw size={15} />}{task.status === "backlog" ? "启动任务" : "重新运行"}</button>}
          {activeStatuses.includes(task.status) && <button className="v4-button danger" type="button" disabled={busy} onClick={() => void perform("cancel")}><CircleStop size={15} />停止任务</button>}
          {task.session_id && <button className="v4-button secondary" type="button" onClick={() => navigate(`/studio/${task.session_id}`)}><ExternalLink size={15} />打开会话</button>}
          <button className="v4-button secondary" type="button" onClick={() => navigate(`/tasks?task=${task.id}`)}><Pencil size={14} />编辑</button>
          <button className="v4-button secondary" type="button" disabled={busy} onClick={() => void perform("duplicate")}><Copy size={14} />复制</button>
          <button className="v4-button ghost" type="button" disabled={busy || activeStatuses.includes(task.status)} onClick={() => void perform("archive")}><Archive size={14} />归档</button>
        </section>
      </header>

      <main className="v5-task-detail-grid">
        <div className="v5-task-detail-main">
          <section className="v4-panel v5-task-acceptance">
            <header><div><ShieldCheck size={17} /><span><strong>验收标准</strong><small>Agent 会收到这些标准，但完成状态需要可验证证据</small></span></div><b>{completedCriteria}/{task.acceptance_criteria.length}</b></header>
            <div className="v5-task-progress"><i style={{ width: `${progress}%` }} /></div>
            <div className="v5-task-criteria">
              {task.acceptance_criteria.map((item, index) => <button type="button" className={item.completed ? "completed" : ""} disabled={busy || activeStatuses.includes(task.status)} onClick={() => void toggleCriterion(index)} key={`${item.text}-${index}`}><span>{item.completed ? <Check size={14} /> : index + 1}</span><strong>{item.text}</strong>{item.completed && <small>已验证</small>}</button>)}
              {!task.acceptance_criteria.length && <div className="v5-task-empty"><ShieldCheck size={21} /><strong>尚未定义验收标准</strong><p>编辑任务并按行添加可检查的完成条件。</p><button type="button" onClick={() => navigate(`/tasks?task=${task.id}`)}>添加验收标准</button></div>}
            </div>
          </section>

          {task.result_summary && <section className="v4-panel v5-task-output"><header><Sparkles size={17} /><strong>Agent 结果摘要</strong></header><p>{task.result_summary}</p>{task.session_id && <button type="button" onClick={() => navigate(`/studio/${task.session_id}`)}>查看完整会话与文件变更<ExternalLink size={13} /></button>}</section>}

          <section className="v4-panel v5-task-timeline">
            <header><Activity size={17} /><span><strong>活动时间线</strong><small>{task.events.length} 条可验证记录</small></span></header>
            <div>{task.events.slice().reverse().map((event) => { const presentation = eventPresentation(event); return <article className={presentation.tone} key={event.id}><i>{presentation.tone === "success" ? <CheckCircle2 size={14} /> : presentation.tone === "danger" ? <TriangleAlert size={14} /> : presentation.tone === "warning" ? <Clock3 size={14} /> : <Activity size={14} />}</i><div><strong>{presentation.label}</strong><p>{presentation.detail}</p></div><time>{dateTime(event.created_at)}</time></article>; })}{!task.events.length && <div className="v5-task-empty"><Activity size={20} /><strong>暂无活动记录</strong></div>}</div>
          </section>
        </div>

        <aside className="v5-task-detail-aside">
          <section className="v4-panel v5-task-facts">
            <header><strong>运行配置</strong><small>LOCAL TASK PROFILE</small></header>
            <dl>
              <div><dt><FolderKanban size={13} />项目</dt><dd>{task.project_id ? <Link to={`/projects/${task.project_id}`}>{task.project_name || "未命名项目"}</Link> : "跨项目"}</dd></div>
              <div><dt><Bot size={13} />Agent</dt><dd>{task.runner_name || "使用项目默认值"}</dd></div>
              <div><dt><Sparkles size={13} />模型</dt><dd>{task.model_name || "使用项目默认值"}</dd></div>
              <div><dt><CalendarClock size={13} />截止时间</dt><dd>{dateTime(task.due_at)}</dd></div>
              <div><dt><Clock3 size={13} />创建时间</dt><dd>{dateTime(task.created_at)}</dd></div>
              <div><dt><RefreshCw size={13} />最近更新</dt><dd>{dateTime(task.updated_at)}</dd></div>
            </dl>
          </section>

          <section className="v4-panel v5-task-dependencies">
            <header><GitFork size={16} /><span><strong>前置任务</strong><small>{pendingDependencies.length ? `${pendingDependencies.length} 项未完成` : "依赖已就绪"}</small></span></header>
            <div>{task.dependencies.map((dependency) => <Link to={`/tasks/${dependency.id}`} key={dependency.id}><span className={dependency.status === "completed" ? "done" : "pending"}>{dependency.status === "completed" ? <Check size={12} /> : <Clock3 size={12} />}</span><div><strong>{dependency.title}</strong><small>{statusLabel(dependency.status)}</small></div><ExternalLink size={12} /></Link>)}{!task.dependencies.length && <div className="v5-task-empty compact"><GitFork size={18} /><span>没有前置任务</span></div>}</div>
          </section>

          <section className="v5-task-local-note"><ShieldCheck size={16} /><div><strong>本地任务记录</strong><p>时间线、结果和关联会话保存在当前设备，不依赖 AgentBench 云端。</p></div></section>
        </aside>
      </main>
    </div>
  );
}
