import { useEffect, useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight, Bot, Check, CircleAlert, Eye, FlaskConical, Play, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ErrorBlock, LoadingBlock, Score, StatusBadge } from "../components/ui";
import { SuiteDrawer } from "../components/SuiteDrawer";
import { api } from "../lib/api";
import { formatDate } from "../lib/format";
import { useApi } from "../lib/useApi";
import type { Experiment, ModelConfig, Participant, ReasoningEffort, ReasoningPolicy, Runner, Suite, SystemStatus } from "../types";

export default function Experiments() {
  const state = useApi<Experiment[]>("/experiments", 4_000);
  const [searchParams, setSearchParams] = useSearchParams();
  const [creating, setCreating] = useState(searchParams.get("create") === "1");
  const initialSuiteId = searchParams.get("suite_id") ?? "";

  useEffect(() => { setCreating(searchParams.get("create") === "1"); }, [searchParams]);

  function openCreator() {
    setCreating(true);
    setSearchParams({ create: "1", ...(initialSuiteId ? { suite_id: initialSuiteId } : {}) }, { replace: true });
  }

  function closeCreator() {
    setCreating(false);
    setSearchParams({}, { replace: true });
  }

  if (creating) return <CreateExperiment initialSuiteId={initialSuiteId} onClose={closeCreator} onSaved={() => { closeCreator(); void state.refresh(); }} />;

  return <div className="ab-view ab-experiment-index v53-experiments">
    <header className="ab-view-header"><div className="ab-view-title"><span className="ab-view-index">运行记录</span><div><h1>评测运行</h1><p>继续草稿、观察进行中的评测，或打开历史结果与评分证据。</p></div></div><div className="ab-header-meta"><button className="ab-run-button" type="button" onClick={openCreator}><Plus size={14} />新建评测</button></div></header>
    <div className="ab-experiment-history">
      <div className="ab-history-intro"><div><span>本机运行记录</span><h2>所有评测</h2><p>每次运行都会固定套件版本、参测对象、运行条件和评分方式。</p></div><FlaskConical size={38} /></div>
      {state.loading ? <LoadingBlock /> : state.error || !state.data ? <ErrorBlock message={state.error ?? "读取失败"} retry={() => void state.refresh()} /> : state.data.length ? <div className="ab-experiment-list">
        <div className="ab-experiment-columns"><span>评测</span><span>参测对象</span><span>进度</span><span>得分</span><span>状态</span><span /></div>
        {state.data.map((item) => <Link className="ab-experiment-row" to={`/experiments/${item.id}`} key={item.id}><span><strong>{item.name}</strong><small>{item.suite_name} · {formatDate(item.created_at)}</small></span><b>{item.participants.length}</b><b>{item.finished_count ?? 0} / {item.run_count ?? 0}</b><Score value={item.avg_score} /><StatusBadge status={item.status} /><ArrowRight size={14} /></Link>)}
      </div> : <div className="ab-history-empty"><FlaskConical size={24} /><strong>还没有评测记录</strong><span>向导会帮助你选择套件、参测对象与运行条件，并在启动前检查环境。</span><button className="ab-run-button" type="button" onClick={openCreator}><Play size={14} />创建第一次评测</button></div>}
    </div>
  </div>;
}

const wizardSteps = ["选择套件", "参测对象", "运行条件", "确认并启动"];

