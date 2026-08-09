import { Ellipsis, ExternalLink, Pause, Play } from "lucide-react";
import { Link } from "react-router-dom";
import { ErrorBlock, LoadingBlock } from "../components/ui";
import { useApi } from "../lib/useApi";
import type { DashboardData, Experiment, ModelProfile, SystemStatus, TestCase } from "../types";

const capabilityNames = ["推理", "编码", "规划", "知识", "分析", "安全"];

function statusText(experiment?: Experiment) {
  if (!experiment) return "等待首次评测";
  if (["running", "queued", "scoring"].includes(experiment.status)) return experiment.status === "queued" ? "等待 Agent" : "正在执行";
  return experiment.status === "completed" ? "最近已完成" : "等待复核";
}

function profileValues(profile?: ModelProfile) {
  if (!profile) return [0, 0, 0, 0, 0, 0];
  const values = profile.dimensions.slice(0, 6).map((item) => item.avg_score);
  while (values.length < 6) values.push(profile.avg_score);
  return values;
}

function CapabilityLedger({ profiles }: { profiles: ModelProfile[] }) {
  const rows = profiles.length ? profiles.slice(0, 2) : [];
  return (
    <section className="ab-model-ledger">
      <div className="ab-ledger-head"><span>MODEL / AGENT</span>{capabilityNames.map((name) => <span key={name}>{name}</span>)}<span>等级</span></div>
      {rows.map((profile, rowIndex) => {
        const values = profileValues(profile);
        return <div className="ab-ledger-row" key={profile.model_id}>
          <div className="ab-model-id"><span className={`ab-model-seal${rowIndex ? " acid" : ""}`}>{profile.model_name.slice(0, 2).toUpperCase()}</span><div><strong>{profile.model_name}</strong><small>{profile.provider} · {profile.total_runs} 个有效样本</small></div></div>
          {values.map((value, index) => <div className="ab-cap-cell" key={`${profile.model_id}-${index}`}><span>{value.toFixed(0)}</span><div className="ab-cap-line"><i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div></div>)}
          <span className="ab-grade">{profile.avg_score >= 90 ? "S" : profile.avg_score >= 75 ? "A" : profile.avg_score >= 60 ? "B" : "C"}</span>
        </div>;
      })}
      {!rows.length && <div className="ab-ledger-empty">还没有形成能力画像。完成第一组评测后，这里会显示真实能力账本。</div>}
    </section>
  );
}

