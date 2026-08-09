import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Bot, Check, Eye, FlaskConical, GitBranch, Minus, Play, Plus, ShieldCheck, Trash2, ZoomIn } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Button, ErrorBlock, LoadingBlock, Score, StatusBadge } from "../components/ui";
import { SuiteDrawer } from "../components/SuiteDrawer";
import { api } from "../lib/api";
import { formatDate } from "../lib/format";
import { useApi } from "../lib/useApi";
import type { Experiment, ModelConfig, Participant, Runner, Suite, SystemStatus } from "../types";

export default function Experiments() {
  const state = useApi<Experiment[]>("/experiments", 4_000);
  const [searchParams, setSearchParams] = useSearchParams();
  const [creating, setCreating] = useState(searchParams.get("history") !== "1");
  const initialSuiteId = searchParams.get("suite_id") ?? "";

  useEffect(() => { setCreating(searchParams.get("history") !== "1"); }, [searchParams]);

  function closeCreator() {
    setCreating(false);
    setSearchParams({ history: "1" }, { replace: true });
  }

  if (creating) return <CreateExperiment initialSuiteId={initialSuiteId} onClose={closeCreator} onSaved={() => { closeCreator(); void state.refresh(); }} />;

  return (
    <div className="ab-view ab-experiment-index">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">03 / COMPOSE</span><div><h1>评测编排</h1><p>保存的评测图与历史运行。新建后进入可视化节点画布。</p></div></div>
        <div className="ab-header-meta"><span className="ab-meta-pill"><i />LOCAL EXECUTION</span><button className="ab-run-button" type="button" onClick={() => setCreating(true)}><Plus size={14} />新建评测</button></div>
      </header>
      <div className="ab-experiment-history">
        <div className="ab-history-intro"><div><span>COMPOSITION ARCHIVE</span><h2>本地评测图</h2><p>每个实验锁定套件版本、模型 × Agent 组合、裁判与运行策略。</p></div><GitBranch size={38} /></div>
        {state.loading ? <LoadingBlock /> : state.error || !state.data ? <ErrorBlock message={state.error ?? "读取失败"} retry={() => void state.refresh()} /> : state.data.length ? <div className="ab-experiment-list">
          <div className="ab-experiment-columns"><span>COMPOSITION</span><span>PARTICIPANTS</span><span>RUNS</span><span>SCORE</span><span>STATUS</span><span /></div>
          {state.data.map((item) => <Link className="ab-experiment-row" to={`/experiments/${item.id}`} key={item.id}><span><strong>{item.name}</strong><small>{item.suite_name} · {formatDate(item.created_at)}</small></span><b>{item.participants.length}</b><b>{item.finished_count ?? 0} / {item.run_count ?? 0}</b><Score value={item.avg_score} /><StatusBadge status={item.status} /><ArrowRight size={14} /></Link>)}
        </div> : <div className="ab-history-empty"><FlaskConical size={24} /><strong>还没有评测图</strong><span>在节点画布连接测试套件、参测模型、Agent 与裁判。</span><button className="ab-run-button" type="button" onClick={() => setCreating(true)}><Play size={14} />创建第一次评测</button></div>}
      </div>
    </div>
  );
}

