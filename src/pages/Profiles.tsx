import { useMemo, useState } from "react";
import { Radar, Play } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button, ErrorBlock, LoadingBlock } from "../components/ui";
import RadarChart, { type RadarDatum } from "../components/RadarChart";
import { useApi } from "../lib/useApi";
import { gradeOf, gradeDescription } from "../lib/grades";
import { categoryName, radarCategories, ultraCategories } from "../lib/categoryMeta";
import type { ModelProfile, ProfileDimension } from "../types";

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function GradeBadge({ score, large = false }: { score: number; large?: boolean }) {
  const grade = gradeOf(score);
  return (
    <span className={large ? `grade-badge grade-${grade}` : `grade-tag grade-${grade}`} title={gradeDescription[grade]}>
      {grade}
    </span>
  );
}

function DimensionGrid({ profile }: { profile: ModelProfile }) {
  const byCategory = useMemo(() => {
    const map = new Map<string, ProfileDimension>();
    profile.dimensions.forEach((dimension) => map.set(dimension.category, dimension));
    return map;
  }, [profile.dimensions]);
  return (
    <div className="profile-dimensions">
      {radarCategories.map((category) => {
        const dimension = byCategory.get(category);
        return (
          <div key={category} className="profile-dimension">
            <span>{categoryName(category)}</span>
            {dimension ? (
              <>
                <strong>{dimension.avg_score.toFixed(1)}</strong>
                <span className={dimension.runs < 3 ? "profile-dim-grade low-sample" : "profile-dim-grade"}>
                  <GradeBadge score={dimension.avg_score} />
                  {dimension.runs < 3 && <i className="low-sample-note">样本少</i>}
                </span>
                <small>{dimension.runs} 次</small>
              </>
            ) : (
              <em className="dim-empty">— 暂无数据</em>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ProfileCard({ profile }: { profile: ModelProfile }) {
  const byCategory = useMemo(() => {
    const map = new Map<string, ProfileDimension>();
    profile.dimensions.forEach((dimension) => map.set(dimension.category, dimension));
    return map;
  }, [profile.dimensions]);
  const radarData: RadarDatum[] = radarCategories
    .map((category) => byCategory.get(category))
    .filter((dimension): dimension is ProfileDimension => Boolean(dimension))
    .map((dimension) => ({ label: categoryName(dimension.category), value: dimension.avg_score }));
  const ultraDimensions = ultraCategories
    .map((category) => byCategory.get(category))
    .filter((dimension): dimension is ProfileDimension => Boolean(dimension));
  return (
    <section className="card profile-card">
      <div className="profile-head">
        <div>
          <h3>{profile.model_name}</h3>
          <span>{profile.provider} · 最近评测 {formatTime(profile.last_run_at)}</span>
          <div className="profile-grade-line">
            <GradeBadge score={profile.avg_score} large />
            <strong>{profile.avg_score.toFixed(1)}</strong>
            <span>综合评分</span>
          </div>
        </div>
        <div className="profile-summary">
          <div><strong>{profile.total_runs}</strong><span>运行次数</span></div>
          <div><strong>{profile.success_rate.toFixed(1)}%</strong><span>成功率</span></div>
        </div>
      </div>
      {radarData.length >= 3 ? (
        <div className="profile-radar">
          <RadarChart data={radarData} ariaLabel={`${profile.model_name} 能力雷达图`} />
        </div>
      ) : (
        <div className="profile-radar-empty">已测维度不足 3 个，暂无法绘制雷达图。</div>
      )}
      <DimensionGrid profile={profile} />
      {ultraDimensions.length > 0 && (
        <div className="profile-ultra-tags">
          {ultraDimensions.map((dimension) => (
            <span key={dimension.category} className="profile-ultra-tag">
              {categoryName(dimension.category)} {dimension.avg_score.toFixed(1)} · {dimension.runs} 次
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

export default function Profiles() {
  const [lane, setLane] = useState<"unified" | "native">("unified");
  const navigate = useNavigate();
  const state = useApi<ModelProfile[]>(`/model-profiles?lane=${lane}`, 10_000);
  return (
    <div className="ab-view ab-secondary-view ab-profiles-view">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">06 / PROFILES</span><div><h1>能力画像</h1><p>按赛道聚合真实运行证据，基础维度与 Ultra 压力测试分层呈现。</p></div></div>
        <div className="ab-header-meta"><span className="ab-meta-pill"><i />{state.data?.length ?? 0} PROFILES</span><button className="ab-run-button" type="button" onClick={() => navigate("/experiments?create=1")}><Play size={14} />新建评测</button></div>
      </header>
      <div className="ab-profile-layout">
        <aside className="ab-section-pane">
          <div className="ab-pane-label">COMPARISON LANES</div>
          <button className={lane === "unified" ? "active" : ""} onClick={() => setLane("unified")}><span><Radar size={15} /></span><div><strong>统一 Agent 赛道</strong><small>控制工具与执行协议</small></div></button>
          <button className={lane === "native" ? "active" : ""} onClick={() => setLane("native")}><span><Play size={15} /></span><div><strong>原生 Agent 赛道</strong><small>模型与系统能力整体计分</small></div></button>
          <section className="ab-side-contract"><label>PROFILE CONTRACT</label><strong>LANES STAY SEPARATE</strong><p>不同执行范式不混合排名；低于 3 个样本的维度会标记为低置信度。</p></section>
        </aside>
        <main className="ab-profile-canvas">
          <div className="ab-canvas-intro"><span>CAPABILITY LEDGER</span><div><h2>{lane === "unified" ? "基础模型能力" : "原生 Agent 系统能力"}</h2><p>从已完成运行提取分数、成功率、维度覆盖与高难任务表现。</p></div><b>{state.data?.reduce((sum, item) => sum + item.total_runs, 0) ?? 0} RUNS</b></div>
          {state.loading ? (
            <LoadingBlock />
          ) : state.error || !state.data ? (
            <ErrorBlock message={state.error ?? "读取能力画像失败"} retry={() => void state.refresh()} />
          ) : state.data.length ? (
            <div className="profile-grid">
              {state.data.map((profile) => (
                <ProfileCard key={profile.model_id} profile={profile} />
              ))}
            </div>
          ) : (
            <div className="inline-empty inline-empty-action">
              <Radar size={30} />
              <strong>该赛道还没有能力画像</strong>
              <span>完成一次评测后，模型的维度能力画像会自动生成在这里。</span>
              <Button onClick={() => navigate("/experiments")}><Play size={15} /> 去创建评测</Button>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
