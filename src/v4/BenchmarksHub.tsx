import { ArrowRight, FlaskConical, LibraryBig, Play } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ErrorBlock, LoadingBlock, EmptyState } from "../components/ui";
import { useApi } from "../lib/useApi";
import type { Suite } from "../types";

const steps = [
  { title: "选择测试套件", detail: "从目标能力出发，确认题目与评分规则。" },
  { title: "配置参测对象", detail: "固定 Agent、模型与思考预算。" },
  { title: "预检并运行", detail: "检查执行环境，跟踪实时进度。" },
  { title: "阅读评测证据", detail: "从分数追溯过程、成本与最终产物。" },
];

export default function BenchmarksHub() {
  const suites = useApi<Suite[]>("/suites");
  const [params] = useSearchParams();
  const [expanded, setExpanded] = useState(params.get("all") === "1");
  const [query, setQuery] = useState("");
  const matching = (suites.data ?? []).filter(suite => `${suite.name} ${suite.description}`.toLowerCase().includes(query.trim().toLowerCase()));
  const visible = expanded || query ? matching : matching.slice(0, 6);
  return <div className="v4-page fn-benchmarks">
    <header className="v4-page-head"><div><span>EVALUATION / 能力评测</span><h1>评测中心</h1><p>让每一次比较，都有可复验的依据。</p></div><div><Link className="v4-button secondary" to="/library"><LibraryBig size={16} />测试套件</Link><Link className="v4-button primary" to="/experiments?create=1"><Play size={16} />新建评测</Link></div></header>
    <section className="fn-evaluation-hero">
      <div><span className="eyebrow">FROM CAPABILITY TO EVIDENCE</span><h2>能力的全貌，来自真实任务。</h2><p>在同一套运行条件下比较 Agent 与模型。查看每个能力维度的表现，再回到代码、文档与执行记录，理解分数背后的原因。</p><Link className="v4-button primary" to="/experiments?create=1">开始一次评测 <ArrowRight size={15} /></Link></div>
      <svg viewBox="0 0 240 214" role="img" aria-label="评测流程示意：六个能力维度连接到评分证据"><g fill="none" stroke="#727767" strokeWidth="1">{[1,.7,.4].map(scale=><polygon key={scale} points="120,17 198,62 198,152 120,197 42,152 42,62" transform={`translate(${120*(1-scale)},${107*(1-scale)}) scale(${scale})`} />)}{[[120,17],[198,62],[198,152],[120,197],[42,152],[42,62]].map(([x,y])=><line key={`${x}-${y}`} x1="120" y1="107" x2={x} y2={y} />)}</g><circle cx="120" cy="107" r="21" fill="#c8402b" /><path d="m110 107 7 7 14-14" stroke="#fdfcf8" strokeWidth="2" fill="none" /></svg>
    </section>
    <header className="fn-section-head"><h2>从一个测试套件开始</h2><input aria-label="搜索测试套件" placeholder="搜索套件名称或能力…" value={query} onChange={event => setQuery(event.target.value)} /></header>
    {suites.loading ? <LoadingBlock label="读取测试套件…" /> : suites.error ? <ErrorBlock message={suites.error} retry={() => void suites.refresh()} /> : !suites.data?.length ? <EmptyState title="暂无测试套件" detail="在测试套件中导入或创建一组测试。" /> : <div className="fn-suite-grid">{visible.map(suite=><Link className="fn-suite-card" key={suite.id} to={`/experiments?create=1&suite_id=${encodeURIComponent(suite.id)}`}><FlaskConical size={24} /><h3>{suite.name}</h3><p>{suite.description}</p><footer><span>{suite.case_count} 项测试 · v{suite.version}</span><span>选择套件 <ArrowRight size={13} /></span></footer></Link>)}</div>}
    {suites.data && matching.length > 6 && !query && <div className="fn-section-head"><button className="v4-button secondary" type="button" onClick={() => setExpanded(value => !value)}>{expanded ? "收起套件" : `查看全部 ${matching.length} 个套件`}</button></div>}
    {suites.data && query && !matching.length && <EmptyState title="没有匹配的测试套件" detail="尝试更短的关键词或其他能力名称。" />}
    <div className="fn-steps" aria-label="评测流程">{steps.map((step,index)=><article key={step.title}><b>0{index+1}</b><strong>{step.title}</strong><p>{step.detail}</p></article>)}</div>
    <div className="fn-section-head"><Link to="/experiments">查看运行记录 <ArrowRight size={14} /></Link><Link to="/leaderboard">排行与报告 <ArrowRight size={14} /></Link><Link to="/profiles">能力画像 <ArrowRight size={14} /></Link></div>
  </div>;
}
