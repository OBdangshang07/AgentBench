import {
  Activity,
  Eye,
  EyeOff,
  FileCode2,
  FlaskConical,
  Radio,
  ShieldCheck,
  Terminal,
  TestTube2,
  Timer,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { formatDuration, formatNumber } from "../lib/format";
import type { JsonObject, RunDetail, RunEvent, RunSummary } from "../types";
import type { StreamState } from "../lib/useRunEvents";
import { StatusBadge } from "./ui";

const ACTIVE_STATUSES = new Set(["queued", "preparing", "running", "validating", "judging"]);

type LiveTone = "activity" | "command" | "file" | "test" | "good" | "warning";

interface DisplayEvent {
  tone: LiveTone;
  title: string;
  detail: string;
  terminal?: string;
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function number(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function displayEvent(event: RunEvent): DisplayEvent {
  const payload = event.payload;
  if (event.event_type === "live.command") {
    const command = text(payload.command, "已过滤命令");
    const done = payload.status === "completed" || payload.exit_code === 0;
    return { tone: "command", title: done ? "命令执行完成" : "执行工作区命令", detail: text(payload.detail, command), terminal: `$ ${command}` };
  }
  if (event.event_type === "live.file_change") {
    const path = text(payload.path, "工作区文件");
    return { tone: "file", title: `${text(payload.change, "modified")} · ${path}`, detail: number(payload.size_delta) ? `大小变化 ${number(payload.size_delta) > 0 ? "+" : ""}${number(payload.size_delta)} bytes` : text(payload.tool, "文件系统已确认变更"), terminal: `Δ ${path}` };
  }
  if (event.event_type === "live.test") {
    const detail = text(payload.detail, text(payload.command, "公开测试正在运行"));
    const failed = /fail|error/i.test(detail);
    return { tone: failed ? "warning" : payload.status === "completed" ? "good" : "test", title: payload.status === "completed" ? "公开测试完成" : "运行公开测试", detail, terminal: text(payload.command) ? `$ ${text(payload.command)}` : detail };
  }
  if (event.event_type === "live.tool") {
    return { tone: "activity", title: `调用 ${text(payload.tool, "Agent 工具")}`, detail: text(payload.detail, text(payload.status, "正在执行")) };
  }
  if (event.event_type === "live.heartbeat") {
    return { tone: "activity", title: "Agent 会话保持活跃", detail: `${formatDuration(number(payload.elapsed_ms))} · ${number(payload.workspace_files)} 个工作区文件` };
  }
  if (event.event_type === "model.requested") return { tone: "activity", title: "请求模型继续决策", detail: `Agent step ${number(payload.step)}` };
  if (event.event_type === "model.responded") return { tone: "activity", title: text(payload.summary, "模型已生成下一项操作"), detail: `Agent step ${number(payload.step)}` };
  if (event.event_type === "tool.requested") return { tone: "activity", title: `调用 ${text(payload.name, "工具")}`, detail: `Agent step ${number(payload.step)}` };
  if (event.event_type === "tool.completed") return { tone: "good", title: `${text(payload.name, "工具")} 已返回`, detail: `Agent step ${number(payload.step)}` };
  if (event.event_type === "run.validating") return { tone: "test", title: "进入确定性验证", detail: `第 ${number(payload.attempt, 1)} 轮提交已完成` };
  if (event.event_type === "validator.completed") return { tone: payload.status === "passed" ? "good" : "test", title: `${text(payload.validator_type, "验证器")} 已完成`, detail: `得分 ${number(payload.score).toFixed(1)} · ${text(payload.status, "completed")}` };
  if (event.event_type === "run.judging") return { tone: "activity", title: "匿名裁判正在复核", detail: `裁判席位 ${text(payload.anonymous_slot, "primary")}` };
  if (event.event_type === "judge.completed") return { tone: "good", title: "匿名裁判已完成", detail: `评分 ${number(payload.score).toFixed(1)} · ${text(payload.summary)}` };
  if (event.event_type === "attempt.started") return { tone: "activity", title: `第 ${number(payload.attempt, 1)} 轮开始`, detail: `本轮倍率 ×${number(payload.multiplier, 1).toFixed(2)}` };
  if (event.event_type === "attempt.retry_scheduled") return { tone: "warning", title: "进入下一轮挑战", detail: text(payload.summary, "已生成下一轮公开提示") };
  if (event.event_type === "run.completed") return { tone: "good", title: "评测运行完成", detail: `最终得分 ${number(payload.score).toFixed(1)}` };
  if (event.event_type === "run.failed") return { tone: "warning", title: "运行未正常完成", detail: `${text(payload.code)} ${text(payload.message)}`.trim() };
  if (event.event_type === "native_cli.started") return { tone: "activity", title: "原生 Agent 已启动", detail: text(payload.runner_type, "native CLI") };
  return { tone: "activity", title: text(payload.summary, event.event_type), detail: text(payload.detail, `事件 #${event.seq}`) };
}

function elapsedFor(run: RunSummary, now: number): number {
  if (!ACTIVE_STATUSES.has(run.status)) return run.duration_ms;
  const started = Date.parse(run.started_at ?? run.created_at);
  return Number.isFinite(started) ? Math.max(run.duration_ms, now - started) : run.duration_ms;
}

function eventUsage(events: RunEvent[]) {
  let input = 0;
  let output = 0;
  let steps = 0;
  for (const event of events) {
    const usage = event.payload.usage as JsonObject | undefined;
    if (usage) {
      input = Math.max(input, number(usage.input_tokens));
      output = Math.max(output, number(usage.output_tokens));
    }
    steps = Math.max(steps, number(event.payload.step));
  }
  return { input, output, steps };
}

function streamLabel(state: StreamState) {
  if (state === "live") return "实时连接";
  if (state === "reconnecting") return "正在补拉事件";
  if (state === "connecting") return "连接直播流";
  return "本地事件回放";
}

function Feed({ events, limit = 12 }: { events: RunEvent[]; limit?: number }) {
  const visible = events.filter((event, index, all) => event.event_type !== "live.heartbeat" || index === all.length - 1).slice(-limit).reverse();
  return <div className="live-feed">
    {visible.map((event) => {
      const view = displayEvent(event);
      return <article className={`live-feed-event live-feed-${view.tone}`} key={`${event.seq}-${event.id}`}>
        <i /><div><strong>{view.title}</strong><p>{view.detail}</p></div><time>#{event.seq}</time>
      </article>;
    })}
    {!visible.length && <div className="live-wait"><i />等待 Agent 产生第一条可验证事件</div>}
  </div>;
}

function TerminalFeed({ events }: { events: RunEvent[] }) {
  const lines = events.map(displayEvent).filter((event) => event.terminal).slice(-12);
  return <div className="live-terminal">
    <header><i /><i /><i /><span>live terminal · sanitized · follow output</span></header>
    <div>{lines.map((line, index) => <p key={`${index}-${line.terminal}`} className={`terminal-${line.tone}`}>{line.terminal}</p>)}<p><b>$</b> <span className="terminal-cursor" /></p></div>
  </div>;
}

export function ExperimentLiveFocus({ run, events, streamState }: { run: RunDetail; events: RunEvent[]; streamState: StreamState }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1_000); return () => window.clearInterval(timer); }, []);
  const views = events.map(displayEvent);
  const focus = [...views].reverse().find((event) => event.title !== "Agent 会话保持活跃") ?? { tone: "activity" as const, title: "正在准备 Agent 工作区", detail: "等待首个工具或命令事件" };
  const usage = eventUsage(events);
  return <div className="experiment-live-focus">
    <section className="live-theater">
      <header><span><Radio size={14} /> ON AIR · <strong>{run.test_title}</strong></span><small>{streamLabel(streamState)}</small></header>
      <div className="live-theater-body">
        <div className="live-focus-stage">
          <div className="live-now-label"><span>WHAT THE AGENT IS DOING NOW</span><b>ROUND {Math.max(1, run.attempt_count)} / STEP {Math.max(run.steps, usage.steps)}</b></div>
          <h2>{focus.title}</h2><p>{focus.detail}</p>
          <div className={`live-action-summary live-feed-${focus.tone}`}><Activity size={16} /><div><strong>{focus.title}</strong><span>{focus.detail}</span></div><code>SAFE EVENT</code></div>
          <TerminalFeed events={events} />
          <div className="live-phase-strip"><span className="done">准备环境</span><span className="done">Agent 执行</span><span className={run.status === "validating" ? "live" : ""}>公开验证</span><span className={run.status === "judging" ? "live" : ""}>匿名裁判</span><span>结果证据</span></div>
        </div>
        <div className="live-activity-column"><header><strong>结构化行为流</strong><small>最新在上</small></header><Feed events={events} limit={8} /><div className="live-safety-note"><ShieldCheck size={13} /><span>已过滤密钥、系统提示、私有验证内容与 Chain-of-Thought。</span></div></div>
      </div>
    </section>
    <aside className="live-focus-side">
      <header><span className="live-model-avatar">{run.model_name.slice(0, 2).toUpperCase()}</span><div><strong>{run.model_name}</strong><small>{run.runner_name}</small></div></header>
      <div className="live-focus-metrics"><div><span>用时</span><strong>{formatDuration(elapsedFor(run, now))}</strong></div><div><span>步骤</span><strong>{Math.max(run.steps, usage.steps)}</strong></div><div><span>Token</span><strong>{formatNumber(Math.max(run.tokens_input + run.tokens_output, usage.input + usage.output))}</strong></div></div>
      <div className="live-focus-privacy"><ShieldCheck size={14} /><strong>录制安全过滤已开启</strong><p>直播只展示工具、命令、文件变化、公开测试和阶段结果。</p></div>
    </aside>
  </div>;
}

