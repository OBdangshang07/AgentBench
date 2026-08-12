import { Bot, Check, Copy, Gauge, Plus, ShieldCheck, Sparkles, Trash2, Wrench, X } from "lucide-react";
import { FormEvent, useState } from "react";
import { useWorkspaceUx } from "../components/WorkspaceUx";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { ModelConfig, Runner } from "../types";
import type { McpServer, PermissionProfile, ReasoningEffort, RuntimeProfile, SkillPack } from "./types";

interface ProfileForm {
  name: string;
  description: string;
  runner_id: string;
  model_id: string;
  permission_profile: PermissionProfile;
  reasoning_effort: ReasoningEffort;
  skill_pack_id: string;
  mcp_server_ids: string[];
}

const emptyForm: ProfileForm = {
  name: "",
  description: "",
  runner_id: "",
  model_id: "",
  permission_profile: "workspace",
  reasoning_effort: "medium",
  skill_pack_id: "",
  mcp_server_ids: [],
};

const permissionLabel: Record<PermissionProfile, string> = {
  readonly: "只读",
  workspace: "工作区",
  standard: "标准开发",
  full: "完全访问",
};

const effortLabel: Record<ReasoningEffort, string> = {
  low: "低",
  medium: "中",
  high: "高",
  xhigh: "极高",
  max: "最大",
};

