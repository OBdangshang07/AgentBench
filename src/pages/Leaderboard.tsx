import {
  BarChart3,
  BookOpenCheck,
  Check,
  Clock3,
  Coins,
  FileSpreadsheet,
  Medal,
  ShieldCheck,
  Trophy,
} from "lucide-react";
import { useState } from "react";
import { ErrorBlock, LoadingBlock } from "../components/ui";
import { formatDuration, formatNumber } from "../lib/format";
import { useApi } from "../lib/useApi";
import type { ExamLeaderboardRow, LeaderboardRow } from "../types";

type Board = "unified" | "native" | "math2025" | "ncre";
type MathMode = "closed-book" | "tool-augmented";
type BenchmarkCondition = "standard" | "maximum" | "nonstandard" | "historical";

const boardMeta = {
  unified: {
    eyebrow: "BASE MODEL CAPABILITY",
    title: "基础模型能力",
    description: "统一工具、上下文与执行协议。",
  },
  native: {
    eyebrow: "NATIVE AGENT SYSTEM",
    title: "完整 Agent 系统能力",
    description: "提示、工具、Runner 与模型作为一个系统。",
  },
  math2025: {
    eyebrow: "2025 POSTGRADUATE MATH I",
    title: "2025 考研数学（一）",
    description: "22 道真题合成完整试卷，按官方 150 分结构计分。",
  },
  ncre: {
    eyebrow: "NCRE LEVEL 2 · MS OFFICE",
    title: "NCRE 二级榜",
    description: "选择题与 Word、Excel、PowerPoint 四部分合成完整试卷。",
  },
} satisfies Record<Board, { eyebrow: string; title: string; description: string }>;

function Participant({ rank, model, runner }: { rank: number; model: string; runner: string }) {
  return (
    <div className="ab-rank-model">
      <i>{rank < 3 ? <Medal size={14} /> : rank + 1}</i>
      <span><strong>{model}</strong><small>{runner}</small></span>
    </div>
  );
}

