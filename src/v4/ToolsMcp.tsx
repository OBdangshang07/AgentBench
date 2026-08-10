import { Bot, Check, Database, Globe2, HardDrive, Plus, ServerCog, TerminalSquare, Wrench, X } from "lucide-react";
import { FormEvent, useState } from "react";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { Runner } from "../types";
import type { McpServer } from "./types";

const builtins = [
  { name: "Filesystem", detail: "受项目根目录限制的文件读取、搜索、写入和 Diff。", icon: HardDrive, status: "ONLINE" },
  { name: "Git Workspace", detail: "分支、worktree、状态、Diff、检查点和安全回滚。", icon: Database, status: "ONLINE" },
  { name: "Browser", detail: "网页导航、DOM 检查、截图和用户接管浏览器。", icon: Globe2, status: "ONLINE" },
  { name: "Terminal", detail: "带审批、进程树管理和敏感信息过滤的交互终端。", icon: TerminalSquare, status: "APPROVAL" },
];

export default function ToolsMcp() {
  const { data: servers, refresh } = useApi<McpServer[]>("/mcp-servers", 5_000);
  const { data: runners } = useApi<Runner[]>("/runners", 10_000);
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [form, setForm] = useState({ name: "", transport: "stdio", command: "", args: "", url: "" });
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/mcp-servers", { method: "POST", body: JSON.stringify({ name: form.name, transport: form.transport, command: form.transport === "stdio" ? form.command : null, args: form.args.split(/\s+/).filter(Boolean), url: form.transport === "stdio" ? null : form.url, env: {} }) });
      setOpen(false);
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法添加 MCP Server");
    }
  }

  async function checkHealth(serverId?: string) {
    setChecking(true);
    setError(null);
    try {
      await api(serverId ? `/mcp-servers/${serverId}/health` : "/mcp-servers/health", { method: "POST" });
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "MCP 健康检查失败");
    } finally {
      setChecking(false);
    }
  }

  return <div className="v4-page"><header className="v4-page-head"><div><span>TOOL GATEWAY</span><h1>工具与 MCP</h1><p>统一管理平台工具、MCP Server、Skills，以及不同 Agent 的能力兼容情况。</p></div><div><button className="v4-button secondary" type="button" onClick={() => void checkHealth()} disabled={checking}><Check size={16} />{checking ? "检查中…" : "运行健康检查"}</button><button className="v4-button primary" type="button" onClick={() => { setForm({ name: "", transport: "stdio", command: "", args: "", url: "" }); setOpen(true); }}><Plus size={16} />添加 MCP Server</button></div></header>{error && <div className="v4-error">{error}</div>}<section className="v4-tools-grid"><article className="v4-panel v4-tool-gateway"><header className="v4-panel-head"><div><strong>平台工具网关</strong><small>本地运行 · 按项目授权</small></div><span className="v4-status green"><i />{builtins.length + (servers?.filter((item) => item.health_status === "online").length ?? 0)} CONNECTED</span></header><div className="v4-tool-cards">{builtins.map(({ name, detail, icon: Icon, status }) => <section key={name}><header><span><Icon size={19} /></span><div><strong>{name}</strong><small>builtin://{name.toLowerCase().replace(" ", "-")}</small></div><b className={status === "ONLINE" ? "online" : "approval"}><i />{status}</b></header><p>{detail}</p><footer><span>项目级权限</span><button type="button">配置</button></footer></section>)}{servers?.map((server) => <section key={server.id}><header><span><ServerCog size={19} /></span><div><strong>{server.name}</strong><small>{server.transport}://{server.command || server.url}</small></div><b className={server.health_status === "online" ? "online" : server.health_status === "offline" ? "offline" : "approval"}><i />{server.health_status?.toUpperCase() || "UNKNOWN"}</b></header><p>{server.last_error || (server.transport === "stdio" ? `${server.command} ${server.args.join(" ")}` : server.url)}</p><footer><span>{server.tools?.length ?? 0} 个工具 · {server.env_keys.length} 个凭据</span><button type="button" onClick={() => void checkHealth(server.id)}>检查</button></footer></section>)}</div></article><article className="v4-panel v4-skills-panel"><header className="v4-panel-head"><div><strong>Skills 与模板</strong><small>项目级能力包</small></div><button type="button">管理</button></header><div>{["代码审查", "前端实现", "数据迁移", "发布前验证", "创建能力包"].map((name, index) => <section key={name}><span>{index === 4 ? <Plus size={15} /> : <Wrench size={15} />}</span><div><strong>{name}</strong><small>{index === 4 ? "提示词、工具和权限组合" : "安全、正确性与可测试性"}</small></div><b>{index === 4 ? "NEW" : `${3 + index} AGENTS`}</b></section>)}</div></article></section><section className="v4-panel v4-capability-panel"><header className="v4-panel-head"><div><strong>Agent 能力矩阵</strong><small>UI 根据真实适配器能力提供原生或降级体验</small></div><span>LAST PROBE / LIVE</span></header><div><table><thead><tr><th>AGENT ADAPTER</th><th>适配模式</th><th>已安装</th><th>多轮</th><th>结构化事件</th><th>MCP</th><th>模型覆盖</th><th>状态</th></tr></thead><tbody>{runners?.map((runner) => <tr key={runner.id}><td><Bot size={14} />{runner.name}</td><td><code>{runner.runner_type === "unified" ? "UNIFIED API" : "NATIVE CLI"}</code></td><td>{runner.capability.installed ? "● 已安装" : "○ 未安装"}</td><td>{runner.adapter?.native_resume ? "● 原生恢复" : "◐ 历史重放"}</td><td>{runner.adapter?.structured_events === "full" ? "● 完整" : runner.adapter?.structured_events === "stream" ? "● 流式" : "◐ 过滤输出"}</td><td>{runner.adapter?.mcp ? "● 原生" : "◐ 平台网关"}</td><td>{runner.adapter?.model_override ? "● 支持" : "◐ CLI 决定"}</td><td><span className={`v4-status ${runner.capability.installed ? "green" : "amber"}`}><i />{runner.capability.installed ? "READY" : "SETUP"}</span></td></tr>)}</tbody></table></div></section>{open && <div className="v4-modal-backdrop" onMouseDown={() => setOpen(false)}><form className="v4-modal small" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}><header><div><strong>添加 MCP Server</strong><small>敏感环境变量将保存到系统凭据存储</small></div><button type="button" onClick={() => setOpen(false)}><X size={18} /></button></header><div className="v4-form-grid"><label className="full"><span>名称</span><input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label className="full"><span>传输方式</span><select value={form.transport} onChange={(event) => setForm({ ...form, transport: event.target.value })}><option value="stdio">stdio</option><option value="sse">SSE</option><option value="streamable_http">Streamable HTTP</option></select></label>{form.transport === "stdio" ? <><label className="full"><span>命令</span><input required value={form.command} onChange={(event) => setForm({ ...form, command: event.target.value })} placeholder="npx" /></label><label className="full"><span>参数</span><input value={form.args} onChange={(event) => setForm({ ...form, args: event.target.value })} placeholder="-y @modelcontextprotocol/server-filesystem" /></label></> : <label className="full"><span>Server URL</span><input required type="url" value={form.url} onChange={(event) => setForm({ ...form, url: event.target.value })} /></label>}</div>{error && <div className="v4-error">{error}</div>}<footer><button className="v4-button secondary" type="button" onClick={() => setOpen(false)}>取消</button><button className="v4-button primary" type="submit"><ServerCog size={16} />保存 Server</button></footer></form></div>}</div>;
}
