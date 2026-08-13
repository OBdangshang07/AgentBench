import { useState, type FormEvent } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight, Copy, ExternalLink, FileCode2, FileDown, FileImage, FileText, FolderOpen, Play, RefreshCw, Upload } from "lucide-react";
import { Link, useLocation, useParams } from "react-router-dom";
import { BroadcastFrame } from "../components/BroadcastFrame";
import { LiveRunSession } from "../components/LiveRunView";
import { Button, ErrorBlock, Field, LoadingBlock, Modal } from "../components/ui";
import { api, apiUpload, downloadUrl } from "../lib/api";
import { copyText } from "../lib/clipboard";
import { formatDuration, formatNumber } from "../lib/format";
import { useOpenFolder } from "../lib/useOpenFolder";
import { useApi } from "../lib/useApi";
import { useRunEvents } from "../lib/useRunEvents";
import type { ManualRubric, ManualReview, RunDetail, RunSummary, ScoreDimension } from "../types";

const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled", "needs_review", "environment_unavailable", "interrupted"]);

const eventNames: Record<string, string> = {
  "run.started": "初始化隔离工作区", "run.environment_ready": "环境已准备", "model.requested": "请求模型", "model.responded": "模型响应", "tool.requested": "调用工具", "tool.completed": "工具完成", "native_cli.started": "启动原生 Agent", "native_cli.event": "Agent 事件", "attempt.started": "挑战轮次开始", "attempt.completed": "挑战轮次完成", "attempt.retry_scheduled": "进入下一轮提示", "run.validating": "开始验证", "validator.completed": "验证器完成", "artifact.created": "产物已记录", "judge.completed": "匿名裁判完成", "run.completed": "运行完成", "run.failed": "运行失败",
};

const dimensionNames: Record<string, { label: string; note: string }> = {
  objective_quality: { label: "客观质量", note: "确定性与私有验证" }, judge_quality: { label: "匿名裁判", note: "Rubric 得分点" }, manual_quality: { label: "人工质量", note: "用户提交的逐项量表" }, time_efficiency: { label: "时间效率", note: "及格线后轻量修正" }, step_efficiency: { label: "步骤效率", note: "轮次与工具调用" }, token_efficiency: { label: "Token 效率", note: "总上下文消耗" },
};

