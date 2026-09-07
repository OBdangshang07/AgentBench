import { ArrowRight, FlaskConical } from "lucide-react";
import { Link } from "react-router-dom";
import { ErrorBlock, LoadingBlock, StatusBadge } from "../components/ui";
import { useApi } from "../lib/useApi";
import { formatDate } from "../lib/format";
import type { Experiment, RunSummary } from "../types";

const terminal = new Set(["completed", "failed", "blocked", "cancelled", "canceled", "interrupted"]);
const active = new Set(["running", "queued", "paused", "pausing"]);

export function EvaluationOverview({ experiments, loading, error, retry }: { experiments: Experiment[] | null; loading: boolean; error: string | null; retry: () => void }) {
  const sorted = [...(experiments ?? [])].sort((a,b) => b.created_at.localeCompare(a.created_at));
  const experiment = sorted.find(item => active.has(item.status)) ?? sorted[0];
  const runs = useApi<RunSummary[]>(experiment ? `/runs?experiment_id=${encodeURIComponent(experiment.id)}&limit=1000` : null, 4_000);
  const total = experiment?.run_count ?? 0;
  const finished = experiment?.finished_count ?? 0;
  const participants = new Map<string, { label: string; total: number; finished: number }>();
  for (const run of runs.data ?? []) {
    const key = `${run.runner_id}/${run.model_id}`;
    const row = participants.get(key) ?? { label: `${run.runner_name} · ${run.model_name}`, total: 0, finished: 0 };
    row.total += 1;
    if (terminal.has(run.status)) row.finished += 1;
    participants.set(key,row);
  }
  return <section className="v4-panel">
    <header className="v4-panel-head"><strong><span className="fn-section-number">01</span>{experiment && active.has(experiment.status) ? "进行中的评测" : "最近评测"}</strong><Link to="/experiments">全部记录 <ArrowRight size={14} /></Link></header>
    {loading && !experiments ? <LoadingBlock /> : error ? <ErrorBlock message={error} retry={retry} /> : experiment ? <>
      <div className="fn-run-feature"><StatusBadge status={experiment.status} /><h2>{experiment.name}</h2><p>{experiment.suite_name}</p><div className="fn-run-meta"><span>{experiment.participants.length} 组参测对象</span><span>{experiment.repetitions} 次重复</span><span>并发 {experiment.concurrency}</span></div>
        <div className="fn-run-progress"><div className="fn-progress-caption"><span>测试进度</span><span>{finished} / {total}</span></div><Segments finished={finished} total={total} />
          {runs.error ? <p role="status">参测进度暂时不可用 <button type="button" className="text-link" onClick={() => void runs.refresh()}>重试</button></p> : Array.from(participants.entries()).map(([key,row])=><div className="fn-participant-progress" key={key}><strong title={row.label}>{row.label}</strong><Segments finished={row.finished} total={row.total} /><span>{row.finished} / {row.total}</span></div>)}
          {total > (runs.data?.length ?? 0) && !runs.loading && !runs.error && <p>下方参测明细显示已读取的 {runs.data?.length ?? 0} 项测试；总进度以评测记录为准。</p>}
        </div>
      </div><footer className="fn-panel-foot"><span>{formatDate(experiment.created_at)}</span><Link to={`/experiments/${experiment.id}`}>打开评测详情 <ArrowRight size={14} /></Link></footer>
    </> : <div className="v4-empty"><FlaskConical size={26} /><strong>准备开始第一次评测</strong><span>选择一组真实任务，建立 Agent 的能力档案。</span><Link className="v4-button primary" to="/experiments?create=1">新建评测 <ArrowRight size={14} /></Link></div>}
  </section>;
}

function Segments({ finished, total }: { finished: number; total: number }) {
  const percent = total ? Math.min(100, Math.round(finished / total * 100)) : 0;
  return <div className="fn-segments" role="progressbar" aria-label="测试完成进度" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>{Array.from({length:20},(_,i)=><i key={i} className={i < Math.floor(percent / 5) ? "filled" : ""} />)}</div>;
}