export default function RuntimeProfilesPanel() {
  const ux = useWorkspaceUx();
  const { data: profiles, refresh } = useApi<RuntimeProfile[]>("/runtime-profiles", 8_000);
  const { data: runners } = useApi<Runner[]>("/runners", 10_000);
  const { data: models } = useApi<ModelConfig[]>("/models", 10_000);
  const { data: skills } = useApi<SkillPack[]>("/skill-packs", 10_000);
  const { data: servers } = useApi<McpServer[]>("/mcp-servers", 10_000);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<RuntimeProfile | null>(null);
  const [form, setForm] = useState<ProfileForm>(emptyForm);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function openProfile(profile?: RuntimeProfile, duplicate = false) {
    setEditing(profile && !duplicate ? profile : null);
    setForm(profile ? {
      name: duplicate ? `${profile.name} · 副本` : profile.name,
      description: profile.description,
      runner_id: profile.runner_id ?? "",
      model_id: profile.model_id ?? "",
      permission_profile: profile.permission_profile,
      reasoning_effort: profile.reasoning_effort,
      skill_pack_id: profile.skill_pack_id ?? "",
      mcp_server_ids: profile.mcp_server_ids,
    } : emptyForm);
    setError(null);
    setOpen(true);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(editing ? `/runtime-profiles/${editing.id}` : "/runtime-profiles", {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify({
          ...form,
          runner_id: form.runner_id || null,
          model_id: form.model_id || null,
          skill_pack_id: form.skill_pack_id || null,
        }),
      });
      await refresh();
      setOpen(false);
      ux.notify({ kind: "success", title: editing ? "运行 Profile 已更新" : "运行 Profile 已创建", message: form.name });
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法保存运行 Profile");
    } finally {
      setBusy(false);
    }
  }

  async function remove(profile: RuntimeProfile) {
    if (profile.builtin || !await ux.confirm({
      title: "删除运行 Profile？",
      message: `“${profile.name}”将不再出现在新会话和 Flow 中。`,
      detail: "已有会话会保留当时实际使用的 Agent、模型与权限。",
      confirmLabel: "删除 Profile",
      tone: "danger",
    })) return;
    await api(`/runtime-profiles/${profile.id}`, { method: "DELETE" });
    await refresh();
    ux.notify({ kind: "success", title: "运行 Profile 已删除", message: profile.name });
  }

  return <>
    <section className="v4-panel v5-runtime-profiles">
      <header className="v4-panel-head"><div><strong>运行 Profile</strong><small>一键复用 Agent、模型、权限、思考强度、能力包与 MCP 组合</small></div><button type="button" onClick={() => openProfile()}><Plus size={13} />新建 Profile</button></header>
      <div>
        {profiles?.map((profile) => <article key={profile.id}>
          <header><span><Gauge size={16} /></span><div><strong>{profile.name}</strong><small>{profile.builtin ? "BUILTIN" : "CUSTOM"}</small></div></header>
          <p>{profile.description || "复用一组稳定的 Agent 运行参数。"}</p>
          <dl><div><dt><Bot size={11} />运行时</dt><dd>{profile.runner_name || "跟随项目"}</dd></div><div><dt><Sparkles size={11} />模型</dt><dd>{profile.model_name || "跟随项目"}</dd></div><div><dt><ShieldCheck size={11} />权限</dt><dd>{permissionLabel[profile.permission_profile]}</dd></div><div><dt><Gauge size={11} />思考</dt><dd>{effortLabel[profile.reasoning_effort]}</dd></div></dl>
          <footer><span>{profile.skill_pack_name || "无能力包"} · {profile.mcp_server_ids.length} MCP</span><div>{profile.builtin ? <button type="button" onClick={() => openProfile(profile, true)}><Copy size={12} />复制</button> : <><button type="button" onClick={() => openProfile(profile)}><Wrench size={12} />编辑</button><button className="danger" type="button" onClick={() => void remove(profile)}><Trash2 size={12} /></button></>}</div></footer>
        </article>)}
      </div>
    </section>

    {open && <div className="v4-modal-backdrop" onMouseDown={() => setOpen(false)}><form className="v4-modal" onSubmit={save} onMouseDown={(event) => event.stopPropagation()}><header><div><strong>{editing ? "编辑运行 Profile" : "创建运行 Profile"}</strong><small>Profile 只保存配置引用，不保存 API 密钥</small></div><button type="button" onClick={() => setOpen(false)}><X size={18} /></button></header><div className="v4-form-grid">
      <label className="full"><span>名称</span><input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：深度代码实现" /></label>
      <label className="full"><span>说明</span><input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="说明适用任务和限制" /></label>
      <label><span>Agent</span><select value={form.runner_id} onChange={(event) => setForm({ ...form, runner_id: event.target.value })}><option value="">跟随项目默认</option>{runners?.filter((item) => item.enabled).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label><span>模型</span><select value={form.model_id} onChange={(event) => setForm({ ...form, model_id: event.target.value })}><option value="">跟随项目默认</option>{models?.filter((item) => item.enabled).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label><span>权限</span><select value={form.permission_profile} onChange={(event) => setForm({ ...form, permission_profile: event.target.value as PermissionProfile })}><option value="readonly">只读</option><option value="workspace">工作区</option><option value="standard">标准开发</option><option value="full">完全访问</option></select></label>
      <label><span>思考强度</span><select value={form.reasoning_effort} onChange={(event) => setForm({ ...form, reasoning_effort: event.target.value as ReasoningEffort })}><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">极高</option><option value="max">最大</option></select></label>
      <label className="full"><span>能力包</span><select value={form.skill_pack_id} onChange={(event) => setForm({ ...form, skill_pack_id: event.target.value })}><option value="">不使用能力包</option>{skills?.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.description}</option>)}</select></label>
      <fieldset className="full v5-profile-mcp"><legend>MCP Server</legend><p>只会启用当前 Profile 勾选的额外工具；凭据仍由系统凭据存储管理。</p><div>{servers?.filter((item) => item.enabled).map((server) => <label key={server.id}><input type="checkbox" checked={form.mcp_server_ids.includes(server.id)} onChange={(event) => setForm({ ...form, mcp_server_ids: event.target.checked ? [...form.mcp_server_ids, server.id] : form.mcp_server_ids.filter((item) => item !== server.id) })} /><i>{form.mcp_server_ids.includes(server.id) && <Check size={10} />}</i><span><strong>{server.name}</strong><small>{server.tools.length} 个工具 · {server.health_status}</small></span></label>)}</div></fieldset>
    </div>{error && <div className="v4-error">{error}</div>}<footer><button className="v4-button secondary" type="button" onClick={() => setOpen(false)}>取消</button><button className="v4-button primary" type="submit" disabled={busy}><Gauge size={15} />{busy ? "保存中…" : "保存 Profile"}</button></footer></form></div>}
  </>;
}
