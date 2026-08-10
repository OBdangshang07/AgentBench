import { Bot, Check, CircleStop, GitFork, Hand, Play, Plus, ShieldAlert, Split, Wrench, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { AgentFlow as AgentFlowData, AgentFlowSummary, Project } from "./types";

const library = [
  { type: "agent", name: "Agent 任务", detail: "选择任意 Agent 与模型", icon: Bot },
  { type: "approval", name: "人工审批", detail: "等待用户确认后继续", icon: Hand },
  { type: "condition", name: "条件分支", detail: "按结构化结果分流", icon: Split },
  { type: "tool", name: "MCP 工具", detail: "调用已连接工具网关", icon: Wrench },
];

const libraryGroups = [
  { label: "AGENTS", items: library.slice(0, 2) },
  { label: "CONTROL", items: library.slice(2, 3) },
  { label: "TOOLS", items: library.slice(3) },
];

export default function AgentFlow() {
  const { data: flows, refresh: refreshFlows } = useApi<AgentFlowSummary[]>("/flows", 4_000);
  const { data: projects } = useApi<Project[]>("/projects");
  const [selectedId, setSelectedId] = useState<string>();
  const { data: selected } = useApi<AgentFlowData>(selectedId ? `/flows/${selectedId}` : null, 3_000);
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState({ project_id: "", name: "", description: "" });
  const [error, setError] = useState<string | null>(null);
  const active = selected?.status === "running" || selected?.status === "waiting_approval" || selected?.status === "cancelling";

  useEffect(() => {
    if (!selectedId && flows?.length) setSelectedId(flows[0].id);
  }, [flows, selectedId]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const flow = await api<AgentFlowData>("/flows", { method: "POST", body: JSON.stringify({ ...form, project_id: form.project_id || null, settings: { max_retries: 1, max_concurrency: 2, max_runtime_seconds: 2700, max_cost_usd: 3, max_tokens: 500000 }, nodes: [{ id: "plan", type: "agent", name: "任务规划", x: 50, y: 175, config: { prompt: "分析项目与目标，给出可执行的实现计划，并指出需要修改的文件。" } }, { id: "build-a", type: "agent", name: "并行实现 A", x: 340, y: 75, config: { prompt: "依据上游计划完成第一部分实现，运行相关验证。" } }, { id: "build-b", type: "agent", name: "并行实现 B", x: 340, y: 275, config: { prompt: "依据上游计划独立完成第二部分实现，运行相关验证。" } }, { id: "review", type: "approval", name: "审查与合并", x: 650, y: 175, config: { description: "两个隔离 worktree 的变更已安全合并，请确认是否继续。" } }], edges: [{ source: "plan", target: "build-a" }, { source: "plan", target: "build-b" }, { source: "build-a", target: "review" }, { source: "build-b", target: "review" }] }) });
      setSelectedId(flow.id);
      setModalOpen(false);
      await refreshFlows();
    } catch (value) {
      setError(value instanceof Error ? value.message : "创建工作流失败");
    }
  }

  async function toggleRun() {
    if (!selected) return;
    setError(null);
    try {
      await api(`/flows/${selected.id}/${active ? "cancel" : "run"}`, { method: "POST" });
      await refreshFlows();
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法运行工作流");
    }
  }

  return (
    <div className="v4-flow-workbench">
      <aside className="v4-flow-library"><header><strong>节点库</strong><small>DRAG TO ADD</small></header>{libraryGroups.map((group) => <section key={group.label}><label>{group.label}</label>{group.items.map(({ name, detail, icon: Icon }) => <button key={name} type="button"><span><Icon size={16} /></span><div><strong>{name}</strong><small>{detail}</small></div></button>)}</section>)}</aside>
      <section className="v4-flow-canvas"><header><div><strong>{selected?.name ?? "选择或创建 Agent Flow"}</strong><small>{selected?.status ?? "DRAFT"} · {selected?.nodes.length ?? 0} NODES</small></div><span className={`v4-status ${selected?.status === "failed" ? "amber" : "green"}`}><i />{selected?.status?.toUpperCase() ?? "READY"}</span><button className={`v4-button ${active ? "secondary" : "primary"}`} type="button" disabled={!selected} onClick={() => void toggleRun()}>{active ? <CircleStop size={16} /> : <Play size={16} />}{active ? "停止工作流" : "运行工作流"}</button><button className="v4-icon-button" type="button" onClick={() => { setForm({ project_id: projects?.[0]?.id ?? "", name: "", description: "" }); setModalOpen(true); }}><Plus size={17} /></button></header>{error && <div className="v4-flow-error">{error}</div>}<div className="v4-flow-grid">{selected?.edges.map((edge) => {
        const source = selected.nodes.find((node) => node.id === edge.source_node_id); const target = selected.nodes.find((node) => node.id === edge.target_node_id); if (!source || !target) return null; const x1 = source.position_x + 112; const y1 = source.position_y + 50; const x2 = target.position_x + 112; const y2 = target.position_y + 50; return <svg key={edge.id} className="v4-flow-edge"><path d={`M ${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`} /></svg>;
      })}{selected?.nodes.map((node, index) => <article key={node.id} className={`v4-flow-node ${node.node_type} ${node.status}`} style={{ left: node.position_x, top: node.position_y }}><header><span>{node.node_type === "approval" ? <ShieldAlert size={16} /> : <Bot size={16} />}</span><div><strong>{node.name}</strong><small>{node.node_type.toUpperCase()} · TRY {node.attempts}</small></div><i /></header><footer><span>{node.error_message || node.status}</span><b>{String(index + 1).padStart(2, "0")}</b></footer></article>)}{!selected && <div className="v4-empty"><GitFork size={30} /><strong>还没有 Agent Flow</strong><span>创建一个由多个 Agent、条件和人工审批组成的工作流</span><button className="v4-button primary" type="button" onClick={() => setModalOpen(true)}><Plus size={16} />新建工作流</button></div>}</div><footer><span><i />状态、节点输出与会话已持久化到本地数据库</span><div><button type="button">−</button><b>100%</b><button type="button">＋</button></div></footer></section>
      <aside className="v4-flow-inspector"><header><strong>流程设置</strong><small>{selected ? "FLOW SELECTED" : "NO SELECTION"}</small></header><section><label>已有工作流</label>{flows?.map((flow) => <button className={flow.id === selectedId ? "active" : ""} key={flow.id} type="button" onClick={() => setSelectedId(flow.id)}><GitFork size={14} /><span><strong>{flow.name}</strong><small>{flow.node_count} 个节点 · {flow.project_name || "跨项目"}</small></span></button>)}</section><section><label>执行约束</label><div className="v4-flow-setting"><span><strong>失败时自动重试</strong><small>最多重试 {Number(selected?.settings.max_retries ?? 1)} 次</small></span><i className="on" /></div><div className="v4-flow-setting"><span><strong>并行隔离与安全合并</strong><small>同层 Agent 使用 Git worktree</small></span><i className="on" /></div><div className="v4-flow-setting"><span><strong>等待人工确认</strong><small>审批节点会真实暂停 DAG</small></span><i className="on" /></div></section><section><label>FLOW BUDGET</label><dl><div><dt>最大用时</dt><dd>{Math.round(Number(selected?.settings.max_runtime_seconds ?? 2700) / 60)} min</dd></div><div><dt>费用预算</dt><dd>${Number(selected?.settings.max_cost_usd ?? 3).toFixed(2)}</dd></div><div><dt>并发 Agent</dt><dd>{String(selected?.settings.max_concurrency ?? 4).padStart(2, "0")}</dd></div><div><dt>失败策略</dt><dd>STOP</dd></div></dl></section></aside>
      {modalOpen && <div className="v4-modal-backdrop" onMouseDown={() => setModalOpen(false)}><form className="v4-modal small" onSubmit={create} onMouseDown={(event) => event.stopPropagation()}><header><div><strong>新建 Agent Flow</strong><small>从可编辑模板建立一个真实流程图</small></div><button type="button" onClick={() => setModalOpen(false)}><X size={18} /></button></header><div className="v4-form-grid"><label className="full"><span>工作流名称</span><input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label className="full"><span>所属项目</span><select value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })}><option value="">跨项目</option>{projects?.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><label className="full"><span>说明</span><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label></div>{error && <div className="v4-error">{error}</div>}<footer><button className="v4-button secondary" type="button" onClick={() => setModalOpen(false)}>取消</button><button className="v4-button primary" type="submit"><Check size={16} />创建模板</button></footer></form></div>}
    </div>
  );
}
