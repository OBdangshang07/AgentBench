import { useState } from "react";
import { Medal, Trophy } from "lucide-react";
import { Card, ErrorBlock, LoadingBlock, PageHeader, Score } from "../components/ui";
import { formatDuration, formatNumber } from "../lib/format";
import { useApi } from "../lib/useApi";
import type { LeaderboardRow } from "../types";

export default function Leaderboard() {
  const [lane, setLane] = useState<"unified" | "native">("unified");
  const state = useApi<LeaderboardRow[]>(`/leaderboard?lane=${lane}`, 5_000);
  return (
    <div className="page">
      <PageHeader eyebrow="FAIR COMPARISON" title="能力排行榜" description="统一 Agent 榜衡量底层模型能力；原生 Agent 榜衡量 Runner 与模型组成的完整系统。二者绝不混排。" />
      <div className="segmented"><button className={lane === "unified" ? "active" : ""} onClick={() => setLane("unified")}>统一 Agent 模型榜</button><button className={lane === "native" ? "active" : ""} onClick={() => setLane("native")}>原生 Agent 系统榜</button></div>
      {state.loading ? <LoadingBlock /> : state.error || !state.data ? <ErrorBlock message={state.error ?? "读取排行失败"} retry={() => void state.refresh()} /> : state.data.length ? (
        <Card className="leaderboard-card"><div className="leaderboard-head"><Trophy size={22} /><div><h2>{lane === "unified" ? "基础模型能力" : "完整 Agent 系统能力"}</h2><p>{lane === "unified" ? "固定 Harness 与工具，仅替换模型。" : "Runner、模型、提示和工具作为一个整体计分。"} 新评分中质量占 94%，各类效率只做轻量区分。</p></div></div><div className="table-wrap"><table><thead><tr><th>排名</th><th>参测者</th><th>运行数</th><th>综合 / 质量</th><th>成功率</th><th>平均耗时 / 时效</th><th>平均 Token / T效</th><th>总费用</th></tr></thead><tbody>{state.data.map((row, index) => <tr key={`${row.model_id}-${row.runner_id}`}><td><div className={`rank rank-${index + 1}`}>{index < 3 ? <Medal size={18} /> : index + 1}</div></td><td><strong>{row.model_name}</strong><small>{row.runner_name}</small></td><td>{row.runs}</td><td><Score value={row.avg_score} />{row.avg_objective_score != null && <small className="score-subline">质量 {row.avg_objective_score.toFixed(1)}</small>}</td><td>{row.success_rate.toFixed(1)}%</td><td>{formatDuration(row.avg_duration_ms)}{row.avg_time_score != null && <small className="score-subline">时效 {row.avg_time_score.toFixed(1)}</small>}</td><td>{formatNumber(row.avg_tokens)}{row.avg_token_score != null && <small className="score-subline">T效 {row.avg_token_score.toFixed(1)}</small>}</td><td>${row.total_cost.toFixed(4)}</td></tr>)}</tbody></table></div></Card>
      ) : <div className="inline-empty">该赛道还没有已完成的评分数据。</div>}
    </div>
  );
}
