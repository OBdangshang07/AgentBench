import {
  Archive,
  Bot,
  CalendarClock,
  Check,
  CheckSquare2,
  CircleStop,
  Copy,
  ExternalLink,
  Filter,
  GitFork,
  Grid2X2,
  ListTodo,
  Pencil,
  Plus,
  RefreshCw,
  Rows3,
  Search,
  Square,
  Tag,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useWorkspaceUx } from "../components/WorkspaceUx";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { ModelConfig, Runner } from "../types";
import type { Project, StudioTask } from "./types";

type TaskStatus = StudioTask["status"];
type ViewMode = "board" | "list";

const columns: Array<{ id: string; statuses: TaskStatus[]; title: string; detail: string }> = [
  { id: "backlog", statuses: ["backlog", "queued"], title: "待处理", detail: "计划与排队" },
  { id: "running", statuses: ["running"], title: "执行中", detail: "Agent 正在工作" },
  { id: "approval", statuses: ["approval"], title: "等待审批", detail: "需要人工决定" },
  { id: "completed", statuses: ["completed"], title: "已完成", detail: "可查看结果" },
  { id: "attention", statuses: ["failed", "cancelled"], title: "需要处理", detail: "失败或已取消" },
];

const emptyForm = {
  project_id: "",
  title: "",
  description: "",
  priority: "normal",
  runner_id: "",
  model_id: "",
  due_at: "",
  tags: "",
  depends_on: [] as string[],
  acceptance_criteria: "",
};

const activeStatuses: TaskStatus[] = ["queued", "running", "approval"];

