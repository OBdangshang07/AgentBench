import {
  Activity,
  Bot,
  Boxes,
  ChevronRight,
  CircleGauge,
  Command,
  FolderKanban,
  FlaskConical,
  GitFork,
  Layers3,
  ListTodo,
  PlugZap,
  Search,
  Settings,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import agentbenchMark from "../assets/agentbench-mark.png";
import { useApi } from "../lib/useApi";
import type { SystemStatus } from "../types";
import type { StudioDashboardData } from "./types";

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
      <em>V4</em>
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
  const [query, setQuery] = useState("");
  const title = pageNames.find(([pattern]) => pattern.test(location.pathname))?.[1] ?? "AgentBench";
  const runners = status?.runners ?? [];
  const installed = runners.filter((runner) => runner.capability.installed).length;

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

  const commandItems = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return [...operationNavigation, ...platformNavigation].filter((item) => (
      !needle || item.label.toLowerCase().includes(needle)
    ));
  }, [query]);

  return (
    <div className="v4-shell">
      <aside className="v4-sidebar">
        <Brand />
        <div className="v4-nav-scroll">
          <NavigationGroup label="OPERATIONS" items={operationNavigation} />
          <NavigationGroup label="PLATFORM" items={platformNavigation} />
        </div>
        <section className="v4-runtime-card">
          <header><strong>Local Runtime</strong><span><i />全部就绪</span></header>
          <div><span>Agent adapters</span><b>{installed} / {runners.length || "—"}</b></div>
          <div><span>Active sessions</span><b>{dashboard?.active_sessions ?? 0}</b></div>
          <div className="v4-runtime-bar"><i style={{ width: `${runners.length ? Math.round(installed / runners.length * 100) : 0}%` }} /></div>
        </section>
      </aside>

      <header className="v4-topbar">
        <div className="v4-breadcrumb"><span>AGENTBENCH</span><ChevronRight size={13} /><strong>{title}</strong></div>
        <div className="v4-top-actions">
          <button className="v4-command-trigger" type="button" onClick={() => setPaletteOpen(true)}><Search size={15} /><span>搜索项目、会话或运行命令</span><kbd>Ctrl K</kbd></button>
          <Link className="v4-live-chip" to="/studio"><Activity size={15} /><span>{dashboard?.active_sessions ?? 0} 个会话运行中</span></Link>
          <span className="v4-avatar">OB</span>
        </div>
      </header>

      <main className="v4-viewport"><Outlet /></main>

      {paletteOpen && (
        <div className="v4-palette-backdrop" onMouseDown={() => setPaletteOpen(false)}>
          <section className="v4-palette" onMouseDown={(event) => event.stopPropagation()}>
            <header><Search size={18} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入页面、项目或命令…" /><button type="button" onClick={() => setPaletteOpen(false)}><X size={16} /></button></header>
            <label>快速前往</label>
            <div>
              {commandItems.map(({ to, label, icon: Icon }) => (
                <Link key={to} to={to} onClick={() => setPaletteOpen(false)}><Icon size={17} /><span>{label}</span><ChevronRight size={15} /></Link>
              ))}
            </div>
            <footer><Command size={13} /> 本地数据 · Desktop {status?.version ?? "4.0 Preview"}</footer>
          </section>
        </div>
      )}
    </div>
  );
}
