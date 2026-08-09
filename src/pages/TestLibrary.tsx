import { useMemo, useState, type FormEvent } from "react";
import {
  ChevronRight,
  FileText,
  FileUp,
  Search,
  Shield,
  Sparkles,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api, apiUpload } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { MathPaperImport, TestCase } from "../types";
import { Button, Card, ErrorBlock, Field, LoadingBlock, Modal, PageHeader } from "../components/ui";
import { categoryMeta } from "../lib/categoryMeta";

function DifficultyBadge({ value = 1 }: { value?: number }) {
  return <span className={`difficulty-badge difficulty-${value}`}><i>{value}</i> {value >= 6 ? "Ultra" : value >= 5 ? "极限" : value >= 4 ? "困难" : value >= 3 ? "进阶" : "基础"}</span>;
}

export default function TestLibrary() {
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "";
  const [query, setQuery] = useState("");
  const [difficulty, setDifficulty] = useState(0);
  const [environment, setEnvironment] = useState<"all" | "local" | "docker" | "judge">("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importingMath, setImportingMath] = useState(false);
  const state = useApi<TestCase[]>("/test-cases?limit=500");

  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    state.data?.forEach((item) => { result[item.category] = (result[item.category] ?? 0) + 1; });
    return result;
  }, [state.data]);
  const filtered = useMemo(() => (state.data ?? []).filter((item) => {
    const keyword = query.trim().toLowerCase();
    if (category && item.category !== category) return false;
    if (difficulty && item.difficulty !== difficulty) return false;
    if (environment === "docker" && !item.requires_docker) return false;
    if (environment === "judge" && !item.requires_judge) return false;
    if (environment === "local" && (item.requires_docker || item.requires_judge)) return false;
    if (keyword && !`${item.title} ${item.description} ${item.slug} ${(item.tags ?? []).join(" ")}`.toLowerCase().includes(keyword)) return false;
    return true;
  }), [category, difficulty, environment, query, state.data]);
  const ultraCases = state.data?.filter((item) => item.difficulty === 6).length ?? 0;
  const projectCases = state.data?.filter((item) => item.requires_docker).length ?? 0;
  const judgedCases = state.data?.filter((item) => item.requires_judge).length ?? 0;

  function selectCategory(value: string) {
    if (value) setParams({ category: value }); else setParams({});
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="CAPABILITY BENCHMARKS"
        title="能力测试"
        description="从确定性基础题到项目型极限任务。按能力、难度和运行环境筛选，先理解测试，再开始实验。"
        actions={<><Button variant="secondary" onClick={() => setImportingMath(true)}><FileText size={16} /> 导入考研数学 PDF</Button><Button onClick={() => setImporting(true)}><FileUp size={16} /> 导入自定义测试</Button></>}
      />
      <div className="library-overview">
        <Card><span>全部测试</span><strong>{state.data?.length ?? 0}</strong><small>11 个能力域</small></Card>
        <Card className="ultra-overview-card"><span>Ultra 挑战</span><strong>{ultraCases}</strong><small>私有故障验证 · 三轮分级提示</small></Card>
        <Card><span>项目型验证</span><strong>{projectCases}</strong><small>Docker 隐藏测试</small></Card>
        <Card><span>AI 裁判</span><strong>{judgedCases}</strong><small>开放质量评分</small></Card>
      </div>

      <Card className="library-shell">
        <div className="category-tabs">
          <button className={!category ? "active" : ""} onClick={() => selectCategory("")}><Sparkles size={15} /> 全部 <b>{state.data?.length ?? 0}</b></button>
          {Object.entries(categoryMeta).map(([key, meta]) => { const Icon = meta.icon; return <button key={key} className={category === key ? "active" : ""} onClick={() => selectCategory(category === key ? "" : key)}><Icon size={15} /> {meta.name} <b>{counts[key] ?? 0}</b></button>; })}
        </div>
        <div className="library-toolbar">
          <div className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务、能力或标签" /></div>
          <select value={difficulty} onChange={(event) => setDifficulty(Number(event.target.value))}><option value={0}>全部难度</option><option value={1}>难度 1 · 入门</option><option value={2}>难度 2 · 基础</option><option value={3}>难度 3 · 进阶</option><option value={4}>难度 4 · 困难</option><option value={5}>难度 5 · 极限</option><option value={6}>难度 6 · Ultra</option></select>
          <select value={environment} onChange={(event) => setEnvironment(event.target.value as typeof environment)}><option value="all">全部环境</option><option value="local">纯本地即可</option><option value="docker">需要 Docker</option><option value="judge">需要 AI 裁判</option></select>
          <span className="result-count">找到 <strong>{filtered.length}</strong> 项</span>
        </div>
        {state.loading ? <LoadingBlock /> : state.error || !state.data ? <ErrorBlock message={state.error ?? "读取失败"} retry={() => void state.refresh()} /> : (
          <div className="test-list enhanced-test-list">
            {filtered.map((item) => {
              const meta = categoryMeta[item.category] ?? categoryMeta.reasoning;
              const Icon = meta.icon;
              return (
                <button key={item.id} className="test-row enhanced-test-row" onClick={() => setSelected(item.id)}>
                  <div className={`test-icon icon-${meta.color}`}><Icon size={18} /></div>
                  <div className="test-main"><strong>{item.title}</strong><span>{item.description}</span><div className="mini-tags">{(item.tags ?? []).slice(0, 3).map((tag) => <i key={tag}>{tag}</i>)}</div></div>
                  <div className="test-capability"><span>{meta.name}</span><small>{item.capability}</small></div>
                  <DifficultyBadge value={item.difficulty} />
                  <div className="environment-tags">{item.requires_docker && <span>Docker</span>}{item.requires_judge && <span>AI 裁判</span>}{!item.requires_docker && !item.requires_judge && <span>本地</span>}</div>
                  <ChevronRight size={17} />
                </button>
              );
            })}
            {!filtered.length && <div className="inline-empty">没有符合当前筛选条件的测试。</div>}
          </div>
        )}
      </Card>
      {selected && <TestDetail caseId={selected} onClose={() => setSelected(null)} />}
      {importing && <ImportModal onClose={() => setImporting(false)} onSaved={() => { setImporting(false); void state.refresh(); }} />}
      {importingMath && <MathPaperImportModal onClose={() => setImportingMath(false)} />}
    </div>
  );
}