export default function Dashboard() {
  const dashboard = useApi<DashboardData>("/dashboard", 5_000);
  const tests = useApi<TestCase[]>("/test-cases?limit=500", 20_000);
  const profiles = useApi<ModelProfile[]>("/model-profiles?lane=unified&benchmark_generation=all", 10_000);
  const system = useApi<SystemStatus>("/system/status", 10_000);
  if (dashboard.loading) return <LoadingBlock />;
  if (dashboard.error || !dashboard.data) return <ErrorBlock message={dashboard.error ?? "没有返回数据"} retry={() => void dashboard.refresh()} />;

  const data = dashboard.data;
  const experiments = data.recent_experiments;
  const active = experiments.find((item) => ["running", "queued", "scoring"].includes(item.status)) ?? experiments[0];
  const total = Math.max(1, active?.run_count ?? 0);
  const finished = Math.min(total, active?.finished_count ?? (active?.status === "completed" ? total : 0));
  const progress = active ? Math.round((finished / total) * 100) : 0;
  const healthCases = tests.data ?? [];
  const lowDiscrimination = healthCases.filter((item) => item.low_discrimination);
  const formatRisk = healthCases.filter((item) => item.category === "reasoning" && item.requires_judge).length;
  const ultraCount = healthCases.filter((item) => (item.difficulty ?? 0) >= 6).length;
  const sortedProfiles = [...(profiles.data ?? [])].sort((left, right) => right.avg_score - left.avg_score);
  const primaryModel = sortedProfiles[0];
  const secondaryModel = sortedProfiles[1];
  const readyAgents = system.data?.runners.filter((runner) => runner.capability.installed).length ?? 0;

  return (
    <div className="ab-view ab-command-view">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">01 / COMMAND</span><div><h1>评测控制台</h1><p>正在监控 {data.active_runs} 个运行 · 所有数据留在本机</p></div></div>
        <div className="ab-header-meta"><span className="ab-meta-pill"><i />{system.data?.docker.available ? "Docker 在线" : "本地沙箱"}</span><span className="ab-meta-pill">{data.test_cases} 个测试</span><Link className="ab-ghost-button" to="/leaderboard">查看证据</Link></div>
      </header>

      <div className="ab-command-deck">
        <section className="ab-mission-stage">
          <div className="ab-stage-toolbar"><div className="ab-live-label"><i /><strong>{active ? "LIVE / BENCH" : "LOCAL / READY"}</strong><span>{active?.suite_name ?? "等待创建评测"}</span></div><div className="ab-stage-actions"><Link className="ab-mini-button" to={active ? `/experiments/${active.id}` : "/experiments?create=1"}>{active ? <Pause size={12} /> : <Play size={12} />}{active ? "查看" : "开始"}</Link><button className="ab-icon-button compact" type="button"><Ellipsis size={14} /></button></div></div>
          <div className="ab-stage-content">
            <div className="ab-mission-copy">
              <span className="ab-overline">MODEL × AGENT COMPARATIVE RUN</span>
              <h2>{active ? "一次运行，看见模型与 Agent 的真实差距。" : "把模型能力变成可复现、可追溯的本地证据。"}</h2>
              <p>{active ? `${active.name} 正在按统一题面与评分协议执行。低区分度题目会被标记，不参与这次排名的误导。` : "从测试库选择能力组合，绑定模型和 Agent 后即可运行。评分、产物与完整事件轨迹都保留在本机。"}</p>
              <div className="ab-duel">
                <div className="ab-duel-model"><span className="ab-model-seal acid">{primaryModel?.model_name.slice(0, 2).toUpperCase() ?? "AI"}</span><div><strong>{primaryModel?.model_name ?? "参测模型"}</strong><small>{primaryModel?.provider ?? "等待配置"}</small></div></div>
                <span className="ab-versus">vs</span>
                <div className="ab-duel-model"><span className="ab-model-seal">{secondaryModel?.model_name.slice(0, 2).toUpperCase() ?? "AG"}</span><div><strong>{secondaryModel?.model_name ?? "统一 Agent"}</strong><small>{secondaryModel?.provider ?? `${readyAgents} 个 Agent 已就绪`}</small></div></div>
              </div>
            </div>

            <div className="ab-orbit-wrap">
              <span className="ab-orbit" />
              <span className="ab-progress-ring" style={{ background: `conic-gradient(var(--ab-acid) 0 ${progress}%, #20262d ${progress}% 100%)` }} />
              <div className="ab-ring-core"><div><strong>{finished}<span>/{active?.run_count ?? data.total_runs ?? 0}</span></strong><small>{progress}% COMPLETE</small></div></div>
              <span className="ab-satellite ab-sat-1"><b>推理计算</b>{Math.min(finished, 12)} / 12</span>
              <span className="ab-satellite ab-sat-2"><b>编码工程</b>{Math.max(0, Math.min(finished - 12, 14))} / 14</span>
              <span className="ab-satellite ab-sat-3"><b>规划决策</b>{Math.max(0, Math.min(finished - 26, 8))} / 8</span>
            </div>

            <aside className="ab-stage-inspector"><h3>CURRENT SIGNAL</h3><div className="ab-stage-stat"><span>状态</span><strong>{statusText(active)}</strong><small>{active ? `EXPERIMENT / ${active.id.slice(0, 8).toUpperCase()}` : "CREATE A LOCAL EVALUATION"}</small></div><div className="ab-stage-stat"><span>领先模型</span><strong>{primaryModel?.model_name ?? "—"}</strong><small>OBJECTIVE QUALITY {primaryModel?.avg_score.toFixed(1) ?? "—"}</small></div><div className="ab-stage-stat"><span>样本规模</span><strong>{active?.run_count ?? data.total_runs} RUNS</strong><small>{data.models} MODELS / {readyAgents} READY AGENTS</small></div></aside>
          </div>
          <div className="ab-pipeline"><span className="ab-pipe-step done">初始化环境</span><span className="ab-pipe-step done">确定任务</span><span className="ab-pipe-step current">Agent 工作流</span><span className="ab-pipe-step">裁判复核</span><span className="ab-pipe-step">生成报告</span></div>
        </section>

        <aside className="ab-signal-console">
          <div className="ab-console-head"><strong>题库信号台</strong><span>AUTO / LOCAL</span></div>
          <div className="ab-health-score"><div className="ab-health-label"><span>区分度健康指数</span><span>{healthCases.length} 个样本</span></div><strong>{Math.max(0, 100 - lowDiscrimination.length * 4)}<small>/100</small></strong><div className="ab-spectrum">{Array.from({ length: 22 }, (_, index) => <i className={index > 6 && index < 17 ? "hot" : ""} style={{ height: `${8 + ((index * 13) % 23)}px` }} key={index} />)}</div></div>
          <div className="ab-signal-feed">
            <div className="ab-signal"><i className="red" /><div><strong>{lowDiscrimination.length} 道题区分度偏低</strong><p>历史满分率过高，已进入难度巡检队列。</p></div><code>P0</code></div>
            <div className="ab-signal"><i /><div><strong>{formatRisk} 道数学题使用等价验证</strong><p>符号等价与 Rubric 复核共同避免格式误判。</p></div><code>P1</code></div>
            <div className="ab-signal"><i className="green" /><div><strong>{ultraCount} 道 Ultra 题信号稳定</strong><p>隐藏实例与多轮提示仍保持有效区分度。</p></div><code>KEEP</code></div>
          </div>
        </aside>

        <CapabilityLedger profiles={sortedProfiles} />
      </div>
    </div>
  );
}
