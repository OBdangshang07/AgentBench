import { useState, type FormEvent } from "react";
import { ArrowLeft, Box, Clock3, Coins, FileCode2, Footprints, RefreshCw, Sparkles, Target, Terminal, Timer, Waypoints } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api, downloadUrl } from "../lib/api";
import { formatDate, formatDuration, formatNumber } from "../lib/format";
import { useApi } from "../lib/useApi";
import type { RunDetail } from "../types";
import { Button, Card, ErrorBlock, Field, LoadingBlock, Modal, PageHeader, Score, StatusBadge } from "../components/ui";

const eventNames: Record<string, string> = {
  "run.started": "运行开始",
  "run.environment_ready": "环境已准备",
  "model.requested": "请求模型",
  "model.responded": "模型响应",
  "tool.requested": "调用工具",
  "tool.completed": "工具完成",
  "native_cli.started": "启动原生 Agent",
  "native_cli.event": "Agent 事件",
  "attempt.started": "挑战轮次开始",
  "attempt.completed": "挑战轮次完成",
  "attempt.retry_scheduled": "进入下一轮提示",
  "run.validating": "开始验证",
  "validator.completed": "验证器完成",
  "artifact.created": "产物已记录",
  "judge.completed": "裁判完成",
  "run.completed": "运行完成",
  "run.failed": "运行失败",
};

const dimensionMeta: Record<string, { label: string; description: string; icon: typeof Target }> = {
  objective_quality: { label: "客观质量", description: "格式、内容、产物与隐藏验证", icon: Target },
  judge_quality: { label: "匿名裁判", description: "Rubric 主观质量判断", icon: Sparkles },
  time_efficiency: { label: "完成时效", description: "按本题时间预算归一化", icon: Clock3 },
  step_efficiency: { label: "步骤效率", description: "按 Agent 最大步数归一化", icon: Footprints },
  token_efficiency: { label: "Token 效率", description: "按本题 Token 预算归一化", icon: Coins },
};

const validatorNames: Record<string, string> = {
  exact_match: "精确答案",
  contains: "关键内容",
  regex: "格式规则",
  json_schema: "JSON 结构",
  json_file: "JSON 产物",
  file_exists: "文件存在",
  file_content: "文件内容",
  file_contains: "文件关键内容",
  forbidden_paths: "安全边界",
  command: "隐藏命令验证",
  ai_rubric: "匿名裁判",
  time_efficiency: "完成时效",
  step_efficiency: "步骤效率",
  token_efficiency: "Token 效率",
  efficiency: "旧版步骤效率",
};

