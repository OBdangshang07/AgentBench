import {
  ArrowRight,
  Bot,
  Check,
  CircleDollarSign,
  FlaskConical,
  Layers3,
  Play,
  PlugZap,
  Settings2,
  ShieldCheck,
  Sparkles,
  Trophy,
} from "lucide-react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Card, ErrorBlock, LoadingBlock, PageHeader, Score, StatusBadge } from "../components/ui";
import { formatDate } from "../lib/format";
import { useApi } from "../lib/useApi";
import type { DashboardData, ModelConfig, Runner, SystemStatus } from "../types";

const categoryMeta: Record<string, { name: string; color: string }> = {
  "instruction-following": { name: "指令遵循", color: "#7662e8" },
  reasoning: { name: "推理计算", color: "#4e83d3" },
  "tool-use": { name: "工具使用", color: "#27a0b4" },
  "software-engineering": { name: "软件工程", color: "#27a47a" },
  "knowledge-work": { name: "知识工作", color: "#a26ad1" },
  "data-analysis": { name: "数据分析", color: "#de8a36" },
  "agentic-workflow": { name: "Agent 工作流", color: "#2f9b91" },
  security: { name: "安全工程", color: "#d75f69" },
  planning: { name: "规划决策", color: "#9b7831" },
  "ultra-engineering": { name: "Ultra 工程", color: "#b53a68" },
  "ultra-planning": { name: "Ultra 规划", color: "#7b3fbd" },
};

