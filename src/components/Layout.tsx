import {
  Activity,
  Boxes,
  FlaskConical,
  Gauge,
  LibraryBig,
  Medal,
  PlugZap,
  Settings,
  ShieldCheck,
  Unplug,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import type { SystemStatus } from "../types";
import { useApi } from "../lib/useApi";

const navigation = [
  { to: "/", label: "开始", icon: Gauge, end: true },
  { to: "/models", label: "参测配置", icon: Boxes },
  { to: "/library", label: "能力测试", icon: LibraryBig },
  { to: "/experiments", label: "实验与结果", icon: FlaskConical },
  { to: "/leaderboard", label: "模型对比", icon: Medal },
  { to: "/settings", label: "环境设置", icon: Settings },
];

export default function Layout() {
  const { data: status } = useApi<SystemStatus>("/system/status", 10_000);
  const readyRunners = status?.runners.filter((runner) => runner.capability.installed).length ?? 0;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Activity size={22} /></div>
          <div>
            <strong>AgentBench</strong>
            <span>DESKTOP · V2</span>
          </div>
        </div>
        <nav>
          <div className="nav-label">评测工作台</div>
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-status">
          <div className="sidebar-status-title">
            {status?.docker.available ? <ShieldCheck size={17} /> : <Unplug size={17} />}
            <strong>{status?.docker.available ? "完整环境已就绪" : "基础环境可用"}</strong>
          </div>
          <p>
            {status?.docker.available
              ? "代码、Shell 与项目型任务可在 Docker 中隔离运行。"
              : "文本和文件任务可运行；代码验证需要 Docker。"}
          </p>
          <div className="sidebar-health-row">
            <span className={status?.docker.available ? "dot dot-green" : "dot dot-amber"}>
              {status?.docker.available ? "沙箱在线" : "未连接 Docker"}
            </span>
            <span className="runner-ready"><PlugZap size={12} /> {readyRunners} Agent</span>
          </div>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