export function taskStatusLabel(status: TaskStatus) {
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

function priorityLabel(priority: StudioTask["priority"]) {
  return ({ low: "低", normal: "普通", high: "高", urgent: "紧急" })[priority];
}

function shortDate(value: string | null) {
  if (!value) return "未设置";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function Tasks() {
  const navigate = useNavigate();
  const ux = useWorkspaceUx();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: tasks, loading, error: loadError, refresh } = useApi<StudioTask[]>("/tasks", 3_000);
  const { data: projects } = useApi<Project[]>("/projects");
  const { data: runners } = useApi<Runner[]>("/runners");
  const { data: models } = useApi<ModelConfig[]>("/models");
  const [query, setQuery] = useState("");
  const [projectFilter, setProjectFilter] = useState(searchParams.get("project") || ux.selectedProjectId || "all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [viewMode, setViewMode] = useState<ViewMode>(() => window.localStorage.getItem("agentbench.tasks.view.v1") === "list" ? "list" : "board");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({ ...emptyForm });
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);

  const selectedFromUrl = searchParams.get("task");
  const createRequested = searchParams.get("new") === "1";
  const selectedTask = tasks?.find((task) => task.id === editingId) ?? null;
  const taskById = useMemo(() => new Map((tasks ?? []).map((task) => [task.id, task])), [tasks]);

  function pendingDependencyCount(task: StudioTask) {
    return task.depends_on.filter((id) => taskById.get(id)?.status !== "completed").length;
  }

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (tasks ?? []).filter((task) => {
      if (needle && !`${task.title} ${task.description} ${task.project_name ?? ""} ${task.tags.join(" ")}`.toLowerCase().includes(needle)) return false;
      if (projectFilter !== "all" && task.project_id !== projectFilter) return false;
      if (priorityFilter !== "all" && task.priority !== priorityFilter) return false;
      if (statusFilter !== "all" && task.status !== statusFilter) return false;
      return true;
    });
  }, [priorityFilter, projectFilter, query, statusFilter, tasks]);

  const summary = useMemo(() => ({
    completed: tasks?.filter((task) => task.status === "completed").length ?? 0,
    running: tasks?.filter((task) => task.status === "running").length ?? 0,
    approval: tasks?.filter((task) => task.status === "approval").length ?? 0,
    attention: tasks?.filter((task) => ["failed", "cancelled"].includes(task.status)).length ?? 0,
  }), [tasks]);

  const allVisibleSelected = visible.length > 0 && visible.every((task) => selectedIds.has(task.id));

  useEffect(() => {
    window.localStorage.setItem("agentbench.tasks.view.v1", viewMode);
  }, [viewMode]);

  useEffect(() => {
    if (!selectedFromUrl || modalOpen || !tasks) return;
    const task = tasks.find((item) => item.id === selectedFromUrl);
    if (task) openEdit(task);
  }, [modalOpen, selectedFromUrl, tasks]);

  useEffect(() => {
    if (!createRequested || !projects) return;
    openCreate();
  }, [createRequested, projects]);

  function openCreate() {
    const project = projects?.find((item) => item.id === ux.selectedProjectId) ?? projects?.[0];
    setEditingId(null);
    setSearchParams({}, { replace: true });
    setForm({
      ...emptyForm,
      project_id: project?.id ?? "",
      runner_id: project?.default_runner_id ?? runners?.find((item) => item.enabled)?.id ?? "",
      model_id: project?.default_model_id ?? models?.find((item) => item.enabled)?.id ?? "",
    });
    setFormError(null);
    setModalOpen(true);
  }

  function openEdit(task: StudioTask) {
    setEditingId(task.id);
    setSearchParams({ task: task.id }, { replace: true });
    setForm({
      project_id: task.project_id ?? "",
      title: task.title,
      description: task.description,
      priority: task.priority,
      runner_id: task.runner_id ?? "",
      model_id: task.model_id ?? "",
      due_at: task.due_at ? task.due_at.slice(0, 16) : "",
      tags: task.tags.join(", "),
      depends_on: task.depends_on,
      acceptance_criteria: (task.acceptance_criteria ?? []).map((item) => item.text).join("\n"),
    });
    setFormError(null);
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
    setEditingId(null);
    setSearchParams({}, { replace: true });
  }

  function toggleSelected(taskId: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  }

  function toggleAllVisible() {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (allVisibleSelected) visible.forEach((task) => next.delete(task.id));
      else visible.forEach((task) => next.add(task.id));
      return next;
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setSaving(true);
    const previousCriteria = new Map((selectedTask?.acceptance_criteria ?? []).map((item) => [item.text, item.completed]));
    const payload = {
      ...form,
      project_id: form.project_id || null,
      runner_id: form.runner_id || null,
      model_id: form.model_id || null,
      due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
      tags: form.tags.split(/[,，]/).map((item) => item.trim()).filter(Boolean),
      acceptance_criteria: form.acceptance_criteria
        .split(/\r?\n/)
        .map((text) => text.trim())
        .filter(Boolean)
        .map((text) => ({ text, completed: previousCriteria.get(text) ?? false })),
    };
    try {
      if (editingId) await api(`/tasks/${editingId}`, { method: "PATCH", body: JSON.stringify(payload) });
      else await api("/tasks", { method: "POST", body: JSON.stringify(payload) });
      const wasEditing = Boolean(editingId);
      closeModal();
      await refresh();
      ux.notify({ kind: "success", title: wasEditing ? "任务已更新" : "任务已创建", message: form.title });
    } catch (value) {
      setFormError(value instanceof Error ? value.message : "无法保存任务");
    } finally {
      setSaving(false);
    }
  }

  async function start(task: StudioTask) {
    try {
      await api(`/tasks/${task.id}/start`, { method: "POST" });
      await refresh();
      ux.notify({ kind: "success", title: "任务已交给 Agent", message: task.title });
    } catch (value) {
      const message = value instanceof Error ? value.message : "未知错误";
      ux.notify({ kind: "error", title: "无法启动任务", message: message.includes("task_dependencies_incomplete") ? "前置任务尚未全部完成" : message });
    }
  }

  async function cancel(task: StudioTask) {
    const approved = await ux.confirm({ title: "停止正在执行的任务？", message: "Agent 会收到取消信号，已经产生的会话和文件变更仍会保留。", confirmLabel: "停止任务", tone: "danger", detail: task.title });
    if (!approved) return;
    try {
      await api(`/tasks/${task.id}/cancel`, { method: "POST" });
      await refresh();
      ux.notify({ kind: "warning", title: "任务已取消", message: task.title });
    } catch (value) {
      ux.notify({ kind: "error", title: "无法取消任务", message: value instanceof Error ? value.message : "未知错误" });
    }
  }

  async function duplicate(task: StudioTask) {
    try {
      const created = await api<StudioTask>(`/tasks/${task.id}/duplicate`, { method: "POST" });
      await refresh();
      ux.notify({ kind: "success", title: "任务副本已创建", message: created.title });
    } catch (value) {
      ux.notify({ kind: "error", title: "无法复制任务", message: value instanceof Error ? value.message : "未知错误" });
    }
  }

  async function archive(task: StudioTask) {
    const approved = await ux.confirm({ title: "归档这个任务？", message: "任务记录和关联会话会保留，但不会继续显示在当前看板。", confirmLabel: "归档", detail: task.title });
    if (!approved) return;
    try {
      await api(`/tasks/${task.id}`, { method: "DELETE" });
      setSelectedIds((current) => new Set([...current].filter((id) => id !== task.id)));
      await refresh();
      ux.notify({ kind: "success", title: "任务已归档", message: task.title });
    } catch (value) {
      ux.notify({ kind: "error", title: "无法归档任务", message: value instanceof Error ? value.message : "未知错误" });
    }
  }

  async function runBulk(action: "archive" | "duplicate" | "set_priority" | "set_status", value?: string) {
    const taskIds = [...selectedIds];
    if (!taskIds.length) return;
    if (action === "archive") {
      const approved = await ux.confirm({ title: `归档 ${taskIds.length} 个任务？`, message: "正在运行或等待审批的任务会保留，并在操作结果中标明。", confirmLabel: "批量归档" });
      if (!approved) return;
    }
    setBulkBusy(true);
    try {
      const result = await api<{ updated: StudioTask[]; errors: Array<{ task_id: string; error: string }> }>("/tasks/bulk", {
        method: "POST",
        body: JSON.stringify({ task_ids: taskIds, action, value: value || null }),
      });
      setSelectedIds(new Set(result.errors.map((item) => item.task_id).filter((id) => taskById.has(id))));
      await refresh();
      ux.notify({
        kind: result.errors.length ? "warning" : "success",
        title: result.errors.length ? "批量操作部分完成" : "批量操作已完成",
        message: `${result.updated.length} 个成功${result.errors.length ? `，${result.errors.length} 个未处理` : ""}`,
      });
    } catch (value) {
      ux.notify({ kind: "error", title: "批量操作失败", message: value instanceof Error ? value.message : "未知错误" });
    } finally {
      setBulkBusy(false);
    }
  }

  async function moveTask(task: StudioTask, target: string) {
    let next: TaskStatus | null = null;
    if (target === "backlog" && ["completed", "failed", "cancelled"].includes(task.status)) next = "backlog";
    if (target === "completed" && task.status === "backlog") next = "completed";
    if (!next) {
      ux.notify({ kind: "info", title: "此状态需要由 Agent 运行产生", message: "执行中、等待审批和失败状态不能手动拖入。" });
      return;
    }
    await api(`/tasks/${task.id}`, { method: "PATCH", body: JSON.stringify({ status: next }) });
    await refresh();
  }

  function taskSelection(task: StudioTask) {
    return (
      <button
        className={`v5-task-select ${selectedIds.has(task.id) ? "selected" : ""}`}
        type="button"
        aria-label={selectedIds.has(task.id) ? `取消选择 ${task.title}` : `选择 ${task.title}`}
        onClick={(event) => { event.stopPropagation(); toggleSelected(task.id); }}
      >
        {selectedIds.has(task.id) ? <CheckSquare2 size={15} /> : <Square size={15} />}
      </button>
    );
  }

  function taskActions(task: StudioTask) {
    return (
      <>
        {(task.status === "backlog" || task.status === "failed" || task.status === "cancelled") && (
          <button type="button" disabled={pendingDependencyCount(task) > 0} title={pendingDependencyCount(task) ? "请先完成前置任务" : undefined} onClick={() => void start(task)}>
            <Bot size={13} />{task.status === "backlog" ? "启动" : "重试"}
          </button>
        )}
        {activeStatuses.includes(task.status) && (
          <>
            <button type="button" onClick={() => task.session_id && navigate(`/studio/${task.session_id}`)} disabled={!task.session_id}><ExternalLink size={13} />会话</button>
            <button type="button" onClick={() => void cancel(task)}><CircleStop size={13} />停止</button>
          </>
        )}
        {task.status === "completed" && task.session_id && <button type="button" onClick={() => navigate(`/studio/${task.session_id}`)}><ExternalLink size={13} />结果</button>}
      </>
    );
  }

  return (
    <div className="v4-page v5-tasks-page">
      <header className="v4-page-head">
        <div><span>AGENT TASK QUEUE</span><h1>任务中心</h1><p>从计划、执行、审批到结果回溯，在一个工作区管理完整的 Agent 生命周期。</p></div>
        <div><button className="v4-button primary" type="button" onClick={openCreate}><Plus size={16} />新建任务</button></div>
      </header>

      <section className="v4-task-summary">
        <article className="main"><span><Check size={24} /></span><div><strong>已完成 {summary.completed} 个 Agent 任务</strong><p>结果、变更和运行记录均保存在本机</p></div></article>
        <article><strong>{String(summary.running).padStart(2, "0")}</strong><span>正在执行</span></article>
        <article><strong>{String(summary.approval).padStart(2, "0")}</strong><span>待审批</span></article>
        <article className={summary.attention ? "attention" : ""}><strong>{String(summary.attention).padStart(2, "0")}</strong><span>需要处理</span></article>
      </section>

      <section className="v4-panel v5-task-filters">
        <label className="search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务、项目或标签" /></label>
        <label><Filter size={13} /><select aria-label="筛选项目" value={projectFilter} onChange={(event) => { setProjectFilter(event.target.value); if (event.target.value !== "all") ux.setSelectedProjectId(event.target.value); }}><option value="all">全部项目</option>{projects?.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select></label>
        <label><select aria-label="筛选状态" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">全部状态</option>{["backlog", "queued", "running", "approval", "completed", "failed", "cancelled"].map((status) => <option value={status} key={status}>{taskStatusLabel(status as TaskStatus)}</option>)}</select></label>
        <label><select aria-label="筛选优先级" value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}><option value="all">全部优先级</option><option value="urgent">紧急</option><option value="high">高</option><option value="normal">普通</option><option value="low">低</option></select></label>
        <span>{visible.length} / {tasks?.length ?? 0} 个任务</span>
        <div className="v5-task-view-toggle" aria-label="任务视图">
          <button type="button" className={viewMode === "board" ? "active" : ""} onClick={() => setViewMode("board")} title="看板视图"><Grid2X2 size={14} /></button>
          <button type="button" className={viewMode === "list" ? "active" : ""} onClick={() => setViewMode("list")} title="列表视图"><Rows3 size={15} /></button>
        </div>
      </section>

      <section className={`v5-task-bulkbar ${selectedIds.size ? "visible" : ""}`} aria-hidden={!selectedIds.size}>
        <button type="button" onClick={toggleAllVisible}>{allVisibleSelected ? <CheckSquare2 size={15} /> : <Square size={15} />}选择当前结果</button>
        <strong>{selectedIds.size} 个已选择</strong>
        <span />
        <button type="button" disabled={bulkBusy} onClick={() => void runBulk("duplicate")}><Copy size={14} />复制</button>
        <label>优先级<select disabled={bulkBusy} defaultValue="" onChange={(event) => { if (event.target.value) void runBulk("set_priority", event.target.value); event.target.value = ""; }}><option value="">修改…</option><option value="urgent">紧急</option><option value="high">高</option><option value="normal">普通</option><option value="low">低</option></select></label>
        <label>状态<select disabled={bulkBusy} defaultValue="" onChange={(event) => { if (event.target.value) void runBulk("set_status", event.target.value); event.target.value = ""; }}><option value="">修改…</option><option value="backlog">待处理</option><option value="completed">已完成</option></select></label>
        <button type="button" disabled={bulkBusy} onClick={() => void runBulk("archive")}><Archive size={14} />归档</button>
        <button type="button" onClick={() => setSelectedIds(new Set())} aria-label="清除选择"><X size={15} /></button>
      </section>

      {loadError && <div className="v4-error">{loadError}<button type="button" onClick={() => void refresh()}>重试</button></div>}

      {viewMode === "board" ? (
        <section className="v4-kanban v5-kanban">
          {columns.map((column) => {
            const items = visible.filter((task) => column.statuses.includes(task.status));
            return (
              <article className={`v4-kanban-column ${column.id}`} key={column.id} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { const task = tasks?.find((item) => item.id === event.dataTransfer.getData("text/task-id")); if (task) void moveTask(task, column.id); }}>
                <header><span><i />{column.title}<small>{column.detail}</small></span><b>{items.length}</b></header>
                <div>{items.map((task) => (
                  <section className={`v4-task-card ${task.status} ${selectedIds.has(task.id) ? "selected" : ""}`} key={task.id} draggable={!activeStatuses.includes(task.status)} onDragStart={(event) => event.dataTransfer.setData("text/task-id", task.id)}>
                    <header>{taskSelection(task)}<code>{task.id.slice(0, 8).toUpperCase()}</code><span>{priorityLabel(task.priority)}</span></header>
                    <button className="v5-task-open" type="button" onClick={() => navigate(`/tasks/${task.id}`)}><h3>{task.title}</h3><p>{task.description || "尚未填写任务说明。"}</p></button>
                    {!!task.acceptance_criteria?.length && <div className="v5-task-acceptance-mini"><CheckSquare2 size={11} />{task.acceptance_criteria.filter((item) => item.completed).length}/{task.acceptance_criteria.length} 项验收标准</div>}
                    {!!task.tags.length && <div className="v5-task-tags">{task.tags.slice(0, 3).map((item) => <span key={item}><Tag size={10} />{item}</span>)}</div>}
                    {!!task.depends_on.length && <div className={`v5-task-dependency-state ${pendingDependencyCount(task) ? "blocked" : "ready"}`}><GitFork size={11} />{pendingDependencyCount(task) ? `${pendingDependencyCount(task)} 个前置任务未完成` : "前置任务已完成"}</div>}
                    <div><span>{task.runner_name || "未分配 Agent"}</span><span>{task.model_name || "自动模型"}</span></div>
                    {task.result_summary && <blockquote>{task.result_summary}</blockquote>}
                    <footer>
                      <span className="v4-agent-avatar">{task.runner_name?.slice(0, 2).toUpperCase() || "AI"}</span>
                      {taskActions(task)}
                      <details><summary aria-label="更多任务操作">•••</summary><div><button type="button" onClick={() => openEdit(task)}><Pencil size={12} />编辑</button><button type="button" onClick={() => void duplicate(task)}><Copy size={12} />复制</button><button type="button" disabled={activeStatuses.includes(task.status)} onClick={() => void archive(task)}><Archive size={12} />归档</button></div></details>
                      {task.due_at && <time><CalendarClock size={11} />{shortDate(task.due_at)}</time>}
                    </footer>
                  </section>
                ))}{!items.length && <div className="v4-kanban-empty">{loading ? <RefreshCw className="spin" size={16} /> : "暂无任务"}</div>}</div>
              </article>
            );
          })}
        </section>
      ) : (
        <section className="v4-panel v5-task-list">
          <header><button type="button" onClick={toggleAllVisible}>{allVisibleSelected ? <CheckSquare2 size={15} /> : <Square size={15} />}</button><span>任务</span><span>状态</span><span>项目 / Agent</span><span>更新</span><span>操作</span></header>
          <div>{visible.map((task) => (
            <article className={selectedIds.has(task.id) ? "selected" : ""} key={task.id}>
              {taskSelection(task)}
              <button className="v5-task-list-title" type="button" onClick={() => navigate(`/tasks/${task.id}`)}><strong>{task.title}</strong><small>{task.description || "尚未填写任务说明"}</small></button>
              <span className={`v5-task-status ${task.status}`}>{taskStatusLabel(task.status)}</span>
              <span><strong>{task.project_name || "跨项目"}</strong><small>{task.runner_name || "未分配 Agent"} · {task.model_name || "自动模型"}</small></span>
              <time>{shortDate(task.updated_at)}</time>
              <div>{taskActions(task)}<button type="button" onClick={() => openEdit(task)} title="编辑"><Pencil size={13} /></button></div>
            </article>
          ))}{!visible.length && <div className="v4-kanban-empty">{loading ? <RefreshCw className="spin" size={16} /> : "没有符合筛选条件的任务"}</div>}</div>
        </section>
      )}

      {modalOpen && (
        <div className="v4-modal-backdrop" onMouseDown={closeModal}>
          <form className="v4-modal v5-task-modal" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}>
            <header><div><strong>{editingId ? "编辑任务" : "新建任务"}</strong><small>任务说明决定要做什么，验收标准决定怎样才算完成</small></div><button type="button" onClick={closeModal}><X size={18} /></button></header>
            <div className="v4-form-grid">
              <label className="full"><span>任务标题</span><input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
              <label className="full"><span>任务说明</span><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="说明目标、范围与关键约束" /></label>
              <label className="full v5-acceptance-input"><span>验收标准 <small>每行一项</small></span><textarea value={form.acceptance_criteria} onChange={(event) => setForm({ ...form, acceptance_criteria: event.target.value })} placeholder={"核心路径通过自动化测试\n关键操作具有明确反馈\n不修改任务范围外的文件"} /></label>
              <label><span>项目</span><select value={form.project_id} onChange={(event) => { const project = projects?.find((item) => item.id === event.target.value); setForm({ ...form, project_id: event.target.value, runner_id: project?.default_runner_id ?? form.runner_id, model_id: project?.default_model_id ?? form.model_id }); }}><option value="">跨项目</option>{projects?.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
              <label><span>优先级</span><select value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value })}><option value="low">低</option><option value="normal">普通</option><option value="high">高</option><option value="urgent">紧急</option></select></label>
              <label><span>Agent</span><select value={form.runner_id} onChange={(event) => setForm({ ...form, runner_id: event.target.value })}><option value="">使用项目默认值</option>{runners?.filter((item) => item.enabled).map((runner) => <option key={runner.id} value={runner.id}>{runner.name}</option>)}</select></label>
              <label><span>模型</span><select value={form.model_id} onChange={(event) => setForm({ ...form, model_id: event.target.value })}><option value="">使用项目默认值</option>{models?.filter((item) => item.enabled).map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
              <label><span>截止时间</span><input type="datetime-local" value={form.due_at} onChange={(event) => setForm({ ...form, due_at: event.target.value })} /></label>
              <label><span>标签</span><input value={form.tags} onChange={(event) => setForm({ ...form, tags: event.target.value })} placeholder="前端, 高优先级" /></label>
              <fieldset className="full v5-dependency-picker"><legend>前置任务</legend>{(tasks ?? []).filter((task) => task.id !== editingId && (!form.project_id || task.project_id === form.project_id)).slice(0, 12).map((task) => <label key={task.id}><input type="checkbox" checked={form.depends_on.includes(task.id)} onChange={(event) => setForm({ ...form, depends_on: event.target.checked ? [...form.depends_on, task.id] : form.depends_on.filter((id) => id !== task.id) })} /><span>{task.title}<small>{taskStatusLabel(task.status)}</small></span></label>)}{!tasks?.length && <small>当前没有可选择的前置任务</small>}</fieldset>
              {selectedTask?.result_summary && <section className="full v5-task-result"><strong>最近结果</strong><p>{selectedTask.result_summary}</p>{selectedTask.session_id && <button type="button" onClick={() => navigate(`/studio/${selectedTask.session_id}`)}><ExternalLink size={13} />打开关联会话</button>}</section>}
            </div>
            {formError && <div className="v4-error">{formError}</div>}
            <footer><button className="v4-button secondary" type="button" onClick={closeModal}>取消</button><button className="v4-button primary" type="submit" disabled={saving}><ListTodo size={16} />{saving ? "保存中…" : editingId ? "保存任务" : "创建任务"}</button></footer>
          </form>
        </div>
      )}
    </div>
  );
}
