import {
  Activity,
  ArrowRight,
  Bot,
  Boxes,
  ChevronRight,
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
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import agentbenchMark from "../assets/agentbench-mark.png";
import { useApi } from "../lib/useApi";
import type { SystemStatus } from "../types";
import type { StudioDashboardData, WorkspaceSearchResult } from "./types";

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
  const { data: dashboard } = useApi<StudioDashboardData>("/studio/dashboard", 4_000);
  const { data: status } = useApi<SystemStatus>("/system/status", 12_000);
  const [paletteOpen, setPaletteOpen] = useState(false);
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
      if (event.key === "Escape") setPaletteOpen(false);
    }
    window.addEventListener("keydown", handleKeyboard);
    return () => window.removeEventListener("keydown", handleKeyboard);
  }, []);

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
    <div className="v4-shell">
      <aside className="v4-sidebar">
        <Brand />
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
        <div className="v4-breadcrumb"><span>AGENTBENCH</span><ChevronRight size={13} /><strong>{title}</strong></div>
        <div className="v4-top-actions">
          <button className="v4-command-trigger" type="button" onClick={() => setPaletteOpen(true)}><Search size={15} /><span>搜索项目、会话或运行命令</span><kbd>Ctrl K</kbd></button>
          {(dashboard?.pending_approvals ?? 0) > 0 && <Link className="v5-approval-chip" to="/"><ShieldAlert size={15} /><span>{dashboard?.pending_approvals} 个操作等待审批</span></Link>}
          <Link className="v4-live-chip" to="/studio"><Activity size={15} /><span>{dashboard?.active_sessions ?? 0} 个会话运行中</span></Link>
          <span className="v4-avatar">OB</span>
        </div>
      </header>

      <main className="v4-viewport"><Outlet /></main>

      {paletteOpen && (
        <div className="v4-palette-backdrop" onMouseDown={() => setPaletteOpen(false)}>
          <section className="v4-palette" onMouseDown={(event) => event.stopPropagation()}>
            <header><Search size={18} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入页面、项目或命令…" /><button type="button" onClick={() => setPaletteOpen(false)}><X size={16} /></button></header>
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
