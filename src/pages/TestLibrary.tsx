import { useMemo, useState, type FormEvent } from "react";
import { Check, ChevronRight, FileText, FileUp, Filter, FlaskConical, Layers3, MonitorSmartphone, Search, Shield, Sigma } from "lucide-react";
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
    <div className="ab-view ab-library-view">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">02 / LIBRARY</span><div><h1>测试库巡检</h1><p>从测试集合追到单题、验证器与历史区分度，不再用卡片堆叠掩盖问题。</p></div></div>
        <div className="ab-header-meta"><span className="ab-meta-pill"><i />{cases.data?.length ?? 0} CASES</span><span className="ab-meta-pill">{lowCount} 个信号待处理</span><button className="ab-ghost-button" type="button" onClick={() => setImporting(true)}><FileUp size={13} />导入题包</button></div>
      </header>

      <div className="ab-library-layout">
        <aside className="ab-collection-pane">
          <div className="ab-pane-label">BUILT-IN SUITES</div>
          {mathSuite && <div className="ab-featured-suite ab-math-suite"><span><Sigma size={13} /></span><div><strong>2025 考研数学（一）</strong><small>内置原题 · 22 题 / 150 分</small><nav><Link to={`/experiments?create=1&suite_id=${mathSuite.id}`}>闭卷推理</Link>{mathToolsSuite && <Link to={`/experiments?create=1&suite_id=${mathToolsSuite.id}`}>工具增强</Link>}</nav></div><b>BUILT IN</b></div>}
          {frontendSuite && <div className="ab-featured-suite ab-frontend-suite"><span><MonitorSmartphone size={13} /></span><div><strong>Xnmk Library 前端工程</strong><small>{frontendSuite.case_count} 项 · D3–Ultra · 纯人工评分</small><nav><Link to={`/experiments?create=1&suite_id=${frontendSuite.id}`}>运行完整套件</Link></nav></div><b>5.2</b></div>}
          {featuredSuites.slice(0, 2).map((suite) => <Link className="ab-featured-suite" key={suite.id} to={`/experiments?create=1&suite_id=${suite.id}`}><span><FlaskConical size={13} /></span><div><strong>{suite.name}</strong><small>{suite.case_count} 项 · 难度 {suite.difficulty_min ?? 1}–{suite.difficulty_max ?? 1}</small></div><ChevronRight size={11} /></Link>)}

          <div className="ab-pane-label spaced">COLLECTIONS</div>
          <button className={`ab-collection${!category ? " active" : ""}`} type="button" onClick={() => chooseCategory("")}><span className="ab-collection-icon"><Layers3 size={12} /></span><span><strong>全部测试</strong><small>按真实历史信号排序</small></span><b>{cases.data?.length ?? 0}</b></button>
          {Object.entries(categoryMeta).map(([key, meta]) => {
            const Icon = meta.icon;
            if (!counts[key]) return null;
            return <button className={`ab-collection${category === key ? " active" : ""}`} type="button" key={key} onClick={() => chooseCategory(key)}><span className="ab-collection-icon"><Icon size={12} /></span><span><strong>{meta.name}</strong><small>{key}</small></span><b>{counts[key]}</b></button>;
          })}
          <button className="ab-import-tile" type="button" onClick={() => setImporting(true)}><strong>＋ 导入自定义测试 DSL</strong><span>支持 JSON / YAML，本机校验后加入题库。</span></button>
        </aside>

        <section className="ab-case-browser">
          <div className="ab-browser-toolbar">
            <label className="ab-browser-search"><Search size={13} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索题目、slug 或标签…" /></label>
            <label className="ab-filter-control"><Filter size={12} /><select value={difficulty} onChange={(event) => setDifficulty(Number(event.target.value))}><option value={0}>全部难度</option>{[1, 2, 3, 4, 5, 6].map((value) => <option value={value} key={value}>难度 {value}</option>)}</select></label>
            <label className="ab-filter-control"><select value={environment} onChange={(event) => setEnvironment(event.target.value as typeof environment)}><option value="all">全部环境</option><option value="local">纯本地</option><option value="docker">Docker</option><option value="judge">AI 裁判</option></select></label>
            <span className="ab-browser-count">{filtered.length} / {cases.data?.length ?? 0}</span>
          </div>
          <div className="ab-case-columns"><span>TEST CASE</span><span>难度</span><span>验证方式</span><span>满分率</span><span>样本</span></div>
          <div className="ab-case-list">
            {cases.loading && <div className="ab-case-empty">正在读取本地测试库…</div>}
            {cases.error && <div className="ab-case-empty error">{cases.error}</div>}
            {!cases.loading && filtered.map((item) => <button className={`ab-case-row${selected?.id === item.id ? " active" : ""}`} key={item.id} type="button" onClick={() => setSelectedId(item.id)}>
              <span className="ab-case-name"><i className={item.low_discrimination ? "warn" : ""} /><span><strong>{item.title}</strong><small>{item.slug}</small></span></span>
              <span className={`ab-difficulty level-${item.difficulty ?? 1}`}><b>{item.difficulty ?? 1}</b>{difficultyLabel(item.difficulty)}</span>
              <span className="ab-validator-type">{item.manual_scoring ? "HUMAN" : item.requires_judge ? "AI + RULE" : item.requires_docker ? "PRIVATE" : "RULE"}</span>
              <span className={Number(item.full_score_rate ?? 0) >= 0.9 ? "ab-rate hot" : "ab-rate"}>{item.full_score_rate == null ? "—" : `${Math.round(item.full_score_rate * 100)}%`}</span>
              <span className="ab-sample">{item.sample_size ?? 0}</span>
            </button>)}
            {!cases.loading && !filtered.length && <div className="ab-case-empty">没有符合当前筛选条件的测试。</div>}
          </div>
        </section>

        <aside className="ab-case-inspector">
          {selected ? <>
            <div className="ab-inspector-head"><span className={selected.low_discrimination ? "warn" : "healthy"}>{selected.low_discrimination ? "P0 / LOW DISCRIMINATION" : "HEALTHY / CALIBRATED"}</span><h2>{selected.title}</h2><code>{selected.slug}</code><p>{selected.description}</p></div>
            <div className="ab-inspector-scroll">
              <div className="ab-case-kpis"><div><span>历史样本</span><strong>{selected.sample_size ?? 0}</strong></div><div><span>平均分</span><strong>{selected.avg_score == null ? "—" : selected.avg_score.toFixed(1)}</strong></div><div><span>满分率</span><strong>{selected.full_score_rate == null ? "—" : `${Math.round(selected.full_score_rate * 100)}%`}</strong></div></div>
              <section className="ab-inspect-block"><label>TEST CONTRACT</label><p className="ab-instruction-preview">{selected.definition?.instruction ?? selected.description}</p><div className="ab-contract-tags"><span>{categoryName(selected.category)}</span><span>难度 {selected.difficulty ?? 1}</span><span>{selected.estimated_minutes ?? selected.definition?.metadata?.estimated_minutes ?? 5} 分钟</span>{selected.builtin && <span>BUILT IN</span>}</div></section>
              <section className="ab-inspect-block"><label>VALIDATOR MAP</label><div className="ab-validator-map">{validators.map((validator, index) => <div className="ab-validator-item" key={`${validator.type}-${index}`}><b>{validator.type.slice(0, 2).toUpperCase()}</b><div><strong>{validatorLabel(validator.type)}</strong><small>{validator.type === "manual_rubric" ? "作品完成后由用户逐项评分" : validator.type === "ai_rubric" ? "等价解法与得分点复核" : "确定性证据验证"}</small></div><em>{validator.weight}%</em></div>)}{!validators.length && <span className="ab-muted">没有公开验证器定义</span>}</div></section>
              {selected.low_discrimination ? <section className="ab-inspect-block"><label>DIAGNOSIS</label><div className="ab-diagnosis">历史满分率或答案模式过于集中。建议增加隐藏实例、冲突证据、失败恢复或性质验证，以提升能力区分度。</div></section> : <section className="ab-inspect-block"><label>QUALITY SIGNAL</label><div className="ab-diagnosis healthy"><Check size={13} /> 当前样本没有触发低区分度告警，继续积累跨模型历史。</div></section>}
            </div>
            <div className="ab-inspect-actions"><Link className="ab-ghost-button" to={`/experiments?create=1${featuredSuites[0] ? `&suite_id=${featuredSuites[0].id}` : ""}`}>加入评测</Link><button className="ab-run-button" type="button" onClick={() => navigator.clipboard?.writeText(selected.slug)}><FileText size={13} />复制 Slug</button></div>
          </> : <div className="ab-case-empty">选择一个测试查看证据与验证器。</div>}
        </aside>
      </div>
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
