import { ArrowRight, BarChart3, CheckCircle2, FlaskConical, LibraryBig, Play, Trophy } from "lucide-react";
import { Link } from "react-router-dom";

const steps = [
  { number: "1", title: "选择测试套件", detail: "明确要验证的能力和评分标准" },
  { number: "2", title: "选择参测对象", detail: "组合 Agent、模型与运行条件" },
  { number: "3", title: "预检并运行", detail: "先检查环境，再消耗正式机会" },
  { number: "4", title: "查看证据", detail: "从结果追溯评分、成本和产物" },
];

const suites = [
  { title: "日常能力评测", detail: "推理、编码、规划和工具使用", tag: "适合快速比较" },
  { title: "后端 Ultra 5.3", detail: "金融账本与分布式任务队列", tag: "需要 Docker" },
  { title: "完整考试", detail: "2025 考研数学与 NCRE Office", tag: "独立计分口径" },
];

export default function BenchmarksHub() {
  return <div className="v4-page v53-benchmarks">
    <header className="v4-page-head v53-page-head"><div><span>能力评测</span><h1>用可复验的证据比较 Agent</h1><p>从测试目标开始，经过环境预检和正式运行，最终得到可追溯的评分与产物。</p></div><div><Link className="v4-button secondary" to="/library"><LibraryBig size={16} />浏览测试套件</Link><Link className="v4-button primary" to="/experiments?create=1"><Play size={16} />新建评测</Link></div></header>

    <section className="v53-eval-flow v4-panel" aria-label="评测流程">
      <header><div><small>推荐流程</small><h2>第一次评测也不需要理解内部架构</h2></div><BarChart3 size={28} /></header>
      <div>{steps.map((step, index) => <article key={step.number}><span>{step.number}</span><div><strong>{step.title}</strong><p>{step.detail}</p></div>{index < steps.length - 1 && <ArrowRight size={15} />}</article>)}</div>
    </section>

    <section className="v53-suite-start">
      <header><div><h2>从评测目标开始</h2><p>套件会自动带入对应的运行约束和评分方式。</p></div></header>
      <div>{suites.map((suite) => <Link to="/library" key={suite.title}><span><FlaskConical size={20} /></span><small>{suite.tag}</small><strong>{suite.title}</strong><p>{suite.detail}</p><footer>查看可用套件 <ArrowRight size={14} /></footer></Link>)}</div>
    </section>

    <section className="v53-eval-links">
      <Link className="v4-panel" to="/experiments"><span><Play size={18} /></span><div><strong>运行记录</strong><p>继续草稿、查看实时进度或打开历史结果。</p></div><ArrowRight size={15} /></Link>
      <Link className="v4-panel" to="/leaderboard"><span><Trophy size={18} /></span><div><strong>排行与报告</strong><p>按相同运行条件比较结果，查看完整评分证据。</p></div><ArrowRight size={15} /></Link>
      <Link className="v4-panel" to="/profiles"><span><CheckCircle2 size={18} /></span><div><strong>能力画像</strong><p>按能力维度发现强项、短板和测试区分度。</p></div><ArrowRight size={15} /></Link>
    </section>
  </div>;
}
