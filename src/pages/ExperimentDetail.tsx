import { AlertTriangle, ArrowLeft, BarChart3, CheckCircle2, Download, Gauge, Play, RotateCcw, Square } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, downloadUrl } from "../lib/api";
import { formatDate, formatDuration, formatNumber } from "../lib/format";
import { useApi } from "../lib/useApi";
import type { Experiment, RunSummary } from "../types";
import { Button, Card, ErrorBlock, LoadingBlock, PageHeader, Score, StatusBadge } from "../components/ui";

export default function ExperimentDetail() {
  const { experimentId = "" } = useParams();
  const experiment = useApi<Experiment>(`/experiments/${experimentId}`, 2_000);
  const runs = useApi<RunSummary[]>(`/runs?experiment_id=${experimentId}&limit=1000`, 2_000);
  const [actionError, setActionError] = useState("");
  async function action(kind: "start" | "cancel") {
    setActionError("");
    try {
      await api(`/experiments/${experimentId}/${kind}`, { method: "POST" });
      await Promise.all([experiment.refresh(), runs.refresh()]);
    } catch (value) {
      setActionError(value instanceof Error ? value.message : "操作失败");
    }
  }
  if (experiment.loading) return <LoadingBlock />;
  if (experiment.error || !experiment.data) return <ErrorBlock message={experiment.error ?? "实验不存在"} retry={() => void experiment.refresh()} />;
  const item = experiment.data;
  const summary = item.summary;
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
    <div className="page">
      <Link to="/experiments" className="back-link"><ArrowLeft size={16} /> 返回实验列表</Link>
      <PageHeader eyebrow={item.suite_name} title={item.name} description={`创建于 ${formatDate(item.created_at)} · ${item.participants.length} 个参测组合 · 重复 ${item.repetitions} 次`} actions={<><a className="button button-secondary" href={downloadUrl(`/experiments/${item.id}/export?format=html`)}><Download size={16} /> 导出报告</a>{["draft", "interrupted"].includes(item.status) && <Button onClick={() => void action("start")}><Play size={16} /> 启动评测</Button>}{item.status === "running" && <Button variant="danger" onClick={() => void action("cancel")}><Square size={15} /> 停止</Button>}</>} />
      {actionError && <div className="error-banner preflight-error"><strong>启动检查未通过</strong><span>{actionError}</span></div>}
      <div className="balanced-score-strip"><Gauge size={18} /><div><strong>平衡评分</strong><span>质量 94% · 完成时间 3% · Agent 步数 2% · Token 1%</span></div><small>新运行支持连续部分分，旧记录保持原始评分</small></div>
      <div className="run-overview">
        <Card><span>状态</span><StatusBadge status={item.status} /><div className="progress-line large"><i style={{ width: `${progress}%` }} /></div><small>{finished} / {summary?.total ?? 0} · {progress}%</small></Card>
        <Card><span>平均得分</span><Score value={summary?.avg_score} large /><small>{summary?.avg_objective_score != null ? `客观质量 ${summary.avg_objective_score.toFixed(1)} · 时效 ${summary.avg_time_score?.toFixed(1) ?? "—"}` : "仅统计完成且成功评分的运行"}</small></Card>
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
          <div className="table-wrap run-table"><table><thead><tr><th>测试任务</th><th>参测组合</th><th>赛道</th><th>重复 / 轮次</th><th>耗时</th><th>Token</th><th>综合 / 分项</th><th>状态 / 原因</th></tr></thead><tbody>{runs.data.map((run) => <tr key={run.id}><td><Link to={`/runs/${run.id}`}><strong>{run.test_title}</strong></Link><small>{run.category}</small></td><td><strong>{run.model_name}</strong><small>{run.runner_name}</small></td><td><span className={`lane lane-${run.lane}`}>{run.lane === "unified" ? "统一" : "原生"}</span></td><td>#{run.repetition}<small>{run.attempt_count > 1 ? `${run.attempt_count} 轮挑战` : "单轮"}</small></td><td>{formatDuration(run.duration_ms)}</td><td>{formatNumber(run.tokens_input + run.tokens_output)}</td><td><Score value={run.score} />{run.objective_score != null && <small className="score-subline">质量 {run.objective_score.toFixed(1)} · 时效 {run.time_score?.toFixed(1) ?? "—"} · T效 {run.token_score?.toFixed(1) ?? "—"}</small>}</td><td><StatusBadge status={run.status} />{run.status === "completed" && run.passed === false && <small className="run-error-preview">能力未及格</small>}{run.error_message && <small className="run-error-preview" title={run.error_message}>{run.error_code ? `${run.error_code} · ` : ""}{run.error_message}</small>}</td></tr>)}</tbody></table></div>
        )}
      </Card>
    </div>
  );
}
