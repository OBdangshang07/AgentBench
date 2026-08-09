import {
  Bot,
  Boxes,
  Command,
  Ellipsis,
  FlaskConical,
  LibraryBig,
  ListChecks,
  Plus,
  Radar,
  Search,
  Settings,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useApi } from "../lib/useApi";
import type { DashboardData, SystemStatus } from "../types";

const primaryNavigation = [
  { to: "/", label: "控制台", icon: Command, end: true },
  { to: "/library", label: "测试库", icon: LibraryBig },
  { to: "/experiments", label: "编排", icon: FlaskConical },
  { to: "/leaderboard", label: "证据", icon: ListChecks },
];

const secondaryNavigation = [
  { to: "/models", label: "模型与 Agent", icon: Boxes },
  { to: "/profiles", label: "能力画像", icon: Radar },
  { to: "/settings", label: "环境设置", icon: Settings },
];

function navigationIsActive(pathname: string, to: string) {
  if (to === "/") return pathname === "/";
  if (to === "/leaderboard") return pathname === "/leaderboard" || pathname.startsWith("/runs/") || pathname.startsWith("/experiments/");
  return pathname.startsWith(to);
}

export function Brand() {
  return (
    <Link className="ab-product" to="/" aria-label="AgentBench 控制台">
      <span className="ab-monogram">AB</span>
      <span><strong>AgentBench</strong><small>EVALUATION OS</small></span>
    </Link>
  );
}

export default function Layout() {
  const location = useLocation();
  const { data: status } = useApi<SystemStatus>("/system/status", 10_000);
  const { data: dashboard } = useApi<DashboardData>("/dashboard", 5_000);
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const installed = status?.runners.filter((runner) => runner.capability.installed).length ?? 0;
  const runnerTotal = status?.runners.length ?? 0;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((value) => !value);
      }
      if (event.key === "Escape") setCommandOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const commandItems = useMemo(() => {
    const query = commandQuery.trim().toLowerCase();
    return [...primaryNavigation, ...secondaryNavigation].filter((item) => !query || item.label.toLowerCase().includes(query));
  }, [commandQuery]);

  return (
    <div className="ab-shell">
      <header className="ab-titlebar">
        <div className="ab-title-product">
          <Brand />
          <button className="ab-workspace-switch" type="button"><i /><b>Local Lab</b><span>⌄</span></button>
        </div>
        <nav className="ab-title-center" aria-label="主要导航">
          {primaryNavigation.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => `ab-top-tab${isActive || navigationIsActive(location.pathname, item.to) ? " active" : ""}`}>{item.label}</NavLink>
          ))}
        </nav>
        <div className="ab-title-actions">
          <button className="ab-command-button" type="button" onClick={() => setCommandOpen(true)}><Search size={14} /><span>搜索或执行命令</span><kbd>Ctrl K</kbd></button>
          <button className="ab-icon-button" type="button" aria-label="更多"><Ellipsis size={15} /></button>
          <Link className="ab-run-button" to="/experiments?create=1"><Plus size={14} />新建评测</Link>
        </div>
      </header>

      <aside className="ab-toolrail" aria-label="工具导航">
        {primaryNavigation.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} data-tip={label} className={() => `ab-tool${navigationIsActive(location.pathname, to) ? " active" : ""}`}><Icon size={18} /></NavLink>
        ))}
        <div className="ab-rail-separator" />
        <NavLink to="/models" data-tip="模型与 Agent" className={({ isActive }) => `ab-tool${isActive ? " active" : ""}`}><Bot size={18} /></NavLink>
        <NavLink to="/profiles" data-tip="能力画像" className={({ isActive }) => `ab-tool${isActive ? " active" : ""}`}><Radar size={18} /></NavLink>
        <div className="ab-rail-spacer" />
        <NavLink to="/settings" data-tip="环境设置" className={({ isActive }) => `ab-tool${isActive ? " active" : ""}`}><Settings size={18} /></NavLink>
        <div className="ab-rail-health" title={`${installed}/${runnerTotal} 个 Agent 已就绪`}>{installed}/{runnerTotal || "—"}</div>
      </aside>

      <main className="ab-viewport"><Outlet /></main>

      {commandOpen && (
        <div className="ab-palette-scrim" onMouseDown={() => setCommandOpen(false)}>
          <section className="ab-palette" onMouseDown={(event) => event.stopPropagation()}>
            <div className="ab-palette-search"><Search size={16} /><input autoFocus value={commandQuery} onChange={(event) => setCommandQuery(event.target.value)} placeholder="搜索测试、模型、运行或执行命令…" /><button type="button" onClick={() => setCommandOpen(false)}><X size={15} /></button><kbd>ESC</kbd></div>
            <div className="ab-palette-label">NAVIGATE</div>
            {commandItems.map(({ to, label, icon: Icon }, index) => <Link className="ab-palette-item" key={to} to={to} onClick={() => setCommandOpen(false)}><Icon size={14} /><span>{label}</span><kbd>{index + 1}</kbd></Link>)}
            <footer>本机数据 · {dashboard?.test_cases ?? 0} 个测试 · Desktop {status?.version ?? "3.1.1"}</footer>
          </section>
        </div>
      )}
    </div>
  );
}