function MathPaperImportModal({ onClose }: { onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<MathPaperImport | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    const file = form.get("paper");
    const year = Number(form.get("year") ?? 2025);
    if (!(file instanceof File) || !file.name.toLowerCase().endsWith(".pdf")) {
      setError("请选择 PDF 试卷文件"); setBusy(false); return;
    }
    try {
      const imported = await apiUpload<MathPaperImport>(
        `/math-papers/import?filename=${encodeURIComponent(file.name)}&year=${year}`,
        file,
        "application/pdf",
      );
      setResult(imported);
    } catch (value) {
      setError(value instanceof Error ? value.message : "PDF 导入失败");
    } finally { setBusy(false); }
  }
  return <Modal title="导入考研数学真题" description="PDF 仅保存在本机。系统先提取 22 道题的待校对草稿，不会自动发布到正式榜单。" onClose={onClose}>
    {result ? <div className="math-import-result"><div><FileText size={22} /><span><strong>{result.title}</strong><small>{result.source.page_count} 页 · {result.questions.filter((item) => item.question_text).length}/22 道已识别 · 150 分制</small></span></div><p>状态：待人工校对。接下来需要逐题确认公式、图形、答案、等价解法和解答题 Rubric。</p>{result.warnings.map((warning) => <em key={warning}>{warning}</em>)}<div className="modal-actions"><Button onClick={onClose}>完成</Button></div></div> : <form className="form-grid one-column" onSubmit={(event) => void submit(event)}><Field label="考试年份"><input name="year" type="number" min="2000" max="2100" defaultValue="2025" /></Field><Field label="真题与答案 PDF"><input name="paper" type="file" accept="application/pdf,.pdf" required /></Field><div className="math-import-note"><Shield size={16} /><span>原始 PDF、抽取文本与校对草稿只写入 AgentBench 本地数据目录，不会上传服务器或提交到公开仓库。</span></div>{error && <div className="form-error">{error}</div>}<div className="modal-actions"><Button type="button" variant="ghost" onClick={onClose}>取消</Button><Button type="submit" busy={busy}>导入并生成草稿</Button></div></form>}
  </Modal>;
}

