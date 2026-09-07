import { useMemo, useState, type FormEvent } from "react";
import { Check, ChevronRight, FileText, FileUp, Filter, FlaskConical, Layers3, MonitorSmartphone, Search, Sigma } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { Button, Field, Modal } from "../components/ui";
import { api } from "../lib/api";
import { categoryMeta, categoryName } from "../lib/categoryMeta";
import { useApi } from "../lib/useApi";
import type { Suite, TestCase } from "../types";

function difficultyLabel(value = 1) {
  if (value >= 6) return "ULTRA";
  if (value >= 5) return "极限";
  if (value >= 4) return "困难";
  if (value >= 3) return "进阶";
  return "基础";
}

function validatorLabel(type: string) {
  const names: Record<string, string> = { exact_match: "Exact match", command: "Command tests", command_metrics: "Metric checks", ai_rubric: "AI Rubric", manual_rubric: "人工评分量表", file_content: "File content", file_exists: "File exists", forbidden_paths: "Forbidden paths", regex: "Format rules", json_schema: "JSON schema" };
  return names[type] ?? type.replaceAll("_", " ");
}

export default function TestLibrary() {
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "";
  const [query, setQuery] = useState("");
  const [difficulty, setDifficulty] = useState(0);
  const [environment, setEnvironment] = useState<"all" | "local" | "docker" | "judge">("all");
  const [selectedId, setSelectedId] = useState("");
  const [importing, setImporting] = useState(false);
  const cases = useApi<TestCase[]>("/test-cases?limit=500", 20_000);
  const suites = useApi<Suite[]>("/suites", 20_000);

  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    for (const item of cases.data ?? []) result[item.category] = (result[item.category] ?? 0) + 1;
    return result;
  }, [cases.data]);

  const filtered = useMemo(() => (cases.data ?? []).filter((item) => {
    const keyword = query.trim().toLowerCase();
    if (category && item.category !== category) return false;
    if (difficulty && item.difficulty !== difficulty) return false;
    if (environment === "docker" && !item.requires_docker) return false;
    if (environment === "judge" && !item.requires_judge) return false;
    if (environment === "local" && (item.requires_docker || item.requires_judge)) return false;
    return !keyword || `${item.title} ${item.description} ${item.slug} ${(item.tags ?? []).join(" ")}`.toLowerCase().includes(keyword);
  }), [cases.data, category, difficulty, environment, query]);

  const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0];
  const allSuites = suites.data ?? [];
  const mathSuite = allSuites.find((suite) => suite.name === "2025 考研数学（一）· 闭卷推理");
  const mathToolsSuite = allSuites.find((suite) => suite.name === "2025 考研数学（一）· 工具增强");
  const frontendSuite = allSuites.find((suite) => suite.name === "Xnmk Library 前端工程全套");
  const featuredSuites = allSuites.filter((suite) => !/考研数学|NCRE|MS Office|Xnmk 前端|Xnmk Library/.test(suite.name)).sort((left, right) => Number(/高难|Ultra|极限/.test(right.name)) - Number(/高难|Ultra|极限/.test(left.name))).slice(0, 3);
  const validators = selected?.definition?.validators ?? [];
  const lowCount = (cases.data ?? []).filter((item) => item.low_discrimination).length;

  function chooseCategory(next: string) {
    const value = next === category ? "" : next;
    setParams(value ? { category: value } : {});
    setSelectedId("");
  }

  return (
    <div className="ab-view ab-agent-document ab-library-view ab-library-vnext">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">能力评测</span><div><h1>测试套件</h1><p>先按评测目标选择套件，再查看其中的题目、运行要求和评分方式。</p></div></div>
        <div className="ab-header-meta"><span className="ab-meta-pill"><i />{cases.data?.length ?? 0} 项测试</span><span className="ab-meta-pill">{lowCount} 项区分度待关注</span><button className="ab-ghost-button" type="button" onClick={() => setImporting(true)}><FileUp size={13} />导入题包</button></div>
      </header>

      <main className="ab-library-document">
        <section className="ab-suite-section" aria-labelledby="recommended-suites">
          <div className="ab-document-section-head"><div><span>从目标开始</span><h2 id="recommended-suites">推荐评测套件</h2><p>套件已经组合好题目与评分规则，适合直接发起一次对比评测。</p></div><Link to="/benchmarks?all=1">查看全部套件 <ChevronRight size={14} /></Link></div>
          <div className="ab-suite-strip">
            {mathSuite && <article className="ab-suite-entry"><span className="ab-suite-mark"><Sigma size={17} /></span><div><small>完整试卷 · 内置题库</small><strong>2025 考研数学（一）</strong><p>22 道原题，150 分制；检验长程推理与答案严谨性。</p></div><nav><Link to={`/experiments?create=1&suite_id=${mathSuite.id}`}>闭卷推理</Link>{mathToolsSuite && <Link to={`/experiments?create=1&suite_id=${mathToolsSuite.id}`}>工具增强</Link>}</nav></article>}
            {frontendSuite && <article className="ab-suite-entry"><span className="ab-suite-mark"><MonitorSmartphone size={17} /></span><div><small>工程实践 · 人工验收</small><strong>Xnmk Library 前端工程</strong><p>{frontendSuite.case_count} 项真实前端任务，覆盖实现质量与视觉结果。</p></div><nav><Link to={`/experiments?create=1&suite_id=${frontendSuite.id}`}>运行完整套件</Link></nav></article>}
            {featuredSuites.slice(0, 1).map((suite) => <article className="ab-suite-entry" key={suite.id}><span className="ab-suite-mark"><FlaskConical size={17} /></span><div><small>综合能力 · 难度 {suite.difficulty_min ?? 1}–{suite.difficulty_max ?? 1}</small><strong>{suite.name}</strong><p>{suite.case_count} 个测试项目，适合建立模型能力基线。</p></div><nav><Link to={`/experiments?create=1&suite_id=${suite.id}`}>发起评测</Link></nav></article>)}
          </div>
        </section>

        <section className="ab-case-section" aria-labelledby="case-library">
          <div className="ab-document-section-head"><div><span>按能力浏览</span><h2 id="case-library">浏览单项测试</h2><p>按能力、难度与运行环境缩小范围，选择一项即可查看完整评分依据。</p></div><button type="button" onClick={() => setImporting(true)}><FileUp size={14} />导入自定义测试</button></div>
          <div className="ab-category-tabs" role="tablist" aria-label="能力分类">
            <button className={!category ? "active" : ""} type="button" onClick={() => chooseCategory("")}><Layers3 size={14} />全部 <b>{cases.data?.length ?? 0}</b></button>
            {Object.entries(categoryMeta).map(([key, meta]) => {
              const Icon = meta.icon;
              if (!counts[key]) return null;
              return <button className={category === key ? "active" : ""} type="button" key={key} onClick={() => chooseCategory(key)}><Icon size={14} />{meta.name}<b>{counts[key]}</b></button>;
            })}
          </div>
          <div className="ab-browser-toolbar">
            <label className="ab-browser-search"><Search size={13} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索题目、slug 或标签…" /></label>
            <label className="ab-filter-control"><Filter size={12} /><select value={difficulty} onChange={(event) => setDifficulty(Number(event.target.value))}><option value={0}>全部难度</option>{[1, 2, 3, 4, 5, 6].map((value) => <option value={value} key={value}>难度 {value}</option>)}</select></label>
            <label className="ab-filter-control"><select value={environment} onChange={(event) => setEnvironment(event.target.value as typeof environment)}><option value="all">全部环境</option><option value="local">纯本地</option><option value="docker">Docker</option><option value="judge">AI 裁判</option></select></label>
            <span className="ab-browser-count">显示 {filtered.length} 项</span>
          </div>
          <div className="ab-library-workspace">
            <div className="ab-case-browser">
              <div className="ab-case-columns"><span>测试项目</span><span>难度</span><span>评分方式</span><span>历史满分率</span></div>
              <div className="ab-case-list">
                {cases.loading && <div className="ab-case-empty">正在读取本地测试库…</div>}
                {cases.error && <div className="ab-case-empty error">{cases.error}</div>}
                {!cases.loading && filtered.map((item) => <button className={`ab-case-row${selected?.id === item.id ? " active" : ""}`} key={item.id} type="button" onClick={() => setSelectedId(item.id)}>
                  <span className="ab-case-name"><i className={item.low_discrimination ? "warn" : ""} /><span><strong>{item.title}</strong><small>{categoryName(item.category)} · {item.slug}</small></span></span>
                  <span className={`ab-difficulty level-${item.difficulty ?? 1}`}><b>{item.difficulty ?? 1}</b>{difficultyLabel(item.difficulty)}</span>
                  <span className="ab-validator-type">{item.manual_scoring ? "人工评分" : item.requires_judge ? "AI 与规则" : item.requires_docker ? "隔离验证" : "规则验证"}</span>
                  <span className={Number(item.full_score_rate ?? 0) >= 0.9 ? "ab-rate hot" : "ab-rate"}>{item.full_score_rate == null ? "暂无样本" : `${Math.round(item.full_score_rate * 100)}%`}</span>
                </button>)}
                {!cases.loading && !filtered.length && <div className="ab-case-empty">没有符合当前筛选条件的测试。尝试清除分类或降低难度筛选。</div>}
              </div>
            </div>

            <aside className="ab-case-inspector">
              {selected ? <>
                <div className="ab-inspector-head"><span className={selected.low_discrimination ? "warn" : "healthy"}>{selected.low_discrimination ? "区分度需要关注" : "评分状态正常"}</span><h2>{selected.title}</h2><p>{selected.description}</p><code>{selected.slug}</code></div>
                <div className="ab-inspector-scroll">
                  <div className="ab-case-kpis"><div><span>历史样本</span><strong>{selected.sample_size ?? 0}</strong></div><div><span>平均分</span><strong>{selected.avg_score == null ? "—" : selected.avg_score.toFixed(1)}</strong></div><div><span>满分率</span><strong>{selected.full_score_rate == null ? "—" : `${Math.round(selected.full_score_rate * 100)}%`}</strong></div></div>
                  <section className="ab-inspect-block"><label>任务要求</label><p className="ab-instruction-preview">{selected.definition?.instruction ?? selected.description}</p><div className="ab-contract-tags"><span>{categoryName(selected.category)}</span><span>难度 {selected.difficulty ?? 1}</span><span>约 {selected.estimated_minutes ?? selected.definition?.metadata?.estimated_minutes ?? 5} 分钟</span>{selected.builtin && <span>内置测试</span>}</div></section>
                  <section className="ab-inspect-block"><label>如何评分<span className="ab-sr-only">VALIDATOR MAP</span></label><div className="ab-validator-map">{validators.map((validator, index) => <div className="ab-validator-item" key={`${validator.type}-${index}`}><b>{index + 1}</b><div><strong>{validatorLabel(validator.type)}</strong><small>{validator.type === "manual_rubric" ? "作品完成后由用户逐项评分" : validator.type === "ai_rubric" ? "复核等价解法与关键得分点" : "通过确定性证据自动验证"}</small></div><em>{validator.weight}%</em></div>)}{!validators.length && <span className="ab-muted">此测试没有公开评分器定义。</span>}</div></section>
                  {selected.low_discrimination ? <section className="ab-inspect-block"><label>质量提醒</label><div className="ab-diagnosis">历史答案模式较集中。建议增加隐藏实例、冲突证据或失败恢复要求。</div></section> : <section className="ab-inspect-block"><label>质量状态</label><div className="ab-diagnosis healthy"><Check size={13} /> 当前样本未触发低区分度告警。</div></section>}
                </div>
                <div className="ab-inspect-actions"><Link className="ab-run-button" to="/benchmarks">选择评测套件</Link><button className="ab-ghost-button" type="button" onClick={() => navigator.clipboard?.writeText(selected.slug)}><FileText size={13} />复制标识</button></div>
              </> : <div className="ab-case-empty">选择一个测试查看要求与评分方式。</div>}
            </aside>
          </div>
        </section>
      </main>
      {importing && <ImportModal onClose={() => setImporting(false)} onSaved={() => { setImporting(false); void cases.refresh(); }} />}
    </div>
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
  return <Modal title="导入测试 DSL" description="支持 JSON 或 YAML；内置考研数学题库无需导入。" onClose={onClose}><form className="form-grid one-column" onSubmit={(event) => void submit(event)}><Field label="测试定义"><textarea name="dsl" rows={18} defaultValue={sample} spellCheck={false} /></Field>{error && <div className="form-error">{error}</div>}<div className="modal-actions"><Button type="button" variant="ghost" onClick={onClose}>取消</Button><Button type="submit" busy={busy}>校验并导入</Button></div></form></Modal>;
}
