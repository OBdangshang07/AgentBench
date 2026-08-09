import { BarChart3, Check, Clock3, Coins, Medal, ShieldCheck, Trophy } from "lucide-react";
import { useState } from "react";
import { ErrorBlock, LoadingBlock } from "../components/ui";
import { formatDuration, formatNumber } from "../lib/format";
import { useApi } from "../lib/useApi";
import type { LeaderboardRow } from "../types";

export default function Leaderboard() {
  const [lane, setLane] = useState<"unified" | "native">("unified");
  const state = useApi<LeaderboardRow[]>(`/leaderboard?lane=${lane}`, 5_000);
  const rows = state.data ?? [];
  const samples = rows.reduce((sum, row) => sum + row.runs, 0);
  const totalCost = rows.reduce((sum, row) => sum + row.total_cost, 0);
  return (
    <div className="ab-view ab-ledger-index-view">
      <header className="ab-view-header"><div className="ab-view-title"><span className="ab-view-index">04 / EVIDENCE</span><div><h1>证据索引</h1><p>聚合后的能力榜与原始运行账本分离；赛道、样本量和评分构成始终可见。</p></div></div><div className="ab-header-meta"><span className="ab-meta-pill"><i />{samples} SCORED RUNS</span><span className="ab-meta-pill">${totalCost.toFixed(3)} COST</span></div></header>
      <div className="ab-ledger-index-layout">
        <aside className="ab-lane-pane"><div className="ab-pane-label">COMPARISON LANES</div><button className={lane === "unified" ? "active" : ""} type="button" onClick={() => setLane("unified")}><span><BarChart3 size={14} /></span><div><strong>统一 Agent 模型榜</strong><small>固定 Harness，仅替换模型</small></div></button><button className={lane === "native" ? "active" : ""} type="button" onClick={() => setLane("native")}><span><ShieldCheck size={14} /></span><div><strong>原生 Agent 系统榜</strong><small>Runner 与模型整体计分</small></div></button><div className="ab-lane-note"><strong>FAIR COMPARISON</strong><p>两条赛道绝不混排。模型能力与 Agent 产品能力分别建立证据。</p></div></aside>
        <section className="ab-ranking-canvas"><div className="ab-ranking-hero"><div><span>{lane === "unified" ? "BASE MODEL CAPABILITY" : "NATIVE AGENT SYSTEM"}</span><h2>{lane === "unified" ? "基础模型能力" : "完整 Agent 系统能力"}</h2><p>{lane === "unified" ? "统一工具、上下文与执行协议。" : "提示、工具、Runner 与模型作为一个系统。"}</p></div><Trophy size={34} /></div>{state.loading ? <LoadingBlock /> : state.error ? <ErrorBlock message={state.error} retry={() => void state.refresh()} /> : rows.length ? <div className="ab-ranking-table"><div className="ab-ranking-columns"><span>RANK / PARTICIPANT</span><span>RUNS</span><span>QUALITY</span><span>SUCCESS</span><span>TIME</span><span>TOKEN</span><span>COST</span></div>{rows.map((row, index) => <div className="ab-ranking-row" key={`${row.model_id}-${row.runner_id}`}><div className="ab-rank-model"><i>{index < 3 ? <Medal size={14} /> : index + 1}</i><span><strong>{row.model_name}</strong><small>{row.runner_name}</small></span></div><b>{row.runs}</b><strong className="ab-ranking-score">{row.avg_score.toFixed(1)}</strong><span>{row.success_rate.toFixed(0)}%</span><span>{formatDuration(row.avg_duration_ms)}<small>{row.avg_time_score?.toFixed(1) ?? "—"}</small></span><span>{formatNumber(row.avg_tokens)}<small>{row.avg_token_score?.toFixed(1) ?? "—"}</small></span><span>${row.total_cost.toFixed(3)}</span></div>)}</div> : <div className="ab-case-empty">该赛道还没有已完成的评分数据。</div>}</section>
        <aside className="ab-ranking-context"><section><label>SCORING CONTRACT</label><div className="ab-contract-score"><strong>94</strong><span>% QUALITY</span></div><p>综合分以任务完成质量为主，效率维度只做轻量修正。</p></section><section><label>WEIGHT MAP</label><div className="ab-weight-row"><ShieldCheck size={13} /><span>客观 / 裁判质量</span><b>94%</b></div><div className="ab-weight-row"><Clock3 size={13} /><span>完成时间</span><b>3%</b></div><div className="ab-weight-row"><Check size={13} /><span>Agent 步数</span><b>2%</b></div><div className="ab-weight-row"><Coins size={13} /><span>Token 消耗</span><b>1%</b></div></section><section><label>AUDIT RULES</label><ul><li>低区分度题目独立标记</li><li>多轮完成应用质量上限</li><li>未计价运行不伪造费用</li><li>原始验证证据永久保留</li></ul></section></aside>
      </div>
    </div>
  );
}