function TestDetail({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const state = useApi<TestCase>(`/test-cases/${caseId}`);
  const definition = state.data?.definition;
  const difficulty = definition?.metadata?.difficulty ?? state.data?.difficulty ?? 1;
  return (
    <Modal title={state.data?.title ?? "测试详情"} description={state.data?.slug} onClose={onClose}>
      {state.loading ? <LoadingBlock /> : state.error || !definition ? <ErrorBlock message={state.error ?? "读取失败"} /> : (
        <div className="detail-stack">
          <div className="test-detail-summary"><DifficultyBadge value={difficulty} /><span>预计 {definition.metadata?.estimated_minutes ?? 5} 分钟</span><span>{definition.metadata?.capability}</span>{definition.validators.some((item) => item.type === "command") && <span>需要 Docker</span>}</div>
          {definition.metadata?.private_validation && <div className="ultra-private-banner"><Shield size={20} /><div><strong>任务结束后注入私有验证器</strong><span>参测 Agent 只能运行公开 smoke；评分阶段会独立执行并发、故障与防篡改测试。{definition.metadata.instance_count ? ` 本题含 ${definition.metadata.instance_count} 个实例、${definition.metadata.task_count ?? "多"} 个任务。` : ""}</span></div></div>}
          <section><span className="section-kicker">TASK</span><h3>模型会收到什么任务？</h3><p className="instruction-box">{definition.instruction}</p></section>
          <section><span className="section-kicker">WORKSPACE</span><h3>可用工具与初始项目</h3><div className="detail-inline"><div><strong>工具</strong><div className="tag-row">{definition.tools.map((tool) => <span className="tag" key={tool}>{tool}</span>)}</div></div><div><strong>初始文件</strong><span>{Object.keys(definition.initial_files ?? {}).length} 个</span></div></div></section>
          <section><span className="section-kicker">SCORING</span><h3>如何评分？</h3>{definition.validators.map((validator, index) => <div className="validator-row" key={`${validator.type}-${index}`}><code>{validator.type}</code><div className="weight-bar"><i style={{ width: `${validator.weight}%` }} /></div><strong>{validator.weight}%</strong></div>)}</section>
          {definition.attempt_policy && <section><span className="section-kicker">ATTEMPTS</span><h3>三轮挑战规则</h3><div className="attempt-policy-summary"><strong>最多 {definition.attempt_policy.max_attempts ?? 3} 轮</strong><span>及格线 {definition.attempt_policy.pass_threshold ?? 85}</span><span>系数 {(definition.attempt_policy.multipliers ?? [1, .85, .7]).map((item) => `×${item.toFixed(2)}`).join(" / ")}</span><small>未通过时逐轮给出固定提示，并保留上一轮工作区；环境失败不消耗能力机会。</small></div></section>}
          <section><span className="section-kicker">LIMITS</span><h3>运行边界</h3><pre>{JSON.stringify(definition.limits, null, 2)}</pre></section>
        </div>
      )}
    </Modal>
  );
}

function ImportModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sample = `{
  "slug": "custom.answer-001",
  "version": "1.0.0",
  "category": "instruction-following",
  "title": "自定义精确回答",
  "instruction": "只输出 OK",
  "validators": [{"type":"exact_match","weight":90,"config":{"expected":"OK"}}],
  "metadata": {"difficulty": 1, "estimated_minutes": 1}
}`;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const document = String(new FormData(event.currentTarget).get("dsl"));
      try { await api("/test-cases", { method: "POST", body: JSON.stringify(JSON.parse(document)) }); }
      catch (value) { if (!(value instanceof SyntaxError)) throw value; await api("/test-cases/import", { method: "POST", headers: { "Content-Type": "text/yaml" }, body: document }); }
      onSaved();
    } catch (value) { setError(value instanceof Error ? value.message : "导入失败"); setBusy(false); }
  }
  return <Modal title="导入测试 DSL" description="支持 JSON 或 YAML；导入前会校验字段、验证器与权重。" onClose={onClose}><form className="form-grid one-column" onSubmit={(event) => void submit(event)}><Field label="测试定义"><textarea name="dsl" rows={18} defaultValue={sample} spellCheck={false} /></Field>{error && <div className="form-error">{error}</div>}<div className="modal-actions"><Button type="button" variant="ghost" onClick={onClose}>取消</Button><Button type="submit" busy={busy}>校验并导入</Button></div></form></Modal>;
}