function CreateExperiment({ initialSuiteId = "", onClose, onSaved }: { initialSuiteId?: string; onClose: () => void; onSaved: () => void }) {
  const models = useApi<ModelConfig[]>("/models");
  const runners = useApi<Runner[]>("/runners");
  const suites = useApi<Suite[]>("/suites");
  const systemStatus = useApi<SystemStatus>("/system/status");
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [suiteId, setSuiteId] = useState(initialSuiteId);
  const [previewSuiteId, setPreviewSuiteId] = useState("");
  const [participants, setParticipants] = useState<Participant[]>([{ model_id: "", runner_id: "" }]);
  const [repetitions, setRepetitions] = useState(1);
  const [concurrency, setConcurrency] = useState(2);
  const [reasoningPolicy, setReasoningPolicy] = useState<ReasoningPolicy>("standard");
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>("high");
  const [judgeReasoningEffort, setJudgeReasoningEffort] = useState<ReasoningEffort>("high");
  const [strictFairness, setStrictFairness] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const loading = models.loading || runners.loading || suites.loading || systemStatus.loading;
  const selectedSuite = suites.data?.find((suite) => suite.id === suiteId);
  const previewSuite = suites.data?.find((suite) => suite.id === previewSuiteId);
  const judgeModel = models.data?.find((model) => model.id === systemStatus.data?.settings.judge_model_id);
  const selectedRunners = participants.map((participant) => runners.data?.find((runner) => runner.id === participant.runner_id));
  const estimatedRuns = (selectedSuite?.case_count ?? 0) * participants.length * repetitions;
  const frontendSuite = Boolean(selectedSuite && /Xnmk (Library )?前端/.test(selectedSuite.name));
  const backendUltraSuite = selectedSuite?.name === "后端 Ultra 极限测试";
  const suiteMinutes = selectedSuite?.estimated_minutes ?? (selectedSuite?.case_count ?? 0) * (frontendSuite ? 110 : 8);
  const estimatedMinutes = estimatedRuns ? Math.ceil(suiteMinutes * participants.length * repetitions / Math.max(1, Math.min(concurrency, estimatedRuns))) : 0;

  const participantIsReady = (participant: Participant) => {
    if (!participant.model_id || !participant.runner_id) return false;
    const runner = runners.data?.find((item) => item.id === participant.runner_id);
    if (!runner?.capability.installed) return false;
    if (runner.runner_type !== "deepseek_harness") return true;
    const modeId = participant.agent_mode ?? runner.adapter?.default_agent_mode ?? "standard";
    const modes = runner.adapter?.agent_modes ?? [];
    return modes.length === 0 || modes.some((mode) => mode.id === modeId && mode.available);
  };
  const participantReady = participants.every(participantIsReady);
  const fairnessReady = !strictFairness || (reasoningPolicy !== "native" && participants.every((participant) => {
    const runner = runners.data?.find((item) => item.id === participant.runner_id);
    return !participant.runner_id || runner?.adapter?.reasoning_control?.supported !== false;
  }));
  const dockerReady = !backendUltraSuite || Boolean(systemStatus.data?.docker.available);
  const canStart = Boolean(suiteId && name.trim() && participantReady && fairnessReady && dockerReady);

  useEffect(() => { if (!suiteId && suites.data?.length) setSuiteId(suites.data[0].id); }, [suiteId, suites.data]);
  useEffect(() => {
    if (!selectedSuite) return;
    if (!name || suites.data?.some((suite) => name.startsWith(suite.name))) setName(`${selectedSuite.name} · ${new Date().toLocaleDateString("zh-CN")}`);
    if (frontendSuite) setConcurrency(1);
    else if (backendUltraSuite) setConcurrency(4);
    setReasoningPolicy((selectedSuite.difficulty_max ?? 0) >= 6 ? "maximum" : "standard");
  }, [selectedSuite?.id]);

  function updateParticipant(index: number, patch: Partial<Participant>) {
    setParticipants((items) => items.map((item, position) => position === index ? { ...item, ...patch } : item));
  }

  function next() {
    setError("");
    if (step === 1 && (!suiteId || !name.trim())) return setError("请先选择测试套件并填写评测名称");
    if (step === 2 && !participantReady) return setError("请为每个参测对象选择已就绪的模型与 Agent");
    if (step === 3 && !fairnessReady) return setError("当前配置无法通过严格公平检查，请调整 Agent 或运行条件");
    setStep((value) => Math.min(4, value + 1));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (step < 4) return next();
    if (!canStart) return;
    setBusy(true); setError("");
    try {
      const created = await api<Experiment>("/experiments", { method: "POST", body: JSON.stringify({ name: name.trim(), suite_id: suiteId, participants, repetitions, concurrency, reasoning_policy: reasoningPolicy, reasoning_effort: reasoningEffort, strict_fairness: strictFairness, judge_reasoning_effort: judgeReasoningEffort }) });
      await api(`/experiments/${created.id}/start`, { method: "POST" });
      onSaved(); navigate(`/experiments/${created.id}`);
    } catch (value) { setError(value instanceof Error ? value.message : "创建失败"); setBusy(false); }
  }

  return <div className="ab-view v53-eval-wizard">
    <header className="ab-view-header"><div className="ab-view-title"><span className="ab-view-index">新建评测</span><div><h1>{wizardSteps[step - 1]}</h1><p>按顺序完成必要配置，高级运行条件已有安全默认值。</p></div></div><button className="ab-ghost-button" type="button" onClick={onClose}><ArrowLeft size={13} />返回运行记录</button></header>
    <nav className="v53-wizard-steps" aria-label="评测创建进度">{wizardSteps.map((label, index) => <button type="button" key={label} className={step === index + 1 ? "active" : step > index + 1 ? "done" : ""} disabled={index + 1 > step} onClick={() => setStep(index + 1)}><span>{step > index + 1 ? <Check size={13} /> : index + 1}</span><strong>{label}</strong></button>)}</nav>

    {loading ? <LoadingBlock /> : <form className="v53-wizard-form" onSubmit={(event) => void submit(event)}>
      <main>
        {step === 1 && <section className="v53-wizard-panel"><header><small>第 1 步</small><h2>你希望验证什么？</h2><p>套件决定测试范围、评分方式和运行前置条件。</p></header><label className="v53-field"><span>评测名称</span><input required value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：后端 Agent 横向比较" /></label><div className="v53-suite-list">{suites.data?.map((suite) => <button className={suite.id === suiteId ? "active" : ""} type="button" key={suite.id} onClick={() => setSuiteId(suite.id)}><span><FlaskConical size={18} /></span><div><strong>{suite.name}</strong><p>{suite.description}</p><small>{suite.case_count} 项测试 · 难度 {suite.difficulty_min ?? 1}–{suite.difficulty_max ?? 1} · 约 {suite.estimated_minutes ?? "—"} 分钟</small></div><i>{suite.id === suiteId ? <Check size={14} /> : null}</i></button>)}</div>{selectedSuite && <button className="v53-preview-link" type="button" onClick={() => setPreviewSuiteId(selectedSuite.id)}><Eye size={14} />查看所选套件的题目与评分说明</button>}</section>}

        {step === 2 && <section className="v53-wizard-panel"><header><small>第 2 步</small><h2>选择参测对象</h2><p>模型决定能力来源，Agent 决定它可以使用的工具和执行方式。</p></header><div className="v53-participants">{participants.map((participant, index) => {
          const runner = runners.data?.find((item) => item.id === participant.runner_id);
          const modes = runner?.adapter?.agent_modes ?? [];
          const modeId = participant.agent_mode ?? runner?.adapter?.default_agent_mode ?? "standard";
          return <article key={index}><header><span><Bot size={16} /></span><div><strong>参测对象 {index + 1}</strong><small>{participantIsReady(participant) ? "已就绪" : "等待配置"}</small></div>{participants.length > 1 && <button type="button" aria-label={`移除参测对象 ${index + 1}`} onClick={() => setParticipants((items) => items.filter((_, position) => position !== index))}><Trash2 size={14} /></button>}</header><div><label><span>模型</span><select aria-label={`参测者 ${index + 1} 模型`} required value={participant.model_id} onChange={(event) => updateParticipant(index, { model_id: event.target.value })}><option value="">请选择模型</option>{models.data?.filter((model) => model.enabled).map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label><label><span>执行 Agent</span><select aria-label={`参测者 ${index + 1} Agent`} required value={participant.runner_id} onChange={(event) => { const nextRunner = runners.data?.find((item) => item.id === event.target.value); const available = nextRunner?.adapter?.agent_modes?.filter((mode) => mode.available) ?? []; updateParticipant(index, { runner_id: event.target.value, agent_mode: nextRunner?.runner_type === "deepseek_harness" ? available.find((mode) => mode.id === nextRunner.adapter?.default_agent_mode)?.id ?? available[0]?.id : undefined }); }}><option value="">请选择 Agent</option>{runners.data?.filter((item) => item.enabled).map((item) => <option key={item.id} value={item.id}>{item.name}{!item.capability.installed ? " · 尚未就绪" : ""}</option>)}</select></label>{runner?.runner_type === "deepseek_harness" && <label className="full"><span>Harness 模式</span><select aria-label={`参测者 ${index + 1} Harness 模式`} value={modeId} onChange={(event) => updateParticipant(index, { agent_mode: event.target.value })}>{modes.map((mode) => <option key={mode.id} value={mode.id} disabled={!mode.available}>{mode.name}{!mode.available ? " · 不可用" : ""}</option>)}</select></label>}</div>{runner && !runner.capability.installed && <p className="v53-inline-warning"><CircleAlert size={13} />{runner.name} 尚未通过本机检测，请先到“Agent 与模型”完成配置。</p>}</article>;
        })}</div><button className="v53-add-participant" type="button" onClick={() => setParticipants((items) => [...items, { model_id: "", runner_id: "" }])}><Plus size={14} />添加另一个参测对象</button></section>}

        {step === 3 && <section className="v53-wizard-panel"><header><small>第 3 步</small><h2>确认运行条件</h2><p>推荐值已根据套件自动设置。只有需要严格控制实验时才需要修改。</p></header><div className="v53-condition-grid"><label><span>思考策略</span><select aria-label="测评思考策略" value={reasoningPolicy} onChange={(event) => { const policy = event.target.value as ReasoningPolicy; setReasoningPolicy(policy); if (policy === "native") setStrictFairness(false); }}><option value="standard">High 标准条件</option><option value="maximum">MAX 极限条件</option><option value="native">Agent 原生默认（非标准榜）</option><option value="custom">自定义映射</option></select><small>不同思考预算不会混入同一排行榜。</small></label>{reasoningPolicy === "custom" && <label><span>参测思考强度</span><select aria-label="参测模型思考强度" value={reasoningEffort} onChange={(event) => setReasoningEffort(event.target.value as ReasoningEffort)}>{(["low", "medium", "high", "xhigh", "max"] as ReasoningEffort[]).map((effort) => <option key={effort} value={effort}>{effort.toUpperCase()}</option>)}</select></label>}{!frontendSuite && <label><span>匿名裁判思考强度</span><select aria-label="匿名裁判思考强度" value={judgeReasoningEffort} onChange={(event) => setJudgeReasoningEffort(event.target.value as ReasoningEffort)}>{(["low", "medium", "high", "xhigh", "max"] as ReasoningEffort[]).map((effort) => <option key={effort} value={effort}>{effort.toUpperCase()}</option>)}</select></label>}<label><span>重复次数</span><input type="number" min="1" max="10" value={repetitions} onChange={(event) => setRepetitions(Number(event.target.value))} /><small>增加重复可降低偶然性，也会增加时间与费用。</small></label><label><span>最大并发</span><input type="number" min="1" max="8" value={concurrency} onChange={(event) => setConcurrency(Number(event.target.value))} /><small>{backendUltraSuite ? "后端 Ultra 推荐 4；私有验证器内部最多并行 2。" : "过高可能触发模型供应商限流。"}</small></label></div><label className="ab-fairness-toggle"><input type="checkbox" checked={strictFairness} onChange={(event) => setStrictFairness(event.target.checked)} /><span><strong>启动前执行严格公平检查</strong><small>无法验证思考档位的 Agent 会阻止启动，而不是静默降级。</small></span></label></section>}

        {step === 4 && <section className="v53-wizard-panel"><header><small>第 4 步</small><h2>确认并启动</h2><p>先检查本机环境和配置；通过后才会创建正式运行。</p></header><div className="v53-preflight"><article className={selectedSuite ? "ready" : "error"}><span>{selectedSuite ? <Check size={15} /> : <CircleAlert size={15} />}</span><div><strong>测试套件</strong><p>{selectedSuite?.name ?? "尚未选择"} · {selectedSuite?.case_count ?? 0} 项</p></div></article><article className={participantReady ? "ready" : "error"}><span>{participantReady ? <Check size={15} /> : <CircleAlert size={15} />}</span><div><strong>参测对象</strong><p>{participantReady ? `${participants.length} 个组合均已就绪` : "存在未配置或不可用的 Agent"}</p></div></article><article className={fairnessReady ? "ready" : "error"}><span>{fairnessReady ? <Check size={15} /> : <CircleAlert size={15} />}</span><div><strong>运行条件</strong><p>{fairnessReady ? `${reasoningPolicy === "maximum" ? "MAX 极限" : reasoningPolicy === "standard" ? "High 标准" : "非标准"} · 并发 ${concurrency}` : "无法通过严格公平检查"}</p></div></article><article className={dockerReady ? "ready" : "error"}><span>{dockerReady ? <Check size={15} /> : <CircleAlert size={15} />}</span><div><strong>本机环境</strong><p>{backendUltraSuite ? dockerReady ? "Docker 已就绪；启动时继续校验固定镜像与私有验证包" : "后端 Ultra 需要 Docker Desktop" : "此套件没有已知的本机阻塞"}</p></div></article></div><div className="v53-run-summary"><div><span>正式运行</span><strong>{estimatedRuns}</strong><small>{selectedSuite?.case_count ?? 0} 项 × {participants.length} 个对象 × {repetitions} 次</small></div><div><span>预计用时</span><strong>约 {estimatedMinutes} 分钟</strong><small>实际用时取决于供应商额度与本机资源</small></div><div><span>评分方式</span><strong>{frontendSuite ? "人工评分" : judgeModel ? "规则 + 匿名裁判" : "确定性规则"}</strong><small>{judgeModel?.name ?? "不会为缺失的裁判静默打分"}</small></div></div></section>}
      </main>
      <footer><div>{error && <span className="v53-wizard-error"><CircleAlert size={14} />{error}</span>}</div><button className="v4-button secondary" type="button" onClick={step === 1 ? onClose : () => { setError(""); setStep((value) => value - 1); }}>{step === 1 ? "取消" : "上一步"}</button>{step < 4 ? <button className="v4-button primary" type="submit">下一步<ArrowRight size={14} /></button> : <button className="v4-button primary" type="submit" disabled={!canStart || busy}><Play size={14} />{busy ? "正在启动…" : "通过预检并开始评测"}</button>}</footer>
    </form>}
    {previewSuite && <SuiteDrawer suiteId={previewSuite.id} suiteName={previewSuite.name} onClose={() => setPreviewSuiteId("")} />}
  </div>;
}
