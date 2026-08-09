import { useMemo, useState } from "react";
import { Radar, Play } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button, ErrorBlock, LoadingBlock, PageHeader } from "../components/ui";
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
    <div className="page">
      <PageHeader
        eyebrow="CAPABILITY PROFILES"
        title="已测试 AI"
        description="基于已完成评测的真实数据，为每个模型绘制能力画像：综合评级、维度雷达图与分类评级，全部来自本地评测记录。"
      />
      <div className="segmented">
        <button className={lane === "unified" ? "active" : ""} onClick={() => setLane("unified")}>统一 Agent 赛道</button>
        <button className={lane === "native" ? "active" : ""} onClick={() => setLane("native")}>原生 Agent 赛道</button>
      </div>
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
    </div>
  );
}
