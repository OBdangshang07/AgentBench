import {
  Bot,
  Check,
  CircleStop,
  GitFork,
  Hand,
  Link2,
  Play,
  Plus,
  Save,
  ShieldAlert,
  Split,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { AgentFlow as AgentFlowData, AgentFlowSummary, McpServer, Project } from "./types";

type NodeType = "agent" | "approval" | "condition" | "tool";

interface DraftNode {
  id: string;
  node_type: NodeType;
  name: string;
  position_x: number;
  position_y: number;
  config: Record<string, unknown>;
  status: string;
  attempts: number;
  error_message: string | null;
}

interface DraftEdge {
  id: string;
  source_node_id: string;
  target_node_id: string;
  condition: Record<string, unknown>;
}

interface FlowDraft {
  name: string;
  description: string;
  settings: Record<string, unknown>;
  nodes: DraftNode[];
  edges: DraftEdge[];
}

const library = [
  { type: "agent" as const, name: "Agent 任务", detail: "选择任意 Agent 与模型", icon: Bot },
  { type: "approval" as const, name: "人工审批", detail: "等待用户确认后继续", icon: Hand },
  { type: "condition" as const, name: "条件分支", detail: "依据上游结构化结果分流", icon: Split },
  { type: "tool" as const, name: "MCP 工具", detail: "调用已连接的工具网关", icon: Wrench },
];

const libraryGroups = [
  { label: "AGENTS", items: library.slice(0, 2) },
  { label: "CONTROL", items: library.slice(2, 3) },
  { label: "TOOLS", items: library.slice(3) },
];

const nodeLabels: Record<NodeType, string> = {
  agent: "Agent 任务",
  approval: "人工审批",
  condition: "条件分支",
  tool: "MCP 工具",
};

function draftFromFlow(flow: AgentFlowData): FlowDraft {
  return {
    name: flow.name,
    description: flow.description,
    settings: { parallel_worktrees: true, ...flow.settings },
    nodes: flow.nodes.map((node) => ({
      id: node.id,
      node_type: node.node_type as NodeType,
      name: node.name,
      position_x: node.position_x,
      position_y: node.position_y,
      config: { ...node.config },
      status: node.status,
      attempts: node.attempts,
      error_message: node.error_message,
    })),
    edges: flow.edges.map((edge) => ({
      id: edge.id,
      source_node_id: edge.source_node_id,
      target_node_id: edge.target_node_id,
      condition: { ...edge.condition },
    })),
  };
}

function nodeIcon(type: NodeType) {
  if (type === "approval") return <ShieldAlert size={16} />;
  if (type === "condition") return <Split size={16} />;
  if (type === "tool") return <Wrench size={16} />;
  return <Bot size={16} />;
}

export default function AgentFlow() {
  const { data: flows, refresh: refreshFlows } = useApi<AgentFlowSummary[]>("/flows", 4_000);
  const { data: projects } = useApi<Project[]>("/projects");
  const { data: servers } = useApi<McpServer[]>("/mcp-servers", 5_000);
  const [selectedId, setSelectedId] = useState<string>();
  const { data: selected, refresh: refreshSelected } = useApi<AgentFlowData>(selectedId ? `/flows/${selectedId}` : null, 3_000);
  const [draft, setDraft] = useState<FlowDraft | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string>();
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState({ project_id: "", name: "", description: "" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const canvasRef = useRef<HTMLDivElement>(null);
  const active = selected?.status === "running" || selected?.status === "waiting_approval" || selected?.status === "cancelling";
  const selectedNode = draft?.nodes.find((node) => node.id === selectedNodeId);

  useEffect(() => {
    if (!selectedId && flows?.length) setSelectedId(flows[0].id);
  }, [flows, selectedId]);

  useEffect(() => {
    if (!selected) return;
    setDraft(draftFromFlow(selected));
    setSelectedNodeId((current) => selected.nodes.some((node) => node.id === current) ? current : selected.nodes[0]?.id);
  }, [selected?.id, selected?.updated_at]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const flow = await api<AgentFlowData>("/flows", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          settings: {
            max_retries: 1,
            max_concurrency: 2,
            max_runtime_seconds: 2700,
            max_cost_usd: 3,
            max_tokens: 500000,
            parallel_worktrees: true,
          },
          nodes: [
            { id: "plan", type: "agent", name: "任务规划", x: 60, y: 160, config: { prompt: "分析项目与目标，给出可执行计划。" } },
            { id: "review", type: "approval", name: "人工确认", x: 390, y: 160, config: { description: "请检查上游结果并确认继续。" } },
          ],
          edges: [{ source: "plan", target: "review" }],
        }),
      });
      setSelectedId(flow.id);
      setDraft(draftFromFlow(flow));
      setSelectedNodeId(flow.nodes[0]?.id);
      setModalOpen(false);
      await refreshFlows();
    } catch (value) {
      setError(value instanceof Error ? value.message : "创建工作流失败");
    }
  }

  async function save() {
    if (!selected || !draft || active) return;
    setSaving(true);
    setError(null);
    try {
      await api(`/flows/${selected.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: draft.name,
          description: draft.description,
          settings: draft.settings,
          nodes: draft.nodes.map((node) => ({
            id: node.id,
            type: node.node_type,
            name: node.name,
            x: node.position_x,
            y: node.position_y,
            config: node.config,
          })),
          edges: draft.edges.map((edge) => ({
            source: edge.source_node_id,
            target: edge.target_node_id,
            condition: edge.condition,
          })),
        }),
      });
      await Promise.all([refreshSelected(), refreshFlows()]);
    } catch (value) {
      setError(value instanceof Error ? value.message : "保存工作流失败");
    } finally {
      setSaving(false);
    }
  }

  async function removeFlow() {
    if (!selected || active || !window.confirm(`删除工作流“${selected.name}”？`)) return;
    setError(null);
    try {
      await api(`/flows/${selected.id}`, { method: "DELETE" });
      setSelectedId(undefined);
      setDraft(null);
      setSelectedNodeId(undefined);
      await refreshFlows();
    } catch (value) {
      setError(value instanceof Error ? value.message : "删除工作流失败");
    }
  }

  async function toggleRun() {
    if (!selected) return;
    setError(null);
    try {
      if (!active) await save();
      await api(`/flows/${selected.id}/${active ? "cancel" : "run"}`, { method: "POST" });
      await Promise.all([refreshSelected(), refreshFlows()]);
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法运行工作流");
    }
  }

  function addNode(type: NodeType) {
    if (!draft || active) return;
    const index = draft.nodes.length;
    const id = `draft-${Date.now()}-${index}`;
    const config = type === "agent"
      ? { prompt: "描述该 Agent 节点需要完成的任务。" }
      : type === "approval"
        ? { description: "检查上游结果并确认是否继续。" }
        : type === "condition"
          ? { operator: "contains", value: "success" }
          : { server_id: "", tool_name: "", arguments: {} };
    setDraft({
      ...draft,
      nodes: [...draft.nodes, {
        id,
        node_type: type,
        name: nodeLabels[type],
        position_x: 70 + (index % 3) * 280,
        position_y: 80 + Math.floor(index / 3) * 170,
        config,
        status: "pending",
        attempts: 0,
        error_message: null,
      }],
    });
    setSelectedNodeId(id);
  }

  function updateNode(changes: Partial<DraftNode>) {
    if (!draft || !selectedNode || active) return;
    setDraft({
      ...draft,
      nodes: draft.nodes.map((node) => node.id === selectedNode.id ? { ...node, ...changes } : node),
    });
  }

  function updateNodeConfig(key: string, value: unknown) {
    if (!selectedNode) return;
    updateNode({ config: { ...selectedNode.config, [key]: value } });
  }

  function removeNode() {
    if (!draft || !selectedNode || draft.nodes.length <= 1 || active) return;
    setDraft({
      ...draft,
      nodes: draft.nodes.filter((node) => node.id !== selectedNode.id),
      edges: draft.edges.filter((edge) => edge.source_node_id !== selectedNode.id && edge.target_node_id !== selectedNode.id),
    });
    setSelectedNodeId(draft.nodes.find((node) => node.id !== selectedNode.id)?.id);
  }

  function toggleIncoming(sourceId: string) {
    if (!draft || !selectedNode || active) return;
    const current = draft.edges.find((edge) => edge.source_node_id === sourceId && edge.target_node_id === selectedNode.id);
    setDraft({
      ...draft,
      edges: current
        ? draft.edges.filter((edge) => edge !== current)
        : [...draft.edges, { id: `edge-${Date.now()}-${sourceId}`, source_node_id: sourceId, target_node_id: selectedNode.id, condition: {} }],
    });
  }

  function setEdgeBranch(sourceId: string, when: string) {
    if (!draft || !selectedNode) return;
    setDraft({
      ...draft,
      edges: draft.edges.map((edge) => edge.source_node_id === sourceId && edge.target_node_id === selectedNode.id
        ? { ...edge, condition: when === "always" ? {} : { when: when === "true" } }
        : edge),
    });
  }

  function moveNode(event: DragEvent<HTMLElement>, node: DraftNode) {
    if (!draft || !canvasRef.current || active) return;
    const bounds = canvasRef.current.getBoundingClientRect();
    const x = Math.max(12, Math.round(event.clientX - bounds.left - 112 + canvasRef.current.scrollLeft));
    const y = Math.max(12, Math.round(event.clientY - bounds.top - 54 + canvasRef.current.scrollTop));
    setDraft({
      ...draft,
      nodes: draft.nodes.map((item) => item.id === node.id ? { ...item, position_x: x, position_y: y } : item),
    });
  }

  const edges = useMemo(() => draft?.edges.map((edge) => {
    const source = draft.nodes.find((node) => node.id === edge.source_node_id);
    const target = draft.nodes.find((node) => node.id === edge.target_node_id);
    return source && target ? { edge, source, target } : null;
  }).filter(Boolean) ?? [], [draft]);

  return (
    <div className="v4-flow-workbench">
      <aside className="v4-flow-library">
        <header><strong>节点库</strong><small>CLICK TO ADD</small></header>
        {libraryGroups.map((group) => (
          <section key={group.label}>
            <label>{group.label}</label>
            {group.items.map(({ type, name, detail, icon: Icon }) => (
              <button key={name} type="button" disabled={!draft || active} onClick={() => addNode(type)}>
                <span><Icon size={16} /></span><div><strong>{name}</strong><small>{detail}</small></div>
              </button>
            ))}
          </section>
        ))}
      </aside>

      <section className="v4-flow-canvas">
        <header>
          <div><strong>{draft?.name ?? "选择或创建 Agent Flow"}</strong><small>{selected?.status ?? "DRAFT"} · {draft?.nodes.length ?? 0} NODES</small></div>
          <span className={`v4-status ${selected?.status === "failed" ? "amber" : "green"}`}><i />{selected?.status?.toUpperCase() ?? "READY"}</span>
          <button className="v4-button secondary" type="button" disabled={!selected || active || saving} onClick={() => void save()}><Save size={15} />{saving ? "保存中" : "保存"}</button>
          <button className={`v4-button ${active ? "secondary" : "primary"}`} type="button" disabled={!selected || saving} onClick={() => void toggleRun()}>{active ? <CircleStop size={16} /> : <Play size={16} />}{active ? "停止" : "运行"}</button>
          <button className="v4-icon-button danger" type="button" disabled={!selected || active} title="删除工作流" onClick={() => void removeFlow()}><Trash2 size={16} /></button>
          <button className="v4-icon-button" type="button" title="新建工作流" onClick={() => { setForm({ project_id: projects?.[0]?.id ?? "", name: "", description: "" }); setModalOpen(true); }}><Plus size={17} /></button>
        </header>
        {error && <div className="v4-flow-error">{error}</div>}
        <div className="v4-flow-grid" ref={canvasRef}>
          {edges.map((item) => item && (
            <svg key={item.edge.id} className="v4-flow-edge">
              <path d={`M ${item.source.position_x + 225} ${item.source.position_y + 54} C ${(item.source.position_x + item.target.position_x + 225) / 2} ${item.source.position_y + 54}, ${(item.source.position_x + item.target.position_x + 225) / 2} ${item.target.position_y + 54}, ${item.target.position_x} ${item.target.position_y + 54}`} />
            </svg>
          ))}
          {draft?.nodes.map((node, index) => (
            <article
              key={node.id}
              draggable={!active}
              className={`v4-flow-node ${node.node_type} ${node.status} ${node.id === selectedNodeId ? "selected" : ""}`}
              style={{ left: node.position_x, top: node.position_y }}
              onClick={() => setSelectedNodeId(node.id)}
              onDragEnd={(event) => moveNode(event, node)}
            >
              <header><span>{nodeIcon(node.node_type)}</span><div><strong>{node.name}</strong><small>{node.node_type.toUpperCase()} · TRY {node.attempts}</small></div><i /></header>
              <footer><span>{node.error_message || node.status}</span><b>{String(index + 1).padStart(2, "0")}</b></footer>
            </article>
          ))}
          {!draft && <div className="v4-empty"><GitFork size={30} /><strong>还没有 Agent Flow</strong><span>创建后即可编辑节点、连线、条件与执行预算</span><button className="v4-button primary" type="button" onClick={() => setModalOpen(true)}><Plus size={16} />新建工作流</button></div>}
        </div>
        <footer><span><i />点击节点编辑，拖动节点调整位置；保存后配置持久化到本地数据库</span><b>{draft?.edges.length ?? 0} EDGES</b></footer>
      </section>

      <aside className="v4-flow-inspector">
        <header><strong>{selectedNode ? "节点设置" : "流程设置"}</strong><small>{selectedNode ? selectedNode.node_type.toUpperCase() : selected ? "FLOW SELECTED" : "NO SELECTION"}</small></header>
        <section className="v4-flow-selector"><label>已有工作流</label>{flows?.map((flow) => <button className={flow.id === selectedId ? "active" : ""} key={flow.id} type="button" onClick={() => { setSelectedId(flow.id); setSelectedNodeId(undefined); }}><GitFork size={14} /><span><strong>{flow.name}</strong><small>{flow.node_count} 个节点 · {flow.project_name || "跨项目"}</small></span></button>)}</section>
        {draft && selectedNode ? (
          <>
            <section className="v4-flow-form">
              <label>节点定义</label>
              <span>名称</span><input value={selectedNode.name} disabled={active} onChange={(event) => updateNode({ name: event.target.value })} />
              <span>类型</span><select value={selectedNode.node_type} disabled={active} onChange={(event) => updateNode({ node_type: event.target.value as NodeType, config: {} })}>{Object.entries(nodeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
              {selectedNode.node_type === "agent" && <><span>任务提示词</span><textarea value={String(selectedNode.config.prompt ?? "")} disabled={active} onChange={(event) => updateNodeConfig("prompt", event.target.value)} /></>}
              {selectedNode.node_type === "approval" && <><span>审批说明</span><textarea value={String(selectedNode.config.description ?? "")} disabled={active} onChange={(event) => updateNodeConfig("description", event.target.value)} /></>}
              {selectedNode.node_type === "condition" && <><span>判断方式</span><select value={String(selectedNode.config.operator ?? "contains")} disabled={active} onChange={(event) => updateNodeConfig("operator", event.target.value)}><option value="contains">包含</option><option value="not_contains">不包含</option><option value="equals">完全等于</option><option value="starts_with">开头为</option><option value="ends_with">结尾为</option></select><span>比较值</span><input value={String(selectedNode.config.value ?? "")} disabled={active} onChange={(event) => updateNodeConfig("value", event.target.value)} /></>}
              {selectedNode.node_type === "tool" && <><span>MCP Server</span><select value={String(selectedNode.config.server_id ?? "")} disabled={active} onChange={(event) => updateNodeConfig("server_id", event.target.value)}><option value="">选择 Server</option>{servers?.filter((server) => server.enabled).map((server) => <option key={server.id} value={server.id}>{server.name}</option>)}</select><span>工具名称</span><input value={String(selectedNode.config.tool_name ?? "")} disabled={active} onChange={(event) => updateNodeConfig("tool_name", event.target.value)} /></>}
            </section>
            <section className="v4-flow-links">
              <label><Link2 size={12} />上游连接</label>
              {draft.nodes.filter((node) => node.id !== selectedNode.id).map((node) => {
                const edge = draft.edges.find((item) => item.source_node_id === node.id && item.target_node_id === selectedNode.id);
                return <div key={node.id}><button className={edge ? "active" : ""} type="button" disabled={active} onClick={() => toggleIncoming(node.id)}><i>{edge && <Check size={10} />}</i><span>{node.name}</span></button>{edge && node.node_type === "condition" && <select value={"when" in edge.condition ? String(edge.condition.when) : "always"} disabled={active} onChange={(event) => setEdgeBranch(node.id, event.target.value)}><option value="always">始终</option><option value="true">条件成立</option><option value="false">条件不成立</option></select>}</div>;
              })}
              <button className="v4-flow-remove-node" type="button" disabled={active || draft.nodes.length <= 1} onClick={removeNode}><Trash2 size={13} />删除节点</button>
            </section>
          </>
        ) : draft ? (
          <>
            <section className="v4-flow-form"><label>流程信息</label><span>名称</span><input value={draft.name} disabled={active} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /><span>说明</span><textarea value={draft.description} disabled={active} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></section>
            <section className="v4-flow-form"><label>执行约束</label><span>失败重试</span><input type="number" min="0" max="3" value={Number(draft.settings.max_retries ?? 1)} disabled={active} onChange={(event) => setDraft({ ...draft, settings: { ...draft.settings, max_retries: Number(event.target.value) } })} /><span>并发 Agent</span><input type="number" min="1" max="8" value={Number(draft.settings.max_concurrency ?? 4)} disabled={active} onChange={(event) => setDraft({ ...draft, settings: { ...draft.settings, max_concurrency: Number(event.target.value) } })} /><span>最大用时（分钟）</span><input type="number" min="1" value={Math.round(Number(draft.settings.max_runtime_seconds ?? 2700) / 60)} disabled={active} onChange={(event) => setDraft({ ...draft, settings: { ...draft.settings, max_runtime_seconds: Number(event.target.value) * 60 } })} /><span>费用预算（USD）</span><input type="number" min="0" step="0.1" value={Number(draft.settings.max_cost_usd ?? 3)} disabled={active} onChange={(event) => setDraft({ ...draft, settings: { ...draft.settings, max_cost_usd: Number(event.target.value) } })} /><span>Token 预算</span><input type="number" min="0" value={Number(draft.settings.max_tokens ?? 500000)} disabled={active} onChange={(event) => setDraft({ ...draft, settings: { ...draft.settings, max_tokens: Number(event.target.value) } })} /><label className="v4-flow-checkbox"><input type="checkbox" checked={Boolean(draft.settings.parallel_worktrees ?? true)} disabled={active} onChange={(event) => setDraft({ ...draft, settings: { ...draft.settings, parallel_worktrees: event.target.checked } })} /><span>并行 Agent 使用隔离 Worktree</span></label></section>
          </>
        ) : null}
        {draft && <button className="v4-flow-inspector-mode" type="button" onClick={() => setSelectedNodeId(undefined)}>{selectedNode ? "返回流程设置" : "选择画布节点进行编辑"}</button>}
      </aside>

      {modalOpen && <div className="v4-modal-backdrop" onMouseDown={() => setModalOpen(false)}><form className="v4-modal small" onSubmit={create} onMouseDown={(event) => event.stopPropagation()}><header><div><strong>新建 Agent Flow</strong><small>创建后可以自由编辑节点、条件、连线和预算</small></div><button type="button" onClick={() => setModalOpen(false)}><X size={18} /></button></header><div className="v4-form-grid"><label className="full"><span>工作流名称</span><input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label className="full"><span>所属项目</span><select required value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })}><option value="">选择项目</option>{projects?.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><label className="full"><span>说明</span><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label></div>{error && <div className="v4-error">{error}</div>}<footer><button className="v4-button secondary" type="button" onClick={() => setModalOpen(false)}>取消</button><button className="v4-button primary" type="submit"><Check size={16} />创建工作流</button></footer></form></div>}
    </div>
  );
}
