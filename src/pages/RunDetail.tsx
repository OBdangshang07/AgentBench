import { useState, type FormEvent } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight, Copy, FileCode2, FileDown, FileText, FolderOpen, RefreshCw } from "lucide-react";
import { Link, useLocation, useParams } from "react-router-dom";
import { BroadcastFrame } from "../components/BroadcastFrame";
import { LiveRunSession } from "../components/LiveRunView";
import { Button, ErrorBlock, Field, LoadingBlock, Modal } from "../components/ui";
import { api, downloadUrl } from "../lib/api";
import { copyText } from "../lib/clipboard";
import { formatDuration, formatNumber } from "../lib/format";
import { openFolder } from "../lib/openPath";
import { useApi } from "../lib/useApi";
import { useRunEvents } from "../lib/useRunEvents";
import type { RunDetail, RunSummary, ScoreDimension } from "../types";

const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled", "needs_review", "environment_unavailable", "interrupted"]);

const eventNames: Record<string, string> = {
  "run.started": "初始化隔离工作区", "run.environment_ready": "环境已准备", "model.requested": "请求模型", "model.responded": "模型响应", "tool.requested": "调用工具", "tool.completed": "工具完成", "native_cli.started": "启动原生 Agent", "native_cli.event": "Agent 事件", "attempt.started": "挑战轮次开始", "attempt.completed": "挑战轮次完成", "attempt.retry_scheduled": "进入下一轮提示", "run.validating": "开始验证", "validator.completed": "验证器完成", "artifact.created": "产物已记录", "judge.completed": "匿名裁判完成", "run.completed": "运行完成", "run.failed": "运行失败",
};

const dimensionNames: Record<string, { label: string; note: string }> = {
  objective_quality: { label: "客观质量", note: "确定性与私有验证" }, judge_quality: { label: "匿名裁判", note: "Rubric 得分点" }, time_efficiency: { label: "时间效率", note: "及格线后轻量修正" }, step_efficiency: { label: "步骤效率", note: "轮次与工具调用" }, token_efficiency: { label: "Token 效率", note: "总上下文消耗" },
};

const validatorNames: Record<string, string> = {
  exact_match: "精确答案", contains: "关键内容", regex: "格式规则", json_schema: "JSON 结构", json_file: "JSON 产物", symbolic_json: "结构化数学答案", file_exists: "文件存在", file_content: "文件内容", file_contains: "文件关键内容", forbidden_paths: "安全边界", command: "隐藏命令验证", command_metrics: "私有指标验证", ai_rubric: "匿名裁判", time_efficiency: "完成时效", step_efficiency: "步骤效率", token_efficiency: "Token 效率", efficiency: "旧版步骤效率",
};

