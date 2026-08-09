import {
  Activity,
  Boxes,
  CircleHelp,
  FlaskConical,
  Gauge,
  LibraryBig,
  Medal,
  Plus,
  Radar,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Unplug,
} from "lucide-react";
import { Link, NavLink, Outlet } from "react-router-dom";
import type { SystemStatus } from "../types";
import { useApi } from "../lib/useApi";

const navigation = [
  { to: "/", label: "控制台", icon: Gauge, end: true },
  { to: "/library", label: "测试库", icon: LibraryBig },
  { to: "/experiments", label: "实验", icon: FlaskConical },
  { to: "/leaderboard", label: "排行榜", icon: Medal },
  { to: "/profiles", label: "能力画像", icon: Radar },
  { to: "/models", label: "模型与 Agent", icon: Boxes },
  { to: "/settings", label: "环境设置", icon: Settings },
];

export default function Layout() {
  const { data: status } = useApi<SystemStatus>("/system/status", 10_000);
  const readyRunners = status?.runners.filter((runner) => runner.capability.installed).length ?? 0;
  const environmentReady = Boolean(status?.docker.available);
  return (
    <div className="app-shell app-shell-v3">
      <header className="workspace-topbar">
        <Link className="workspace-brand" to="/" aria-label="AgentBench 控制台">
          <span className="workspace-brand-mark">AB<i /></span>
          <span><strong>AgentBench</strong><small>EVALUATION OS · V3</small></span>
        </Link>
        <div className="environment-chip" title={environmentReady ? "Docker 隔离环境在线" : "基础本地环境可用"}>
          <span className={environmentReady ? "signal-online" : "signal-warning"} />
          Local Lab
          <small>{readyRunners} agents</small>
        </div>
        <nav className="workspace-tabs" aria-label="主工作区">
          <NavLink to="/" end>控制台</NavLink>
          <NavLink to="/library">测试库</NavLink>
          <NavLink to="/experiments">编排</NavLink>
          <NavLink to="/leaderboard">证据</NavLink>
        </nav>
        <div className="workspace-command">
          <button type="button" aria-label="搜索或执行命令"><Search size={14} /><span>搜索或执行命令</span><kbd>Ctrl K</kbd></button>
          <button className="topbar-icon-button" type="button" aria-label="帮助"><CircleHelp size={16} /></button>
          <Link className="topbar-create" to="/experiments"><Plus size={16} /> 新建评测</Link>
        </div>
      </header>

      <aside className="workspace-rail">
        <div className="rail-primary">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} aria-label={label} title={label}>
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </div>
        <div className="rail-health" title={environmentReady ? "完整环境已就绪" : "Docker 未连接"}>
          {environmentReady ? <ShieldCheck size={17} /> : <Unplug size={17} />}
          <small>{readyRunners}</small>
        </div>
        <div className="rail-version"><Sparkles size={15} /><span>V3</span></div>
      </aside>

      <main className="main-content workspace-main">
        <div className="workspace-scanline" aria-hidden="true"><Activity size={13} /> LIVE LOCAL BENCH</div>
        <Outlet />
      </main>
    </div>
  );
}
