import {
  Archive,
  Bot,
  ExternalLink,
  FolderGit2,
  FolderOpen,
  GitBranch,
  MessageSquarePlus,
  MoreHorizontal,
  Pin,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import { useWorkspaceUx } from "../components/WorkspaceUx";
import type { ModelConfig, Runner } from "../types";
import type { PermissionProfile, Project } from "./types";

interface ProjectForm {
  name: string;
  description: string;
  root_path: string;
  default_runner_id: string;
  default_model_id: string;
  permission_profile: PermissionProfile;
}

const initialForm: ProjectForm = {
  name: "",
  description: "",
  root_path: "",
  default_runner_id: "",
  default_model_id: "",
  permission_profile: "workspace",
};

export default function Projects() {
  const navigate = useNavigate();
  const ux = useWorkspaceUx();
  const { data: projects, loading, error, refresh } = useApi<Project[]>("/projects?include_archived=true");
  const { data: runners } = useApi<Runner[]>("/runners");
  const { data: models } = useApi<ModelConfig[]>("/models");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "recent" | "running" | "archived">("all");
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<ProjectForm>(initialForm);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!modalOpen) return;
    setForm((current) => ({
      ...current,
      default_runner_id: current.default_runner_id || runners?.find((runner) => runner.enabled)?.id || "",
      default_model_id: current.default_model_id || models?.find((model) => model.enabled)?.id || "",
    }));
  }, [modalOpen, runners, models]);

  const visible = useMemo(() => (projects ?? []).filter((project) => {
    const matches = `${project.name} ${project.description} ${project.root_path}`.toLowerCase().includes(query.trim().toLowerCase());
    if (!matches) return false;
    if (filter === "archived") return project.archived;
    if (project.archived) return false;
    if (filter === "running") return project.active_sessions > 0;
    if (filter === "recent") return Boolean(project.last_opened_at && Date.now() - new Date(project.last_opened_at).getTime() <= 30 * 86_400_000);
    return true;
  }), [filter, projects, query]);

  function openCreate() {
    setForm({
      ...initialForm,
      default_runner_id: runners?.find((runner) => runner.enabled)?.id ?? "",
      default_model_id: models?.find((model) => model.enabled)?.id ?? "",
    });
    setFormError(null);
    setModalOpen(true);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const payload = {
        ...form,
        default_runner_id: form.default_runner_id || runners?.find((runner) => runner.enabled)?.id || "",
        default_model_id: form.default_model_id || models?.find((model) => model.enabled)?.id || "",
      };
      if (!payload.default_runner_id || !payload.default_model_id) {
        throw new Error("请先配置至少一个可用 Agent 和模型");
      }
      await api<Project>("/projects", { method: "POST", body: JSON.stringify(payload) });
      setModalOpen(false);
      await refresh();
    } catch (value) {
      setFormError(value instanceof Error ? value.message : "无法创建项目");
    } finally {
      setSubmitting(false);
    }
  }

  async function chooseProjectRoot() {
    setFormError(null);
    if (!isTauri()) {
      setFormError("原生目录选择器仅在 AgentBench 桌面客户端中可用；浏览器预览时可以手动输入路径。");
      return;
    }
    try {
      const selected = await open({
        directory: true,
        multiple: false,
        title: "选择允许 Agent 访问的项目根目录",
      });
      if (typeof selected === "string") {
        setForm((current) => ({
          ...current,
          root_path: selected,
          name: current.name || selected.split(/[\\/]/).filter(Boolean).at(-1) || "本地项目",
        }));
      }
    } catch (value) {
      setFormError(value instanceof Error ? value.message : "无法打开目录选择器");
    }
  }

  async function startSession(project: Project) {
    const session = await api<{ id: string }>("/sessions", {
      method: "POST",
      body: JSON.stringify({ project_id: project.id, title: `${project.name} Agent 会话` }),
    });
    navigate(`/studio/${session.id}`);
  }

  async function togglePin(project: Project) {
    await api(`/projects/${project.id}`, { method: "PATCH", body: JSON.stringify({ pinned: !project.pinned }) });
    await refresh();
  }

  async function archive(project: Project) {
    const approved = await ux.confirm({ title: "归档这个项目？", message: "项目文件不会被删除，会话、任务和 Flow 也会继续保留。", confirmLabel: "归档项目", detail: project.name });
    if (!approved) return;
    try {
      await api(`/projects/${project.id}`, { method: "DELETE" });
      await refresh();
      ux.notify({ kind: "success", title: "项目已归档", message: project.name });
    } catch (value) {
      ux.notify({ kind: "error", title: "无法归档项目", message: value instanceof Error ? value.message : "未知错误" });
    }
  }

  async function restore(project: Project) {
    try {
      await api(`/projects/${project.id}`, { method: "PATCH", body: JSON.stringify({ archived: false }) });
      await refresh();
      ux.notify({ kind: "success", title: "项目已恢复", message: project.name });
    } catch (value) {
      ux.notify({ kind: "error", title: "无法恢复项目", message: value instanceof Error ? value.message : "未知错误" });
    }
  }

  return (
    <div className="v4-page">
      <header className="v4-page-head">
        <div><span>AUTHORIZED WORKSPACES</span><h1>项目中心</h1><p>每个项目都有独立的授权目录、会话、权限规则与 Agent 配置。</p></div>
        <div><button className="v4-button primary" type="button" onClick={openCreate}><Plus size={16} />新建项目</button></div>
      </header>

      <section className="v4-panel v4-filter-bar">
        <label><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目、目录或分支" /></label>
        <div>{(["all", "recent", "running", "archived"] as const).map((value) => <button key={value} className={filter === value ? "active" : ""} type="button" onClick={() => setFilter(value)}>{value === "all" ? "全部" : value === "recent" ? "最近" : value === "running" ? "运行中" : "已归档"}</button>)}</div>
        <span>{visible.length} 个已授权目录</span>
      </section>

      {error && <div className="v4-error">{error}<button type="button" onClick={() => void refresh()}>重试</button></div>}
      <section className="v4-project-grid">
        {visible.map((project) => (
          <article key={project.id} className={`v4-project-card v4-panel${project.pinned ? " featured" : ""}${project.archived ? " archived" : ""}`}>
            <header><span className="v4-project-logo">{project.name.slice(0, 2).toUpperCase()}</span><div><button className="v5-project-name" type="button" onClick={() => navigate(`/projects/${project.id}`)}>{project.name}</button><code>{project.root_path}</code></div><button type="button" title={project.pinned ? "取消置顶" : "置顶"} onClick={() => void togglePin(project)}>{project.pinned ? <Pin size={16} fill="currentColor" /> : <MoreHorizontal size={17} />}</button></header>
            <p>{project.description || "本地 Agent 工作区，所有文件操作都限制在已授权项目根目录内。"}</p>
            <div className="v4-project-tags"><span><ShieldCheck size={12} />{project.permission_profile}</span>{project.branch && <span><GitBranch size={12} />{project.branch}</span>}{project.active_sessions > 0 && <span className="live"><i />{project.active_sessions} RUNNING</span>}</div>
            <dl><div><dt>{project.session_count}</dt><dd>会话</dd></div><div><dt>{project.active_sessions}</dt><dd>活跃 Agent</dd></div><div><dt>{project.pending_approvals}</dt><dd>待审批</dd></div></dl>
            <footer><span><GitBranch size={13} />{project.branch || "local workspace"}</span><div><button type="button" title="项目详情" onClick={() => navigate(`/projects/${project.id}`)}><ExternalLink size={15} /></button>{project.archived ? <button type="button" title="恢复项目" onClick={() => void restore(project)}><RotateCcw size={15} />恢复</button> : <><button type="button" title="归档项目" onClick={() => void archive(project)}><Archive size={15} /></button><button className="primary" type="button" onClick={() => void startSession(project)}><MessageSquarePlus size={15} />Agent 会话</button></>}</div></footer>
          </article>
        ))}
        <button className="v4-add-project v4-panel" type="button" onClick={openCreate}><span><FolderGit2 size={24} /></span><strong>添加本地项目</strong><small>授权一个目录供 Agent 操作</small></button>
      </section>
      {!loading && !visible.length && projects?.length ? <div className="v4-empty"><Search size={26} /><strong>没有匹配项目</strong><span>清除搜索词或切换筛选条件</span></div> : null}

      {modalOpen && (
        <div className="v4-modal-backdrop" onMouseDown={() => setModalOpen(false)}>
          <form className="v4-modal" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}>
            <header><div><strong>新建本地项目</strong><small>Agent 只能访问你明确授权的项目目录</small></div><button type="button" onClick={() => setModalOpen(false)}><X size={18} /></button></header>
            <div className="v4-form-grid">
              <label><span>项目名称</span><input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如 AgentBench Desktop" /></label>
              <label className="full" htmlFor="v4-project-root"><span>项目根目录</span><div className="v4-path-picker"><input id="v4-project-root" aria-label="项目根目录" required value={form.root_path} onChange={(event) => setForm({ ...form, root_path: event.target.value })} placeholder="D:\Projects\MyProject" /><button type="button" onClick={() => void chooseProjectRoot()}><FolderOpen size={16} />浏览…</button></div><small>选择一个项目文件夹进行授权；磁盘根目录和越界路径会被拒绝。</small></label>
              <label className="full"><span>项目说明</span><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="告诉 Agent 这个项目的用途与边界" /></label>
              <label><span>默认 Agent</span><select required value={form.default_runner_id} onChange={(event) => setForm({ ...form, default_runner_id: event.target.value })}>{runners?.filter((runner) => runner.enabled).map((runner) => <option key={runner.id} value={runner.id}>{runner.name}{runner.capability.installed ? "" : "（未安装）"}</option>)}</select></label>
              <label><span>默认模型</span><select required value={form.default_model_id} onChange={(event) => setForm({ ...form, default_model_id: event.target.value })}>{models?.filter((model) => model.enabled).map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
              <label className="full"><span>权限配置</span><select value={form.permission_profile} onChange={(event) => setForm({ ...form, permission_profile: event.target.value as PermissionProfile })}><option value="readonly">只读</option><option value="workspace">工作区读写</option><option value="standard">标准开发</option><option value="full">完全访问</option></select></label>
            </div>
            {formError && <div className="v4-error">{formError}</div>}
            <footer><button className="v4-button secondary" type="button" onClick={() => setModalOpen(false)}>取消</button><button className="v4-button primary" type="submit" disabled={submitting}><Bot size={16} />{submitting ? "正在创建…" : "创建并授权"}</button></footer>
          </form>
        </div>
      )}
    </div>
  );
}