const validatorNames: Record<string, string> = {
  exact_match: "精确答案", contains: "关键内容", regex: "格式规则", json_schema: "JSON 结构", json_file: "JSON 产物", symbolic_json: "结构化数学答案", file_exists: "文件存在", file_content: "文件内容", file_contains: "文件关键内容", forbidden_paths: "安全边界", command: "隐藏命令验证", command_metrics: "私有指标验证", ai_rubric: "匿名裁判", manual_rubric: "人工评分量表", time_efficiency: "完成时效", step_efficiency: "步骤效率", token_efficiency: "Token 效率", efficiency: "旧版步骤效率",
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
  const openWorkspace = useOpenFolder();
  const [reviewing, setReviewing] = useState(false);
  const [previewError, setPreviewError] = useState("");
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
  async function previewFrontend() {
    setPreviewError("");
    try {
      const result = await api<{ url: string }>(`/runs/${run.id}/frontend-preview`, { method: "POST", body: JSON.stringify({ allow_project_scripts: false }) });
      window.open(result.url, "_blank", "noopener,noreferrer");
    } catch (error) { setPreviewError(error instanceof Error ? error.message : "作品暂时无法预览"); }
  }

  return (
    <div className="ab-view ab-evidence-view">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">04 / EVIDENCE</span><div><h1>{run.frontend ? "作品评审台" : "证据账本"}</h1><p>{run.frontend ? "预览 AI 的实际交付，逐项完成人工量表并保留评审证据。" : "从最终分数追溯到轮次、验证义务、裁判理由和工作区产物。"}</p></div></div>
        <div className="ab-header-meta"><Link className="ab-ghost-button" to={backTo}><ArrowLeft size={13} />返回实验</Link><Link className={`ab-ghost-button${!previousTo ? " disabled" : ""}`} to={previousTo ?? backTo} state={{ from: backTo }} aria-disabled={!previousTo}><ChevronLeft size={13} />上一题</Link><Link className={`ab-ghost-button${!nextTo ? " disabled" : ""}`} to={nextTo ?? backTo} state={{ from: backTo }} aria-disabled={!nextTo}>下一题<ChevronRight size={13} /></Link><span className="ab-meta-pill">RUN / {run.id.slice(0, 8)}</span>{run.frontend && <button className="ab-ghost-button" type="button" onClick={() => void previewFrontend()}><Play size={13} />预览作品</button>}{run.workspace_path && <button className="ab-ghost-button" type="button" onClick={() => void openWorkspace(run.workspace_path!, "工作区")}><FolderOpen size={13} />打开工作区</button>}<a className="ab-ghost-button" href={downloadUrl(`/experiments/${run.experiment_id}/export?format=html`)}><FileDown size={13} />导出报告</a></div>
      </header>

      <div className="ab-run-layout">
        <aside className="ab-attempt-pane">
          <div className="ab-run-id"><code>{run.category.toUpperCase()} / {run.id.slice(0, 8).toUpperCase()}</code><h3>{run.test_title}</h3><span>{run.model_name} × {run.runner_name}</span></div>
          <div className="ab-pane-label">ATTEMPT TRACE</div>
          {attempts.length ? attempts.map((attempt) => <div className={`ab-attempt${attempt.passed ? " pass" : ""}`} key={attempt.id}><strong>ROUND {String(attempt.attempt_no).padStart(2, "0")}</strong><p>{attempt.attempt_no === 1 ? "原始题面与公开 checker" : `第 ${attempt.attempt_no} 轮分级提示，质量上限 ×${attempt.multiplier.toFixed(2)}`}</p><span>{attempt.adjusted_score?.toFixed(1) ?? "—"} · {attempt.passed ? "PASSED" : attempt.status.toUpperCase()}</span></div>) : <div className={`ab-attempt${run.passed ? " pass" : ""}`}><strong>ROUND 01</strong><p>单轮任务与公开题面</p><span>{run.score?.toFixed(1) ?? "—"} · {run.passed ? "PASSED" : run.status.toUpperCase()}</span></div>}
          <div className="ab-outline-group"><div className="ab-pane-label">SECTIONS</div><button className="ab-outline-button active" type="button">评分构成</button><button className="ab-outline-button" type="button">验证义务</button><button className="ab-outline-button" type="button">执行事件</button><button className="ab-outline-button" type="button">产物与日志</button></div>
          <div className="ab-attempt-actions"><button type="button" onClick={() => setReviewing(true)}>{run.frontend ? run.frontend.review?.status === "submitted" ? "修改人工评分" : "开始人工评分" : "人工复核"}</button><button type="button" onClick={() => void retry()}><RefreshCw size={11} />重试运行</button><Link to={backTo}><ArrowLeft size={11} />返回实验</Link></div>
        </aside>

        <section className="ab-evidence-canvas">
          <div className="ab-score-hero"><div><div className="ab-big-score"><strong>{run.score?.toFixed(1) ?? "—"}</strong><span>/ 100</span></div><div className="ab-score-caption">{run.frontend ? <><b>{run.frontend.review?.status === "submitted" ? "人工评分已提交" : run.frontend.review?.status === "draft" ? "人工评分草稿" : "等待人工评分"}</b> · 难度 {run.frontend.difficulty >= 6 ? "ULTRA" : `D${run.frontend.difficulty}`} · 未评分不计 0 分</> : <><b>第 {Math.max(1, passedAttempt?.attempt_no ?? run.attempt_count)} 轮{run.passed ? "通过" : "完成"}</b> · 原始质量 {passedAttempt?.raw_score?.toFixed(1) ?? run.objective_score?.toFixed(1) ?? "—"}{passedAttempt && passedAttempt.multiplier < 1 ? " · 轮次折扣后" : " · 证据已固化"}</>}</div></div>{!run.frontend && <div className="ab-score-stack">{dimensions.map((dimension) => { const meta = dimensionNames[dimension.dimension] ?? { label: dimension.dimension, note: "评分维度" }; return <div className="ab-score-part" key={dimension.id}><label>{meta.label} · {dimension.weight.toFixed(0)}%</label><strong>{dimension.score.toFixed(1)}</strong><small>{meta.note}</small><i className="ab-vertical-meter"><i style={{ height: `${Math.max(0, Math.min(100, dimension.score))}%` }} /></i></div>; })}</div>}</div>
          {previewError && <div className="error-banner"><strong>预览不可用</strong><span>{previewError}</span></div>}
          {run.frontend && <section className="frontend-source-ledger"><div><span>FIXED SOURCE</span><strong>{run.frontend.source_path}</strong><code>{run.frontend.source_commit}</code></div><a href={run.frontend.source_repository} target="_blank" rel="noreferrer"><ExternalLink size={12} />来源仓库</a></section>}
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
      {reviewing && (run.frontend ? <ManualRubricModal runId={run.id} rubric={run.frontend.rubric} review={run.frontend.review} onClose={() => setReviewing(false)} onSaved={() => { setReviewing(false); void state.refresh(); }} /> : <ReviewModal runId={run.id} currentScore={run.score} onClose={() => setReviewing(false)} onSaved={() => { setReviewing(false); void state.refresh(); }} />)}
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

function ManualRubricModal({ runId, rubric, review, onClose, onSaved }: { runId: string; rubric: ManualRubric; review?: ManualReview | null; onClose: () => void; onSaved: () => void }) {
  const [scores, setScores] = useState<Record<string, number>>(review?.dimension_scores ?? {});
  const [checks, setChecks] = useState<Record<string, boolean>>(review?.checklist ?? {});
  const [defects, setDefects] = useState<string[]>(review?.critical_defects ?? []);
  const [reviewer, setReviewer] = useState(review?.reviewer ?? "本机用户");
  const [comment, setComment] = useState(review?.comment ?? "");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [evidence, setEvidence] = useState(review?.evidence ?? []);
  const [error, setError] = useState("");
  const total = rubric.dimensions.reduce((sum, item) => sum + Number(scores[item.key] ?? 0), 0);
  const effective = defects.length ? Math.min(total, 59) : total;
  const payload = { reviewer, dimension_scores: scores, checklist: checks, critical_defects: defects, comment };
  async function save(submit: boolean) {
    setBusy(true); setError("");
    try {
      await api(`/runs/${runId}/manual-review/${submit ? "submit" : "draft"}`, { method: submit ? "POST" : "PUT", body: JSON.stringify(payload) });
      onSaved();
    } catch (value) { setError(value instanceof Error ? value.message : "人工评分保存失败"); setBusy(false); }
  }
  async function uploadEvidence(file?: File) {
    if (!file) return;
    setUploading(true); setError("");
    try {
      const updated = await apiUpload<ManualReview>(`/runs/${runId}/manual-review/evidence?filename=${encodeURIComponent(file.name)}`, file, file.type || "application/octet-stream");
      setEvidence(updated.evidence ?? []);
    } catch (value) { setError(value instanceof Error ? value.message : "截图证据上传失败"); }
    finally { setUploading(false); }
  }
  return <Modal title="前端作品人工评分" description={`Rubric ${rubric.version} · 最终成绩只来自本次人工评审；严重缺陷会将总分上限限制为 59 分。`} onClose={onClose}>
    <div className="manual-rubric-form">
      <div className="manual-rubric-total"><div><span>当前合计</span><strong>{effective.toFixed(1)}</strong><small>/ 100{defects.length ? " · 严重缺陷上限生效" : ""}</small></div><label><span>评分者</span><input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label></div>
      <section className="manual-rubric-dimensions">{rubric.dimensions.map((item) => <label key={item.key}><span><strong>{item.label}</strong><small>{item.criteria}</small></span><input type="number" min="0" max={item.max_score} step="0.5" value={scores[item.key] ?? ""} placeholder={`0–${item.max_score}`} onChange={(event) => setScores((current) => ({ ...current, [item.key]: Math.min(item.max_score, Math.max(0, Number(event.target.value))) }))} /><i>/ {item.max_score}</i></label>)}</section>
      <section className="manual-rubric-checklist"><header><strong>验收清单</strong><span>辅助核对，不自动换算分数</span></header>{rubric.checklist.map((item) => <label key={item.key}><input type="checkbox" checked={Boolean(checks[item.key])} onChange={(event) => setChecks((current) => ({ ...current, [item.key]: event.target.checked }))} /><span>{item.label}</span></label>)}</section>
      <section className="manual-rubric-defects"><header><strong>严重缺陷 / 红线</strong><span>勾选后总分最高 59</span></header>{rubric.critical_defects.map((item) => <label key={item.key}><input type="checkbox" checked={defects.includes(item.key)} onChange={(event) => setDefects((current) => event.target.checked ? [...current, item.key] : current.filter((value) => value !== item.key))} /><span>{item.label}</span></label>)}</section>
      <section className="manual-rubric-evidence"><header><div><strong>截图证据</strong><span>PNG / JPG / WEBP，单张不超过 12 MB</span></div><label className="ab-ghost-button"><Upload size={12} />{uploading ? "上传中…" : "添加截图"}<input type="file" accept="image/png,image/jpeg,image/webp" disabled={uploading} onChange={(event) => { void uploadEvidence(event.target.files?.[0]); event.currentTarget.value = ""; }} /></label></header>{evidence.length ? <div>{evidence.map((item) => <a key={item.path} href={downloadUrl(`/runs/${runId}/manual-review/evidence/${encodeURIComponent(item.path)}`)} target="_blank" rel="noreferrer"><FileImage size={13} /><span>{item.name}</span><small>{formatNumber(item.size)} B</small></a>)}</div> : <p>还没有截图证据。可上传关键画面、异常状态或完成效果，便于之后复核。</p>}</section>
      <label className="manual-rubric-comment"><span>评语与扣分依据</span><textarea rows={4} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="记录作品优点、缺陷、复现方式和人工判断依据。" /></label>
      {error && <div className="form-error">{error}</div>}
      <div className="modal-actions"><Button type="button" variant="ghost" onClick={onClose}>取消</Button><Button type="button" variant="secondary" busy={busy} onClick={() => void save(false)}>保存草稿</Button><Button type="button" busy={busy} disabled={rubric.dimensions.some((item) => scores[item.key] == null)} onClick={() => void save(true)}>确认提交评分</Button></div>
    </div>
  </Modal>;
}
