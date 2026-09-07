import {
  Activity,
  ArrowRight,
  Bell,
  Bot,
  Boxes,
  CheckCheck,
  ChevronRight,
  Menu,
  CircleGauge,
  Command,
  FolderKanban,
  FlaskConical,
  GitFork,
  HelpCircle,
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
import { APP_VERSION } from "../lib/api";
import { useWorkspaceUx } from "../components/WorkspaceUx";
import { useApi } from "../lib/useApi";
import type { SystemStatus } from "../types";
import type { Project, StudioDashboardData, WorkspaceSearchResult } from "./types";

interface NavigationItem {
  to: string;
  label: string;
  icon: typeof CircleGauge;
  end?: boolean;
  aliases?: string[];
}

const workspaceNavigation: NavigationItem[] = [
  { to: "/", label: "工作台", icon: CircleGauge, end: true },
  { to: "/studio", label: "Agent 会话", icon: Sparkles },
  { to: "/projects", label: "项目", icon: FolderKanban },
  { to: "/tasks", label: "任务", icon: ListTodo },
  { to: "/flows", label: "工作流", icon: GitFork },
];

const benchmarkNavigation: NavigationItem[] = [
  { to: "/benchmarks", label: "评测中心", icon: FlaskConical },
  { to: "/library", label: "测试套件", icon: Boxes },
  { to: "/experiments", label: "运行记录", icon: Activity, aliases: ["/runs"] },
  { to: "/leaderboard", label: "排行与报告", icon: CircleGauge, aliases: ["/profiles"] },
];

const resourceNavigation: NavigationItem[] = [
  { to: "/models", label: "Agent 与模型", icon: Bot },
  { to: "/tools", label: "工具与 MCP", icon: PlugZap },
  { to: "/settings", label: "设置", icon: Settings },
];

const quickActions = [
  { to: "/studio?new=1", label: "开始新会话", detail: "选择项目并把工作交给 Agent", icon: Sparkles },
  { to: "/tasks?new=1", label: "新建任务", detail: "创建可追踪、可重试的工作项", icon: ListTodo },
  { to: "/flows?new=1", label: "新建自动化 Flow", detail: "编排多 Agent 与工具节点", icon: GitFork },
  { to: "/projects?new=1", label: "添加本地项目", detail: "授权一个新的工作目录", icon: FolderKanban },
];

const pageNames: Array<[RegExp, string]> = [
  [/^\/$/, "工作台"],
  [/^\/projects/, "项目"],
  [/^\/studio/, "Agent 会话"],
  [/^\/flows/, "工作流"],
  [/^\/tasks/, "任务"],
  [/^\/tools/, "工具与 MCP"],
  [/^\/models/, "模型与 Agent"],
  [/^\/benchmarks|^\/library|^\/experiments|^\/leaderboard|^\/profiles|^\/runs/, "能力评测"],
  [/^\/settings/, "设置"],
];

function Brand() {
  return (
    <Link className="v4-brand" to="/" aria-label="AgentBench 控制中心">
      <span className="v4-brand-mark" aria-hidden="true">A</span>
      <span><strong>AgentBench</strong><small>LOCAL WORKSPACE</small></span>
    </Link>
  );
}

function NavigationGroup({ label, items, pathname }: { label: string; items: NavigationItem[]; pathname: string }) {
  return (
    <section className="v4-nav-group">
      <header><span>{label}</span></header>
      <nav>
        {items.map((item) => {
          const { to, label: itemLabel, icon: Icon, end } = item;
          return <NavLink key={to} to={to} end={end} title={itemLabel} className={({ isActive }) => isActive || item.aliases?.some((path) => pathname.startsWith(path)) ? "active" : ""}>
            <Icon size={19} /><span>{itemLabel}</span>
          </NavLink>;
        })}
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
  const [navigationOpen, setNavigationOpen] = useState(false);
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
  const showOnboarding = onboardingOpen && Boolean(status && dashboard);
  const selectedProject = projects?.find((project) => project.id === ux.selectedProjectId) ?? projects?.[0];
  const setupStep = installed === 0 ? 0 : (dashboard?.project_count ?? 0) === 0 ? 1 : 2;
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
        setNavigationOpen(false);
      }
    }
    window.addEventListener("keydown", handleKeyboard);
    return () => window.removeEventListener("keydown", handleKeyboard);
  }, []);

  useEffect(() => {
    setNavigationOpen(false);
  }, [location.pathname, location.search]);

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
    return [...workspaceNavigation, ...benchmarkNavigation, ...resourceNavigation].filter((item, index, items) => (
      items.findIndex((candidate) => candidate.to === item.to) === index &&
      (!needle || item.label.toLowerCase().includes(needle))
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
    <div className={`v4-shell density-${ux.density} ${navigationOpen ? "navigation-open" : ""} ${location.pathname.startsWith("/studio") ? "studio-route" : ""}`}>
      {navigationOpen && <button className="fn-nav-backdrop" aria-label="关闭主导航" onClick={() => setNavigationOpen(false)} />}
      <aside id="main-navigation" className="v4-sidebar" aria-label="主导航">
        <Brand />
        <label className="fn-workspace-select"><FolderKanban size={16} /><select aria-label="当前工作项目" value={selectedProject?.id ?? ""} onChange={(event) => ux.setSelectedProjectId(event.target.value)}>{projects?.length ? projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>) : <option value="">本地工作区</option>}</select></label>
        <div className="v4-nav-scroll">
          <NavigationGroup label="工作区" items={workspaceNavigation} pathname={location.pathname} />
          <NavigationGroup label="能力评测" items={benchmarkNavigation} pathname={location.pathname} />
          <NavigationGroup label="资源管理" items={resourceNavigation} pathname={location.pathname} />
        </div>
        <section className={`v4-runtime-card ${runtime.tone}`}>
          <header><span><i />{runtime.label}</span><Link to="/models">检查环境</Link></header>
          <small>AGENTBENCH / {APP_VERSION}</small>
        </section>
      </aside>

      <header className="v4-topbar">
        <button className="fn-mobile-menu icon-button" type="button" aria-label="打开主导航" aria-controls="main-navigation" aria-expanded={navigationOpen} onClick={() => setNavigationOpen((value) => !value)}><Menu size={18} /></button>
        <div className="v4-breadcrumb"><span>本地工作区</span><ChevronRight size={13} /><strong>{title}</strong></div>
        <div className="v4-top-actions">
          <button className="v4-command-trigger" type="button" onClick={() => setPaletteOpen(true)}><Search size={15} /><span>搜索或新建</span><kbd>Ctrl K</kbd></button>
          {(dashboard?.pending_approvals ?? 0) > 0 && <Link className="v5-approval-chip" to="/"><ShieldAlert size={15} /><span>{dashboard?.pending_approvals} 个操作等待审批</span></Link>}
          <button className="v5-help-trigger" type="button" title="打开入门向导" aria-label="打开入门向导" onClick={() => setOnboardingOpen(true)}><HelpCircle size={17} /></button>
          <button className={`v5-notification-trigger ${ux.unreadCount ? "unread" : ""}`} type="button" aria-label={`通知中心，${ux.unreadCount} 条未读`} onClick={() => { const opening = !notificationsOpen; setNotificationsOpen(opening); if (opening) ux.markNotificationsRead(); }}><Bell size={17} />{ux.unreadCount > 0 && <b>{Math.min(99, ux.unreadCount)}</b>}</button>
        </div>
      </header>

      <main className="v4-viewport"><Outlet /></main>

      {paletteOpen && (
        <div className="v4-palette-backdrop" onMouseDown={() => setPaletteOpen(false)}>
          <section className="v4-palette" role="dialog" aria-modal="true" aria-label="搜索工作区" onMouseDown={(event) => event.stopPropagation()}>
            <header><Search size={18} /><input aria-label="搜索页面、项目或命令" autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入页面、项目或命令…" /><button type="button" aria-label="关闭搜索" onClick={() => setPaletteOpen(false)}><X size={16} /></button></header>
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
            <footer><Command size={13} /> 数据仅保存在本机 · Desktop {status?.version ?? APP_VERSION}</footer>
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
            <header><div><small>入门向导 · 第 {setupStep + 1} 步，共 3 步</small><h2 id="v5-onboarding-title">完成第一个本地 Agent 任务</h2><p>每一步都可以稍后继续。项目目录、模型配置和会话记录只保存在这台设备。</p></div><button type="button" aria-label="关闭入门向导" onClick={dismissOnboarding}><X size={17} /></button></header>
            <div className="v5-onboarding-progress" aria-label={`入门进度 ${setupStep} / 3`}><i className={setupStep >= 1 ? "done" : "active"} /><i className={setupStep >= 2 ? "done" : setupStep === 1 ? "active" : ""} /><i className={setupStep === 2 ? "active" : ""} /></div>
            <div className="v5-onboarding-steps">
              <Link className={setupStep === 0 ? "current" : ""} to="/models" onClick={dismissOnboarding}><span className={installed > 0 ? "done" : "pending"}>{installed > 0 ? "✓" : "1"}</span><div><strong>准备 Agent 与模型</strong><p>{installed > 0 ? `已发现 ${installed} 个可运行 Agent` : "检查 CLI、登录状态与可用模型，并按提示完成配置"}</p></div><TerminalSquare size={17} /></Link>
              <Link className={setupStep === 1 ? "current" : ""} to="/projects?new=1" onClick={dismissOnboarding}><span className={(dashboard?.project_count ?? 0) > 0 ? "done" : "pending"}>{(dashboard?.project_count ?? 0) > 0 ? "✓" : "2"}</span><div><strong>添加一个本地项目</strong><p>{(dashboard?.project_count ?? 0) > 0 ? `已有 ${dashboard?.project_count} 个项目可用` : "选择目录并确认 Agent 可以访问的范围"}</p></div><FolderKanban size={17} /></Link>
              <Link className={setupStep === 2 ? "current" : ""} to="/studio?new=1" onClick={dismissOnboarding}><span className="pending">3</span><div><strong>发送第一个任务</strong><p>描述目标，确认运行配置，然后观察执行、审批与结果</p></div><Sparkles size={17} /></Link>
            </div>
            <footer><button className="v4-button secondary" type="button" onClick={dismissOnboarding}>稍后继续</button><Link className="v4-button primary" to={setupStep === 0 ? "/models" : setupStep === 1 ? "/projects?new=1" : "/studio?new=1"} onClick={dismissOnboarding}>{setupStep === 2 ? "开始第一个任务" : "继续下一步"}<ArrowRight size={15} /></Link></footer>
          </section>
        </div>
      )}
    </div>
  );
}
