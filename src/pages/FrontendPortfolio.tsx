import { ArrowLeft, ExternalLink, FolderOpen, Gauge, LayoutGrid, Play, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Button, ErrorBlock, LoadingBlock, Score, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { formatDuration, formatNumber } from "../lib/format";
import { useOpenFolder } from "../lib/useOpenFolder";
import { useApi } from "../lib/useApi";
import type { FrontendPortfolio as FrontendPortfolioData, FrontendPortfolioRun } from "../types";

function difficulty(value: number) {
  return value >= 6 ? "ULTRA" : `D${value}`;
}

export default function FrontendPortfolio() {
  const { experimentId = "" } = useParams();
  const state = useApi<FrontendPortfolioData>(`/experiments/${experimentId}/frontend-portfolio`, 3_000);
  const openWorkspace = useOpenFolder();
  const [message, setMessage] = useState("");

  async function openPreview(run: FrontendPortfolioRun) {
    setMessage("");
    try {
      const result = await api<{ url: string }>(`/runs/${run.id}/frontend-preview`, {
        method: "POST",
        body: JSON.stringify({ allow_project_scripts: false }),
      });
      window.open(result.url, "_blank", "noopener,noreferrer");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "无法启动预览");
    }
  }

  if (state.loading) return <LoadingBlock label="正在整理前端作品集…" />;
  if (state.error || !state.data) return <ErrorBlock message={state.error ?? "作品集不存在"} retry={() => void state.refresh()} />;
  const portfolio = state.data;
  const scored = portfolio.score.frontend_weighted_score ?? portfolio.score.reviewed_weighted_score;
  return <div className="ab-view ab-frontend-portfolio">
    <header className="ab-view-header">
      <div className="ab-view-title"><span className="ab-view-index">05 / PORTFOLIO</span><div><h1>前端作品集</h1><p>一个模型 × Agent 的所有交付集中展示；作品仍保存在独立本地工作区。</p></div></div>
      <div className="ab-header-meta"><Link className="ab-ghost-button" to={`/experiments/${experimentId}`}><ArrowLeft size={13} />返回实验</Link><button className="ab-run-button" type="button" onClick={() => void openWorkspace(portfolio.root_path, "作品目录")}><FolderOpen size={14} />打开全部作品</button></div>
    </header>
    <section className="frontend-portfolio-hero">
      <div><span>XNmk LIBRARY / {portfolio.metadata.suite_revision}</span><h2>{portfolio.runs.length} 个真实前端项目</h2><p>来源固定在 <code>{portfolio.metadata.source_commit?.slice(0, 12)}</code>，不在运行时访问远程仓库。</p></div>
      <div className="frontend-portfolio-metrics"><div><small>人工评审</small><strong>{portfolio.score.reviewed_runs} / {portfolio.runs.length}</strong></div><div><small>评审进度</small><strong>{portfolio.score.review_progress.toFixed(0)}%</strong></div><div><small>{portfolio.score.frontend_weighted_score == null ? "当前已评均分" : "正式加权总分"}</small><Score value={scored} large /></div></div>
    </section>
    {message && <div className="error-banner"><strong>预览提示</strong><span>{message}</span></div>}
    <div className="frontend-portfolio-toolbar"><div><LayoutGrid size={16} /><strong>全部作品</strong><span>静态入口可直接预览；需要构建的工程仅显示状态，不自动执行脚本。</span></div><button className="ab-ghost-button" type="button" onClick={() => void state.refresh()}><RotateCcw size={13} />刷新入口</button></div>
    <section className="frontend-work-grid">{portfolio.runs.map((run, index) => <article className="frontend-work-card" key={run.id}>
      <header><span>{String(index + 1).padStart(2, "0")}</span><i>{difficulty(run.difficulty)}</i><StatusBadge status={run.status} /></header>
      <div className="frontend-work-cover"><Gauge size={28} /><span>{run.preview.available ? run.preview.entry : run.preview.kind === "project" ? "BUILD REQUIRED" : "WAITING FOR ENTRY"}</span></div>
      <div className="frontend-work-copy"><h3>{run.title}</h3><p>{run.model_name} × {run.runner_name}</p><div><span>{formatDuration(run.duration_ms)}</span><span>{formatNumber(run.tokens_input + run.tokens_output)} Token</span><span>{run.review?.status === "submitted" ? `${run.score?.toFixed(1)} 分` : run.review?.status === "draft" ? "评分草稿" : "待评审"}</span></div></div>
      <footer>{run.workspace_path && <button type="button" onClick={() => void openWorkspace(run.workspace_path!, "工作区")}><FolderOpen size={12} />工作区</button>}{run.preview.available && <button type="button" onClick={() => void openPreview(run)}><Play size={12} />预览</button>}<Link to={`/runs/${run.id}`} state={{ from: `/experiments/${experimentId}/portfolio` }}><ExternalLink size={12} />详情与评分</Link></footer>
    </article>)}</section>
  </div>;
}