export function LiveRunSession({ run, events, streamState }: { run: RunDetail; events: RunEvent[]; streamState: StreamState }) {
  const [audience, setAudience] = useState(false);
  const [tab, setTab] = useState<"activity" | "files" | "tests">("activity");
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1_000); return () => window.clearInterval(timer); }, []);
  const views = useMemo(() => events.map((event) => ({ event, view: displayEvent(event) })), [events]);
  const focus = [...views].reverse().find(({ view }) => view.title !== "Agent 会话保持活跃")?.view ?? { tone: "activity" as const, title: "正在准备 Agent 工作区", detail: "等待第一条安全直播事件" };
  const fileEvents = views.filter(({ event }) => event.event_type === "live.file_change");
  const testEvents = views.filter(({ event }) => event.event_type === "live.test" || event.event_type === "validator.completed");
  const latestTool = [...views].reverse().find(({ event }) => ["live.tool", "live.command", "tool.requested"].includes(event.event_type));
  const usage = eventUsage(events);
  const validators = run.test_definition?.validators ?? [];
  return <div className={`live-session ${audience ? "live-audience" : ""}`}>
    <header className="live-session-head">
      <div><span><Radio size={13} /> LIVE AGENT SESSION</span><h1>{run.test_title}</h1><p>{run.model_name} × {run.runner_name} · ROUND {Math.max(1, run.attempt_count)} · 工作区连续保留</p></div>
      <div className="live-session-controls"><span className="live-stream-chip"><i /> {streamLabel(streamState)}</span><button className="button button-secondary" type="button" onClick={() => setAudience((value) => !value)}>{audience ? <EyeOff size={14} /> : <Eye size={14} />}{audience ? "退出观众模式" : "观众模式"}</button></div>
    </header>
    <div className="live-session-layout">
      <aside className="live-obligations">
        <code>{run.category.toUpperCase()} / {run.test_case_id.slice(0, 8)}</code><h3>{run.test_title}</h3><span>当前第 {Math.max(1, run.attempt_count)} 轮 · {run.status}</span>
        <label>ROUND TRACE</label>
        {[1, 2, 3].map((round) => {
          const attempt = run.attempts.find((item) => item.attempt_no === round);
          const active = round === Math.max(1, run.attempt_count) && ACTIVE_STATUSES.has(run.status);
          return <div className={`live-round ${active ? "active" : ""}`} key={round}><i /><div><strong>ROUND {String(round).padStart(2, "0")}</strong><p>{attempt ? (attempt.passed ? "本轮已通过" : "本轮未达及格线") : active ? "Agent 正在执行" : "尚未进入"}</p><span>{attempt?.adjusted_score != null ? `${attempt.adjusted_score.toFixed(1)} · ${attempt.status}` : active ? `${formatDuration(elapsedFor(run, now))} · LIVE` : "—"}</span></div></div>;
        })}
        <label>PUBLIC OBLIGATIONS</label>
        {validators.slice(0, 7).map((validator, index) => <div className={`live-obligation ${index < run.validators.length ? "done" : index === run.validators.length ? "active" : ""}`} key={`${validator.type}-${index}`}><i>{index < run.validators.length ? "✓" : ""}</i><span>{validator.type.replaceAll("_", " ")}</span></div>)}
      </aside>
      <main className="live-workbench">
        <div className="live-workbench-head"><span className="live-model-avatar">{run.model_name.slice(0, 2).toUpperCase()}</span><div><strong>{run.model_name} 正在工作</strong><small>{run.runner_name} · viewer-safe event stream</small></div><span className="live-stage-chip"><i /> {run.status}</span></div>
        <section className="live-safe-summary"><Activity size={19} /><div><label>WHAT THE AGENT IS DOING NOW</label><h2>{focus.title}</h2><p>{focus.detail}</p></div><div><strong>{Math.max(run.steps, usage.steps)}</strong><span>Agent steps</span></div></section>
        <nav className="live-tabs"><button className={tab === "activity" ? "active" : ""} onClick={() => setTab("activity")}>实时活动 <b>LIVE</b></button><button className={tab === "files" ? "active" : ""} onClick={() => setTab("files")}>文件变化 <b>{fileEvents.length}</b></button><button className={tab === "tests" ? "active" : ""} onClick={() => setTab("tests")}>测试结果 <b>{testEvents.length}</b></button></nav>
        <div className="live-work-area">
          {tab === "activity" && <div className="live-activity-panel"><Feed events={events} limit={14} /><TerminalFeed events={events} /></div>}
          {tab === "files" && <div className="live-file-panel">{fileEvents.map(({ event, view }) => <article key={event.seq}><FileCode2 size={15} /><div><strong>{text(event.payload.path, "工作区文件")}</strong><span>{view.detail}</span></div><code>#{event.seq}</code></article>)}{!fileEvents.length && <p>等待工作区产生可确认的文件变化。</p>}</div>}
          {tab === "tests" && <div className="live-test-panel">{testEvents.map(({ event, view }) => <article key={event.seq}><TestTube2 size={15} /><div><strong>{view.title}</strong><span>{view.detail}</span></div><code>#{event.seq}</code></article>)}{!testEvents.length && <p>Agent 尚未运行公开检查。</p>}</div>}
        </div>
      </main>
      <aside className="live-context">
        <section><label>CURRENT TOOL</label><div className="live-current-tool"><Wrench size={16} /><div><strong>{latestTool?.view.title ?? "等待下一项工具调用"}</strong><span>{latestTool?.view.detail ?? "直播流保持连接"}</span></div></div></section>
        <section><label>LIVE TELEMETRY</label><div className="live-telemetry"><div><Timer size={13} /><span>运行用时</span><strong>{formatDuration(elapsedFor(run, now))}</strong></div><div><Activity size={13} /><span>Agent 步骤</span><strong>{Math.max(run.steps, usage.steps)}</strong></div><div><Terminal size={13} /><span>输入 Token</span><strong>{formatNumber(Math.max(run.tokens_input, usage.input))}</strong></div><div><FlaskConical size={13} /><span>输出 Token</span><strong>{formatNumber(Math.max(run.tokens_output, usage.output))}</strong></div></div></section>
        <section><label>RECORDING SAFETY</label><div className="live-recording-safety"><ShieldCheck size={16} /><div><strong>可公开事件流</strong><p>不会显示 Chain-of-Thought、系统提示、API Key、环境变量、私有验证输入或隐藏答案。</p></div></div></section>
        <section className="live-status-block"><StatusBadge status={run.status} /><span>{streamLabel(streamState)}</span></section>
      </aside>
    </div>
  </div>;
}
