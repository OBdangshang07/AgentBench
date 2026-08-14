import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Braces,
  Cable,
  Check,
  CircleStop,
  Clock3,
  Copy,
  FlaskConical,
  GitFork,
  Hand,
  History,
  Link2,
  ListChecks,
  LayoutTemplate,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Play,
  Plus,
  Redo2,
  RefreshCcw,
  RotateCcw,
  Save,
  Scan,
  ShieldAlert,
  Split,
  TestTube2,
  Trash2,
  Undo2,
  Wrench,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { DragEvent, FormEvent, PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useWorkspaceUx } from "../components/WorkspaceUx";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import JsonSchemaForm from "./JsonSchemaForm";
import type {
  AgentFlow as AgentFlowData,
  AgentFlowRun,
  AgentFlowSummary,
  AgentFlowVersion,
  FlowValidation,
  McpServer,
  Project,
  RuntimeProfile,
} from "./types";

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

interface FlowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  settings: Record<string, unknown>;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
}

interface InputBinding {
  source_node_id: string;
  path: string;
  target: string;
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

function cloneDraft(draft: FlowDraft): FlowDraft {
  return structuredClone(draft);
}

function flowPayload(draft: FlowDraft, projectId?: string | null) {
  return {
    project_id: projectId || null,
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
  };
}

function relativeTime(value: string) {
  const elapsed = Date.now() - new Date(value).getTime();
  if (elapsed < 60_000) return "刚刚";
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前`;
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} 小时前`;
  return new Date(value).toLocaleDateString("zh-CN");
}

export default function AgentFlow() {
  const { confirm, notify, selectedProjectId } = useWorkspaceUx();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: flows, refresh: refreshFlows } = useApi<AgentFlowSummary[]>("/flows", 4_000);
  const { data: projects } = useApi<Project[]>("/projects");
  const { data: servers } = useApi<McpServer[]>("/mcp-servers", 5_000);
  const { data: templates } = useApi<FlowTemplate[]>("/flow-templates", 30_000);
  const { data: runtimeProfiles } = useApi<RuntimeProfile[]>("/runtime-profiles", 10_000);
  const [selectedId, setSelectedId] = useState<string>();
  const { data: selected, refresh: refreshSelected } = useApi<AgentFlowData>(selectedId ? `/flows/${selectedId}` : null, 3_000);
  const { data: versions, refresh: refreshVersions } = useApi<AgentFlowVersion[]>(selectedId ? `/flows/${selectedId}/versions` : null, 5_000);
  const { data: runs, refresh: refreshRuns } = useApi<AgentFlowRun[]>(selectedId ? `/flows/${selectedId}/runs?limit=30` : null, 4_000);
  const [draft, setDraft] = useState<FlowDraft | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string>();
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState({ project_id: "", name: "", description: "", template_id: "single-delivery" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState<"saved" | "dirty" | "saving" | "error">("saved");
  const [historyStack, setHistoryStack] = useState<FlowDraft[]>([]);
  const [futureStack, setFutureStack] = useState<FlowDraft[]>([]);
  const [validation, setValidation] = useState<FlowValidation | null>(null);
  const [inspectorTab, setInspectorTab] = useState<"edit" | "validation" | "history">("edit");
  const [zoom, setZoom] = useState(1);
  const [panning, setPanning] = useState(false);
  const [connectingFrom, setConnectingFrom] = useState<string>();
  const [connectionPointer, setConnectionPointer] = useState({ x: 0, y: 0 });
  const [libraryOpen, setLibraryOpen] = useState(() => window.localStorage.getItem("agentbench.flow.library") !== "closed");
  const [inspectorOpen, setInspectorOpen] = useState(() => window.localStorage.getItem("agentbench.flow.inspector") !== "closed");
  const draftRevision = useRef(0);
  const loadedFlowId = useRef<string | undefined>(undefined);
  const panStart = useRef({ x: 0, y: 0, left: 0, top: 0 });
  const canvasRef = useRef<HTMLDivElement>(null);
  const active = selected?.status === "running" || selected?.status === "waiting_approval" || selected?.status === "testing" || selected?.status === "cancelling";
  const selectedNode = draft?.nodes.find((node) => node.id === selectedNodeId);
  const createRequested = searchParams.get("new") === "1";

  useEffect(() => {
    window.localStorage.setItem("agentbench.flow.library", libraryOpen ? "open" : "closed");
  }, [libraryOpen]);

  useEffect(() => {
    window.localStorage.setItem("agentbench.flow.inspector", inspectorOpen ? "open" : "closed");
  }, [inspectorOpen]);

  useEffect(() => {
    if (!selectedId && flows?.length) setSelectedId(flows[0].id);
  }, [flows, selectedId]);

  useEffect(() => {
    if (!createRequested || !projects) return;
    setForm({ project_id: projects.find((project) => project.id === selectedProjectId)?.id ?? projects[0]?.id ?? "", name: "", description: "", template_id: templates?.[0]?.id ?? "single-delivery" });
    setModalOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete("new");
    setSearchParams(next, { replace: true });
  }, [createRequested, projects, selectedProjectId, templates]);

  useEffect(() => {
    if (!selected) return;
    const switched = loadedFlowId.current !== selected.id;
    if (!switched && (dirty || saving)) return;
    loadedFlowId.current = selected.id;
    setDraft(draftFromFlow(selected));
    setDirty(false);
    setSaveState("saved");
    if (switched) {
      setHistoryStack([]);
      setFutureStack([]);
      setValidation(null);
      setZoom(1);
    }
    setSelectedNodeId((current) => selected.nodes.some((node) => node.id === current) ? current : selected.nodes[0]?.id);
  }, [selected?.id, selected?.updated_at]);

  useEffect(() => {
    if (!dirty || !draft || !selected || active || saving) return;
    const handle = window.setTimeout(() => void save(true), 1_400);
    return () => window.clearTimeout(handle);
  }, [dirty, draft, selected?.id, active, saving]);

  useEffect(() => {
    function handleKeyboard(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const editing = target?.matches("input, textarea, select, [contenteditable='true']");
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && !editing) {
        event.preventDefault();
        if (event.shiftKey) redo(); else undo();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y" && !editing) {
        event.preventDefault();
        redo();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "d" && !editing) {
        event.preventDefault();
        duplicateNode();
      } else if ((event.key === "Delete" || event.key === "Backspace") && !editing && selectedNodeId) {
        event.preventDefault();
        removeNode();
      }
    }
    window.addEventListener("keydown", handleKeyboard);
    return () => window.removeEventListener("keydown", handleKeyboard);
  }, [draft, selectedNodeId, historyStack, futureStack, active]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const template = templates?.find((item) => item.id === form.template_id);
      if (!template) throw new Error("请选择一个可用的 Flow 模板");
      const flow = await api<AgentFlowData>("/flows", {
        method: "POST",
        body: JSON.stringify({
          project_id: form.project_id,
          name: form.name,
          description: form.description || template.description,
          settings: template.settings,
          nodes: template.nodes,
          edges: template.edges,
        }),
      });
      setSelectedId(flow.id);
      loadedFlowId.current = flow.id;
      setDraft(draftFromFlow(flow));
      setSelectedNodeId(flow.nodes[0]?.id);
      setDirty(false);
      setSaveState("saved");
      setHistoryStack([]);
      setFutureStack([]);
      setModalOpen(false);
      await Promise.all([refreshFlows(), refreshVersions()]);
      notify({ title: "Agent Flow 已创建", message: "已生成初始版本快照", kind: "success" });
    } catch (value) {
      setError(value instanceof Error ? value.message : "创建工作流失败");
    }
  }