function CreateExperiment({ initialSuiteId = "", onClose, onSaved }: { initialSuiteId?: string; onClose: () => void; onSaved: () => void }) {
  const models = useApi<ModelConfig[]>("/models");
  const runners = useApi<Runner[]>("/runners");
  const suites = useApi<Suite[]>("/suites");
  const systemStatus = useApi<SystemStatus>("/system/status");
  const navigate = useNavigate();
  const [suiteId, setSuiteId] = useState(initialSuiteId);
  const [previewSuiteId, setPreviewSuiteId] = useState("");
  const [participants, setParticipants] = useState<Participant[]>([{ model_id: "", runner_id: "" }]);
  const [repetitions, setRepetitions] = useState(1);
  const [concurrency, setConcurrency] = useState(2);
  const [selectedNode, setSelectedNode] = useState("suite");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const loading = models.loading || runners.loading || suites.loading;
  const selectedSuite = suites.data?.find((suite) => suite.id === suiteId);
  const previewSuite = suites.data?.find((suite) => suite.id === previewSuiteId);
  const judgeModel = models.data?.find((model) => model.id === systemStatus.data?.settings.judge_model_id);
  const judgeRunner = runners.data?.find((runner) => runner.id === systemStatus.data?.settings.judge_runner_id);
  const estimatedRuns = (selectedSuite?.case_count ?? 0) * participants.length * repetitions;
  const participantReady = participants.every((item) => item.model_id && item.runner_id);

  useEffect(() => { if (!suiteId && suites.data?.length) setSuiteId(suites.data[0].id); }, [suiteId, suites.data]);

  function updateParticipant(index: number, patch: Partial<Participant>) {
    setParticipants((items) => items.map((item, position) => position === index ? { ...item, ...patch } : item));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    try {
      const created = await api<Experiment>("/experiments", { method: "POST", body: JSON.stringify({ name: form.get("name"), suite_id: suiteId, participants, repetitions, concurrency }) });
      await api(`/experiments/${created.id}/start`, { method: "POST" });
      onSaved(); navigate(`/experiments/${created.id}`);
    } catch (value) { setError(value instanceof Error ? value.message : "创建失败"); setBusy(false); }
  }

  const selectedTitle = selectedNode === "suite" ? selectedSuite?.name ?? "测试套件" : selectedNode.startsWith("participant") ? `参测者 ${Number(selectedNode.split("-")[1]) + 1}` : selectedNode === "judge" ? "匿名裁判" : "本地运行策略";
  const selectedDescription = selectedNode === "suite" ? "测试套件定义评测范围；启动时锁定题目版本和评分器版本。" : selectedNode.startsWith("participant") ? "参测节点将底层模型与负责执行任务的 Agent 明确绑定。" : selectedNode === "judge" ? "裁判节点只处理无法完全确定性验证的评分维度。" : "定义并发、重复、时间及格线和产物保留规则。";

  return (
    <div className="ab-view ab-compose-view">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">03 / COMPOSE</span><div><h1>评测编排</h1><p>将测试集、模型、Agent、裁判和本地运行策略连接成可审计的评测图。</p></div></div>
        <div className="ab-header-meta"><span className="ab-meta-pill"><i />DRAFT / LOCAL</span><button className="ab-ghost-button" type="button" onClick={onClose}><ArrowLeft size={13} />历史实验</button></div>
      </header>

      {loading ? <LoadingBlock /> : <form className="ab-composer-layout" onSubmit={(event) => void submit(event)}>
        <section className="ab-graph-workspace">
          <div className="ab-graph-toolbar"><button className="ab-mini-button" type="button"><ZoomIn size={12} />100%</button><button className="ab-icon-button compact" type="button"><Plus size={13} /></button><button className="ab-icon-button compact" type="button"><Minus size={13} /></button><span className="ab-toolbar-separator" /><button className="ab-mini-button" type="button" onClick={() => setParticipants((items) => [...items, { model_id: "", runner_id: "" }])}><Plus size={12} />参测者</button><span className="ab-toolbar-spacer" /><span className="ab-graph-stat"><strong>{participants.length}</strong> PARTICIPANTS · <strong>{estimatedRuns}</strong> RUNS</span></div>
          <div className="ab-graph-canvas">
            <p className="ab-canvas-note">EVALUATION GRAPH / LOCAL<br />每条连线都会固化在实验快照中</p>
            <svg className="ab-connections" viewBox="0 0 1100 650" preserveAspectRatio="none" aria-hidden="true"><path className="live" d="M273 310 C360 310 315 200 420 200" /><path className="live" d="M273 310 C360 310 315 430 420 430" /><path className="live" d="M616 200 C690 200 650 315 730 315" /><path className="live" d="M616 430 C690 430 650 315 730 315" /><path className="live" d="M926 315 C970 315 960 315 1000 315" /></svg>
            <GraphNode className="suite" selected={selectedNode === "suite"} onClick={() => setSelectedNode("suite")} label="TEST SUITE" icon={<FlaskConical size={15} />} title={selectedSuite?.name ?? "选择测试套件"} detail={`${selectedSuite?.case_count ?? 0} CASES · V${selectedSuite?.version ?? "—"}`} footerLeft="LOCKED SNAPSHOT" footerRight={suiteId ? "READY" : "WAIT"} />
            {participants.slice(0, 3).map((participant, index) => {
              const model = models.data?.find((item) => item.id === participant.model_id);
              const runner = runners.data?.find((item) => item.id === participant.runner_id);
              return <GraphNode key={index} className={`participant-${index}`} selected={selectedNode === `participant-${index}`} onClick={() => setSelectedNode(`participant-${index}`)} label={`PARTICIPANT ${String(index + 1).padStart(2, "0")}`} icon={<Bot size={15} />} title={model?.name ?? "选择参测模型"} detail={`${runner?.name ?? "选择 Agent"} · ${runner?.capability.installed ? "已检测" : "待配置"}`} footerLeft={runner?.runner_type ?? "MODEL × AGENT"} footerRight={participant.model_id && participant.runner_id ? "READY" : "WAIT"} />;
            })}
            <GraphNode className="judge" selected={selectedNode === "judge"} onClick={() => setSelectedNode("judge")} label="JUDGE" icon={<ShieldCheck size={15} />} title={judgeModel?.name ?? "确定性评分优先"} detail={`${judgeRunner?.name ?? "未启用裁判 Agent"} · 匿名评审`} footerLeft="RUBRIC ONLY" footerRight={judgeModel ? "READY" : "OPTIONAL"} />
            <GraphNode className="policy" selected={selectedNode === "policy"} onClick={() => setSelectedNode("policy")} label="RUN POLICY" icon={<Play size={15} />} title="本地执行" detail={`并发 ${concurrency} · 重复 ${repetitions}\n无硬超时`} footerLeft={`${estimatedRuns} RUNS`} footerRight="READY" />
          </div>
          <div className="ab-minimap"><i /></div>
        </section>

        <aside className="ab-composer-inspector">
          <div className="ab-composer-summary"><span>SELECTED NODE</span><h2>{selectedTitle}</h2><p>{selectedDescription}</p></div>
          <div className="ab-inspector-form">
            <label className="ab-form-field"><span>实验名称 <small>必填</small></span><input name="name" required defaultValue={`${selectedSuite?.name ?? "能力评测"} · ${new Date().toLocaleDateString("zh-CN")}`} /></label>
            <label className="ab-form-field"><span>测试套件 <button type="button" onClick={() => selectedSuite && setPreviewSuiteId(selectedSuite.id)}><Eye size={11} />预览</button></span><select required value={suiteId} onChange={(event) => setSuiteId(event.target.value)}><option value="" disabled>选择测试套件</option>{suites.data?.map((suite) => <option key={suite.id} value={suite.id}>{suite.name}</option>)}</select><small>{selectedSuite ? `${selectedSuite.case_count} 项 · 难度 ${selectedSuite.difficulty_min ?? 1}–${selectedSuite.difficulty_max ?? 1}` : "等待选择"}</small></label>
            <div className="ab-form-section-label">PARTICIPANTS</div>
            {participants.map((participant, index) => {
              const runner = runners.data?.find((item) => item.id === participant.runner_id);
              return <section className="ab-participant-config" key={index}><header><strong>参测者 {String(index + 1).padStart(2, "0")}</strong><span className={participant.model_id && participant.runner_id ? "ready" : ""}>{participant.model_id && participant.runner_id ? "● READY" : "○ WAIT"}</span>{participants.length > 1 && <button type="button" onClick={() => setParticipants((items) => items.filter((_, position) => position !== index))}><Trash2 size={12} /></button>}</header><select required aria-label={`参测者 ${index + 1} 模型`} value={participant.model_id} onChange={(event) => updateParticipant(index, { model_id: event.target.value })}><option value="" disabled>选择模型</option>{models.data?.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select><select required aria-label={`参测者 ${index + 1} Agent`} value={participant.runner_id} onChange={(event) => updateParticipant(index, { runner_id: event.target.value })}><option value="" disabled>选择 Agent</option>{runners.data?.map((item) => <option key={item.id} value={item.id}>{item.name}{!item.capability.installed ? " · 未检测" : ""}</option>)}</select><small>{runner?.capability.installed ? `✓ ${runner.name} 已就绪` : "选择后检查本机执行环境"}</small></section>;
            })}
            <button className="ab-add-participant" type="button" onClick={() => setParticipants((items) => [...items, { model_id: "", runner_id: "" }])}><Plus size={12} />添加参测组合</button>
            <div className="ab-policy-grid"><label className="ab-form-field"><span>重复次数</span><input type="number" min="1" max="10" value={repetitions} onChange={(event) => setRepetitions(Number(event.target.value))} /></label><label className="ab-form-field"><span>并发任务</span><input type="number" min="1" max="8" value={concurrency} onChange={(event) => setConcurrency(Number(event.target.value))} /></label></div>
            <div className="ab-node-diagnostics"><strong><Check size={11} />连接检查{suiteId && participantReady ? "通过" : "等待配置"}</strong><span>{selectedSuite?.case_count ?? 0} 个测试 × {participants.length} 个参测组合 × {repetitions} 次重复；超过时间及格线继续运行，仅作轻量效率扣分。</span></div>
            {error && <div className="ab-compose-error">{error}</div>}
          </div>
          <div className="ab-launch-panel"><div className="ab-launch-stats"><div><span>参测者</span><strong>{participants.length}</strong></div><div><span>运行</span><strong>{estimatedRuns}</strong></div><div><span>裁判</span><strong>{judgeModel ? "ON" : "RULE"}</strong></div></div><button className="ab-run-button wide" type="submit" disabled={!suiteId || !participantReady || busy}><Play size={14} />{busy ? "正在创建…" : "验证并开始本地评测"}</button></div>
        </aside>
      </form>}
      {previewSuite && <SuiteDrawer suiteId={previewSuite.id} suiteName={previewSuite.name} onClose={() => setPreviewSuiteId("")} />}
    </div>
  );
}

function GraphNode({ className, selected, onClick, label, icon, title, detail, footerLeft, footerRight }: { className: string; selected: boolean; onClick: () => void; label: string; icon: ReactNode; title: string; detail: string; footerLeft: string; footerRight: string }) {
  return <button className={`ab-graph-node ab-node-${className}${selected ? " selected" : ""}`} type="button" onClick={onClick}><i className="ab-port in" /><i className="ab-port out" /><span className="ab-node-head"><span>{label}</span><i className={footerRight === "READY" ? "ready" : ""} /></span><span className="ab-node-body"><span className="ab-node-symbol">{icon}</span><strong>{title}</strong><small>{detail}</small><span className="ab-node-foot"><span>{footerLeft}</span><span>{footerRight}</span></span></span></button>;
}
