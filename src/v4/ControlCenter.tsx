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
  Play,
  ShieldAlert,
  Sparkles,
  Unplug,
  X,
  Zap,
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

export default function ControlCenter() {
  const navigate = useNavigate();
  const { data, loading, error, refresh } = useApi<StudioDashboardData>("/studio/dashboard", 3_000);

  async function decide(approval: ApprovalRequest, decision: "allow_once" | "deny") {
    await api(`/approvals/${approval.id}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, reason: "在控制中心处理" }),
    });
    await refresh();
  }

  return (
    <div className="v4-page v4-control-page">
      <header className="v4-page-head">
        <div><span>LOCAL AGENT COMMAND</span><h1>控制中心</h1><p>统一观察项目、会话、审批和 Agent Runtime 状态，所有操作都在本机完成。</p></div>
        <div><Link className="v4-button secondary" to="/flows"><GitFork size={16} />新建工作流</Link><Link className="v4-button primary" to="/studio"><Sparkles size={16} />新建 Agent 会话</Link></div>
      </header>

      {error && <div className="v4-error">{error}<button type="button" onClick={() => void refresh()}>重试</button></div>}

      <section className="v4-command-grid">
        <article className="v4-panel v4-hero-panel">
          <div className="v4-hero-copy">
            <span><i />Agent Runtime 5.0</span>
            <h2>把所有 Agent 放进一个<br /><em>真正可操作的工作台。</em></h2>
            <p>在统一界面中对话、审阅文件、批准命令、观察终端，并把任务交给不同 Agent 协同完成。</p>
            <div><Link className="v4-button primary" to="/studio"><Play size={16} />进入 Agent Studio</Link><Link className="v4-button secondary" to="/projects"><FolderKanban size={16} />选择项目</Link><small><b>{data?.active_sessions ?? 0} 个</b> Agent 正在本机运行</small></div>
          </div>
          <div className="v4-orbit" aria-hidden="true"><i /><b /><em /><span /></div>
        </article>

        <article className="v4-panel v4-approval-panel" id="pending-approvals">
          <header className="v4-panel-head"><div><strong>待你处理</strong><small>{data?.pending_approvals ?? 0} 个权限请求</small></div><span className="v4-status amber"><i />REVIEW</span></header>
          {data?.pending_approvals_list?.length ? (
            <div className="v4-approval-list">
              {data.pending_approvals_list.slice(0, 2).map((approval) => (
                <section key={approval.id} className="v4-approval-card">
                  <header><ShieldAlert size={17} /><strong>{approval.title}</strong><small>{approval.risk_level.toUpperCase()}</small></header>
                  <p>{approval.description || "Agent 请求执行一项受保护的操作。"}</p>
                  <code>{String(approval.request.command ?? approval.request.path ?? approval.request_type)}</code>
                  <div><button type="button" className="deny" onClick={() => void decide(approval, "deny")}><X size={14} />拒绝</button><button type="button" className="allow" onClick={() => void decide(approval, "allow_once")}><Check size={14} />允许一次</button></div>
                </section>
              ))}
            </div>
          ) : <div className="v4-empty compact"><Check size={22} /><strong>没有待处理审批</strong><span>受保护操作会在这里等待你的决定</span></div>}
        </article>
      </section>

      <section className="v4-metrics">
        <article><header><span>活跃会话</span><Bot size={16} /></header><strong>{String(data?.active_sessions ?? 0).padStart(2, "0")}</strong><small>{data?.session_count ?? 0} 个历史会话</small></article>
        <article><header><span>开放任务</span><Zap size={16} /></header><strong>{String(data?.open_tasks ?? 0).padStart(2, "0")}</strong><small>{data?.completed_tasks ?? 0} 个已完成</small></article>
        <article><header><span>Token 使用</span><Clock3 size={16} /></header><strong>{compact(data?.total_tokens ?? 0)}</strong><small>跨全部 Studio 会话</small></article>
        <article><header><span>本地运行费用</span><Coins size={16} /></header><strong>${(data?.total_cost ?? 0).toFixed(2)}</strong><small>按模型公开价格估算</small></article>
      </section>

      <section className="v4-dashboard-lower">
        <article className="v4-panel">
          <header className="v4-panel-head"><div><strong>正在运行</strong><small>Agent 活动与项目进度</small></div><Link to="/studio">查看 Studio <ArrowRight size={14} /></Link></header>
          <div className="v4-run-list">
            {data?.active_sessions_list?.length ? data.active_sessions_list.map((session) => (
              <button key={session.id} type="button" onClick={() => navigate(`/studio/${session.id}`)}>
                <span className="v4-agent-avatar">{session.runner_name?.slice(0, 2).toUpperCase() || "AI"}</span>
                <span><strong>{session.title}</strong><small>{session.runner_name} · {session.model_name}</small></span>
                <span><strong>{session.project_name}</strong><small>{session.summary || "Agent 正在处理任务"}</small></span>
                <span className={`v4-status ${session.status === "waiting_approval" ? "amber" : "green"}`}><i />{session.status}</span>
                <time>{relativeTime(session.updated_at)}</time>
              </button>
            )) : <div className="v4-empty compact"><Bot size={22} /><strong>{loading ? "正在读取 Runtime…" : "当前没有运行中的 Agent"}</strong><span>进入 Agent Studio 开始一个本地会话</span></div>}
          </div>
        </article>

        <article className="v4-panel">
          <header className="v4-panel-head"><div><strong>最近项目</strong><small>已授权的本地工作区</small></div><Link to="/projects">全部项目 <ArrowRight size={14} /></Link></header>
          <div className="v4-project-strip">
            {data?.recent_projects?.slice(0, 2).map((project) => (
              <button key={project.id} type="button" onClick={() => navigate(`/projects/${project.id}`)}>
                <span><FolderKanban size={18} /></span><strong>{project.name}</strong><small>{project.branch || "local"}</small><p>{project.description || project.root_path}</p><footer><b>{project.session_count} 会话</b><time>{relativeTime(project.last_opened_at)}</time></footer>
              </button>
            ))}
            {!data?.recent_projects?.length && <div className="v4-empty compact"><FolderKanban size={22} /><strong>还没有项目</strong><span>添加本地目录后即可交给 Agent 操作</span></div>}
          </div>
        </article>
      </section>

      <section className="v5-control-activity">
        <article className="v4-panel v5-unified-activity">
          <header className="v4-panel-head"><div><strong>统一活动流</strong><small>会话、任务与 Flow 的可验证进度</small></div><span className="v4-status green"><i />LIVE</span></header>
          <div>
            {data?.activity?.length ? data.activity.slice(0, 12).map((item) => {
              const Icon = item.source_type === "session" ? Bot : item.source_type === "task" ? ListTodo : GitFork;
              return <button key={item.id} type="button" onClick={() => navigate(item.href)}>
                <span className={`v5-activity-icon ${item.status}`}><Icon size={15} /></span>
                <span><strong>{item.summary}</strong><small>{item.source_title} · {item.project_name || "本地工作区"}</small></span>
                <b>{item.source_type === "session" ? "SESSION" : item.source_type === "task" ? "TASK" : "FLOW"}</b>
                <time>{relativeTime(item.created_at)}</time>
                <ArrowRight size={13} />
              </button>;
            }) : <div className="v4-empty compact"><Activity size={22} /><strong>还没有运行活动</strong><span>Agent、任务和 Flow 的进度会汇总到这里</span></div>}
          </div>
        </article>

        <article className="v4-panel v5-active-work">
          <header className="v4-panel-head"><div><strong>当前工作队列</strong><small>离开页面也能掌握执行状态</small></div><Link to="/tasks">任务中心 <ArrowRight size={14} /></Link></header>
          <div>
            {data?.active_tasks_list?.map((task) => <button key={`task-${task.id}`} type="button" onClick={() => navigate(`/tasks/${task.id}`)}>
              <span><ListTodo size={15} /></span><div><strong>{task.title}</strong><small>{task.project_name || "未绑定项目"} · {task.priority.toUpperCase()}</small></div><b className={task.status === "approval" ? "attention" : "running"}>{task.status}</b>
            </button>)}
            {data?.active_flows_list?.map((flow) => <button key={`flow-${flow.id}`} type="button" onClick={() => navigate(`/flows?flow=${flow.id}`)}>
              <span><GitFork size={15} /></span><div><strong>{flow.name}</strong><small>{flow.project_name || "未绑定项目"} · {flow.completed_nodes}/{flow.node_count} 节点</small></div><b className="running">{flow.status}</b>
            </button>)}
            {!data?.active_tasks_list?.length && !data?.active_flows_list?.length && <div className="v4-empty compact"><Check size={22} /><strong>工作队列为空</strong><span>后台任务和 Flow 运行时会显示在这里</span></div>}
          </div>
        </article>
      </section>

      <section className="v5-observability-grid">
        <article className="v4-panel v5-runtime-health">
          <header className="v4-panel-head"><div><strong>运行环境摘要</strong><small>模型、Agent 与 MCP 配置状态</small></div><Link to="/models">管理运行时 <ArrowRight size={14} /></Link></header>
          <div className="v5-health-grid">
            <Link to="/models"><Cpu size={18} /><span><strong>{data?.runtime_health?.models_enabled ?? 0} 个模型</strong><small>可供 Studio、Flow 与测评选择</small></span><i className={(data?.runtime_health?.models_enabled ?? 0) > 0 ? "healthy" : "warning"} /></Link>
            <Link to="/models"><Bot size={18} /><span><strong>{data?.runtime_health?.runners_enabled ?? 0} 个 Agent</strong><small>进入运行时页可执行真实能力检测</small></span><i className={(data?.runtime_health?.runners_enabled ?? 0) > 0 ? "healthy" : "warning"} /></Link>
            <Link to="/tools"><Unplug size={18} /><span><strong>{data?.runtime_health?.mcp_healthy ?? 0} / {data?.runtime_health?.mcp_enabled ?? 0} MCP 健康</strong><small>{(data?.runtime_health?.mcp_error ?? 0) > 0 ? `${data?.runtime_health?.mcp_error} 个连接需要处理` : "工具连接没有已知错误"}</small></span><i className={(data?.runtime_health?.mcp_error ?? 0) > 0 ? "danger" : (data?.runtime_health?.mcp_enabled ?? 0) > 0 ? "healthy" : "muted"} /></Link>
          </div>
        </article>

        <article className="v4-panel v5-recent-failures">
          <header className="v4-panel-head"><div><strong>最近需要关注</strong><small>失败或因重启中断的 Agent 会话</small></div><Link to="/studio">全部会话 <ArrowRight size={14} /></Link></header>
          <div className="v5-failure-list">
            {data?.recent_failures?.length ? data.recent_failures.map((failure) => (
              <button key={failure.id} type="button" onClick={() => navigate(`/studio/${failure.id}`)}>
                <CircleAlert size={17} />
                <span><strong>{failure.title}</strong><small>{failure.project_name} · {failure.runner_name || "Agent"} · {relativeTime(failure.updated_at)}</small></span>
                <p>{failure.error_message || (failure.status === "interrupted" ? "应用退出时任务仍在运行，可打开会话继续处理。" : "会话执行失败，打开查看公开进度与错误详情。")}</p>
                <ArrowRight size={14} />
              </button>
            )) : <div className="v4-empty compact"><Check size={22} /><strong>最近没有 Agent 失败</strong><span>失败和意外中断会集中显示在这里</span></div>}
          </div>
        </article>
      </section>
    </div>
  );
}
