import { ChevronLeft, ChevronRight, Eye, Maximize2, Pause, Radio, Terminal } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

export function BroadcastFrame({ children, backTo = "/experiments", previousTo, nextTo }: { children: ReactNode; backTo?: string; previousTo?: string; nextTo?: string }) {
  const location = useLocation();
  const session = location.pathname.startsWith("/runs/");
  const [audience, setAudience] = useState(false);
  const [paused, setPaused] = useState(false);
  return (
    <div className={`broadcast-shell broadcast-overlay${audience ? " broadcast-audience" : ""}`}>
      <header className="broadcast-shell-bar">
        <Link className="broadcast-live-brand" to="/experiments">
          <span>AB</span><div><strong>AgentBench Live</strong><small>RECORDING WORKSPACE</small></div>
        </Link>
        <nav><Link className={!session ? "active" : ""} to={session ? backTo : "/experiments"}><i /> {session ? "返回实验" : "实验直播"}</Link><span className={session ? "active" : ""}>单任务追踪</span></nav>
        <div className="broadcast-top-actions">{session && <div className="broadcast-sibling-nav"><Link className={!previousTo ? "disabled" : ""} to={previousTo ?? backTo} aria-disabled={!previousTo}><ChevronLeft size={12} />上一题</Link><Link className={!nextTo ? "disabled" : ""} to={nextTo ?? backTo} aria-disabled={!nextTo}>下一题<ChevronRight size={12} /></Link></div>}<span className="broadcast-status"><i />事件流已连接</span><button className="broadcast-management" type="button" onClick={() => setPaused((value) => !value)}><Pause size={13} />{paused ? "继续演示" : "暂停演示"}</button><button className="broadcast-acid" type="button" onClick={() => setAudience((value) => !value)}><Eye size={13} />{audience ? "退出预览" : "观众模式"}</button></div>
      </header>
      <aside className="broadcast-rail">
        <Link className={!session ? "active" : ""} to="/experiments" aria-label="实验直播"><Radio size={18} /></Link>
        <button className={session ? "active" : ""} type="button" aria-label="单任务追踪"><Terminal size={18} /></button>
        <div className="broadcast-rail-gap" />
        <button type="button" onClick={() => setAudience((value) => !value)} aria-label="观众模式"><Maximize2 size={17} /></button>
        <div className="broadcast-record-light" />
      </aside>
      <main className="broadcast-main">{children}</main>
    </div>
  );
}
