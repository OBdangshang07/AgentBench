import { AlertTriangle, ArrowLeft, BarChart3, CheckCircle2, Download, FolderOpen, Gauge, Pause, Play, RefreshCw, RotateCcw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, downloadUrl } from "../lib/api";
import { formatDate, formatDuration, formatNumber } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useRunEvents } from "../lib/useRunEvents";
import type { CapabilityReport, Experiment, RunDetail, RunSummary } from "../types";
import { Button, Card, ErrorBlock, LoadingBlock, Score, StatusBadge } from "../components/ui";
import { ExperimentLiveFocus } from "../components/LiveRunView";
import { BroadcastFrame } from "../components/BroadcastFrame";
import { useOpenFolder } from "../lib/useOpenFolder";

const ACTIVE_RUN_STATUSES = new Set(["queued", "preparing", "running", "validating", "judging"]);
const INCOMPLETE_RUN_STATUSES = new Set([...ACTIVE_RUN_STATUSES, "interrupted"]);
const RUN_STATUS_PRIORITY: Record<string, number> = { running: 0, validating: 1, judging: 2, preparing: 3, queued: 4 };
const reasoningPolicyNames: Record<string, string> = { standard: "HIGH 标准条件", maximum: "MAX 极限条件", native: "Agent 原生条件", custom: "自定义条件", historical: "历史未固化条件" };
const failureClassNames: Record<string, string> = { agent_solution_failure: "能力未通过", agent_timeout: "Agent 执行超时", runtime_environment_failure: "运行环境故障", validator_infrastructure_failure: "验证器环境故障", permission_mismatch: "权限条件不一致" };

function questionNumber(run: RunSummary) {
  const match = run.test_title.match(/第\s*(\d+)\s*题/);
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
}

function byQuestion(left: RunSummary, right: RunSummary) {
  return questionNumber(left) - questionNumber(right) || left.created_at.localeCompare(right.created_at);
}

function byLivePriority(left: RunSummary, right: RunSummary) {
  return (RUN_STATUS_PRIORITY[left.status] ?? 9) - (RUN_STATUS_PRIORITY[right.status] ?? 9) || byQuestion(left, right);
}

