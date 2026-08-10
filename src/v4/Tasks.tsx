import { Bot, Check, CircleStop, Clock3, ExternalLink, ListTodo, Plus, ShieldAlert, X } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { ModelConfig, Runner } from "../types";
import type { Project, StudioTask } from "./types";

const columns: Array<{ status: StudioTask["status"]; title: string }> = [
  { status: "backlog", title: "待处理" },
  { status: "running", title: "执行中" },
  { status: "approval", title: "等待审批" },
  { status: "completed", title: "已完成" },
];

export default function Tasks() {
  const navigate = useNavigate();
  const { data: tasks, refresh } = useApi<StudioTask[]>("/tasks", 3_000);
  const { data: projects } = useApi<Project[]>("/projects");
  const { data: runners } = useApi<Runner[]>("/runners");
  const { data: models } = useApi<ModelConfig[]>("/models");
  const [modalOpen, setModalOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ project_id: "", title: "", description: "", priority: "normal", runner_id: "", model_id: "" });
  const summary = useMemo(() => ({
    completed: tasks?.filter((task) => task.status === "completed").length ?? 0,
    running: tasks?.filter((task) => task.status === "running").length ?? 0,
    approval: tasks?.filter((task) => task.status === "approval").length ?? 0,
  }), [tasks]);

  function openCreate() {
    const project = projects?.[0];
    setForm({ project_id: project?.id ?? "", title: "", description: "", priority: "normal", runner_id: project?.default_runner_id ?? runners?.find((item) => item.enabled)?.id ?? "", model_id: project?.default_model_id ?? models?.find((item) => item.enabled)?.id ?? "" });
    setModalOpen(true);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/tasks", { method: "POST", body: JSON.stringify({ ...form, project_id: form.project_id || null, runner_id: form.runner_id || null, model_id: form.model_id || null }) });
      setModalOpen(false);
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "创建任务失败");
    }
  }

  async function start(task: StudioTask) {
    setError(null);
    try {
      await api(`/tasks/${task.id}/start`, { method: "POST" });
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法启动 Agent 任务");
    }
  }

  async function cancel(task: StudioTask) {
    await api(`/tasks/${task.id}/cancel`, { method: "POST" });
    await refresh();
  }

  return (
    <div className="v4-page">
      <header className="v4-page-head"><div><span>AGENT TASK QUEUE</span><h1>任务中心</h1><p>用看板管理人工任务、Agent 运行、审批和自动化队列。</p></div><div><button className="v4-button primary" type="button" onClick={openCreate}><Plus size={16} />新建任务</button></div></header>
      <section className="v4-task-summary"><article className="main"><span><Check size={24} /></span><div><strong>已完成 {summary.completed} 个 Agent 任务</strong><p>任务状态来自本机持久化队列</p></div></article><article><strong>{String(summary.running).padStart(2, "0")}</strong><span>正在执行</span></article><article><strong>{String(summary.approval).padStart(2, "0")}</strong><span>待审批</span></article><article><strong>{tasks?.length ?? 0}</strong><span>全部任务</span></article></section>
      <section className="v4-kanban">
        {columns.map((column) => {
          const items = tasks?.filter((task) => task.status === column.status || (column.status === "backlog" && task.status === "queued")) ?? [];
          return <article className="v4-kanban-column" key={column.status}><header><span><i />{column.title}</span><b>{items.length}</b></header><div>{items.map((task) => <section className={`v4-task-card ${task.status}`} key={task.id}><header><code>{task.id.slice(0, 8).toUpperCase()}</code><span>{task.priority}</span></header><h3>{task.title}</h3><p>{task.description || "尚未填写任务说明。"}</p><div><span>{task.runner_name || "未分配 Agent"}</span><span>{task.model_name || "自动模型"}</span></div><footer><span className="v4-agent-avatar">{task.runner_name?.slice(0, 2).toUpperCase() || "AI"}</span>{column.status === "backlog" && <button type="button" onClick={() => void start(task)}><Bot size={13} />启动 Agent</button>}{(column.status === "running" || column.status === "approval") && <><button type="button" onClick={() => task.session_id && navigate(`/studio/${task.session_id}`)} disabled={!task.session_id}><ExternalLink size={13} />查看</button><button type="button" onClick={() => void cancel(task)}><CircleStop size={13} />停止</button></>}{column.status === "completed" && <>{task.session_id && <button type="button" onClick={() => navigate(`/studio/${task.session_id}`)}><ExternalLink size={13} />结果</button>}<time><Clock3 size={12} />{new Date(task.updated_at).toLocaleDateString()}</time></>}</footer></section>)}{!items.length && <div className="v4-kanban-empty">暂无任务</div>}</div></article>;
        })}
      </section>
      {modalOpen && <div className="v4-modal-backdrop" onMouseDown={() => setModalOpen(false)}><form className="v4-modal small" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}><header><div><strong>新建任务</strong><small>为项目安排一个可追踪的 Agent 工作项</small></div><button type="button" onClick={() => setModalOpen(false)}><X size={18} /></button></header><div className="v4-form-grid"><label className="full"><span>任务标题</span><input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label><label className="full"><span>任务说明</span><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label><span>项目</span><select value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })}><option value="">跨项目</option>{projects?.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><label><span>优先级</span><select value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value })}><option value="low">低</option><option value="normal">普通</option><option value="high">高</option><option value="urgent">紧急</option></select></label><label><span>Agent</span><select value={form.runner_id} onChange={(event) => setForm({ ...form, runner_id: event.target.value })}><option value="">稍后分配</option>{runners?.filter((item) => item.enabled).map((runner) => <option key={runner.id} value={runner.id}>{runner.name}</option>)}</select></label><label><span>模型</span><select value={form.model_id} onChange={(event) => setForm({ ...form, model_id: event.target.value })}><option value="">稍后分配</option>{models?.filter((item) => item.enabled).map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label></div>{error && <div className="v4-error">{error}</div>}<footer><button className="v4-button secondary" type="button" onClick={() => setModalOpen(false)}>取消</button><button className="v4-button primary" type="submit"><ListTodo size={16} />创建任务</button></footer></form></div>}
    </div>
  );
}