export default function Leaderboard() {
  const [board, setBoard] = useState<Board>("unified");
  const [mathMode, setMathMode] = useState<MathMode>("closed-book");
  const [condition, setCondition] = useState<BenchmarkCondition>("standard");
  const regularPath = board === "unified" || board === "native"
    ? `/leaderboard?lane=${board}&condition=${condition}`
    : null;
  const examPath = board === "math2025"
    ? `/leaderboard/exams/math-2025?mode=${mathMode}`
    : board === "ncre"
      ? "/leaderboard/exams/ncre"
      : null;
  const regularState = useApi<LeaderboardRow[]>(regularPath, 5_000);
  const examState = useApi<ExamLeaderboardRow[]>(examPath, 5_000);
  const regularRows = regularState.data ?? [];
  const examRows = examState.data ?? [];
  const isExam = board === "math2025" || board === "ncre";
  const loading = isExam ? examState.loading : regularState.loading;
  const error = isExam ? examState.error : regularState.error;
  const refresh = isExam ? examState.refresh : regularState.refresh;
  const samples = isExam
    ? examRows.reduce((sum, row) => sum + row.papers, 0)
    : regularRows.reduce((sum, row) => sum + row.runs, 0);
  const totalCost = (isExam ? examRows : regularRows).reduce((sum, row) => sum + row.total_cost, 0);
  const meta = boardMeta[board];

  return (
    <div className="ab-view ab-ledger-index-view">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">04 / EVIDENCE</span><div><h1>证据索引</h1><p>能力榜与考试榜采用独立口径；样本量、卷面结构与评分构成始终可见。</p></div></div>
        <div className="ab-header-meta"><span className="ab-meta-pill"><i />{samples} {isExam ? "COMPLETE PAPERS" : "SCORED RUNS"}</span><span className="ab-meta-pill">${totalCost.toFixed(3)} COST</span></div>
      </header>
      <div className="ab-ledger-index-layout">
        <aside className="ab-lane-pane">
          <div className="ab-pane-label">MODEL & AGENT</div>
          <button className={board === "unified" ? "active" : ""} type="button" onClick={() => setBoard("unified")}><span><BarChart3 size={14} /></span><div><strong>统一 Agent 模型榜</strong><small>固定 Harness，仅替换模型</small></div></button>
          <button className={board === "native" ? "active" : ""} type="button" onClick={() => setBoard("native")}><span><ShieldCheck size={14} /></span><div><strong>原生 Agent 系统榜</strong><small>Runner 与模型整体计分</small></div></button>
          <div className="ab-pane-label ab-exam-label">OFFICIAL EXAMS</div>
          <button className={board === "math2025" ? "active" : ""} type="button" onClick={() => setBoard("math2025")}><span><BookOpenCheck size={14} /></span><div><strong>2025 考研数学（一）榜</strong><small>完整 22 题 · 官方 150 分</small></div></button>
          <button className={board === "ncre" ? "active" : ""} type="button" onClick={() => setBoard("ncre")}><span><FileSpreadsheet size={14} /></span><div><strong>NCRE 二级榜</strong><small>完整四部分 · 官方 100 分</small></div></button>
          <div className="ab-lane-note"><strong>ISOLATED BOARDS</strong><p>四个榜单独立排名。考试榜只纳入完整试卷，不将单题成绩外推成整卷。</p></div>
        </aside>
        <section className="ab-ranking-canvas">
          <div className="ab-ranking-hero">
            <div><span>{meta.eyebrow}</span><h2>{meta.title}</h2><p>{meta.description}</p></div><Trophy size={34} />
          </div>
          {board === "math2025" && <div className="ab-exam-mode" role="group" aria-label="考研数学榜模式"><span>考试模式</span><button className={mathMode === "closed-book" ? "active" : ""} type="button" onClick={() => setMathMode("closed-book")}>闭卷推理</button><button className={mathMode === "tool-augmented" ? "active" : ""} type="button" onClick={() => setMathMode("tool-augmented")}>工具增强</button><small>两种模式不混排</small></div>}
          {!isExam && <div className="ab-exam-mode" role="group" aria-label="测评运行条件"><span>运行条件</span><button className={condition === "standard" ? "active" : ""} type="button" onClick={() => setCondition("standard")}>HIGH 标准榜</button><button className={condition === "maximum" ? "active" : ""} type="button" onClick={() => setCondition("maximum")}>MAX 极限榜</button><button className={condition === "nonstandard" ? "active" : ""} type="button" onClick={() => setCondition("nonstandard")}>非标准</button><button className={condition === "historical" ? "active" : ""} type="button" onClick={() => setCondition("historical")}>历史</button><small>不同思考预算不混排</small></div>}
          {loading ? <LoadingBlock /> : error ? <ErrorBlock message={error} retry={() => void refresh()} /> : isExam ? examRows.length ? (
            <div className="ab-ranking-table ab-exam-ranking-table">
              <div className="ab-ranking-columns"><span>RANK / PARTICIPANT</span><span>PAPERS</span><span>AVERAGE</span><span>BEST</span><span>{board === "math2025" ? "90 POINT" : "PASS"}</span><span>TIME</span><span>TOKEN</span><span>COST</span></div>
              {examRows.map((row, index) => <div className="ab-ranking-row" key={`${row.model_id}-${row.runner_id}`}><Participant rank={index} model={row.model_name} runner={row.runner_name} /><b>{row.papers}</b><strong className="ab-ranking-score">{row.avg_exam_score.toFixed(1)}<small> / {row.exam_total.toFixed(0)}</small></strong><span>{row.best_exam_score.toFixed(1)}<small> / {row.exam_total.toFixed(0)}</small></span><span>{row.benchmark_rate.toFixed(0)}%<small>≥ {row.benchmark_score.toFixed(0)}</small></span><span>{formatDuration(row.avg_duration_ms)}</span><span>{formatNumber(row.avg_tokens)}</span><span>${row.total_cost.toFixed(3)}</span></div>)}
            </div>
          ) : <div className="ab-case-empty">该榜单还没有完整试卷。未完成的半张卷不会进入排行，也不会按已答部分外推。</div> : regularRows.length ? (
            <div className="ab-ranking-table"><div className="ab-ranking-columns"><span>RANK / PARTICIPANT</span><span>RUNS</span><span>QUALITY</span><span>SUCCESS</span><span>TIME</span><span>TOKEN</span><span>COST</span></div>{regularRows.map((row, index) => <div className="ab-ranking-row" key={`${row.model_id}-${row.runner_id}`}><Participant rank={index} model={row.model_name} runner={row.runner_name} /><b>{row.runs}</b><strong className="ab-ranking-score">{row.avg_score.toFixed(1)}</strong><span>{row.success_rate.toFixed(0)}%</span><span>{formatDuration(row.avg_duration_ms)}<small>{row.avg_time_score?.toFixed(1) ?? "—"}</small></span><span>{row.avg_tokens == null ? "N/A" : formatNumber(row.avg_tokens)}<small>{row.avg_tokens == null ? "未上报" : row.avg_token_score?.toFixed(1) ?? "—"}</small></span><span>${row.total_cost.toFixed(3)}</span></div>)}</div>
          ) : <div className="ab-case-empty">该赛道还没有已完成的评分数据。</div>}
        </section>
        <aside className="ab-ranking-context">
          {isExam ? <ExamContract board={board} /> : <BenchmarkContract />}
        </aside>
      </div>
    </div>
  );
}