export default function Dashboard() {
  const dashboard = useApi<DashboardData>("/dashboard", 5_000);
  const system = useApi<SystemStatus>("/system/status", 10_000);
  const models = useApi<ModelConfig[]>("/models");
  const runners = useApi<Runner[]>("/runners", 10_000);
  if (dashboard.loading) return <LoadingBlock />;
  if (dashboard.error || !dashboard.data) {
    return <ErrorBlock message={dashboard.error ?? "没有返回数据"} retry={() => void dashboard.refresh()} />;
  }

  const data = dashboard.data;
  const realModels = models.data?.filter((model) => model.api_style !== "mock").length ?? 0;
  const readyRunners = runners.data?.filter((runner) => runner.capability.installed).length ?? 0;
  const judgeReady = Boolean(system.data?.settings.judge_model_id && system.data?.settings.judge_runner_id);
  const setupSteps = [
    { done: realModels > 0, title: "添加参测模型", detail: realModels ? `${realModels} 个真实模型可用` : "配置 API 模型或 CLI 模型身份", to: "/models" },
    { done: readyRunners > 1, title: "确认执行 Agent", detail: `${readyRunners} 个 Runner 已在本机检测`, to: "/models" },
    { done: judgeReady, title: "选择评分 Agent", detail: judgeReady ? "AI 裁判已启用" : "用于主观任务与项目质量评分", to: "/settings" },
    { done: Boolean(system.data?.docker.available), title: "连接 Docker（可选）", detail: system.data?.docker.available ? "代码沙箱在线" : "代码和安全测试需要 Docker", to: "/settings" },
  ];
  const setupDone = setupSteps.filter((step) => step.done).length;
  const readiness = Math.round((setupDone / setupSteps.length) * 100);
  const maxCategory = Math.max(...data.categories.map((item) => item.count), 1);

  const metrics = [
    { label: "分层测试", value: data.test_cases, suffix: "项", icon: Layers3, tone: "violet", detail: "难度 1–6 · 含 Ultra" },
    { label: "参测模型", value: data.models, suffix: "个", icon: Bot, tone: "cyan", detail: `${realModels} 个真实模型` },
    { label: "可用 Agent", value: readyRunners, suffix: "个", icon: PlugZap, tone: "blue", detail: "统一与原生赛道" },
    { label: "累计费用", value: `$${Number(data.total_cost ?? 0).toFixed(3)}`, suffix: "", icon: CircleDollarSign, tone: "green", detail: data.unpriced_runs ? `${data.unpriced_runs} 次运行缺少价格` : `${data.total_runs ?? 0} 次运行` },
  ];

  return (
    <div className="page">
      <PageHeader
        eyebrow="AGENT EVALUATION WORKSPACE"
        title="从快速验证到极限压力，一条路径完成评测"
        description="选择模型和 Agent，挑选分层测试集，运行后直接查看能力、成本、速度与失败证据。"
        actions={<Link className="button button-primary" to="/experiments?create=1"><Sparkles size={16} /> 新建评测</Link>}
      />

      <Card className="dashboard-hero">
        <div className="hero-copy">
          <span className="hero-pill"><Trophy size={14} /> V2 实战基准已就绪</span>
          <h2>先用 20 题验证配置，再用 75 题实战或 37 题极限集拉开差距</h2>
          <p>测试覆盖长上下文检索、数据分析、多文件工作流、隐藏测试编码、安全修复和高约束规划。</p>
          <div className="hero-actions">
            <Link className="button button-primary" to="/experiments?create=1"><Play size={15} /> 选择测试集</Link>
            <Link className="button button-secondary" to="/library">浏览能力地图 <ArrowRight size={15} /></Link>
          </div>
        </div>
        <div className="readiness-ring" style={{ "--progress": `${readiness * 3.6}deg` } as CSSProperties}>
          <div><strong>{readiness}%</strong><span>环境就绪度</span></div>
        </div>
      </Card>

      <div className="metric-grid">
        {metrics.map(({ label, value, suffix, icon: Icon, tone, detail }) => (
          <Card key={label} className="metric-card">
            <div className={`metric-icon metric-${tone}`}><Icon size={19} /></div>
            <span>{label}</span>
            <strong>{value}<small>{suffix}</small></strong>
            <em>{detail}</em>
          </Card>
        ))}
      </div>

      <div className="dashboard-grid dashboard-primary-grid">
        <Card className="panel-span-2">
          <div className="card-header">
            <div><span className="section-kicker">RECENT RUNS</span><h2>最近实验</h2></div>
            <Link to="/experiments" className="text-link">全部实验 <ArrowRight size={15} /></Link>
          </div>
          {data.recent_experiments.length ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>实验</th><th>测试集</th><th>进度</th><th>均分</th><th>状态</th><th /></tr></thead>
                <tbody>
                  {data.recent_experiments.map((item) => (
                    <tr key={item.id}>
                      <td><strong>{item.name}</strong><small>{formatDate(item.created_at)}</small></td>
                      <td>{item.suite_name}</td>
                      <td>{item.finished_count ?? 0} / {item.run_count ?? 0}</td>
                      <td><Score value={item.avg_score} /></td>
                      <td><StatusBadge status={item.status} /></td>
                      <td><Link className="row-link" to={`/experiments/${item.id}`}><ArrowRight size={16} /></Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <div className="inline-empty">还没有实验。建议从“V2 快速上手”开始。</div>}
        </Card>

        <Card className="setup-card">
          <div className="card-header"><div><span className="section-kicker">SETUP</span><h2>开始前检查</h2></div><strong className="setup-count">{setupDone}/4</strong></div>
          <div className="setup-list">
            {setupSteps.map((step, index) => (
              <Link className={step.done ? "setup-step done" : "setup-step"} to={step.to} key={step.title}>
                <span className="setup-index">{step.done ? <Check size={14} /> : index + 1}</span>
                <div><strong>{step.title}</strong><small>{step.detail}</small></div>
                <ArrowRight size={14} />
              </Link>
            ))}
          </div>
          <div className={system.data?.native_cli_enabled ? "setup-note ready" : "setup-note"}>
            {system.data?.native_cli_enabled ? <ShieldCheck size={15} /> : <Settings2 size={15} />}
            {system.data?.native_cli_enabled ? "原生 Agent 权限已开启" : "原生 Agent 尚未启用"}
          </div>
        </Card>
      </div>

      <Card className="capability-map-card">
        <div className="card-header">
          <div><span className="section-kicker">CAPABILITY MAP</span><h2>能力覆盖地图</h2></div>
          <span className="muted-copy">共 {data.categories.length} 个能力域</span>
        </div>
        <div className="capability-bars">
          {data.categories.map((item) => {
            const meta = categoryMeta[item.category] ?? { name: item.category, color: "#718096" };
            return (
              <Link to={`/library?category=${encodeURIComponent(item.category)}`} className="capability-bar" key={item.category}>
                <div><strong>{meta.name}</strong><span>{item.category}</span></div>
                <div className="capability-track"><i style={{ width: `${(item.count / maxCategory) * 100}%`, background: meta.color }} /></div>
                <b>{item.count}</b>
              </Link>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