export default function ExperimentDetail() {
  const { experimentId = "" } = useParams();
  const experiment = useApi<Experiment>(`/experiments/${experimentId}`, 2_000);
  const runs = useApi<RunSummary[]>(`/runs?experiment_id=${experimentId}&limit=1000`, 2_000);
  const capability = useApi<CapabilityReport>(experiment.data?.suite_metadata?.capability_report ? `/experiments/${experimentId}/capability-report` : "", 5_000);
  const openWorkspace = useOpenFolder();
  const [actionError, setActionError] = useState("");
  const [actionBusy, setActionBusy] = useState<"start" | "pause" | "cancel" | "">("");
  const [rejudgeBusy, setRejudgeBusy] = useState(false);
  const [actionMessage, setActionMessage] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return undefined;
    const key = `agentbench:experiment-scroll:${experimentId}`;
    const saved = Number(window.sessionStorage.getItem(key) ?? 0);
    if (Number.isFinite(saved)) node.scrollTop = saved;
    const remember = () => window.sessionStorage.setItem(key, String(node.scrollTop));
    node.addEventListener("scroll", remember, { passive: true });
    return () => node.removeEventListener("scroll", remember);
  }, [experimentId, experiment.data?.status]);
  async function action(kind: "start" | "pause" | "cancel") {
    setActionError("");
    setActionBusy(kind);
    try {
      await api(`/experiments/${experimentId}/${kind}`, { method: "POST" });
      await Promise.all([experiment.refresh(), runs.refresh()]);
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "操作失败");
    } finally {
      setActionBusy("");
    }
  }
  async function rejudge() {
    setActionError(""); setActionMessage(""); setRejudgeBusy(true);
    try {
      const result = await api<{ updated: number; failed: number; previous_exam_score?: number | null; exam_score?: number | null }>(`/experiments/${experimentId}/rejudge?scope=structured`, { method: "POST" });
      const delta = result.previous_exam_score != null && result.exam_score != null ? `，卷面 ${result.previous_exam_score.toFixed(1)} → ${result.exam_score.toFixed(1)}` : "";
      setActionMessage(`已使用原答案复判 ${result.updated} 项${delta}${result.failed ? `；${result.failed} 项需人工检查` : ""}`);
      await Promise.all([experiment.refresh(), runs.refresh()]);
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "批量复判失败");
    } finally { setRejudgeBusy(false); }
  }
  async function openPortfolioFolder() {
    setActionError("");
    try {
      const portfolio = await api<{ root_path: string }>(`/experiments/${experimentId}/frontend-portfolio`);
      await openWorkspace(portfolio.root_path, "作品目录");
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "无法读取作品目录");
    }
  }
  if (experiment.loading) return <LoadingBlock />;
  if (experiment.error || !experiment.data) return <ErrorBlock message={experiment.error ?? "实验不存在"} retry={() => void experiment.refresh()} />;
  const item = experiment.data;
  const isSixDimension = item.suite_metadata?.kind === "six-dimension";
  const summary = item.summary;
  if (["running", "pausing"].includes(item.status)) return <ExperimentBroadcast item={item} runs={runs.data ?? []} actionError={actionError} pausing={item.status === "pausing"} actionBusy={actionBusy} onCancel={item.status === "running" ? () => void action("cancel") : undefined} onPause={item.status === "running" ? async () => { await action("pause"); } : undefined} onSkip={item.suite_metadata?.kind === "frontend" ? async (runId) => { setActionError(""); try { await api(`/runs/${runId}/skip`, { method: "POST" }); await runs.refresh(); } catch (value) { setActionError(value instanceof Error ? value.message : "跳过项目失败"); } } : undefined} />;
  const remaining = runs.data?.filter((run) => INCOMPLETE_RUN_STATUSES.has(run.status)).length ?? 0;
  const finished = runs.data?.length
    ? runs.data.length - remaining
    : (summary?.completed ?? 0) + (summary?.failed ?? 0) + (summary?.blocked ?? 0);
  const progress = summary?.total ? Math.round((finished / summary.total) * 100) : 0;
  const completedRuns = runs.data?.filter((run) => run.score != null) ?? [];
  const agentModeOf = (run: RunSummary) => String(run.runtime_identity?.effective_agent_mode ?? run.runtime_identity?.requested_agent_mode ?? "");
  const participantGroups = new Map<string, RunSummary[]>();
  const categoryGroups = new Map<string, RunSummary[]>();
  for (const run of runs.data ?? []) {
    const participantKey = `${run.model_id}:${run.runner_id}:${agentModeOf(run)}`;
    participantGroups.set(participantKey, [...(participantGroups.get(participantKey) ?? []), run]);
    categoryGroups.set(run.category, [...(categoryGroups.get(run.category) ?? []), run]);
  }
  const participantStats = [...participantGroups.values()].map((group) => {
    const scored = group.filter((run) => run.score != null);
    const objectiveScored = group.filter((run) => run.objective_score != null);
    const timeScored = group.filter((run) => run.time_score != null);
    return {
      key: `${group[0].model_id}:${group[0].runner_id}:${agentModeOf(group[0])}`,
      name: group[0].model_name,
      runner: group[0].runner_name,
      agentMode: agentModeOf(group[0]),
      score: scored.length ? scored.reduce((sum, run) => sum + Number(run.score), 0) / scored.length : null,
      objective: objectiveScored.length ? objectiveScored.reduce((sum, run) => sum + Number(run.objective_score), 0) / objectiveScored.length : null,
      time: timeScored.length ? timeScored.reduce((sum, run) => sum + Number(run.time_score), 0) / timeScored.length : null,
      success: scored.length ? scored.filter((run) => run.passed ?? run.status === "completed").length / scored.length * 100 : 0,
    };
  }).sort((left, right) => Number(right.score ?? -1) - Number(left.score ?? -1));
  const categoryStats = [...categoryGroups.entries()].map(([category, group]) => {
    const scored = group.filter((run) => run.score != null);
    return { category, score: scored.length ? scored.reduce((sum, run) => sum + Number(run.score), 0) / scored.length : null, runs: group.length };
  }).sort((left, right) => Number(right.score ?? -1) - Number(left.score ?? -1));
  return (
    <div className="ab-view ab-agent-document ab-experiment-detail-view">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">03 / COMPOSITION</span><div><h1>{item.name}</h1><p>{item.suite_name} · {formatDate(item.created_at)} · {item.participants.length} 个参测组合 · {reasoningPolicyNames[item.reasoning_policy ?? "historical"]}</p></div></div>
        <div className="ab-header-meta"><Link to="/experiments?history=1" className="ab-ghost-button"><ArrowLeft size={13} />实验账本</Link>{item.suite_metadata?.kind === "frontend" && <><Link className="ab-ghost-button" to={`/experiments/${item.id}/portfolio`}><FolderOpen size={13} />作品集</Link><button className="ab-ghost-button" type="button" onClick={() => void openPortfolioFolder()}><FolderOpen size={13} />打开全部作品</button></>}{isSixDimension && <a className="ab-ghost-button" href={downloadUrl(`/experiments/${item.id}/capability-panel.svg?download=true`)}><Download size={13} />六维面板 SVG</a>}<a className="ab-ghost-button" href={downloadUrl(`/experiments/${item.id}/export?format=html`)}><Download size={13} />导出报告</a>{item.status === "completed" && item.suite_metadata?.kind !== "frontend" && <Button variant="ghost" busy={rejudgeBusy} onClick={() => void rejudge()}><RefreshCw size={13} />复判结构化答案</Button>}{["draft", "paused", "interrupted"].includes(item.status) && <Button busy={actionBusy === "start"} onClick={() => void action("start")}><Play size={13} />{item.status === "draft" ? "启动评测" : `继续剩余 ${remaining} 项`}</Button>}</div>
      </header>
      <div className="ab-experiment-detail-scroll" ref={scrollRef}>
      {actionError && <div className="error-banner preflight-error"><strong>启动检查未通过</strong><span>{actionError}</span></div>}
      {actionMessage && <div className="ab-rejudge-success"><CheckCircle2 size={15} /><span>{actionMessage}</span></div>}
      {["paused", "interrupted"].includes(item.status) && <div className="balanced-score-strip"><Pause size={18} /><div><strong>{item.status === "paused" ? "套件已暂停，进度已安全保存" : "套件被意外中断，可从断点继续"}</strong><span>已保留 {finished} / {summary?.total ?? runs.data?.length ?? 0} 项结果；继续后只调度剩余 {remaining} 项，已完成项目不会重跑。</span></div><small>模型已提交答案的项目只续验证或评分</small></div>}
      <div className="balanced-score-strip"><Gauge size={18} /><div><strong>{isSixDimension ? "六维等权能力评分" : item.suite_metadata?.kind === "frontend" ? "纯人工评分" : summary?.exam_total ? "卷面与效率分离" : `${reasoningPolicyNames[item.reasoning_policy ?? "historical"]} · 平衡评分`}</strong><span>{isSixDimension ? "各维先聚合本维题目，再以六维等权计算总分；人工未评与环境阻塞保持为空，不伪装成能力 0 分" : item.suite_metadata?.kind === "frontend" ? `已评 ${summary?.reviewed_runs ?? 0} / ${summary?.total ?? 0} · 未评分不会记为 0 分 · 正式总分按 D2–Ultra 难度加权` : summary?.exam_total ? "考研卷面仅按答案质量计分 · 时间、步骤与 Token 独立展示" : `质量 94% · 完成时间 3% · Agent 步数 2% · Token 1% · ${item.strict_fairness ? "严格公平" : "非标准条件"}`}</span></div><small>{isSixDimension ? "前端人工盲评 · 后端/办公/Agent 私有验证 · 数学双裁判+答案锚点 · 研究证据裁判" : item.suite_metadata?.kind === "frontend" ? `题库 ${item.suite_metadata.suite_revision} · ${item.suite_metadata.source_commit?.slice(0, 12)}` : summary?.exam_total ? "满分 150 · 解答题按 10 + 12×5 计 70 分" : `参测 ${item.reasoning_effort?.toUpperCase() ?? "AGENT DEFAULT"} · 裁判 ${item.judge_reasoning_effort?.toUpperCase() ?? "未固化"}`}</small></div>
      {isSixDimension && <CapabilityPanel experimentId={item.id} report={capability.data ?? undefined} loading={capability.loading} error={capability.error ?? undefined} />}
      <div className="run-overview">
        <Card><span>状态</span><StatusBadge status={item.status} /><div className="progress-line large"><i style={{ width: `${progress}%` }} /></div><small>{finished} / {summary?.total ?? 0} · {progress}%</small></Card>
        <Card><span>{item.suite_metadata?.kind === "frontend" ? "人工加权分" : summary?.exam_total ? "卷面得分" : "平均得分"}</span>{item.suite_metadata?.kind === "frontend" ? <Score value={summary?.frontend_weighted_score ?? summary?.reviewed_weighted_score} large /> : summary?.exam_total ? <strong>{summary.exam_score?.toFixed(1) ?? "—"}<small> / {summary.exam_total.toFixed(0)}</small></strong> : <Score value={summary?.avg_score} large />}<small>{item.suite_metadata?.kind === "frontend" ? summary?.frontend_weighted_score != null ? "全部项目完成评审，正式分已生成" : `当前为已评分部分 · 进度 ${summary?.review_progress ?? 0}%` : summary?.exam_total ? `按每题官方分值加权 · 百分制 ${summary.avg_score?.toFixed(1) ?? "—"}` : summary?.avg_objective_score != null ? `客观质量 ${summary.avg_objective_score.toFixed(1)} · 时效 ${summary.avg_time_score?.toFixed(1) ?? "—"}` : "仅统计完成且成功评分的运行"}</small></Card>
        <Card><span>总 Token</span><strong>{formatNumber(summary?.tokens)}</strong><small>输入与输出合计</small></Card>
        <Card><span>累计费用</span><strong>${Number(summary?.cost_usd ?? 0).toFixed(4)}</strong><small>{summary?.unpriced_runs ? `${summary.unpriced_runs} 次运行缺少单价，当前合计不完整` : "实际上报或按模型单价估算"}</small></Card>
      </div>
      {Boolean(runs.data?.length) && <div className="experiment-insights">
        <Card>
          <div className="card-header"><div><span className="section-kicker">PARTICIPANTS</span><h2>参测者对比</h2></div><BarChart3 size={18} /></div>
          <div className="participant-bars">
            {participantStats.map((stat, index) => <div className="participant-bar" key={stat.key}>
              <span className="insight-rank">{index + 1}</span><div><strong>{stat.name}</strong><small>{stat.runner}{stat.agentMode ? ` · ${stat.agentMode}` : ""} · 成功率 {stat.success.toFixed(0)}%{stat.objective != null ? ` · 质量 ${stat.objective.toFixed(1)} · 时效 ${stat.time?.toFixed(1) ?? "—"}` : ""}</small></div><div className="score-track"><i style={{ width: `${stat.score ?? 0}%` }} /></div><Score value={stat.score} />
            </div>)}
          </div>
        </Card>
        <Card>
          <div className="card-header"><div><span className="section-kicker">CAPABILITIES</span><h2>能力域表现</h2></div>{(summary?.failed ?? 0) + (summary?.blocked ?? 0) ? <AlertTriangle size={18} className="text-amber" /> : <CheckCircle2 size={18} className="text-green" />}</div>
          <div className="category-score-grid">
            {categoryStats.map((stat) => <div key={stat.category}><span>{stat.category}</span><div className="score-track"><i style={{ width: `${stat.score ?? 0}%` }} /></div><Score value={stat.score} /><small>{stat.runs} 次</small></div>)}
          </div>
          {!completedRuns.length && <div className="inline-empty">任务运行后会在这里显示能力分布。</div>}
        </Card>
      </div>}
      <Card>
        <div className="card-header"><div><span className="section-kicker">RUN MATRIX</span><h2>运行任务</h2></div><button className="icon-button" onClick={() => void runs.refresh()}><RotateCcw size={16} /></button></div>
        {runs.loading ? <LoadingBlock /> : runs.error || !runs.data ? <ErrorBlock message={runs.error ?? "运行列表读取失败"} /> : (
          <div className="table-wrap run-table"><table><thead><tr><th>测试任务</th><th>参测组合</th><th>条件</th><th>重复 / 轮次</th><th>耗时</th><th>Token</th><th>综合 / 分项</th><th>状态 / 原因</th></tr></thead><tbody>{runs.data.map((run) => <tr key={run.id}><td><Link to={`/runs/${run.id}`} state={{ from: `/experiments/${item.id}` }}><strong>{run.test_title}</strong></Link><small>{run.category}</small></td><td><strong>{run.model_name}</strong><small>{run.runner_name}{agentModeOf(run) ? ` · ${agentModeOf(run)}` : ""}</small></td><td><span className={`lane lane-${run.effort_verified ? "unified" : "native"}`}>{run.effective_reasoning_effort?.toUpperCase() ?? "DEFAULT"}</span><small>{run.effort_verified ? "已验证" : "未验证映射"}</small></td><td>#{run.repetition}<small>{run.attempt_count > 1 ? `${run.attempt_count} 轮挑战` : "单轮"}</small></td><td>{formatDuration(run.duration_ms)}</td><td>{run.telemetry_status === "unavailable" ? "N/A" : formatNumber(run.tokens_input + run.tokens_output)}</td><td><Score value={run.score} />{run.objective_score != null && <small className="score-subline">质量 {run.objective_score.toFixed(1)} · 时效 {run.time_score?.toFixed(1) ?? "—"} · T效 {run.token_score?.toFixed(1) ?? "—"}</small>}</td><td><StatusBadge status={run.status} />{run.failure_class && <small className="run-error-preview">{failureClassNames[run.failure_class] ?? run.failure_class}</small>}{run.error_message && <small className="run-error-preview" title={run.error_message}>{run.error_code ? `${run.error_code} · ` : ""}{run.error_message}</small>}</td></tr>)}</tbody></table></div>
        )}
      </Card>
      </div>
    </div>
  );
}

function CapabilityPanel({ experimentId, report, loading, error }: { experimentId: string; report?: CapabilityReport; loading: boolean; error?: string }) {
  const [selected, setSelected] = useState("");
  const profile = report?.profiles.find((item) => item.profile_id === selected) ?? report?.profiles[0];
  useEffect(() => {
    if (!selected && report?.profiles[0]) setSelected(report.profiles[0].profile_id);
  }, [report, selected]);
  if (loading && !report) return <Card className="capability-panel-card"><LoadingBlock /></Card>;
  if (error && !report) return <Card className="capability-panel-card"><ErrorBlock message={error} /></Card>;
  if (!profile || !report) return <Card className="capability-panel-card"><div className="inline-empty">六维运行创建后会在这里生成能力面板。</div></Card>;
  const panelPath = `/experiments/${experimentId}/capability-panel.svg?profile_id=${encodeURIComponent(profile.profile_id)}`;
  return <section className="capability-panel-card">
    <div className="capability-panel-head">
      <div><span className="section-kicker">SIX-DIMENSION REPORT</span><h2>六维能力面板</h2><p>六个能力域等权聚合；待评分项目显示为空，不按 0 分处理。每一分都可下钻到题目、验证证据和人工评审。</p></div>
      <div className="capability-panel-actions">
        {report.profiles.length > 1 && <div className="capability-profile-tabs">{report.profiles.map((item) => <button className={item.profile_id === profile.profile_id ? "active" : ""} type="button" key={item.profile_id} onClick={() => setSelected(item.profile_id)}>{item.model.name}</button>)}</div>}
        <a className="ab-ghost-button" href={downloadUrl(`${panelPath}&download=true`)}><Download size={13} />下载 16:9 SVG</a>
        <a className="ab-ghost-button" href={downloadUrl(`/experiments/${experimentId}/capability-report`)} target="_blank" rel="noreferrer"><BarChart3 size={13} />详细 JSON</a>
      </div>
    </div>
    <div className="capability-panel-layout">
      <div className="capability-panel-preview"><img src={downloadUrl(panelPath)} alt={`${profile.model.name} 六维能力面板`} /></div>
      <div className="capability-dimension-list">
        {profile.dimensions.map((dimension) => <article key={dimension.key}>
          <div><strong>{dimension.label}</strong><span>{dimension.score == null ? "待评分" : dimension.score.toFixed(1)}</span></div>
          <div className="capability-score-track"><i style={{ width: `${dimension.score ?? 0}%` }} /></div>
          <small>{dimension.scored}/{dimension.total} 已评分 · 置信度 {dimension.confidence_label} · {formatDuration(dimension.duration_ms)}</small>
          <div className="capability-run-chips">{dimension.runs.map((run) => <Link key={run.run_id} to={`/runs/${run.run_id}`} title={`${run.score_source} · ${run.confidence_label}`}>{run.title}<b>{run.score == null ? "—" : run.score.toFixed(1)}</b>{run.hard_gates.length > 0 && <AlertTriangle size={12} />}</Link>)}</div>
        </article>)}
      </div>
    </div>
    <footer className="capability-panel-footer"><span><strong>{profile.model.name}</strong> × {profile.runner.name}</span><span>总分 {profile.overall_score?.toFixed(1) ?? "—"} · {profile.overall_complete ? "最终成绩" : "阶段成绩"}</span><span>强项 {profile.strengths.join(" / ") || "待生成"} · 待提升 {profile.weaknesses.join(" / ") || "待生成"}</span></footer>
  </section>;
}

function ExperimentBroadcast({ item, runs, actionError, pausing, actionBusy, onCancel, onPause, onSkip }: { item: Experiment; runs: RunSummary[]; actionError: string; pausing: boolean; actionBusy: "start" | "pause" | "cancel" | ""; onCancel?: () => void; onPause?: () => Promise<void>; onSkip?: (runId: string) => Promise<void> }) {
  const [queueView, setQueueView] = useState<"follow" | "all">("follow");
  const [autoFollow, setAutoFollow] = useState(true);
  const [focusRunId, setFocusRunId] = useState("");
  const activeRuns = runs.filter((run) => ACTIVE_RUN_STATUSES.has(run.status)).sort(byLivePriority);
  const primaryActive = activeRuns[0];
  useEffect(() => {
    if (autoFollow && primaryActive?.id) setFocusRunId(primaryActive.id);
  }, [autoFollow, primaryActive?.id]);
  const focusSummary = runs.find((run) => run.id === focusRunId) ?? primaryActive ?? [...runs].sort(byQuestion)[0];
  const focus = useApi<RunDetail>(focusSummary ? `/runs/${focusSummary.id}` : "", 1_500);
  const active = Boolean(focus.data && ACTIVE_RUN_STATUSES.has(focus.data.status));
  const live = useRunEvents(focusSummary?.id ?? "", focus.data?.events ?? [], active);
  const finished = runs.filter((run) => !INCOMPLETE_RUN_STATUSES.has(run.status)).length;
  const progress = runs.length ? Math.round(finished / runs.length * 100) : 0;
  const recentFinished = runs.filter((run) => !INCOMPLETE_RUN_STATUSES.has(run.status)).sort((left, right) => (right.completed_at ?? right.created_at).localeCompare(left.completed_at ?? left.created_at));
  const followRuns = [...new Map([...activeRuns, ...recentFinished].map((run) => [run.id, run])).values()].slice(0, 8);
  const visibleRuns = queueView === "all" ? [...runs].sort(byQuestion) : followRuns;
  const runningCount = runs.filter((run) => ["preparing", "running"].includes(run.status)).length;
  const verifyingCount = runs.filter((run) => ["validating", "judging"].includes(run.status)).length;
  return <BroadcastFrame><div className="experiment-broadcast-page">
    <header className="broadcast-page-head"><div className="broadcast-page-title"><span>LIVE 01 / EXPERIMENT</span><div><h1>{item.name}</h1><p>{item.suite_name} · {item.participants.length} 个参测组合 · 并发 {item.concurrency}</p></div></div><div className="broadcast-head-meta"><span className="broadcast-record-badge"><i />{pausing ? "PAUSING" : "REC / 16:9 SAFE"}</span><span className="broadcast-clock">{finished} / {runs.length} COMPLETED</span>{pausing && <span className="broadcast-clock">正在安全结束当前调用…</span>}{onPause && <Button variant="ghost" busy={actionBusy === "pause"} onClick={() => void onPause()}><Pause size={15} /> 暂停套件</Button>}{onCancel && <Button variant="danger" busy={actionBusy === "cancel"} onClick={onCancel}><Square size={15} /> 停止评测</Button>}</div></header>
    {actionError && <div className="error-banner"><strong>操作失败</strong><span>{actionError}</span></div>}
    {focus.loading || !focus.data ? <Card className="broadcast-loading"><LoadingBlock /></Card> : <ExperimentLiveFocus run={focus.data} events={live.events} streamState={live.streamState} />}
    <section className={`live-race-board live-race-board-${queueView}`}>
      <div className="live-race-controls"><div><strong>实时任务队列</strong><span>{runningCount} 执行中 · {verifyingCount} 验证中 · {finished} 已结束</span></div><nav><button className={queueView === "follow" ? "active" : ""} type="button" onClick={() => setQueueView("follow")}>当前 / 最近</button><button className={queueView === "all" ? "active" : ""} type="button" onClick={() => setQueueView("all")}>全部 {runs.length}</button><button className={autoFollow ? "active" : ""} type="button" onClick={() => setAutoFollow((value) => !value)}>{autoFollow ? "自动跟随中" : "手动聚焦"}</button></nav></div>
      <header><span>测试任务</span><span>当前状态</span><span>执行阶段</span><span>用时</span><span>实时分数 / 详情</span></header>
      <div className="live-race-list">{visibleRuns.map((run) => {
        const isLive = ACTIVE_RUN_STATUSES.has(run.status);
        const stage = run.status === "queued" ? 3 : run.status === "preparing" ? 16 : run.status === "running" ? 52 : run.status === "validating" ? 74 : run.status === "judging" ? 88 : 100;
        const focused = focusSummary?.id === run.id;
        const skippable = onSkip && ["queued", "preparing", "running"].includes(run.status);
        return <article className={`${isLive ? "live" : ""}${focused ? " focused" : ""}`} key={run.id}><button className="live-race-focus" type="button" onClick={() => { setAutoFollow(false); setFocusRunId(run.id); }}><strong>{run.test_title}</strong><small>{run.model_name} × {run.runner_name} · ROUND {Math.max(1, run.attempt_count)}</small></button><span><i /> {run.status}</span><div className="live-race-track"><i style={{ left: `${stage}%` }} /></div><code>{formatDuration(run.duration_ms)}</code><div className="live-race-result"><Score value={run.score} />{skippable && <button type="button" title="停止当前项目或从队列中移除未开始项目" onClick={() => void onSkip(run.id)}>跳过</button>}<Link to={`/runs/${run.id}`} state={{ from: `/experiments/${item.id}` }}>详情</Link></div></article>;
      })}</div>
      {!runs.length && <div className="live-race-empty">任务正在编排，运行队列即将出现。</div>}
      <footer><span>总进度</span><div className="progress-line"><i style={{ width: `${progress}%` }} /></div><strong>{progress}%</strong></footer>
    </section>
  </div></BroadcastFrame>;
}
