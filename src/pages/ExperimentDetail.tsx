import { AlertTriangle, ArrowLeft, BarChart3, CheckCircle2, Download, Gauge, Play, RefreshCw, RotateCcw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, downloadUrl } from "../lib/api";
import { formatDate, formatDuration, formatNumber } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useRunEvents } from "../lib/useRunEvents";
import type { Experiment, RunDetail, RunSummary } from "../types";
import { Button, Card, ErrorBlock, LoadingBlock, Score, StatusBadge } from "../components/ui";
import { ExperimentLiveFocus } from "../components/LiveRunView";
import { BroadcastFrame } from "../components/BroadcastFrame";

const ACTIVE_RUN_STATUSES = new Set(["queued", "preparing", "running", "validating", "judging"]);
const RUN_STATUS_PRIORITY: Record<string, number> = { running: 0, validating: 1, judging: 2, preparing: 3, queued: 4 };

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
  const [actionError, setActionError] = useState("");
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
  async function action(kind: "start" | "cancel") {
    setActionError("");
    try {
      await api(`/experiments/${experimentId}/${kind}`, { method: "POST" });
      await Promise.all([experiment.refresh(), runs.refresh()]);
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "操作失败");
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
  if (experiment.loading) return <LoadingBlock />;
  if (experiment.error || !experiment.data) return <ErrorBlock message={experiment.error ?? "实验不存在"} retry={() => void experiment.refresh()} />;
  const item = experiment.data;
  const summary = item.summary;
  if (item.status === "running") return <ExperimentBroadcast item={item} runs={runs.data ?? []} actionError={actionError} onCancel={() => void action("cancel")} />;
  const finished = (summary?.completed ?? 0) + (summary?.failed ?? 0) + (summary?.blocked ?? 0);
  const progress = summary?.total ? Math.round((finished / summary.total) * 100) : 0;
  const completedRuns = runs.data?.filter((run) => run.score != null) ?? [];
  const participantGroups = new Map<string, RunSummary[]>();
  const categoryGroups = new Map<string, RunSummary[]>();
  for (const run of runs.data ?? []) {
    const participantKey = `${run.model_id}:${run.runner_id}`;
    participantGroups.set(participantKey, [...(participantGroups.get(participantKey) ?? []), run]);
    categoryGroups.set(run.category, [...(categoryGroups.get(run.category) ?? []), run]);
  }
  const participantStats = [...participantGroups.values()].map((group) => {
    const scored = group.filter((run) => run.score != null);
    const objectiveScored = group.filter((run) => run.objective_score != null);
    const timeScored = group.filter((run) => run.time_score != null);
    return {
      key: `${group[0].model_id}:${group[0].runner_id}`,
      name: group[0].model_name,
      runner: group[0].runner_name,
      score: scored.length ? scored.reduce((sum, run) => sum + Number(run.score), 0) / scored.length : null,
      objective: objectiveScored.length ? objectiveScored.reduce((sum, run) => sum + Number(run.objective_score), 0) / objectiveScored.length : null,
      time: timeScored.length ? timeScored.reduce((sum, run) => sum + Number(run.time_score), 0) / timeScored.length : null,
      success: group.length ? group.filter((run) => run.passed ?? run.status === "completed").length / group.length * 100 : 0,
    };
  }).sort((left, right) => Number(right.score ?? -1) - Number(left.score ?? -1));
  const categoryStats = [...categoryGroups.entries()].map(([category, group]) => {
    const scored = group.filter((run) => run.score != null);
    return { category, score: scored.length ? scored.reduce((sum, run) => sum + Number(run.score), 0) / scored.length : null, runs: group.length };
  }).sort((left, right) => Number(right.score ?? -1) - Number(left.score ?? -1));
  return (
    <div className="ab-view ab-experiment-detail-view">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">03 / COMPOSITION</span><div><h1>{item.name}</h1><p>{item.suite_name} · {formatDate(item.created_at)} · {item.participants.length} 个参测组合 · 重复 {item.repetitions} 次</p></div></div>
        <div className="ab-header-meta"><Link to="/experiments?history=1" className="ab-ghost-button"><ArrowLeft size={13} />实验账本</Link><a className="ab-ghost-button" href={downloadUrl(`/experiments/${item.id}/export?format=html`)}><Download size={13} />导出报告</a>{item.status === "completed" && <Button variant="ghost" busy={rejudgeBusy} onClick={() => void rejudge()}><RefreshCw size={13} />复判结构化答案</Button>}{["draft", "interrupted"].includes(item.status) && <button className="ab-run-button" type="button" onClick={() => void action("start")}><Play size={13} />启动评测</button>}{item.status === "running" && <Button variant="danger" onClick={() => void action("cancel")}><Square size={15} /> 停止</Button>}</div>
      </header>
      <div className="ab-experiment-detail-scroll" ref={scrollRef}>
      {actionError && <div className="error-banner preflight-error"><strong>启动检查未通过</strong><span>{actionError}</span></div>}
      {actionMessage && <div className="ab-rejudge-success"><CheckCircle2 size={15} /><span>{actionMessage}</span></div>}
      <div className="balanced-score-strip"><Gauge size={18} /><div><strong>{summary?.exam_total ? "卷面与效率分离" : "平衡评分"}</strong><span>{summary?.exam_total ? "考研卷面仅按答案质量计分 · 时间、步骤与 Token 独立展示" : "质量 94% · 完成时间 3% · Agent 步数 2% · Token 1%"}</span></div><small>{summary?.exam_total ? "满分 150 · 解答题按 10 + 12×5 计 70 分" : "新运行支持连续部分分，旧记录保持原始评分"}</small></div>
      <div className="run-overview">
        <Card><span>状态</span><StatusBadge status={item.status} /><div className="progress-line large"><i style={{ width: `${progress}%` }} /></div><small>{finished} / {summary?.total ?? 0} · {progress}%</small></Card>
        <Card><span>{summary?.exam_total ? "卷面得分" : "平均得分"}</span>{summary?.exam_total ? <strong>{summary.exam_score?.toFixed(1) ?? "—"}<small> / {summary.exam_total.toFixed(0)}</small></strong> : <Score value={summary?.avg_score} large />}<small>{summary?.exam_total ? `按每题官方分值加权 · 百分制 ${summary.avg_score?.toFixed(1) ?? "—"}` : summary?.avg_objective_score != null ? `客观质量 ${summary.avg_objective_score.toFixed(1)} · 时效 ${summary.avg_time_score?.toFixed(1) ?? "—"}` : "仅统计完成且成功评分的运行"}</small></Card>
        <Card><span>总 Token</span><strong>{formatNumber(summary?.tokens)}</strong><small>输入与输出合计</small></Card>
        <Card><span>累计费用</span><strong>${Number(summary?.cost_usd ?? 0).toFixed(4)}</strong><small>{summary?.unpriced_runs ? `${summary.unpriced_runs} 次运行缺少单价，当前合计不完整` : "实际上报或按模型单价估算"}</small></Card>
      </div>
      {Boolean(runs.data?.length) && <div className="experiment-insights">
        <Card>
          <div className="card-header"><div><span className="section-kicker">PARTICIPANTS</span><h2>参测者对比</h2></div><BarChart3 size={18} /></div>
          <div className="participant-bars">
            {participantStats.map((stat, index) => <div className="participant-bar" key={stat.key}>
              <span className="insight-rank">{index + 1}</span><div><strong>{stat.name}</strong><small>{stat.runner} · 成功率 {stat.success.toFixed(0)}%{stat.objective != null ? ` · 质量 ${stat.objective.toFixed(1)} · 时效 ${stat.time?.toFixed(1) ?? "—"}` : ""}</small></div><div className="score-track"><i style={{ width: `${stat.score ?? 0}%` }} /></div><Score value={stat.score} />
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
          <div className="table-wrap run-table"><table><thead><tr><th>测试任务</th><th>参测组合</th><th>赛道</th><th>重复 / 轮次</th><th>耗时</th><th>Token</th><th>综合 / 分项</th><th>状态 / 原因</th></tr></thead><tbody>{runs.data.map((run) => <tr key={run.id}><td><Link to={`/runs/${run.id}`} state={{ from: `/experiments/${item.id}` }}><strong>{run.test_title}</strong></Link><small>{run.category}</small></td><td><strong>{run.model_name}</strong><small>{run.runner_name}</small></td><td><span className={`lane lane-${run.lane}`}>{run.lane === "unified" ? "统一" : "原生"}</span></td><td>#{run.repetition}<small>{run.attempt_count > 1 ? `${run.attempt_count} 轮挑战` : "单轮"}</small></td><td>{formatDuration(run.duration_ms)}</td><td>{formatNumber(run.tokens_input + run.tokens_output)}</td><td><Score value={run.score} />{run.objective_score != null && <small className="score-subline">质量 {run.objective_score.toFixed(1)} · 时效 {run.time_score?.toFixed(1) ?? "—"} · T效 {run.token_score?.toFixed(1) ?? "—"}</small>}</td><td><StatusBadge status={run.status} />{run.status === "completed" && run.passed === false && <small className="run-error-preview">能力未及格</small>}{run.error_message && <small className="run-error-preview" title={run.error_message}>{run.error_code ? `${run.error_code} · ` : ""}{run.error_message}</small>}</td></tr>)}</tbody></table></div>
        )}
      </Card>
      </div>
    </div>
  );
}

function ExperimentBroadcast({ item, runs, actionError, onCancel }: { item: Experiment; runs: RunSummary[]; actionError: string; onCancel: () => void }) {
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
  const finished = runs.filter((run) => !ACTIVE_RUN_STATUSES.has(run.status)).length;
  const progress = runs.length ? Math.round(finished / runs.length * 100) : 0;
  const recentFinished = runs.filter((run) => !ACTIVE_RUN_STATUSES.has(run.status)).sort((left, right) => (right.completed_at ?? right.created_at).localeCompare(left.completed_at ?? left.created_at));
  const followRuns = [...new Map([...activeRuns, ...recentFinished].map((run) => [run.id, run])).values()].slice(0, 8);
  const visibleRuns = queueView === "all" ? [...runs].sort(byQuestion) : followRuns;
  const runningCount = runs.filter((run) => ["preparing", "running"].includes(run.status)).length;
  const verifyingCount = runs.filter((run) => ["validating", "judging"].includes(run.status)).length;
  return <BroadcastFrame><div className="experiment-broadcast-page">
    <header className="broadcast-page-head"><div className="broadcast-page-title"><span>LIVE 01 / EXPERIMENT</span><div><h1>{item.name}</h1><p>{item.suite_name} · {item.participants.length} 个参测组合 · 并发 {item.concurrency}</p></div></div><div className="broadcast-head-meta"><span className="broadcast-record-badge"><i />REC / 16:9 SAFE</span><span className="broadcast-clock">{finished} / {runs.length} COMPLETED</span><Button variant="danger" onClick={onCancel}><Square size={15} /> 停止评测</Button></div></header>
    {actionError && <div className="error-banner"><strong>操作失败</strong><span>{actionError}</span></div>}
    {focus.loading || !focus.data ? <Card className="broadcast-loading"><LoadingBlock /></Card> : <ExperimentLiveFocus run={focus.data} events={live.events} streamState={live.streamState} />}
    <section className={`live-race-board live-race-board-${queueView}`}>
      <div className="live-race-controls"><div><strong>实时任务队列</strong><span>{runningCount} 执行中 · {verifyingCount} 验证中 · {finished} 已结束</span></div><nav><button className={queueView === "follow" ? "active" : ""} type="button" onClick={() => setQueueView("follow")}>当前 / 最近</button><button className={queueView === "all" ? "active" : ""} type="button" onClick={() => setQueueView("all")}>全部 {runs.length}</button><button className={autoFollow ? "active" : ""} type="button" onClick={() => setAutoFollow((value) => !value)}>{autoFollow ? "自动跟随中" : "手动聚焦"}</button></nav></div>
      <header><span>测试任务</span><span>当前状态</span><span>执行阶段</span><span>用时</span><span>实时分数 / 详情</span></header>
      <div className="live-race-list">{visibleRuns.map((run) => {
        const isLive = ACTIVE_RUN_STATUSES.has(run.status);
        const stage = run.status === "queued" ? 3 : run.status === "preparing" ? 16 : run.status === "running" ? 52 : run.status === "validating" ? 74 : run.status === "judging" ? 88 : 100;
        const focused = focusSummary?.id === run.id;
        return <article className={`${isLive ? "live" : ""}${focused ? " focused" : ""}`} key={run.id}><button className="live-race-focus" type="button" onClick={() => { setAutoFollow(false); setFocusRunId(run.id); }}><strong>{run.test_title}</strong><small>{run.model_name} × {run.runner_name} · ROUND {Math.max(1, run.attempt_count)}</small></button><span><i /> {run.status}</span><div className="live-race-track"><i style={{ left: `${stage}%` }} /></div><code>{formatDuration(run.duration_ms)}</code><div className="live-race-result"><Score value={run.score} /><Link to={`/runs/${run.id}`} state={{ from: `/experiments/${item.id}` }}>详情</Link></div></article>;
      })}</div>
      {!runs.length && <div className="live-race-empty">任务正在编排，运行队列即将出现。</div>}
      <footer><span>总进度</span><div className="progress-line"><i style={{ width: `${progress}%` }} /></div><strong>{progress}%</strong></footer>
    </section>
  </div></BroadcastFrame>;
}
