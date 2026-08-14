import { ArrowRight, BarChart3, FlaskConical, LibraryBig, Radar, Trophy } from "lucide-react";
import { Link } from "react-router-dom";

const modules = [
  { to: "/library", title: "测试项目库", detail: "浏览推理、编程、规划、Office、Ultra 与考研数学测试。", icon: LibraryBig },
  { to: "/experiments", title: "评测编排", detail: "选择参测 Agent、模型、测试组合、并发与重复次数。", icon: FlaskConical },
  { to: "/leaderboard", title: "历史与证据", detail: "查看排行榜、评分证据、Token、成本和完成用时。", icon: Trophy },
  { to: "/profiles", title: "能力画像", detail: "按能力维度比较模型，并识别测试项目的区分度。", icon: Radar },
];

export default function BenchmarksHub() {
  return <div className="v4-page"><header className="v4-page-head"><div><span>EVALUATION SYSTEM</span><h1>Benchmarks</h1><p>保留 AgentBench 原有测试、评分、Ultra 多轮机制、考研数学和 NCRE Office 验证器。</p></div></header><section className="v4-benchmark-hero v4-panel"><div><span><BarChart3 size={18} />EVALUATION ENGINE 3.1</span><h2>Agent 操作平台与模型评测系统<br />现在属于同一个本地工作台。</h2><p>Studio 会话与 Benchmark 运行使用不同的数据域。升级 V4 不会改变已有评测记录、试题修订、匿名裁判配置或评分证据。</p></div><FlaskConical size={96} /></section><section className="v4-benchmark-grid">{modules.map(({ to, title, detail, icon: Icon }) => <Link className="v4-panel" to={to} key={to}><span><Icon size={23} /></span><strong>{title}</strong><p>{detail}</p><footer>打开模块 <ArrowRight size={15} /></footer></Link>)}</section></div>;
}
