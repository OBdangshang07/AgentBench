import {
  Activity,
  ArrowRight,
  Bell,
  Bot,
  Boxes,
  CheckCheck,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  CircleGauge,
  Command,
  FolderKanban,
  FlaskConical,
  GitFork,
  ListTodo,
  LoaderCircle,
  MessageSquareText,
  PlugZap,
  Search,
  Settings,
  ShieldAlert,
  Sparkles,
  TerminalSquare,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import agentbenchMark from "../assets/agentbench-mark.png";
import { useWorkspaceUx } from "../components/WorkspaceUx";
import { useApi } from "../lib/useApi";
import type { SystemStatus } from "../types";
import type { Project, StudioDashboardData, WorkspaceSearchResult } from "./types";

const operationNavigation = [
  { to: "/", label: "控制中心", icon: CircleGauge, end: true },
  { to: "/projects", label: "项目中心", icon: FolderKanban },
  { to: "/studio", label: "Agent Studio", icon: Sparkles },
  { to: "/flows", label: "Agent Flow", icon: GitFork },
  { to: "/tasks", label: "任务中心", icon: ListTodo },
];

const platformNavigation = [
  { to: "/models", label: "模型与 Agent", icon: Bot },
  { to: "/tools", label: "工具与 MCP", icon: PlugZap },
  { to: "/benchmarks", label: "Benchmarks", icon: FlaskConical },
  { to: "/settings", label: "本地设置", icon: Settings },
];

const quickActions = [
  { to: "/studio?new=1", label: "新建 Agent 会话", detail: "选择当前项目并开始一轮工作", icon: Sparkles },
  { to: "/tasks?new=1", label: "新建任务", detail: "创建可追踪、可重试的工作项", icon: ListTodo },
  { to: "/flows?new=1", label: "新建 Agent Flow", detail: "编排多 Agent 与工具节点", icon: GitFork },
  { to: "/projects?new=1", label: "添加本地项目", detail: "授权一个新的工作目录", icon: FolderKanban },
];

const pageNames: Array<[RegExp, string]> = [
  [/^\/$/, "控制中心"],
  [/^\/projects/, "项目中心"],
  [/^\/studio/, "Agent Studio"],
  [/^\/flows/, "Agent Flow"],
  [/^\/tasks/, "任务中心"],
  [/^\/tools/, "工具与 MCP"],
  [/^\/models/, "模型与 Agent"],
  [/^\/benchmarks|^\/library|^\/experiments|^\/leaderboard|^\/profiles|^\/runs/, "Benchmarks"],
  [/^\/settings/, "本地设置"],
];

function Brand() {
  return (
    <Link className="v4-brand" to="/" aria-label="AgentBench 控制中心">
      <span className="v4-brand-mark"><img src={agentbenchMark} alt="" /></span>
      <span><strong>AgentBench</strong><small>AGENT OPERATIONS</small></span>
      <em>V5</em>
    </Link>
  );
}

function NavigationGroup({ label, items }: { label: string; items: typeof operationNavigation }) {
  return (
    <section className="v4-nav-group">
      <header><span>{label}</span><small>{items.length} MODULES</small></header>
      <nav>
        {items.map(({ to, label: itemLabel, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => isActive ? "active" : ""}>
            <Icon size={19} /><span>{itemLabel}</span>
          </NavLink>
        ))}
      </nav>
    </section>
  );
}

export default function V4Layout() {
  const location = useLocation();
  const ux = useWorkspaceUx();
  const { data: dashboard } = useApi<StudioDashboardData>("/studio/dashboard", 4_000);
  const { data: status } = useApi<SystemStatus>("/system/status", 12_000);
  const { data: projects } = useApi<Project[]>("/projects", 10_000);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.localStorage.getItem("agentbench.workspace.sidebar.v1") === "collapsed");
  const [onboardingOpen, setOnboardingOpen] = useState(() => window.localStorage.getItem("agentbench.v5.onboarding.done") !== "1");
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const title = pageNames.find(([pattern]) => pattern.test(location.pathname))?.[1] ?? "AgentBench";
  const runners = status?.runners ?? [];
  const installed = runners.filter((runner) => runner.capability.installed).length;
  const unhealthyRunners = runners.filter((runner) => runner.capability.error).length;
  const searchPath = debouncedQuery.trim().length >= 2
    ? `/studio/search?query=${encodeURIComponent(debouncedQuery.trim())}&limit=32`
    : null;
  const { data: searchResults, loading: searchLoading, error: searchError } = useApi<WorkspaceSearchResult[]>(searchPath);
  const runtime = !status
    ? { label: "正在检测", tone: "checking" }
    : !status.database.ready
      ? { label: "服务异常", tone: "error" }
      : unhealthyRunners > 0
        ? { label: "部分异常", tone: "warning" }
        : installed === 0
          ? { label: "等待配置", tone: "warning" }
          : { label: "运行正常", tone: "ready" };
  const showOnboarding = onboardingOpen && Boolean(status && dashboard) && (installed === 0 || (dashboard?.project_count ?? 0) === 0);
  const selectedProject = projects?.find((project) => project.id === ux.selectedProjectId) ?? projects?.[0];

  function dismissOnboarding() {
    window.localStorage.setItem("agentbench.v5.onboarding.done", "1");
    setOnboardingOpen(false);
  }

  useEffect(() => {
    function handleKeyboard(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((value) => !value);
      }
      if (event.key === "Escape") {
        setPaletteOpen(false);
        setNotificationsOpen(false);
      }
    }
    window.addEventListener("keydown", handleKeyboard);
    return () => window.removeEventListener("keydown", handleKeyboard);
  }, []);

  useEffect(() => {
    window.localStorage.setItem("agentbench.workspace.sidebar.v1", sidebarCollapsed ? "collapsed" : "expanded");
  }, [sidebarCollapsed]);

  useEffect(() => {
    if (!projects?.length) return;
    if (!projects.some((project) => project.id === ux.selectedProjectId)) ux.setSelectedProjectId(projects[0].id);
  }, [projects, ux.selectedProjectId, ux.setSelectedProjectId]);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedQuery(query), 180);
    return () => window.clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    if (!paletteOpen) {
      setQuery("");
      setDebouncedQuery("");
    }
  }, [paletteOpen]);

  const commandItems = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return [...operationNavigation, ...platformNavigation].filter((item) => (
      !needle || item.label.toLowerCase().includes(needle)
    ));
  }, [query]);
  const visibleActions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return quickActions.filter((action) => !needle || `${action.label} ${action.detail}`.toLowerCase().includes(needle));
  }, [query]);

  const groupedResults = useMemo(() => {
    const groups: Record<WorkspaceSearchResult["kind"], WorkspaceSearchResult[]> = {
      project: [], session: [], task: [], flow: [],
    };
    for (const result of searchResults ?? []) groups[result.kind].push(result);
    return groups;
  }, [searchResults]);

  const resultMeta = {
    project: { label: "项目", icon: FolderKanban },
    session: { label: "会话", icon: MessageSquareText },
    task: { label: "任务", icon: ListTodo },
    flow: { label: "Flow", icon: GitFork },
  };

  return (
    <div className={`v4-shell density-${ux.density} ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className="v4-sidebar">
        <Brand />
        <button className="v5-shell-collapse" type="button" aria-label={sidebarCollapsed ? "展开主导航" : "收起主导航"} title={sidebarCollapsed ? "展开主导航" : "收起主导航"} onClick={() => setSidebarCollapsed((value) => !value)}>{sidebarCollapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}<span>{sidebarCollapsed ? "展开" : "收起导航"}</span></button>
        <div className="v4-nav-scroll">
          <NavigationGroup label="OPERATIONS" items={operationNavigation} />
          <NavigationGroup label="PLATFORM" items={platformNavigation} />
        </div>
        <section className={`v4-runtime-card ${runtime.tone}`}>
          <header><strong>Local Runtime</strong><span><i />{runtime.label}</span></header>
          <div><span>Agent adapters</span><b>{installed} / {runners.length || "—"}</b></div>
          <div><span>Active sessions</span><b>{dashboard?.active_sessions ?? 0}</b></div>
          <div className="v4-runtime-bar"><i style={{ width: `${runners.length ? Math.round(installed / runners.length * 100) : 0}%` }} /></div>
        </section>
      </aside>

      <header className="v4-topbar">
        <div className="v4-breadcrumb"><span>AGENTBENCH</span><ChevronRight size={13} /><strong>{title}</strong>{projects?.length ? <label className="v5-project-switcher" title={selectedProject?.root_path}><FolderKanban size={14} /><select aria-label="当前工作项目" value={selectedProject?.id ?? ""} onChange={(event) => ux.setSelectedProjectId(event.target.value)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label> : null}</div>
        <div className="v4-top-actions">
          <button className="v4-command-trigger" type="button" onClick={() => setPaletteOpen(true)}><Search size={15} /><span>搜索项目、会话或运行命令</span><kbd>Ctrl K</kbd></button>
          {(dashboard?.pending_approvals ?? 0) > 0 && <Link className="v5-approval-chip" to="/"><ShieldAlert size={15} /><span>{dashboard?.pending_approvals} 个操作等待审批</span></Link>}
          <Link className="v4-live-chip" to="/studio"><Activity size={15} /><span>{dashboard?.active_sessions ?? 0} 个会话运行中</span></Link>
          <button className="v5-density-toggle" type="button" title={`切换为${ux.density === "comfortable" ? "紧凑" : "舒适"}密度`} onClick={() => ux.setDensity(ux.density === "comfortable" ? "compact" : "comfortable")}><Boxes size={16} /><span>{ux.density === "comfortable" ? "舒适" : "紧凑"}</span></button>
          <button className={`v5-notification-trigger ${ux.unreadCount ? "unread" : ""}`} type="button" aria-label={`通知中心，${ux.unreadCount} 条未读`} onClick={() => { const opening = !notificationsOpen; setNotificationsOpen(opening); if (opening) ux.markNotificationsRead(); }}><Bell size={17} />{ux.unreadCount > 0 && <b>{Math.min(99, ux.unreadCount)}</b>}</button>
        </div>
      </header>

      <main className="v4-viewport"><Outlet /></main>

      {paletteOpen && (
        <div className="v4-palette-backdrop" onMouseDown={() => setPaletteOpen(false)}>
          <section className="v4-palette" onMouseDown={(event) => event.stopPropagation()}>
            <header><Search size={18} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入页面、项目或命令…" /><button type="button" onClick={() => setPaletteOpen(false)}><X size={16} /></button></header>
            {!!visibleActions.length && <label>立即执行</label>}
            {!!visibleActions.length && <div className="v5-command-actions">{visibleActions.map(({ to, label, detail, icon: Icon }) => <Link key={to} to={to} onClick={() => setPaletteOpen(false)}><span><Icon size={16} /></span><div><strong>{label}</strong><small>{detail}</small></div><ArrowRight size={14} /></Link>)}</div>}
            <label>{query.trim() ? "页面与命令" : "快速前往"}</label>
            <div className="v5-palette-list">
              {commandItems.map(({ to, label, icon: Icon }) => (
                <Link key={to} to={to} onClick={() => setPaletteOpen(false)}><Icon size={17} /><span>{label}</span><ChevronRight size={15} /></Link>
              ))}
            </div>
            {query.trim().length >= 2 && <label>工作区结果</label>}
            {query.trim().length >= 2 && (
              <div className="v5-palette-results">
                {(["project", "session", "task", "flow"] as const).flatMap((kind) => groupedResults[kind].map((result) => {
                  const Icon = resultMeta[kind].icon;
                  return (
                    <Link className="v5-search-result" key={`${kind}-${result.id}`} to={result.path} onClick={() => setPaletteOpen(false)}>
                      <span className="icon"><Icon size={16} /></span>
                      <span className="copy"><strong>{result.title}</strong><small>{result.extra || result.subtitle || resultMeta[kind].label}</small></span>
                      <em>{result.status || resultMeta[kind].label}</em><ChevronRight size={15} />
                    </Link>
                  );
                }))}
                {searchLoading && <div className="v5-palette-state"><LoaderCircle className="spin" size={16} />正在搜索本地工作区…</div>}
                {!searchLoading && !searchError && !searchResults?.length && <div className="v5-palette-state">没有匹配的项目、会话、任务或 Flow</div>}
                {searchError && <div className="v5-palette-state error">搜索失败：{searchError}</div>}
              </div>
            )}
            <footer><Command size={13} /> 本地数据 · Desktop {status?.version ?? "4.0 Preview"}</footer>
          </section>
        </div>
      )}

      {notificationsOpen && <aside className="v5-notification-center" aria-label="通知中心">
        <header><div><strong>通知中心</strong><small>{ux.notifications.length} 条本地事件</small></div><button type="button" title="全部标记已读" onClick={ux.markNotificationsRead}><CheckCheck size={15} /></button><button type="button" title="清空通知" onClick={ux.clearNotifications}><Trash2 size={15} /></button><button type="button" title="关闭" onClick={() => setNotificationsOpen(false)}><X size={15} /></button></header>
        <div>{[...ux.notifications].reverse().map((notification) => <article className={`${notification.kind} ${notification.read ? "read" : "unread"}`} key={notification.id}><i /><div><strong>{notification.title}</strong>{notification.message && <p>{notification.message}</p>}<time>{new Date(notification.created_at).toLocaleString("zh-CN")}</time></div></article>)}{!ux.notifications.length && <section><Bell size={24} /><strong>还没有通知</strong><p>任务完成、审批、失败和配置结果会保存在这里。</p></section>}</div>
      </aside>}

      {showOnboarding && (
        <div className="v4-modal-backdrop v5-onboarding-backdrop" onMouseDown={dismissOnboarding}>
          <section className="v5-onboarding" role="dialog" aria-modal="true" aria-labelledby="v5-onboarding-title" onMouseDown={(event) => event.stopPropagation()}>
            <header><div><small>AGENTBENCH V5 · LOCAL FIRST</small><h2 id="v5-onboarding-title">三步开始第一个本地 Agent 任务</h2><p>配置只保存在这台设备。平台不会自动访问未授权目录。</p></div><button type="button" aria-label="关闭首次使用向导" onClick={dismissOnboarding}><X size={17} /></button></header>
            <div className="v5-onboarding-steps">
              <Link to="/models" onClick={dismissOnboarding}><span className={installed > 0 ? "done" : "pending"}>{installed > 0 ? "✓" : "01"}</span><div><strong>检测 Agent 与模型</strong><p>{installed > 0 ? `已发现 ${installed} 个可运行 Agent` : "自动识别 CLI、登录状态和可选模型；支持快捷安装"}</p></div><TerminalSquare size={17} /></Link>
              <Link to="/projects" onClick={dismissOnboarding}><span className={(dashboard?.project_count ?? 0) > 0 ? "done" : "pending"}>{(dashboard?.project_count ?? 0) > 0 ? "✓" : "02"}</span><div><strong>授权一个本地项目</strong><p>{(dashboard?.project_count ?? 0) > 0 ? `已有 ${dashboard?.project_count} 个项目` : "只授权需要操作的目录，并为项目设置默认 Agent"}</p></div><FolderKanban size={17} /></Link>
              <Link to="/studio" onClick={dismissOnboarding}><span className="pending">03</span><div><strong>发送任务并观察执行</strong><p>附件、权限、审批、浏览器和终端都在同一个会话中</p></div><Sparkles size={17} /></Link>
            </div>
            <footer><button className="v4-button secondary" type="button" onClick={dismissOnboarding}>暂时跳过</button><Link className="v4-button primary" to={installed === 0 ? "/models" : "/projects"} onClick={dismissOnboarding}>开始配置<ArrowRight size={15} /></Link></footer>
          </section>
        </div>
      )}
    </div>
  );
}