function evidenceText(evidence: Record<string, unknown>) {
  for (const key of ["summary", "reason", "detail", "message"]) {
    const value = evidence[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  const visible = Object.entries(evidence).find(([, value]) => typeof value === "string" || typeof value === "number" || typeof value === "boolean");
  return visible ? `${visible[0]} = ${String(visible[1])}` : "隐藏数据仅展示评分结论，不泄露答案";
}

function pickDimensions(dimensions: ScoreDimension[], run: RunDetail) {
  const fallback: ScoreDimension[] = [
    { id: "objective", dimension: "objective_quality", score: run.objective_score ?? run.score ?? 0, weight: 94, evidence: {} },
    { id: "time", dimension: "time_efficiency", score: run.time_score ?? 100, weight: 3, evidence: {} },
    { id: "step", dimension: "step_efficiency", score: run.step_score ?? 100, weight: 2, evidence: {} },
    { id: "token", dimension: "token_efficiency", score: run.token_score ?? 100, weight: 1, evidence: {} },
  ];
  return (dimensions.length ? dimensions : fallback).slice(0, 4);
}

export default function RunDetailPage() {
  const { runId = "" } = useParams();
  const location = useLocation();
  const state = useApi<RunDetail>(`/runs/${runId}`, (run) => (run && TERMINAL_RUN_STATUSES.has(run.status) ? 0 : 2_000));
  const siblings = useApi<RunSummary[]>(state.data ? `/runs?experiment_id=${state.data.experiment_id}&limit=1000` : null, state.data && !TERMINAL_RUN_STATUSES.has(state.data.status) ? 2_000 : 0);
  const active = Boolean(state.data && !TERMINAL_RUN_STATUSES.has(state.data.status));
  const live = useRunEvents(runId, state.data?.events ?? [], active);
  const [reviewing, setReviewing] = useState(false);
  const [workspaceHint, setWorkspaceHint] = useState("");
  async function retry() { await api(`/runs/${runId}/retry`, { method: "POST" }); await state.refresh(); }
  if (state.loading) return <LoadingBlock />;
  if (state.error || !state.data) return <ErrorBlock message={state.error ?? "运行不存在"} retry={() => void state.refresh()} />;
  const run = state.data;
  const routeState = location.state as { from?: string } | null;
  const backTo = routeState?.from ?? `/experiments/${run.experiment_id}`;
  const orderedSiblings = [...(siblings.data ?? [])].sort((left, right) => {
    const leftNumber = Number(left.test_title.match(/第\s*(\d+)\s*题/)?.[1] ?? Number.MAX_SAFE_INTEGER);
    const rightNumber = Number(right.test_title.match(/第\s*(\d+)\s*题/)?.[1] ?? Number.MAX_SAFE_INTEGER);
    return leftNumber - rightNumber || left.created_at.localeCompare(right.created_at);
  });
  const siblingIndex = orderedSiblings.findIndex((item) => item.id === run.id);
  const previousRun = siblingIndex > 0 ? orderedSiblings[siblingIndex - 1] : undefined;
  const nextRun = siblingIndex >= 0 && siblingIndex < orderedSiblings.length - 1 ? orderedSiblings[siblingIndex + 1] : undefined;
  const previousTo = previousRun ? `/runs/${previousRun.id}` : undefined;
  const nextTo = nextRun ? `/runs/${nextRun.id}` : undefined;
  if (active) return <BroadcastFrame backTo={backTo} previousTo={previousTo} nextTo={nextTo}><div className="live-run-page"><LiveRunSession run={run} events={live.events} streamState={live.streamState} /></div></BroadcastFrame>;

  const dimensions = pickDimensions(run.score_dimensions ?? [], run);
  const attempts = run.attempts?.length ? run.attempts : [];
  const passedAttempt = attempts.find((item) => item.passed) ?? attempts.at(-1);
  const eventTrace = run.events.filter((event) => ["run.started", "attempt.started", "attempt.completed", "attempt.retry_scheduled", "run.validating", "judge.completed", "run.completed", "run.failed"].includes(event.event_type)).slice(-6);
  const questionInstruction = run.test_definition?.instruction?.trim() ?? "";
  const materials = run.materials ?? [];
  const showQuestion = Boolean(questionInstruction) || materials.length > 0;

  function flash(text: string) { setWorkspaceHint(text); window.setTimeout(() => setWorkspaceHint(""), 1800); }

  return (
    <div className="ab-view ab-evidence-view">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">04 / EVIDENCE</span><div><h1>证据账本</h1><p>从最终分数追溯到轮次、验证义务、裁判理由和工作区产物。</p></div></div>
        <div className="ab-header-meta"><Link className="ab-ghost-button" to={backTo}><ArrowLeft size={13} />返回实验</Link><Link className={`ab-ghost-button${!previousTo ? " disabled" : ""}`} to={previousTo ?? backTo} state={{ from: backTo }} aria-disabled={!previousTo}><ChevronLeft size={13} />上一题</Link><Link className={`ab-ghost-button${!nextTo ? " disabled" : ""}`} to={nextTo ?? backTo} state={{ from: backTo }} aria-disabled={!nextTo}>下一题<ChevronRight size={13} /></Link><span className="ab-meta-pill">RUN / {run.id.slice(0, 8)}</span>{run.workspace_path && <button className="ab-ghost-button" type="button" onClick={() => void openFolder(run.workspace_path!)}><FolderOpen size={13} />打开工作区</button>}<a className="ab-ghost-button" href={downloadUrl(`/experiments/${run.experiment_id}/export?format=html`)}><FileDown size={13} />导出报告</a></div>
      </header>

      <div className="ab-run-layout">
        <aside className="ab-attempt-pane">
          <div className="ab-run-id"><code>{run.category.toUpperCase()} / {run.id.slice(0, 8).toUpperCase()}</code><h3>{run.test_title}</h3><span>{run.model_name} × {run.runner_name}</span></div>
          <div className="ab-pane-label">ATTEMPT TRACE</div>
          {attempts.length ? attempts.map((attempt) => <div className={`ab-attempt${attempt.passed ? " pass" : ""}`} key={attempt.id}><strong>ROUND {String(attempt.attempt_no).padStart(2, "0")}</strong><p>{attempt.attempt_no === 1 ? "原始题面与公开 checker" : `第 ${attempt.attempt_no} 轮分级提示，质量上限 ×${attempt.multiplier.toFixed(2)}`}</p><span>{attempt.adjusted_score?.toFixed(1) ?? "—"} · {attempt.passed ? "PASSED" : attempt.status.toUpperCase()}</span></div>) : <div className={`ab-attempt${run.passed ? " pass" : ""}`}><strong>ROUND 01</strong><p>单轮任务与公开题面</p><span>{run.score?.toFixed(1) ?? "—"} · {run.passed ? "PASSED" : run.status.toUpperCase()}</span></div>}
          <div className="ab-outline-group"><div className="ab-pane-label">SECTIONS</div><button className="ab-outline-button active" type="button">评分构成</button><button className="ab-outline-button" type="button">验证义务</button><button className="ab-outline-button" type="button">执行事件</button><button className="ab-outline-button" type="button">产物与日志</button></div>
          <div className="ab-attempt-actions"><button type="button" onClick={() => setReviewing(true)}>人工复核</button><button type="button" onClick={() => void retry()}><RefreshCw size={11} />重试运行</button><Link to={backTo}><ArrowLeft size={11} />返回实验</Link></div>
        </aside>

        <section className="ab-evidence-canvas">
          <div className="ab-score-hero"><div><div className="ab-big-score"><strong>{run.score?.toFixed(1) ?? "—"}</strong><span>/ 100</span></div><div className="ab-score-caption"><b>第 {Math.max(1, passedAttempt?.attempt_no ?? run.attempt_count)} 轮{run.passed ? "通过" : "完成"}</b> · 原始质量 {passedAttempt?.raw_score?.toFixed(1) ?? run.objective_score?.toFixed(1) ?? "—"}{passedAttempt && passedAttempt.multiplier < 1 ? " · 轮次折扣后" : " · 证据已固化"}</div></div><div className="ab-score-stack">{dimensions.map((dimension) => { const meta = dimensionNames[dimension.dimension] ?? { label: dimension.dimension, note: "评分维度" }; return <div className="ab-score-part" key={dimension.id}><label>{meta.label} · {dimension.weight.toFixed(0)}%</label><strong>{dimension.score.toFixed(1)}</strong><small>{meta.note}</small><i className="ab-vertical-meter"><i style={{ height: `${Math.max(0, Math.min(100, dimension.score))}%` }} /></i></div>; })}</div></div>
          <div className="ab-proof-ledger"><div className="ab-ledger-title"><h3>验证义务 / PROOF OBLIGATIONS</h3><span>隐藏数据仅展示摘要，不泄露答案</span></div>{run.validators.length ? run.validators.map((validator, index) => <div className="ab-proof-item" key={validator.id}><i className="ab-proof-index">{String(index + 1).padStart(2, "0")}</i><div className="ab-proof-copy"><strong>{validatorNames[validator.validator_type] ?? validator.validator_type}</strong><small>{evidenceText(validator.evidence)}</small></div><code className="ab-proof-evidence">status = {validator.status}</code><b className="ab-proof-score">{validator.score.toFixed(1)} / 100</b></div>) : <div className="ab-proof-empty">这条历史运行没有独立验证器记录，最终分数来自兼容评分路径。</div>}</div>
          {showQuestion && <section className="ab-question-evidence"><div className="ab-ledger-title"><h3>题目 / <span>EXAM QUESTION</span></h3><span>本次运行收到的公开任务</span></div>{questionInstruction && <pre>{questionInstruction}</pre>}{materials.length > 0 && <div className="ab-materials">{materials.map((material) => <a key={material.name} href={downloadUrl(`/runs/${run.id}/materials/${encodeURIComponent(material.name)}`)}><FileText size={13} /><span>{material.name}</span><b>{formatNumber(material.size_bytes)} bytes</b></a>)}</div>}</section>}
        </section>

        <aside className="ab-context-pane">
          <section className="ab-context-block"><label>EXECUTION COST</label><div className="ab-cost-grid"><div><span>总用时</span><strong>{formatDuration(run.duration_ms)}</strong></div><div><span>轮次</span><strong>{Math.max(1, run.attempt_count)} / {Math.max(1, attempts.length || run.attempt_count)}</strong></div><div><span>输入 Token</span><strong>{formatNumber(run.tokens_input)}</strong></div><div><span>输出 Token</span><strong>{formatNumber(run.tokens_output)}</strong></div></div></section>
          <section className="ab-context-block"><label>EVENT TRACE</label>{eventTrace.length ? eventTrace.map((event) => <div className={`ab-context-event${event.event_type.includes("failed") || event.event_type.includes("retry") ? " warn" : ""}`} key={event.id}><strong>{eventNames[event.event_type] ?? event.event_type}</strong><span>{typeof event.payload.summary === "string" ? event.payload.summary : `EVENT #${event.seq}`}</span></div>) : <div className="ab-muted">没有结构化事件记录</div>}</section>
          <section className="ab-context-block"><label>ARTIFACTS</label>{run.artifacts.length ? run.artifacts.slice(0, 6).map((artifact) => <a className="ab-artifact-row" key={artifact.id} href={downloadUrl(`/runs/${run.id}/artifacts/${artifact.id}`)}><FileCode2 size={13} /><span>{artifact.path} · {formatNumber(artifact.size)} B</span><b>查看</b></a>) : <div className="ab-muted">没有文件产物</div>}</section>
          {run.final_answer && <section className="ab-context-block"><label>FINAL ANSWER</label><pre className="ab-final-answer">{run.final_answer}</pre></section>}
          {run.workspace_path && <section className="ab-context-block"><label>WORKSPACE</label><code className="ab-workspace-path">{run.workspace_path}</code><button className="ab-mini-button wide" type="button" onClick={() => void copyText(run.workspace_path!).then((ok) => flash(ok ? "已复制" : "复制失败"))}><Copy size={11} />复制路径</button>{workspaceHint && <span className="ab-copy-hint">{workspaceHint}</span>}</section>}
        </aside>
      </div>
      {reviewing && <ReviewModal runId={run.id} currentScore={run.score} onClose={() => setReviewing(false)} onSaved={() => { setReviewing(false); void state.refresh(); }} />}
    </div>
  );
}

function ReviewModal({ runId, currentScore, onClose, onSaved }: { runId: string; currentScore?: number | null; onClose: () => void; onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    try { await api(`/runs/${runId}/manual-score`, { method: "POST", body: JSON.stringify({ score: Number(form.get("score")), reason: form.get("reason") }) }); onSaved(); }
    catch (value) { setError(value instanceof Error ? value.message : "复核保存失败"); setBusy(false); }
  }
  return <Modal title="人工复核评分" description="人工分数将作为显式覆盖记录写入审计日志，不会删除原验证证据。" onClose={onClose}><form className="form-grid one-column" onSubmit={(event) => void submit(event)}><Field label="最终分数"><input name="score" type="number" min="0" max="100" step="0.1" defaultValue={currentScore ?? 0} required /></Field><Field label="复核理由"><textarea name="reason" rows={5} minLength={3} required placeholder="说明覆盖依据。" /></Field>{error && <div className="form-error">{error}</div>}<div className="modal-actions"><Button type="button" variant="ghost" onClick={onClose}>取消</Button><Button type="submit" busy={busy}>保存复核</Button></div></form></Modal>;
}