  async function save(silent = false) {
    if (!selected || !draft || active || saving) return false;
    const revision = draftRevision.current;
    const activeNode = selectedNode;
    setSaving(true);
    setSaveState("saving");
    setError(null);
    try {
      const saved = await api<AgentFlowData>(`/flows/${selected.id}`, {
        method: "PATCH",
        body: JSON.stringify(flowPayload(draft, selected.project_id)),
      });
      if (draftRevision.current === revision) {
        setDraft(draftFromFlow(saved));
        setDirty(false);
        setSaveState("saved");
        if (activeNode) {
          const replacement = saved.nodes.find((node) => (
            node.name === activeNode.name && node.node_type === activeNode.node_type
          ));
          setSelectedNodeId(replacement?.id);
        }
      }
      await Promise.all([refreshSelected(), refreshFlows(), refreshVersions()]);
      if (!silent) notify({ title: "Flow 已保存", message: `已创建或更新版本快照`, kind: "success" });
      return true;
    } catch (value) {
      setError(value instanceof Error ? value.message : "保存工作流失败");
      setSaveState("error");
      if (!silent) notify({ title: "保存失败", message: value instanceof Error ? value.message : "请检查节点配置", kind: "error" });
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function removeFlow() {
    if (!selected || active) return;
    const approved = await confirm({
      title: "删除 Agent Flow",
      message: `确认删除“${selected.name}”及其版本和运行历史？`,
      detail: "关联项目文件不会被删除。",
      confirmLabel: "删除 Flow",
      tone: "danger",
    });
    if (!approved) return;
    setError(null);
    try {
      await api(`/flows/${selected.id}`, { method: "DELETE" });
      setSelectedId(undefined);
      setDraft(null);
      setSelectedNodeId(undefined);
      await refreshFlows();
      notify({ title: "Flow 已删除", kind: "success" });
    } catch (value) {
      setError(value instanceof Error ? value.message : "删除工作流失败");
    }
  }

  async function toggleRun() {
    if (!selected) return;
    setError(null);
    try {
      if (!active) {
        const saved = dirty ? await save(true) : true;
        if (!saved) return;
        const result = await validateDraft(false);
        if (!result?.valid) {
          setInspectorTab("validation");
          return;
        }
      }
      await api(`/flows/${selected.id}/${active ? "cancel" : "run"}`, { method: "POST" });
      await Promise.all([refreshSelected(), refreshFlows(), refreshRuns()]);
      notify({ title: active ? "正在停止 Flow" : "Flow 已开始运行", kind: active ? "warning" : "success" });
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法运行工作流");
    }
  }

  function commitDraft(next: FlowDraft) {
    if (!draft || active) return;
    setHistoryStack((current) => [...current.slice(-49), cloneDraft(draft)]);
    setFutureStack([]);
    setDraft(next);
    draftRevision.current += 1;
    setDirty(true);
    setSaveState("dirty");
    setValidation(null);
  }

  function undo() {
    if (!draft || !historyStack.length || active) return;
    const previous = historyStack[historyStack.length - 1];
    setFutureStack((current) => [cloneDraft(draft), ...current.slice(0, 49)]);
    setHistoryStack((current) => current.slice(0, -1));
    setDraft(cloneDraft(previous));
    draftRevision.current += 1;
    setDirty(true);
    setSaveState("dirty");
    setValidation(null);
  }

  function redo() {
    if (!draft || !futureStack.length || active) return;
    const next = futureStack[0];
    setHistoryStack((current) => [...current.slice(-49), cloneDraft(draft)]);
    setFutureStack((current) => current.slice(1));
    setDraft(cloneDraft(next));
    draftRevision.current += 1;
    setDirty(true);
    setSaveState("dirty");
    setValidation(null);
  }

  function duplicateNode() {
    if (!draft || !selectedNode || active) return;
    const id = `draft-${Date.now()}-copy`;
    commitDraft({
      ...draft,
      nodes: [...draft.nodes, {
        ...cloneDraft({ ...draft, nodes: [selectedNode], edges: [] }).nodes[0],
        id,
        name: `${selectedNode.name} · 副本`,
        position_x: selectedNode.position_x + 42,
        position_y: selectedNode.position_y + 42,
        status: "pending",
        attempts: 0,
        error_message: null,
      }],
    });
    setSelectedNodeId(id);
  }

  async function validateDraft(showNotice = true) {
    if (!draft || !selected) return null;
    setError(null);
    try {
      const result = await api<FlowValidation>("/flows/validate", {
        method: "POST",
        body: JSON.stringify(flowPayload(draft, selected.project_id)),
      });
      setValidation(result);
      if (showNotice) {
        notify({
          title: result.valid ? "静态验证通过" : `发现 ${result.errors.length} 个阻塞问题`,
          message: result.valid
            ? `${result.warnings.length} 条建议，不会调用 Agent 或修改项目`
            : result.errors[0]?.message,
          kind: result.valid ? (result.warnings.length ? "warning" : "success") : "error",
        });
      }
      return result;
    } catch (value) {
      const message = value instanceof Error ? value.message : "无法验证工作流";
      setError(message);
      notify({ title: "验证失败", message, kind: "error" });
      return null;
    }
  }

  async function dryRun() {
    if (!selected || active) return;
    if (dirty && !(await save(true))) return;
    const result = await validateDraft(false);
    if (!result?.valid) {
      setInspectorTab("validation");
      notify({ title: "Dry Run 已阻止", message: result?.errors[0]?.message ?? "请先修复节点配置", kind: "error" });
      return;
    }
    try {
      await api<AgentFlowRun>(`/flows/${selected.id}/dry-run`, { method: "POST" });
      await refreshRuns();
      setInspectorTab("history");
      notify({ title: "Dry Run 完成", message: "已验证执行顺序；没有调用 Agent、工具或修改项目", kind: "success" });
    } catch (value) {
      notify({ title: "Dry Run 失败", message: value instanceof Error ? value.message : "未知错误", kind: "error" });
    }
  }

  async function restoreVersion(version: AgentFlowVersion) {
    if (!selected || active) return;
    const approved = await confirm({
      title: `恢复 Flow V${version.version_no}`,
      message: `将当前草稿恢复为“${version.label || version.name}”。恢复前的版本仍会保留。`,
      confirmLabel: "恢复版本",
    });
    if (!approved) return;
    try {
      await api(`/flows/${selected.id}/versions/${version.version_no}/restore`, { method: "POST" });
      setDirty(false);
      setHistoryStack([]);
      setFutureStack([]);
      await Promise.all([refreshSelected(), refreshFlows(), refreshVersions()]);
      notify({ title: `已恢复到 V${version.version_no}`, kind: "success" });
    } catch (value) {
      notify({ title: "恢复失败", message: value instanceof Error ? value.message : "未知错误", kind: "error" });
    }
  }

  async function retrySelectedNode() {
    if (!selected || !selectedNode || active) return;
    try {
      await api(`/flows/${selected.id}/nodes/${selectedNode.id}/retry`, { method: "POST" });
      await Promise.all([refreshSelected(), refreshFlows(), refreshRuns()]);
      notify({ title: `正在重试“${selectedNode.name}”`, message: "已完成的上游节点不会重新执行", kind: "success" });
    } catch (value) {
      notify({ title: "节点无法重试", message: value instanceof Error ? value.message : "未知错误", kind: "error" });
    }
  }

  async function testSelectedNode() {
    if (!selected || !selectedNode || active || selectedNode.node_type === "approval") return;
    const identity = { name: selectedNode.name, type: selectedNode.node_type };
    try {
      if (dirty && !(await save(true))) return;
      const latest = await api<AgentFlowData>(`/flows/${selected.id}`);
      const node = latest.nodes.find((item) => item.name === identity.name && item.node_type === identity.type);
      if (!node) throw new Error("保存后无法定位要测试的节点");
      await api(`/flows/${selected.id}/nodes/${node.id}/test`, { method: "POST" });
      setInspectorTab("history");
      await Promise.all([refreshSelected(), refreshFlows(), refreshRuns()]);
      notify({ title: `正在测试“${identity.name}”`, message: "只运行这个节点，不会继续执行下游", kind: "success" });
    } catch (value) {
      notify({ title: "节点测试无法启动", message: value instanceof Error ? value.message : "未知错误", kind: "error" });
    }
  }

  function fitCanvas() {
    if (!draft || !canvasRef.current || !draft.nodes.length) return;
    const maxX = Math.max(...draft.nodes.map((node) => node.position_x + 250));
    const maxY = Math.max(...draft.nodes.map((node) => node.position_y + 135));
    const nextZoom = Math.max(0.45, Math.min(1.25, Math.min(
      (canvasRef.current.clientWidth - 50) / Math.max(maxX, 400),
      (canvasRef.current.clientHeight - 50) / Math.max(maxY, 300),
    )));
    setZoom(Number(nextZoom.toFixed(2)));
    canvasRef.current.scrollTo({ left: 0, top: 0, behavior: "smooth" });
  }

  function startPan(event: ReactPointerEvent<HTMLDivElement>) {
    if (!canvasRef.current || event.button !== 0 || (event.target as HTMLElement).closest(".v4-flow-node")) return;
    panStart.current = {
      x: event.clientX,
      y: event.clientY,
      left: canvasRef.current.scrollLeft,
      top: canvasRef.current.scrollTop,
    };
    setPanning(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function movePan(event: ReactPointerEvent<HTMLDivElement>) {
    if (connectingFrom && canvasRef.current) {
      const bounds = canvasRef.current.getBoundingClientRect();
      setConnectionPointer({
        x: Math.max(0, (event.clientX - bounds.left + canvasRef.current.scrollLeft) / zoom),
        y: Math.max(0, (event.clientY - bounds.top + canvasRef.current.scrollTop) / zoom),
      });
      return;
    }
    if (!panning || !canvasRef.current) return;
    canvasRef.current.scrollLeft = panStart.current.left - (event.clientX - panStart.current.x);
    canvasRef.current.scrollTop = panStart.current.top - (event.clientY - panStart.current.y);
  }

  async function switchFlow(flowId: string) {
    if (flowId === selectedId) return;
    if (dirty && !(await save(true))) return;
    setSelectedNodeId(undefined);
    setInspectorTab("edit");
    setSelectedId(flowId);
  }

  function addNode(type: NodeType) {
    if (!draft || active) return;
    const index = draft.nodes.length;
    const id = `draft-${Date.now()}-${index}`;
    const baseConfig = { error_strategy: "fail_flow", retry_count: 1, input_bindings: [] };
    const config = type === "agent"
      ? { prompt: "描述该 Agent 节点需要完成的任务。" }
      : type === "approval"
        ? { description: "检查上游结果并确认是否继续。" }
        : type === "condition"
          ? { operator: "contains", value: "success" }
          : { server_id: "", tool_name: "", arguments: {} };
    commitDraft({
      ...draft,
      nodes: [...draft.nodes, {
        id,
        node_type: type,
        name: nodeLabels[type],
        position_x: 70 + (index % 3) * 280,
        position_y: 80 + Math.floor(index / 3) * 170,
        config: { ...baseConfig, ...config },
        status: "pending",
        attempts: 0,
        error_message: null,
      }],
    });
    setSelectedNodeId(id);
  }

  function updateNode(changes: Partial<DraftNode>) {
    if (!draft || !selectedNode || active) return;
    commitDraft({
      ...draft,
      nodes: draft.nodes.map((node) => node.id === selectedNode.id ? { ...node, ...changes } : node),
    });
  }

  function updateNodeConfig(key: string, value: unknown) {
    if (!selectedNode) return;
    updateNode({ config: { ...selectedNode.config, [key]: value } });
  }

  function updateFlow(changes: Partial<Pick<FlowDraft, "name" | "description">>) {
    if (!draft) return;
    commitDraft({ ...draft, ...changes });
  }

  function updateFlowSetting(key: string, value: unknown) {
    if (!draft) return;
    commitDraft({ ...draft, settings: { ...draft.settings, [key]: value } });
  }

  function removeNode() {
    if (!draft || !selectedNode || draft.nodes.length <= 1 || active) return;
    commitDraft({
      ...draft,
      nodes: draft.nodes.filter((node) => node.id !== selectedNode.id),
      edges: draft.edges.filter((edge) => edge.source_node_id !== selectedNode.id && edge.target_node_id !== selectedNode.id),
    });
    setSelectedNodeId(draft.nodes.find((node) => node.id !== selectedNode.id)?.id);
  }

  function toggleIncoming(sourceId: string) {
    if (!draft || !selectedNode || active) return;
    const current = draft.edges.find((edge) => edge.source_node_id === sourceId && edge.target_node_id === selectedNode.id);
    commitDraft({
      ...draft,
      edges: current
        ? draft.edges.filter((edge) => edge !== current)
        : [...draft.edges, { id: `edge-${Date.now()}-${sourceId}`, source_node_id: sourceId, target_node_id: selectedNode.id, condition: {} }],
    });
  }

  function wouldCreateCycle(sourceId: string, targetId: string) {
    if (!draft) return false;
    const outgoing = new Map<string, string[]>();
    draft.nodes.forEach((node) => outgoing.set(node.id, []));
    draft.edges.forEach((edge) => outgoing.get(edge.source_node_id)?.push(edge.target_node_id));
    const queue = [targetId];
    const visited = new Set<string>();
    while (queue.length) {
      const current = queue.shift()!;
      if (current === sourceId) return true;
      if (visited.has(current)) continue;
      visited.add(current);
      queue.push(...(outgoing.get(current) ?? []));
    }
    return false;
  }

  function connectNodes(sourceId: string, targetId: string) {
    if (!draft || active || sourceId === targetId) return;
    if (draft.edges.some((edge) => edge.source_node_id === sourceId && edge.target_node_id === targetId)) {
      notify({ title: "节点已经连接", message: "可以在右侧设置数据绑定与分支条件", kind: "info" });
      return;
    }
    if (wouldCreateCycle(sourceId, targetId)) {
      notify({ title: "无法创建循环连接", message: "Agent Flow 当前只支持有向无环执行图", kind: "error" });
      return;
    }
    const source = draft.nodes.find((node) => node.id === sourceId);
    const target = draft.nodes.find((node) => node.id === targetId);
    if (!source || !target) return;
    const currentBindings = Array.isArray(target.config.input_bindings)
      ? target.config.input_bindings as InputBinding[]
      : [];
    const binding: InputBinding = {
      source_node_id: sourceId,
      path: source.node_type === "condition" ? "matched" : "summary",
      target: target.node_type === "condition" ? "source" : "context",
    };
    commitDraft({
      ...draft,
      nodes: draft.nodes.map((node) => node.id === targetId ? {
        ...node,
        config: {
          ...node.config,
          input_bindings: currentBindings.some((item) => item.source_node_id === sourceId)
            ? currentBindings
            : [...currentBindings, binding],
        },
      } : node),
      edges: [...draft.edges, {
        id: `edge-${Date.now()}-${sourceId}`,
        source_node_id: sourceId,
        target_node_id: targetId,
        condition: {},
      }],
    });
    setSelectedNodeId(targetId);
  }

  function updateInputBinding(sourceId: string, changes: Partial<InputBinding> | null) {
    if (!selectedNode) return;
    const bindings = Array.isArray(selectedNode.config.input_bindings)
      ? selectedNode.config.input_bindings as InputBinding[]
      : [];
    const current = bindings.find((item) => item.source_node_id === sourceId);
    if (changes === null) {
      updateNodeConfig("input_bindings", bindings.filter((item) => item.source_node_id !== sourceId));
      return;
    }
    const replacement = {
      source_node_id: sourceId,
      path: current?.path ?? "summary",
      target: current?.target ?? "context",
      ...changes,
    };
    updateNodeConfig("input_bindings", current
      ? bindings.map((item) => item.source_node_id === sourceId ? replacement : item)
      : [...bindings, replacement]);
  }

  function setEdgeBranch(sourceId: string, when: string) {
    if (!draft || !selectedNode) return;
    commitDraft({
      ...draft,
      edges: draft.edges.map((edge) => edge.source_node_id === sourceId && edge.target_node_id === selectedNode.id
        ? { ...edge, condition: when === "always" ? {} : { when: when === "true" } }
        : edge),
    });
  }

  function moveNode(event: DragEvent<HTMLElement>, node: DraftNode) {
    if (!draft || !canvasRef.current || active) return;
    const bounds = canvasRef.current.getBoundingClientRect();
    const x = Math.max(12, Math.round((event.clientX - bounds.left - 112 + canvasRef.current.scrollLeft) / zoom));
    const y = Math.max(12, Math.round((event.clientY - bounds.top - 54 + canvasRef.current.scrollTop) / zoom));
    commitDraft({
      ...draft,
      nodes: draft.nodes.map((item) => item.id === node.id ? { ...item, position_x: x, position_y: y } : item),
    });
  }

  const edges = useMemo(() => draft?.edges.map((edge) => {
    const source = draft.nodes.find((node) => node.id === edge.source_node_id);
    const target = draft.nodes.find((node) => node.id === edge.target_node_id);
    return source && target ? { edge, source, target } : null;
  }).filter(Boolean) ?? [], [draft]);
  const stageSize = useMemo(() => ({
    width: Math.max(1200, ...(draft?.nodes.map((node) => node.position_x + 360) ?? [1200])),
    height: Math.max(760, ...(draft?.nodes.map((node) => node.position_y + 230) ?? [760])),
  }), [draft]);
  const selectedServer = servers?.find((server) => server.id === String(selectedNode?.config.server_id ?? ""));
  const selectedTool = selectedServer?.tools.find((tool) => tool.name === String(selectedNode?.config.tool_name ?? ""));
  const connectingSource = draft?.nodes.find((node) => node.id === connectingFrom);
  const incomingNodes = selectedNode && draft
    ? draft.edges
      .filter((edge) => edge.target_node_id === selectedNode.id)
      .map((edge) => draft.nodes.find((node) => node.id === edge.source_node_id))
      .filter((node): node is DraftNode => Boolean(node))
    : [];
  const saveLabels = {
    saved: "已自动保存",
    dirty: "有未保存修改",
    saving: "正在保存",
    error: "保存失败",
  };

  return (
    <div className={`v4-flow-workbench ${libraryOpen ? "library-open" : "library-closed"} ${inspectorOpen ? "inspector-open" : "inspector-closed"}`}>
      {libraryOpen && <aside className="v4-flow-library">
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
      </aside>}

      <section className="v4-flow-canvas">
        <header>
          <button className="v4-icon-button v5-flow-panel-toggle" type="button" title={libraryOpen ? "收起节点库" : "显示节点库"} aria-label={libraryOpen ? "收起节点库" : "显示节点库"} onClick={() => setLibraryOpen((value) => !value)}>{libraryOpen ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}</button>
          <div className="v5-flow-title"><strong>{draft?.name ?? "选择或创建 Agent Flow"}</strong><small>{selected?.status ?? "DRAFT"} · {draft?.nodes.length ?? 0} NODES · {saveLabels[saveState]}</small></div>
          <span className={`v4-status ${["failed", "interrupted"].includes(selected?.status ?? "") ? "amber" : "green"}`}><i />{selected?.status?.toUpperCase() ?? "READY"}</span>
          <div className="v5-flow-toolbar">
            <button className="v4-icon-button" type="button" disabled={!historyStack.length || active} title="撤销 Ctrl+Z" onClick={undo}><Undo2 size={15} /></button>
            <button className="v4-icon-button" type="button" disabled={!futureStack.length || active} title="重做 Ctrl+Y" onClick={redo}><Redo2 size={15} /></button>
            <button className="v4-button secondary" type="button" disabled={!selected || active} onClick={() => { setInspectorTab("validation"); void validateDraft(); }}><ListChecks size={15} />验证</button>
            <button className="v4-button secondary" type="button" disabled={!selected || active || saving} onClick={() => void dryRun()}><FlaskConical size={15} />Dry Run</button>
            <button className="v4-button secondary" type="button" disabled={!selected || active || saving || !dirty} onClick={() => void save()}><Save size={15} />{saving ? "保存中" : "保存"}</button>
            <button className={`v4-button ${active ? "secondary" : "primary"}`} type="button" disabled={!selected || saving} onClick={() => void toggleRun()}>{active ? <CircleStop size={16} /> : <Play size={16} />}{active ? "停止" : "运行"}</button>
            <button className="v4-icon-button danger" type="button" disabled={!selected || active} title="删除工作流" onClick={() => void removeFlow()}><Trash2 size={16} /></button>
            <button className="v4-icon-button" type="button" title="新建工作流" onClick={() => { setForm({ project_id: projects?.find((project) => project.id === selectedProjectId)?.id ?? projects?.[0]?.id ?? "", name: "", description: "", template_id: templates?.[0]?.id ?? "single-delivery" }); setModalOpen(true); }}><Plus size={17} /></button>
          </div>
          <button className="v4-icon-button v5-flow-panel-toggle" type="button" title={inspectorOpen ? "收起检查器" : "显示检查器"} aria-label={inspectorOpen ? "收起检查器" : "显示检查器"} onClick={() => setInspectorOpen((value) => !value)}>{inspectorOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}</button>
        </header>
        {error && <div className="v4-flow-error">{error}</div>}
        <div
          className={`v4-flow-grid ${panning ? "panning" : ""}`}
          ref={canvasRef}
          onPointerDown={startPan}
          onPointerMove={movePan}
          onPointerUp={(event) => { setPanning(false); setConnectingFrom(undefined); if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
          onPointerCancel={() => { setPanning(false); setConnectingFrom(undefined); }}
        >
          <div className="v5-flow-stage" style={{ width: stageSize.width, height: stageSize.height, transform: `scale(${zoom})` }}>
            <svg className="v4-flow-edge" width={stageSize.width} height={stageSize.height} viewBox={`0 0 ${stageSize.width} ${stageSize.height}`}>
              {edges.map((item) => item && (
                <path key={item.edge.id} d={`M ${item.source.position_x + 225} ${item.source.position_y + 54} C ${(item.source.position_x + item.target.position_x + 225) / 2} ${item.source.position_y + 54}, ${(item.source.position_x + item.target.position_x + 225) / 2} ${item.target.position_y + 54}, ${item.target.position_x} ${item.target.position_y + 54}`} />
              ))}
              {connectingSource && <path className="preview" d={`M ${connectingSource.position_x + 225} ${connectingSource.position_y + 54} C ${connectingSource.position_x + 300} ${connectingSource.position_y + 54}, ${connectionPointer.x - 75} ${connectionPointer.y}, ${connectionPointer.x} ${connectionPointer.y}`} />}
            </svg>
            {draft?.nodes.map((node, index) => (
              <article
                key={node.id}
                draggable={!active && !connectingFrom}
                className={`v4-flow-node ${node.node_type} ${node.status} ${node.id === selectedNodeId ? "selected" : ""}`}
                style={{ left: node.position_x, top: node.position_y }}
                onClick={(event) => { event.stopPropagation(); setSelectedNodeId(node.id); setInspectorTab("edit"); }}
                onDragEnd={(event) => moveNode(event, node)}
              >
                <button
                  className="v5-flow-port input"
                  type="button"
                  draggable={false}
                  aria-label={`连接到 ${node.name}`}
                  title="输入端口"
                  onClick={(event) => event.stopPropagation()}
                  onPointerUp={(event) => {
                    event.stopPropagation();
                    if (connectingFrom) connectNodes(connectingFrom, node.id);
                    setConnectingFrom(undefined);
                  }}
                ><i /></button>
                <header><span>{nodeIcon(node.node_type)}</span><div><strong>{node.name}</strong><small>{node.node_type.toUpperCase()} · TRY {node.attempts}</small></div><i /></header>
                <footer><span>{node.error_message || node.status}</span><b>{String(index + 1).padStart(2, "0")}</b></footer>
                <button
                  className="v5-flow-port output"
                  type="button"
                  draggable={false}
                  aria-label={`从 ${node.name} 创建连接`}
                  title="拖到其他节点的输入端口"
                  onClick={(event) => event.stopPropagation()}
                  onPointerDown={(event) => {
                    if (active) return;
                    event.stopPropagation();
                    setConnectingFrom(node.id);
                    setConnectionPointer({ x: node.position_x + 225, y: node.position_y + 54 });
                  }}
                ><i /></button>
              </article>
            ))}
          </div>
          {!draft && <div className="v4-empty"><GitFork size={30} /><strong>还没有 Agent Flow</strong><span>创建后即可编辑节点、连线、条件与执行预算</span><button className="v4-button primary" type="button" onClick={() => setModalOpen(true)}><Plus size={16} />新建工作流</button></div>}
          {draft && <div className="v5-flow-minimap" aria-label="Flow 小地图"><svg viewBox={`0 0 ${stageSize.width} ${stageSize.height}`}>{draft.nodes.map((node) => <rect key={node.id} className={node.status} x={node.position_x} y={node.position_y} width="225" height="108" rx="10" />)}</svg></div>}
        </div>
        <footer><span><i />拖动节点端口创建连线；拖动画布平移；修改会自动保存版本</span><div><button type="button" title="缩小" onClick={() => setZoom((value) => Math.max(0.4, Number((value - .1).toFixed(2))))}><ZoomOut size={14} /></button><b>{Math.round(zoom * 100)}%</b><button type="button" title="放大" onClick={() => setZoom((value) => Math.min(1.6, Number((value + .1).toFixed(2))))}><ZoomIn size={14} /></button><button type="button" title="适应画布" onClick={fitCanvas}><Scan size={14} /></button></div><b>{draft?.edges.length ?? 0} EDGES</b></footer>
      </section>

      {inspectorOpen && <aside className="v4-flow-inspector">
        <header><strong>{inspectorTab === "validation" ? "静态验证" : inspectorTab === "history" ? "版本与运行" : selectedNode ? "节点设置" : "流程设置"}</strong><small>{selectedNode ? selectedNode.node_type.toUpperCase() : selected ? "FLOW SELECTED" : "NO SELECTION"}</small></header>
        <section className="v4-flow-selector"><label>已有工作流</label>{flows?.map((flow) => <button className={flow.id === selectedId ? "active" : ""} key={flow.id} type="button" onClick={() => void switchFlow(flow.id)}><GitFork size={14} /><span><strong>{flow.name}</strong><small>{flow.node_count} 个节点 · {flow.project_name || "跨项目"}</small></span></button>)}</section>
        {draft && <nav className="v5-flow-inspector-tabs"><button className={inspectorTab === "edit" ? "active" : ""} type="button" onClick={() => setInspectorTab("edit")}><Wrench size={13} />编辑</button><button className={inspectorTab === "validation" ? "active" : ""} type="button" onClick={() => setInspectorTab("validation")}><ListChecks size={13} />验证</button><button className={inspectorTab === "history" ? "active" : ""} type="button" onClick={() => setInspectorTab("history")}><History size={13} />历史</button></nav>}
        {inspectorTab === "validation" && draft ? (
          <section className="v5-flow-validation">
            <header><div><strong>{validation ? (validation.valid ? "可以运行" : "需要修复") : "尚未验证"}</strong><small>{validation ? `${validation.node_count} 节点 · ${validation.edge_count} 连线` : "检查节点、连接、Agent 和 MCP 配置"}</small></div><button className="v4-button secondary" type="button" onClick={() => void validateDraft()}><RefreshCcw size={14} />重新验证</button></header>
            {!validation && <div className="v5-flow-panel-empty"><ListChecks size={24} /><span>静态验证不会调用 Agent，也不会修改项目文件。</span></div>}
            {validation && <>
              <div className={`v5-flow-validation-summary ${validation.valid ? "valid" : "invalid"}`}><span>{validation.valid ? <Check size={17} /> : <AlertTriangle size={17} />}</span><div><strong>{validation.errors.length} 个错误</strong><small>{validation.warnings.length} 条建议 · {validation.levels.length} 个执行阶段</small></div></div>
              {[...validation.errors.map((item) => ({ ...item, tone: "error" })), ...validation.warnings.map((item) => ({ ...item, tone: "warning" }))].map((item, index) => <button className={`v5-flow-issue ${item.tone}`} type="button" key={`${item.code}-${item.node_id}-${index}`} onClick={() => { if (item.node_id) { setSelectedNodeId(item.node_id); setInspectorTab("edit"); } }}><span>{item.tone === "error" ? <AlertTriangle size={14} /> : <ListChecks size={14} />}</span><div><strong>{item.message}</strong><small>{item.code}{item.node_id ? " · 点击定位节点" : ""}</small></div></button>)}
              {validation.valid && !validation.warnings.length && <div className="v5-flow-panel-empty success"><Check size={24} /><span>未发现阻塞问题或配置建议。</span></div>}
            </>}
          </section>
        ) : inspectorTab === "history" && draft ? (
          <div className="v5-flow-history">
            <section><label><Clock3 size={12} />运行历史</label>{runs?.length ? runs.map((run) => <article key={run.id}><span className={`v4-status ${run.status === "completed" ? "green" : "amber"}`}><i />{run.dry_run ? "DRY RUN" : run.status.toUpperCase()}</span><div><strong>{run.dry_run ? "静态试运行" : Boolean(run.result.node_test) ? "单节点测试" : run.retry_node_id ? "节点恢复运行" : "完整运行"}</strong><small>V{run.version_no ?? "-"} · {relativeTime(run.created_at)}</small></div><b>{Number(run.usage.tokens_input ?? 0) + Number(run.usage.tokens_output ?? 0)} T</b></article>) : <div className="v5-flow-panel-empty"><History size={22} /><span>还没有运行记录</span></div>}</section>
            <section><label><RotateCcw size={12} />版本快照</label>{versions?.map((version, index) => <article key={version.id}><span className="v5-flow-version">V{version.version_no}</span><div><strong>{version.label || "自动保存"}</strong><small>{relativeTime(version.created_at)} · {version.name}</small></div><button type="button" disabled={active || index === 0} onClick={() => void restoreVersion(version)}>恢复</button></article>)}</section>
          </div>
        ) : draft && selectedNode ? (
          <>
            <section className="v4-flow-form">
              <label>节点定义</label>
              <span>名称</span><input value={selectedNode.name} disabled={active} onChange={(event) => updateNode({ name: event.target.value })} />
              <span>类型</span><select value={selectedNode.node_type} disabled={active} onChange={(event) => updateNode({ node_type: event.target.value as NodeType, config: {} })}>{Object.entries(nodeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
              {selectedNode.node_type === "agent" && <><span>运行 Profile</span><select value={String(selectedNode.config.profile_id ?? "")} disabled={active} onChange={(event) => updateNodeConfig("profile_id", event.target.value || null)}><option value="">跟随 Flow / 项目设置</option>{runtimeProfiles?.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.description}</option>)}</select><span>任务提示词</span><textarea value={String(selectedNode.config.prompt ?? "")} disabled={active} onChange={(event) => updateNodeConfig("prompt", event.target.value)} /></>}
              {selectedNode.node_type === "approval" && <><span>审批说明</span><textarea value={String(selectedNode.config.description ?? "")} disabled={active} onChange={(event) => updateNodeConfig("description", event.target.value)} /></>}
              {selectedNode.node_type === "condition" && <><span>判断方式</span><select value={String(selectedNode.config.operator ?? "contains")} disabled={active} onChange={(event) => updateNodeConfig("operator", event.target.value)}><option value="contains">包含</option><option value="not_contains">不包含</option><option value="equals">完全等于</option><option value="starts_with">开头为</option><option value="ends_with">结尾为</option></select><span>比较值</span><input value={String(selectedNode.config.value ?? "")} disabled={active} onChange={(event) => updateNodeConfig("value", event.target.value)} /></>}
              {selectedNode.node_type === "tool" && <><span>MCP Server</span><select value={String(selectedNode.config.server_id ?? "")} disabled={active} onChange={(event) => updateNode({ config: { ...selectedNode.config, server_id: event.target.value, tool_name: "", arguments: {} } })}><option value="">选择 Server</option>{servers?.filter((server) => server.enabled).map((server) => <option key={server.id} value={server.id}>{server.name}</option>)}</select><span>工具名称</span><select value={String(selectedNode.config.tool_name ?? "")} disabled={active || !selectedServer} onChange={(event) => updateNode({ config: { ...selectedNode.config, tool_name: event.target.value, arguments: {} } })}><option value="">{selectedServer?.tools.length ? "选择已发现工具" : "先检测 MCP Server"}</option>{selectedServer?.tools.map((tool) => <option key={tool.name} value={tool.name}>{tool.name}</option>)}</select>{selectedTool && <><span>工具参数</span><JsonSchemaForm schema={selectedTool.inputSchema} value={selectedNode.config.arguments && typeof selectedNode.config.arguments === "object" ? selectedNode.config.arguments as Record<string, unknown> : {}} disabled={active} onChange={(value) => updateNodeConfig("arguments", value)} /></>}</>}
              <span>失败策略</span><select value={String(selectedNode.config.error_strategy ?? "fail_flow")} disabled={active} onChange={(event) => updateNodeConfig("error_strategy", event.target.value)}><option value="fail_flow">终止整个 Flow</option><option value="continue">记录失败并继续</option><option value="skip_branch">跳过当前分支</option></select>
              <span>节点重试</span><select value={String(selectedNode.config.retry_count ?? draft.settings.max_retries ?? 1)} disabled={active} onChange={(event) => updateNodeConfig("retry_count", Number(event.target.value))}><option value="0">不重试</option><option value="1">重试 1 次</option><option value="2">重试 2 次</option><option value="3">重试 3 次</option></select>
              <span>单节点测试输入</span><textarea className="v5-flow-test-input" value={typeof selectedNode.config.test_input === "string" ? selectedNode.config.test_input : JSON.stringify(selectedNode.config.test_input ?? {}, null, 2)} disabled={active} onChange={(event) => updateNodeConfig("test_input", event.target.value)} placeholder="可选：输入文字或 JSON 示例" />
            </section>
            <section className="v5-flow-bindings">
              <label><Braces size={12} />上游数据绑定</label>
              <p>把直接上游的输出字段映射为当前节点的命名输入。</p>
              {incomingNodes.map((node) => {
                const bindings = Array.isArray(selectedNode.config.input_bindings) ? selectedNode.config.input_bindings as InputBinding[] : [];
                const binding = bindings.find((item) => item.source_node_id === node.id);
                return <article key={node.id} className={binding ? "active" : ""}><header><button type="button" disabled={active} onClick={() => updateInputBinding(node.id, binding ? null : {})}><i>{binding && <Check size={10} />}</i><span>{node.name}</span></button><ArrowRight size={12} /></header>{binding && <div><label>输出字段<input value={binding.path} disabled={active} onChange={(event) => updateInputBinding(node.id, { path: event.target.value })} placeholder="summary" /></label><label>目标名称<input value={binding.target} disabled={active} onChange={(event) => updateInputBinding(node.id, { target: event.target.value })} placeholder="context" /></label></div>}</article>;
              })}
              {!incomingNodes.length && <div className="v5-flow-panel-empty compact"><Cable size={18} /><span>从节点输出端口拖到这里的输入端口后，即可绑定数据。</span></div>}
            </section>
            <section className="v4-flow-links">
              <label><Link2 size={12} />上游连接</label>
              {draft.nodes.filter((node) => node.id !== selectedNode.id).map((node) => {
                const edge = draft.edges.find((item) => item.source_node_id === node.id && item.target_node_id === selectedNode.id);
                return <div key={node.id}><button className={edge ? "active" : ""} type="button" disabled={active} onClick={() => toggleIncoming(node.id)}><i>{edge && <Check size={10} />}</i><span>{node.name}</span></button>{edge && node.node_type === "condition" && <select value={"when" in edge.condition ? String(edge.condition.when) : "always"} disabled={active} onChange={(event) => setEdgeBranch(node.id, event.target.value)}><option value="always">始终</option><option value="true">条件成立</option><option value="false">条件不成立</option></select>}</div>;
              })}
              <div className="v5-flow-node-actions"><button type="button" disabled={active} onClick={duplicateNode}><Copy size={13} />复制节点</button>{selectedNode.node_type !== "approval" && <button type="button" disabled={active} onClick={() => void testSelectedNode()}><TestTube2 size={13} />测试节点</button>}{["failed", "cancelled"].includes(selectedNode.status) && <button type="button" disabled={active} onClick={() => void retrySelectedNode()}><RefreshCcw size={13} />从此节点重试</button>}</div>
              <button className="v4-flow-remove-node" type="button" disabled={active || draft.nodes.length <= 1} onClick={removeNode}><Trash2 size={13} />删除节点</button>
            </section>
          </>
        ) : draft ? (
          <>
            <section className="v4-flow-form"><label>流程信息</label><span>名称</span><input value={draft.name} disabled={active} onChange={(event) => updateFlow({ name: event.target.value })} /><span>说明</span><textarea value={draft.description} disabled={active} onChange={(event) => updateFlow({ description: event.target.value })} /></section>
            <section className="v4-flow-form"><label>执行约束</label><span>默认运行 Profile</span><select value={String(draft.settings.profile_id ?? "")} disabled={active} onChange={(event) => updateFlowSetting("profile_id", event.target.value || null)}><option value="">跟随项目默认配置</option>{runtimeProfiles?.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select><span>失败重试</span><input type="number" min="0" max="3" value={Number(draft.settings.max_retries ?? 1)} disabled={active} onChange={(event) => updateFlowSetting("max_retries", Number(event.target.value))} /><span>并发 Agent</span><input type="number" min="1" max="8" value={Number(draft.settings.max_concurrency ?? 4)} disabled={active} onChange={(event) => updateFlowSetting("max_concurrency", Number(event.target.value))} /><span>最大用时（分钟）</span><input type="number" min="1" value={Math.round(Number(draft.settings.max_runtime_seconds ?? 2700) / 60)} disabled={active} onChange={(event) => updateFlowSetting("max_runtime_seconds", Number(event.target.value) * 60)} /><span>费用预算（USD）</span><input type="number" min="0" step="0.1" value={Number(draft.settings.max_cost_usd ?? 3)} disabled={active} onChange={(event) => updateFlowSetting("max_cost_usd", Number(event.target.value))} /><span>Token 预算</span><input type="number" min="0" value={Number(draft.settings.max_tokens ?? 500000)} disabled={active} onChange={(event) => updateFlowSetting("max_tokens", Number(event.target.value))} /><label className="v4-flow-checkbox"><input type="checkbox" checked={Boolean(draft.settings.parallel_worktrees ?? true)} disabled={active} onChange={(event) => updateFlowSetting("parallel_worktrees", event.target.checked)} /><span>并行 Agent 使用隔离 Worktree</span></label></section>
          </>
        ) : null}
        {draft && inspectorTab === "edit" && <button className="v4-flow-inspector-mode" type="button" onClick={() => setSelectedNodeId(undefined)}>{selectedNode ? "返回流程设置" : "选择画布节点进行编辑"}</button>}
      </aside>}

      {modalOpen && (
        <div className="v4-modal-backdrop" onMouseDown={() => setModalOpen(false)}>
          <form className="v4-modal v5-flow-create-modal" onSubmit={create} onMouseDown={(event) => event.stopPropagation()}>
            <header><div><strong>新建 Agent Flow</strong><small>从经过验证的结构开始，再自由编辑节点、连接、数据与失败策略</small></div><button type="button" onClick={() => setModalOpen(false)}><X size={18} /></button></header>
            <div className="v5-flow-create-body">
              <section className="v5-flow-template-picker">
                <label><LayoutTemplate size={13} />选择起点</label>
                <div>{templates?.map((template) => <button className={form.template_id === template.id ? "active" : ""} type="button" key={template.id} onClick={() => setForm({ ...form, template_id: template.id, description: form.description || template.description })}><span>{template.category}</span><strong>{template.name}</strong><p>{template.description}</p><small>{template.nodes.length} 节点 · {template.edges.length} 连线</small></button>)}</div>
              </section>
              <div className="v4-form-grid">
                <label className="full"><span>工作流名称</span><input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：版本发布前复核" /></label>
                <label className="full"><span>所属项目</span><select required value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })}><option value="">选择项目</option>{projects?.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
                <label className="full"><span>说明</span><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="说明这个 Flow 的目标与使用场景" /></label>
              </div>
            </div>
            {error && <div className="v4-error">{error}</div>}
            <footer><button className="v4-button secondary" type="button" onClick={() => setModalOpen(false)}>取消</button><button className="v4-button primary" type="submit" disabled={!templates?.length}><Check size={16} />使用模板创建</button></footer>
          </form>
        </div>
      )}
    </div>
  );
}
