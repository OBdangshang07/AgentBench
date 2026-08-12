import {
  Activity,
  ArrowLeft,
  Bot,
  Check,
  ExternalLink,
  FileCode2,
  FolderOpen,
  GitBranch,
  GitFork,
  ListTodo,
  MessageSquarePlus,
  Pencil,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useWorkspaceUx } from "../components/WorkspaceUx";
import { api } from "../lib/api";
import { openFolder } from "../lib/openPath";
import { useApi } from "../lib/useApi";
import type { ModelConfig, Runner } from "../types";
import type { AgentFlowSummary, AgentSession, PermissionProfile, Project, ProjectHealth, StudioTask } from "./types";

type DetailTab = "overview" | "sessions" | "tasks" | "flows" | "settings";

function relative(value: string | null | undefined) {
  if (!value) return "暂无活动";
  const elapsed = Math.max(0, Date.now() - new Date(value).getTime());
  if (elapsed < 60_000) return "刚刚";
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前`;
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} 小时前`;
  return new Date(value).toLocaleDateString("zh-CN");
}

export default function ProjectDetail() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const ux = useWorkspaceUx();
  const { data: project, loading, error, refresh } = useApi<Project>(projectId ? `/projects/${projectId}` : null, 8_000);
  const { data: health, refresh: refreshHealth } = useApi<ProjectHealth>(projectId ? `/projects/${projectId}/health` : null, 15_000);
  const { data: sessions } = useApi<AgentSession[]>(projectId ? `/sessions?project_id=${projectId}&limit=200` : null, 4_000);
  const { data: tasks } = useApi<StudioTask[]>(projectId ? `/tasks?project_id=${projectId}` : null, 4_000);
  const { data: flows } = useApi<AgentFlowSummary[]>(projectId ? `/flows?project_id=${projectId}` : null, 4_000);
  const { data: runners } = useApi<Runner[]>("/runners");
  const { data: models } = useApi<ModelConfig[]>("/models");
  const [tab, setTab] = useState<DetailTab>("overview");
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", default_runner_id: "", default_model_id: "", permission_profile: "workspace" as PermissionProfile });

  useEffect(() => {
    if (!project) return;
    ux.setSelectedProjectId(project.id);
    setForm({
      name: project.name,
      description: project.description,
      default_runner_id: project.default_runner_id ?? "",
      default_model_id: project.default_model_id ?? "",
      permission_profile: project.permission_profile,
    });
  }, [project?.id, project?.updated_at]);

  const stats = useMemo(() => ({
    running: sessions?.filter((item) => ["queued", "preparing", "running", "waiting_approval"].includes(item.status)).length ?? 0,
    openTasks: tasks?.filter((item) => !["completed", "cancelled"].includes(item.status)).length ?? 0,
    completed: tasks?.filter((item) => item.status === "completed").length ?? 0,
  }), [sessions, tasks]);

  async function startSession() {
    if (!project) return;
    try {
      const session = await api<{ id: string }>("/sessions", { method: "POST", body: JSON.stringify({ project_id: project.id, title: `${project.name} Agent 会话` }) });
      navigate(`/studio/${session.id}`);
    } catch (value) {
      ux.notify({ kind: "error", title: "无法创建会话", message: value instanceof Error ? value.message : "未知错误" });
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    setSaving(true);
    try {
      await api(`/projects/${project.id}`, { method: "PATCH", body: JSON.stringify(form) });
      await Promise.all([refresh(), refreshHealth()]);
      ux.notify({ kind: "success", title: "项目设置已保存", message: form.name });
    } catch (value) {
      ux.notify({ kind: "error", title: "无法保存项目", message: value instanceof Error ? value.message : "未知错误" });
    } finally {
      setSaving(false);
    }
  }

  async function archiveOrRestore() {
    if (!project) return;
    if (!project.archived) {
      const approved = await ux.confirm({ title: "归档这个项目？", message: "项目文件不会被删除，会话、任务与 Flow 也会保留。运行中的会话必须先停止。", confirmLabel: "归档项目", detail: project.root_path });
      if (!approved) return;
    }
    try {
      await api(`/projects/${project.id}`, { method: "PATCH", body: JSON.stringify({ archived: !project.archived }) });
      ux.notify({ kind: "success", title: project.archived ? "项目已恢复" : "项目已归档", message: project.name });
      if (project.archived) await refresh();
      else navigate("/projects");
    } catch (value) {
      ux.notify({ kind: "error", title: "无法更新项目状态", message: value instanceof Error ? value.message : "未知错误" });
    }
  }

  if (loading && !project) return <div className="v4-page"><div className="v4-empty"><RefreshCw className="spin" size={24} /><strong>正在读取项目工作区</strong></div></div>;
  if (error || !project) return <div className="v4-page"><div className="v4-error">{error || "项目不存在"}<button type="button" onClick={() => navigate("/projects")}>返回项目中心</button></div></div>;

  const tabs: Array<{ id: DetailTab; label: string; icon: typeof Activity }> = [
    { id: "overview", label: "概览", icon: Activity },
    { id: "sessions", label: `会话 ${sessions?.length ?? 0}`, icon: Bot },
    { id: "tasks", label: `任务 ${tasks?.length ?? 0}`, icon: ListTodo },
    { id: "flows", label: `Flow ${flows?.length ?? 0}`, icon: GitFork },
    { id: "settings", label: "设置", icon: Settings2 },
  ];

  return (
    <div className="v4-page v5-project-detail">
      <header className="v5-project-hero">
        <Link to="/projects" className="v5-back-link"><ArrowLeft size={15} />项目中心</Link>
        <div className="v5-project-identity"><span className="v4-project-logo">{project.name.slice(0, 2).toUpperCase()}</span><div><small>AUTHORIZED WORKSPACE</small><h1>{project.name}</h1><p>{project.description || "本地 Agent 工作区"}</p><code>{project.root_path}</code></div></div>
        <div className="v5-project-hero-actions"><button className="v4-button secondary" type="button" onClick={() => void openFolder(project.root_path)}><FolderOpen size={15} />打开目录</button><button className="v4-button primary" type="button" onClick={() => void startSession()}><MessageSquarePlus size={15} />新建会话</button></div>
        <div className="v5-project-badges"><span><ShieldCheck size={12} />{project.permission_profile}</span><span><GitBranch size={12} />{project.branch || "local workspace"}</span><span className={health?.ready ? "ready" : "warning"}><i />{health?.ready ? "环境就绪" : "需要检查"}</span></div>
      </header>

      <nav className="v5-detail-tabs">{tabs.map(({ id, label, icon: Icon }) => <button className={tab === id ? "active" : ""} type="button" key={id} onClick={() => setTab(id)}><Icon size={14} />{label}</button>)}</nav>

      {tab === "overview" && <div className="v5-project-overview">
        <section className="v5-project-stats"><article><strong>{stats.running}</strong><span>活跃 Agent</span></article><article><strong>{stats.openTasks}</strong><span>开放任务</span></article><article><strong>{stats.completed}</strong><span>已完成任务</span></article><article><strong>{project.pending_approvals}</strong><span>待审批</span></article></section>
        <section className="v4-panel v5-health-panel"><header className="v4-panel-head"><div><strong>项目环境</strong><small>目录、权限和默认运行配置</small></div><button className="v4-icon-button" type="button" onClick={() => void refreshHealth()}><RefreshCw size={14} /></button></header><div>{health?.checks.map((check) => <article key={check.id}><span className={check.ok ? "ok" : "bad"}>{check.ok ? <Check size={14} /> : <TriangleAlert size={14} />}</span><div><strong>{check.label}</strong><small>{check.detail}</small></div></article>)}</div></section>
        <section className="v4-panel v5-project-activity"><header className="v4-panel-head"><div><strong>最近会话</strong><small>项目内的 Agent 工作记录</small></div><button type="button" onClick={() => setTab("sessions")}>查看全部</button></header><div>{sessions?.slice(0, 5).map((session) => <button type="button" key={session.id} onClick={() => navigate(`/studio/${session.id}`)}><span className="v4-agent-avatar">{session.runner_name.slice(0, 2).toUpperCase()}</span><div><strong>{session.title}</strong><small>{session.runner_name} · {session.model_name}</small></div><em>{session.status}</em><time>{relative(session.updated_at)}</time></button>)}{!sessions?.length && <div className="v4-empty compact"><Bot size={21} /><strong>还没有项目会话</strong></div>}</div></section>
      </div>}

      {tab === "sessions" && <section className="v4-panel v5-detail-list"><header className="v4-panel-head"><div><strong>项目会话</strong><small>打开、继续或检查每个 Agent 会话</small></div><button className="v4-button primary" type="button" onClick={() => void startSession()}><MessageSquarePlus size={14} />新建会话</button></header>{sessions?.map((session) => <button key={session.id} type="button" onClick={() => navigate(`/studio/${session.id}`)}><span className="v4-agent-avatar">{session.runner_name.slice(0, 2).toUpperCase()}</span><div><strong>{session.title}</strong><small>{session.runner_name} · {session.model_name} · {session.turn_count} 轮</small></div><em>{session.status}</em><time>{relative(session.updated_at)}</time><ExternalLink size={14} /></button>)}{!sessions?.length && <div className="v4-empty"><Bot size={24} /><strong>还没有会话</strong></div>}</section>}

      {tab === "tasks" && <section className="v4-panel v5-detail-list"><header className="v4-panel-head"><div><strong>项目任务</strong><small>任务状态与最近结果</small></div><Link className="v4-button secondary" to={`/tasks?project=${project.id}`}><ListTodo size={14} />进入任务中心</Link></header>{tasks?.map((task) => <button key={task.id} type="button" onClick={() => navigate(`/tasks?task=${task.id}`)}><span className={`v5-task-state ${task.status}`}><ListTodo size={14} /></span><div><strong>{task.title}</strong><small>{task.result_summary || task.description || "尚无结果摘要"}</small></div><em>{task.status}</em><time>{relative(task.updated_at)}</time><ExternalLink size={14} /></button>)}{!tasks?.length && <div className="v4-empty"><ListTodo size={24} /><strong>还没有任务</strong></div>}</section>}

      {tab === "flows" && <section className="v4-panel v5-detail-list"><header className="v4-panel-head"><div><strong>项目 Flow</strong><small>多 Agent 自动化编排</small></div><Link className="v4-button secondary" to={`/flows?project=${project.id}`}><GitFork size={14} />进入 Flow</Link></header>{flows?.map((flow) => <button key={flow.id} type="button" onClick={() => navigate(`/flows?flow=${flow.id}`)}><span className="v5-task-state"><GitFork size={14} /></span><div><strong>{flow.name}</strong><small>{flow.description || `${flow.node_count} 个节点`}</small></div><em>{flow.status}</em><time>{relative(flow.updated_at)}</time><ExternalLink size={14} /></button>)}{!flows?.length && <div className="v4-empty"><GitFork size={24} /><strong>还没有 Flow</strong></div>}</section>}

      {tab === "settings" && <form className="v4-panel v5-project-settings" onSubmit={save}><header className="v4-panel-head"><div><strong>项目设置</strong><small>默认配置会应用到新会话和任务</small></div><Pencil size={15} /></header><div className="v4-form-grid"><label><span>项目名称</span><input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label><span>权限配置</span><select value={form.permission_profile} onChange={(event) => setForm({ ...form, permission_profile: event.target.value as PermissionProfile })}><option value="readonly">只读</option><option value="workspace">工作区读写</option><option value="standard">标准开发</option><option value="full">完全访问</option></select></label><label className="full"><span>项目说明</span><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label><span>默认 Agent</span><select value={form.default_runner_id} onChange={(event) => setForm({ ...form, default_runner_id: event.target.value })}>{runners?.filter((item) => item.enabled).map((runner) => <option key={runner.id} value={runner.id}>{runner.name}</option>)}</select></label><label><span>默认模型</span><select value={form.default_model_id} onChange={(event) => setForm({ ...form, default_model_id: event.target.value })}>{models?.filter((item) => item.enabled).map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label><label className="full"><span>授权目录</span><input value={project.root_path} disabled /><small>修改项目根目录需要重新授权，当前版本不会静默移动项目范围。</small></label></div><footer><button className="v4-button danger" type="button" disabled={project.active_sessions > 0} onClick={() => void archiveOrRestore()}>{project.archived ? "恢复项目" : "归档项目"}</button><button className="v4-button primary" type="submit" disabled={saving}><Save size={14} />{saving ? "保存中…" : "保存设置"}</button></footer></form>}
    </div>
  );
}