export default function RunDetailPage() {
  const { runId = "" } = useParams();
  const state = useApi<RunDetail>(`/runs/${runId}`, 2_000);
  const [reviewing, setReviewing] = useState(false);
  async function retry() { await api(`/runs/${runId}/retry`, { method: "POST" }); await state.refresh(); }
  if (state.loading) return <LoadingBlock />;
  if (state.error || !state.data) return <ErrorBlock message={state.error ?? "运行不存在"} retry={() => void state.refresh()} />;
  const run = state.data;
  const dimensions = run.score_dimensions ?? [];
  const objective = dimensions.find((item) => item.dimension === "objective_quality");
  const time = dimensions.find((item) => item.dimension === "time_efficiency");
  const finalAttempt = run.attempts?.at(-1);
  const costNote = run.cost_source === "reported"
    ? "Agent 实际上报"
    : run.cost_source === "configured"
      ? "按模型单价估算"
      : run.cost_source === "unpriced"
        ? "已统计 Token，待配置单价"
        : "Agent 未提供用量";
  return (
    <div className="page">
      <Link to={`/experiments/${run.experiment_id}`} className="back-link"><ArrowLeft size={16} /> 返回实验</Link>
      <PageHeader eyebrow={`${run.model_name} × ${run.runner_name}`} title={run.test_title} description={`${run.category} · 第 ${run.repetition} 次运行 · ${formatDate(run.created_at)}`} actions={<><Button variant="ghost" onClick={() => setReviewing(true)}>人工复核</Button><Button variant="secondary" onClick={() => void retry()}><RefreshCw size={15} /> 重试运行</Button></>} />
      <div className="run-overview run-detail-overview">
        <Card><span>最终状态</span><StatusBadge status={run.status} /><small>{run.error_code ?? (run.passed === false ? "三轮内未达到及格线" : "流程完整")}</small></Card>
        <Card><span>综合得分</span><Score value={run.score} large /><small>{objective ? `质量 ${objective.score.toFixed(1)} · 时效 ${time?.score.toFixed(1) ?? "—"}${finalAttempt && finalAttempt.multiplier < 1 ? ` · 轮次 ×${finalAttempt.multiplier.toFixed(2)}` : ""}` : `${run.validators.length} 个评分分量`}</small></Card>
        <Card><span>执行耗时</span><strong>{formatDuration(run.duration_ms)}</strong><small><Timer size={13} /> {run.steps} 个 Agent 步骤</small></Card>
        <Card><span>Token / 费用</span><strong>{formatNumber(run.tokens_input + run.tokens_output)}</strong><small>${Number(run.cost_usd ?? 0).toFixed(5)} · {costNote}</small></Card>
      </div>
      {dimensions.length > 0 && <Card className="score-composition-card">
        <div className="card-header"><div><span className="section-kicker">BALANCED SCORE</span><h2>综合评分构成</h2></div><small>质量 94% · 时间 3% · 步骤 2% · Token 1%</small></div>
        <div className="score-dimension-grid">
          {dimensions.map((dimension) => {
            const meta = dimensionMeta[dimension.dimension] ?? { label: dimension.dimension, description: "评分维度", icon: Target };
            const Icon = meta.icon;
            const contribution = dimension.score * dimension.weight / 100;
            return <div className={`score-dimension score-dimension-${dimension.dimension}`} key={dimension.id}>
              <div className="score-dimension-icon"><Icon size={17} /></div><div><span>{meta.label}</span><strong>{dimension.score.toFixed(1)}</strong><small>{meta.description}</small></div><div className="score-contribution"><b>+{contribution.toFixed(2)}</b><small>权重 {dimension.weight.toFixed(1)}%</small></div>
            </div>;
          })}
        </div>
        <div className="score-method-note"><Sparkles size={15} /><span>效率只做轻量区分；即使速度最快、Token 最少，也无法弥补质量失败。Token 未可靠上报时使用中性分，避免统计口径差异造成虚假优势。</span></div>
      </Card>}
      {Boolean(run.attempts?.length) && <Card className="attempt-history-card">
        <div className="card-header"><div><span className="section-kicker">ULTRA ATTEMPTS</span><h2>挑战轮次</h2></div><small>工作区连续保留 · 环境错误不消耗能力机会</small></div>
        <div className="attempt-grid">
          {run.attempts.map((attempt) => <div className={`attempt-card ${attempt.passed ? "attempt-passed" : ""}`} key={attempt.id}>
            <header><div><span>第 {attempt.attempt_no} 轮</span><strong>×{attempt.multiplier.toFixed(2)}</strong></div><StatusBadge status={attempt.passed ? "passed" : attempt.status} /></header>
            <div className="attempt-score-line"><div><span>原始分</span><Score value={attempt.raw_score} /></div><div><span>计入分</span><Score value={attempt.adjusted_score} /></div></div>
            <small>{formatDuration(attempt.duration_ms)} · {attempt.steps} 步 · {formatNumber(attempt.tokens_input + attempt.tokens_output)} Token</small>
            {attempt.error_message && <p className="attempt-error">{attempt.error_code} · {attempt.error_message}</p>}
            {attempt.attempt_no > 1 && <details><summary>查看本轮分级提示</summary><pre>{attempt.prompt}</pre></details>}
          </div>)}
        </div>
      </Card>}
      {run.error_message && <div className="error-banner"><strong>{run.error_code}</strong><span>{run.error_message}</span></div>}
      <div className="run-detail-grid">
        <Card>
          <div className="card-header"><div><span className="section-kicker">TRACE</span><h2>Agent 轨迹</h2></div><Waypoints size={18} /></div>
          <div className="timeline">{run.events.map((event) => <div className="timeline-event" key={event.id}><div className="timeline-dot" /><div className="timeline-card"><header><strong>{eventNames[event.event_type] ?? event.event_type}</strong><span>#{event.seq}</span></header><pre>{JSON.stringify(event.payload, null, 2)}</pre></div></div>)}</div>
        </Card>
        <div className="detail-side">
          <Card>
            <div className="card-header"><div><span className="section-kicker">SCORE EVIDENCE</span><h2>评分证据</h2></div></div>
            <div className="validator-list">{run.validators.map((validator) => <div className="validator-card" key={validator.id}><div><span className="validator-label">{validatorNames[validator.validator_type] ?? validator.validator_type}</span><Score value={validator.score} /></div><div className="weight-bar"><i style={{ width: `${validator.score}%` }} /></div><small>权重 {validator.weight.toFixed(1)}% · {validator.status === "partial" ? "部分达成" : validator.status}</small><details><summary>查看评分证据</summary><pre>{JSON.stringify(validator.evidence, null, 2)}</pre></details></div>)}</div>
          </Card>
          <Card>
            <div className="card-header"><div><span className="section-kicker">DELIVERABLES</span><h2>工作区产物</h2></div><Box size={18} /></div>
            {run.artifacts.length ? <div className="artifact-list">{run.artifacts.map((artifact) => <a key={artifact.id} href={downloadUrl(`/runs/${run.id}/artifacts/${artifact.id}`)}><FileCode2 size={16} /><div><strong>{artifact.path}</strong><span>{formatNumber(artifact.size)} bytes</span></div></a>)}</div> : <div className="inline-empty">没有文件产物</div>}
          </Card>
          <Card>
            <div className="card-header"><div><span className="section-kicker">FINAL</span><h2>最终回答</h2></div><Terminal size={18} /></div>
            <pre className="final-answer">{run.final_answer || "没有最终文本回答"}</pre>
          </Card>
        </div>
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
    try {
      await api(`/runs/${runId}/manual-score`, { method: "POST", body: JSON.stringify({ score: Number(form.get("score")), reason: form.get("reason") }) });
      onSaved();
    } catch (value) { setError(value instanceof Error ? value.message : "复核保存失败"); setBusy(false); }
  }
  return <Modal title="人工复核评分" description="人工分数将作为显式覆盖记录写入审计日志，不会删除原验证证据。" onClose={onClose}><form className="form-grid one-column" onSubmit={(event) => void submit(event)}><Field label="最终分数"><input name="score" type="number" min="0" max="100" step="0.1" defaultValue={currentScore ?? 0} required /></Field><Field label="复核理由"><textarea name="reason" rows={5} minLength={3} required placeholder="说明为什么需要覆盖，以及依据了哪些证据。" /></Field>{error && <div className="form-error">{error}</div>}<div className="modal-actions"><Button type="button" variant="ghost" onClick={onClose}>取消</Button><Button type="submit" busy={busy}>保存复核</Button></div></form></Modal>;
}