function BenchmarkContract() {
  return <><section><label>SCORING CONTRACT</label><div className="ab-contract-score"><strong>94</strong><span>% QUALITY</span></div><p>综合分以任务完成质量为主，效率维度只做轻量修正。</p></section><section><label>WEIGHT MAP</label><div className="ab-weight-row"><ShieldCheck size={13} /><span>客观 / 裁判质量</span><b>94%</b></div><div className="ab-weight-row"><Clock3 size={13} /><span>完成时间</span><b>3%</b></div><div className="ab-weight-row"><Check size={13} /><span>Agent 步数</span><b>2%</b></div><div className="ab-weight-row"><Coins size={13} /><span>Token 消耗</span><b>1%</b></div></section><section><label>AUDIT RULES</label><ul><li>低区分度题目独立标记</li><li>多轮完成应用质量上限</li><li>未计价运行不伪造费用</li><li>原始验证证据永久保留</li></ul></section></>;
}

function ExamContract({ board }: { board: Board }) {
  const math = board === "math2025";
  return <><section><label>OFFICIAL PAPER SCORE</label><div className="ab-contract-score"><strong>{math ? 150 : 100}</strong><span>POINTS</span></div><p>卷面分仅由答案质量按官方分值加权；时间、Token 与成本只做旁列观察，不扣卷面分。</p></section><section><label>OFFICIAL STRUCTURE</label>{math ? <><div className="ab-weight-row"><BookOpenCheck size={13} /><span>选择题</span><b>50</b></div><div className="ab-weight-row"><Check size={13} /><span>填空题</span><b>30</b></div><div className="ab-weight-row"><ShieldCheck size={13} /><span>第 17 题</span><b>10</b></div><div className="ab-weight-row"><ShieldCheck size={13} /><span>第 18–22 题</span><b>60</b></div></> : <><div className="ab-weight-row"><Check size={13} /><span>选择题</span><b>20</b></div><div className="ab-weight-row"><BookOpenCheck size={13} /><span>Word 操作</span><b>30</b></div><div className="ab-weight-row"><FileSpreadsheet size={13} /><span>Excel 操作</span><b>30</b></div><div className="ab-weight-row"><ShieldCheck size={13} /><span>PowerPoint 操作</span><b>20</b></div></>}</section><section><label>ENTRY RULES</label><ul><li>{math ? "必须完成同一轮的全部 22 题" : "必须完成同一套卷的四个部分"}</li><li>不完整试卷不入榜、不外推</li><li>{math ? "闭卷与工具增强模式分开排名" : "每套真题卷先独立合成成绩"}</li><li>{math ? "90 分仅作展示基准，不代表国家线" : "60 分作为 NCRE 及格基准"}</li></ul></section></>;
}
