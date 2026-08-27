import {
  Activity,
  ArrowRight,
  Bot,
  Check,
  CircleAlert,
  Clock3,
  Coins,
  Cpu,
  FolderKanban,
  GitFork,
  ListTodo,
  MessageSquarePlus,
  Plus,
  ShieldAlert,
  Sparkles,
  Unplug,
  X,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { ApprovalRequest, StudioDashboardData } from "./types";

function compact(value: number) {
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value || 0);
}

function relativeTime(value: string | null | undefined) {
  if (!value) return "刚刚";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function failureSummary(value: string | null | undefined) {
  if (!value) return "会话意外中断，打开查看原因和可恢复操作。";
  let summary: unknown = value.trim();
  for (let depth = 0; depth < 2; depth += 1) {
    if (typeof summary !== "string" || !summary.trim().startsWith("{")) break;
    try {
      const parsed = JSON.parse(summary) as Record<string, unknown>;
      summary = parsed.message ?? parsed.error ?? parsed.result ?? parsed.detail ?? summary;
    } catch {
      break;
    }
  }
  const readable = String(summary).replace(/\\n/g, " ").replace(/\s+/g, " ").trim();
  return readable.length > 180 ? `${readable.slice(0, 177)}…` : readable;
}

const sessionStatus: Record<string, string> = {
  queued: "排队中",
  running: "执行中",
  waiting_approval: "等待审批",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
};

export default function ControlCenter() {
  const navigate = useNavigate();
  const { data, loading, error, refresh } = useApi<StudioDashboardData>("/studio/dashboard", 3_000);

  async function decide(approval: ApprovalRequest, decision: "allow_once" | "deny") {
    await api(`/approvals/${approval.id}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, reason: "在首页处理" }),
    });
    await refresh();
  }

  const hasProjects = (data?.project_count ?? 0) > 0;
  const hasRuntime = (data?.runtime_health?.models_enabled ?? 0) > 0 && (data?.runtime_health?.runners_enabled ?? 0) > 0;
  const nextAction = (data?.pending_approvals ?? 0) > 0
    ? { eyebrow: "需要你的决定", title: `处理 ${data?.pending_approvals} 个待审批操作`, detail: "Agent 已暂停在安全边界，处理后会继续执行。", to: "#pending-approvals", label: "查看审批", icon: ShieldAlert }
    : (data?.active_sessions ?? 0) > 0
      ? { eyebrow: "工作正在进行", title: `继续查看 ${data?.active_sessions} 个运行中会话`, detail: "查看公开进度、工具调用和文件变更。", to: "/studio", label: "查看运行", icon: Activity }
      : !hasRuntime
        ? { eyebrow: "首次使用 · 第 1 步", title: "准备 Agent 与模型", detail: "检查本机 CLI、登录状态和可用模型。", to: "/models", label: "检查运行环境", icon: Cpu }
        : !hasProjects
          ? { eyebrow: "首次使用 · 第 2 步", title: "添加一个本地项目", detail: "只授权 Agent 本次工作真正需要的目录。", to: "/projects?new=1", label: "添加项目", icon: FolderKanban }
          : { eyebrow: "一切就绪", title: "开始一项新的 Agent 工作", detail: "选择项目、Agent 和模型，然后直接描述目标。", to: "/studio?new=1", label: "开始新会话", icon: Sparkles };
  const NextIcon = nextAction.icon;

  return (
    <div className="v4-page v4-control-page v53-home">
      <header className="v4-page-head v53-page-head">
        <div><span>本地 Agent 工作台</span><h1>今天要做什么？</h1><p>继续正在进行的工作，处理阻塞，或从一个项目开始新任务。</p></div>
        <div><Link className="v4-button secondary" to="/projects?new=1"><Plus size={16} />添加项目</Link><Link className="v4-button primary" to="/studio?new=1"><MessageSquarePlus size={16} />开始新会话</Link></div>
      </header>

      {error && <div className="v4-error" role="alert"><CircleAlert size={16} />无法读取工作台数据：{error}<button type="button" onClick={() => void refresh()}>重试</button></div>}

      <section className="v53-home-lead">
        <article className="v53-next-action">
          <span className="v53-next-icon"><NextIcon size={22} /></span>
          <div><small>{nextAction.eyebrow}</small><h2>{nextAction.title}</h2><p>{nextAction.detail}</p></div>
          {nextAction.to.startsWith("#")
            ? <a className="v4-button primary" href={nextAction.to}>{nextAction.label}<ArrowRight size={15} /></a>
            : <Link className="v4-button primary" to={nextAction.to}>{nextAction.label}<ArrowRight size={15} /></Link>}
        </article>
        <nav className="v53-quick-actions" aria-label="常用操作">
          <Link to="/studio?new=1"><Sparkles size={18} /><span><strong>新会话</strong><small>直接交代一项工作</small></span></Link>
          <Link to="/tasks?new=1"><ListTodo size={18} /><span><strong>新任务</strong><small>建立可追踪工作项</small></span></Link>
          <Link to="/flows?new=1"><GitFork size={18} /><span><strong>自动化</strong><small>编排重复流程</small></span></Link>
          <Link to="/benchmarks"><Activity size={18} /><span><strong>能力评测</strong><small>比较 Agent 与模型</small></span></Link>
        </nav>
      </section>

      <section className="v53-home-main">
        <article className="v4-panel v53-attention" id="pending-approvals">
          <header className="v4-panel-head"><div><strong>需要你处理</strong><small>审批、失败与中断会优先出现在这里</small></div>{(data?.pending_approvals ?? 0) > 0 && <span className="v4-status amber"><i />{data?.pending_approvals} 项待处理</span>}</header>
          {data?.pending_approvals_list?.length ? <div className="v53-approval-list">
            {data.pending_approvals_list.slice(0, 3).map((approval) => <section key={approval.id} className="v53-approval-row">
              <span className={`risk ${approval.risk_level}`}><ShieldAlert size={17} /></span>
              <div><strong>{approval.title}</strong><p>{approval.description || "Agent 请求执行一项受保护的操作。"}</p><code>{String(approval.request.command ?? approval.request.path ?? approval.request_type)}</code></div>
              <small>{approval.risk_level === "high" ? "高风险" : approval.risk_level === "medium" ? "需确认" : "低风险"}</small>
              <div className="actions"><button type="button" className="deny" onClick={() => void decide(approval, "deny")}><X size={14} />拒绝</button><button type="button" className="allow" onClick={() => void decide(approval, "allow_once")}><Check size={14} />仅允许这一次</button></div>
            </section>)}
          </div> : data?.recent_failures?.length ? <div className="v53-failure-list">
            {data.recent_failures.slice(0, 3).map((failure) => <button key={failure.id} type="button" onClick={() => navigate(`/studio/${failure.id}`)}><CircleAlert size={17} /><span><strong>{failure.title}</strong><small>{failure.project_name} · {relativeTime(failure.updated_at)}</small><p>{failureSummary(failure.error_message)}</p></span><ArrowRight size={14} /></button>)}
          </div> : <div className="v4-empty compact"><Check size={22} /><strong>目前没有阻塞</strong><span>需要审批、失败或中断的工作会优先显示在这里</span></div>}
        </article>

        <article className="v4-panel v53-running-work">
          <header className="v4-panel-head"><div><strong>继续工作</strong><small>最近更新的会话与项目</small></div><Link to="/studio">全部会话 <ArrowRight size={14} /></Link></header>
          <div className="v53-session-list">
            {data?.active_sessions_list?.length ? data.active_sessions_list.slice(0, 4).map((session) => <button key={session.id} type="button" onClick={() => navigate(`/studio/${session.id}`)}>
              <span className="v4-agent-avatar">{session.runner_name?.slice(0, 2).toUpperCase() || "AI"}</span>
              <span><strong>{session.title}</strong><small>{session.project_name} · {session.runner_name}</small><p>{session.summary || "Agent 正在处理任务"}</p></span>
              <em className={session.status === "waiting_approval" ? "attention" : "running"}>{sessionStatus[session.status] ?? session.status}</em><time>{relativeTime(session.updated_at)}</time>
            </button>) : data?.recent_projects?.length ? data.recent_projects.slice(0, 3).map((project) => <button key={project.id} type="button" onClick={() => navigate(`/projects/${project.id}`)}>
              <span className="v4-agent-avatar project"><FolderKanban size={17} /></span><span><strong>{project.name}</strong><small>{project.branch || "本地项目"}</small><p>{project.description || project.root_path}</p></span><em>{project.session_count} 个会话</em><time>{relativeTime(project.last_opened_at)}</time>
            </button>) : <div className="v4-empty compact"><FolderKanban size={22} /><strong>{loading ? "正在读取本地工作…" : "还没有可以继续的工作"}</strong><span>添加一个项目，然后开始第一轮会话</span></div>}
          </div>
        </article>
      </section>

      <section className="v53-home-secondary">
        <article className="v4-panel v53-work-queue">
          <header className="v4-panel-head"><div><strong>任务与自动化</strong><small>可以离开页面持续执行的工作</small></div><Link to="/tasks">打开任务中心 <ArrowRight size={14} /></Link></header>
          <div>
            {data?.active_tasks_list?.slice(0, 4).map((task) => <button key={`task-${task.id}`} type="button" onClick={() => navigate(`/tasks/${task.id}`)}><span><ListTodo size={15} /></span><div><strong>{task.title}</strong><small>{task.project_name || "未绑定项目"}</small></div><b className={task.status === "approval" ? "attention" : "running"}>{task.status === "approval" ? "等待审批" : "执行中"}</b></button>)}
            {data?.active_flows_list?.slice(0, 3).map((flow) => <button key={`flow-${flow.id}`} type="button" onClick={() => navigate(`/flows?flow=${flow.id}`)}><span><GitFork size={15} /></span><div><strong>{flow.name}</strong><small>{flow.project_name || "未绑定项目"} · {flow.completed_nodes}/{flow.node_count} 节点</small></div><b className="running">运行中</b></button>)}
            {!data?.active_tasks_list?.length && !data?.active_flows_list?.length && <div className="v4-empty compact"><Check size={22} /><strong>当前没有后台工作</strong><span>需要追踪进度或重复执行时，可以创建任务或 Flow</span></div>}
          </div>
        </article>

        <article className="v4-panel v53-runtime-summary">
          <header className="v4-panel-head"><div><strong>运行准备</strong><small>开始工作前需要的本地资源</small></div><Link to="/settings">管理资源 <ArrowRight size={14} /></Link></header>
          <div className="v5-health-grid">
            <Link to="/models"><Cpu size={18} /><span><strong>{data?.runtime_health?.models_enabled ?? 0} 个模型</strong><small>用于会话、Flow 与评测</small></span><i className={(data?.runtime_health?.models_enabled ?? 0) > 0 ? "healthy" : "warning"} /></Link>
            <Link to="/models"><Bot size={18} /><span><strong>{data?.runtime_health?.runners_enabled ?? 0} 个 Agent</strong><small>本机已启用的执行入口</small></span><i className={(data?.runtime_health?.runners_enabled ?? 0) > 0 ? "healthy" : "warning"} /></Link>
            <Link to="/tools"><Unplug size={18} /><span><strong>{data?.runtime_health?.mcp_healthy ?? 0} / {data?.runtime_health?.mcp_enabled ?? 0} 个工具连接正常</strong><small>{(data?.runtime_health?.mcp_error ?? 0) > 0 ? `${data?.runtime_health?.mcp_error} 个连接需要处理` : "没有已知连接错误"}</small></span><i className={(data?.runtime_health?.mcp_error ?? 0) > 0 ? "danger" : "healthy"} /></Link>
          </div>
        </article>
      </section>

      <section className="v53-home-stats" aria-label="使用概览">
        <article><Clock3 size={15} /><span>历史会话</span><strong>{data?.session_count ?? 0}</strong></article>
        <article><ListTodo size={15} /><span>已完成任务</span><strong>{data?.completed_tasks ?? 0}</strong></article>
        <article><Activity size={15} /><span>Token 使用</span><strong>{compact(data?.total_tokens ?? 0)}</strong></article>
        <article><Coins size={15} /><span>费用估算</span><strong>${(data?.total_cost ?? 0).toFixed(2)}</strong></article>
      </section>
    </div>
  );
}
