import { useMemo, useState, type FormEvent } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Box,
  Check,
  FlaskConical,
  Layers3,
  Play,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { formatDate } from "../lib/format";
import { useApi } from "../lib/useApi";
import type { Experiment, ModelConfig, Participant, Runner, Suite } from "../types";
import { Button, Card, ErrorBlock, Field, LoadingBlock, Modal, PageHeader, Score, StatusBadge } from "../components/ui";

export default function Experiments() {
  const state = useApi<Experiment[]>("/experiments", 4_000);
  const [searchParams, setSearchParams] = useSearchParams();
  const [creating, setCreating] = useState(searchParams.get("create") === "1");
  function closeCreator() {
    setCreating(false);
    if (searchParams.has("create")) {
      const next = new URLSearchParams(searchParams);
      next.delete("create");
      setSearchParams(next, { replace: true });
    }
  }
  return (
    <div className="page">
      <PageHeader
        eyebrow="EVALUATION RUNS"
        title="实验与结果"
        description="三步完成评测：选测试强度、组合模型与 Agent、确认运行规模。"
        actions={<Button onClick={() => setCreating(true)}><Plus size={16} /> 新建评测</Button>}
      />
      <div className="experiment-guide">
        <div><span>1</span><strong>选测试集</strong><small>快速、实战或极限</small></div>
        <ArrowRight size={16} />
        <div><span>2</span><strong>组参测者</strong><small>模型 × Agent Runner</small></div>
        <ArrowRight size={16} />
        <div><span>3</span><strong>运行与复盘</strong><small>分数、证据、成本</small></div>
      </div>
      {state.loading ? <LoadingBlock /> : state.error || !state.data ? (
        <ErrorBlock message={state.error ?? "读取失败"} retry={() => void state.refresh()} />
      ) : state.data.length ? (
        <div className="experiment-grid">
          {state.data.map((item) => {
            const progress = item.run_count ? Math.round(((item.finished_count ?? 0) / item.run_count) * 100) : 0;
            return (
              <Card key={item.id} className="experiment-card">
                <div className="experiment-heading"><div className="experiment-icon"><FlaskConical size={20} /></div><StatusBadge status={item.status} /></div>
                <h3>{item.name}</h3><p>{item.suite_name}</p>
                <div className="experiment-stats">
                  <div><span>参测组合</span><strong>{item.participants.length}</strong></div>
                  <div><span>运行任务</span><strong>{item.run_count ?? 0}</strong></div>
                  <div><span>平均分</span><Score value={item.avg_score} /></div>
                </div>
                <div className="progress-line"><i style={{ width: `${progress}%` }} /></div>
                <div className="experiment-footer"><span>{formatDate(item.created_at)} · {progress}%</span><Link to={`/experiments/${item.id}`}>查看结果 <ArrowRight size={15} /></Link></div>
              </Card>
            );
          })}
        </div>
      ) : (
        <div className="inline-empty inline-empty-action"><FlaskConical size={28} /><strong>还没有评测实验</strong><span>先运行 V2 快速上手，几分钟确认整个链路。</span><Button onClick={() => setCreating(true)}><Play size={15} /> 创建第一次评测</Button></div>
      )}
      {creating && <CreateExperiment onClose={closeCreator} onSaved={() => { closeCreator(); void state.refresh(); }} />}
    </div>
  );
}

function Difficulty({ min = 1, max = 1 }: { min?: number; max?: number }) {
  return <span className={`difficulty-dots ${max >= 6 ? "difficulty-dots-ultra" : ""}`} title={max >= 6 ? "Ultra 难度 6" : `难度 ${min}–${max}`}>{[1, 2, 3, 4, 5, 6].map((level) => <i className={level <= max ? "active" : ""} key={level} />)}</span>;
}

function CreateExperiment({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const models = useApi<ModelConfig[]>("/models");
  const runners = useApi<Runner[]>("/runners");
  const suites = useApi<Suite[]>("/suites");
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [suiteId, setSuiteId] = useState("");
  const [participants, setParticipants] = useState<Participant[]>([{ model_id: "", runner_id: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const loading = models.loading || runners.loading || suites.loading;
  const selectedSuite = suites.data?.find((suite) => suite.id === suiteId);
  const suiteGroups = useMemo(() => {
    const all = suites.data ?? [];
    return [
      { label: "综合与强度基准", hint: "快速体验、全量横评与 Ultra 极限挑战", items: all.filter((suite) => !suite.name.startsWith("专项 ·")) },
      { label: "单项能力测试", hint: "只测一个能力方向，便于做针对性横向比较", items: all.filter((suite) => suite.name.startsWith("专项 ·")) },
    ].filter((group) => group.items.length);
  }, [suites.data]);
  const selectedParticipants = useMemo(() => participants.map((participant) => ({
    model: models.data?.find((model) => model.id === participant.model_id),
    runner: runners.data?.find((runner) => runner.id === participant.runner_id),
  })), [models.data, participants, runners.data]);

  function updateParticipant(index: number, patch: Partial<Participant>) {
    setParticipants((items) => items.map((item, position) => position === index ? { ...item, ...patch } : item));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    try {
      const created = await api<Experiment>("/experiments", { method: "POST", body: JSON.stringify({
        name: form.get("name"), suite_id: suiteId, participants,
        repetitions: Number(form.get("repetitions")), concurrency: Number(form.get("concurrency")),
      }) });
      if (form.get("start_now") === "on") await api(`/experiments/${created.id}/start`, { method: "POST" });
      onSaved(); navigate(`/experiments/${created.id}`);
    } catch (value) { setError(value instanceof Error ? value.message : "创建失败"); setBusy(false); }
  }

  const participantReady = participants.every((item) => item.model_id && item.runner_id);
  return (
    <Modal title="创建评测" description="按步骤选择，创建后可立即运行。" onClose={onClose}>
      {loading ? <LoadingBlock /> : (
        <form className="wizard" onSubmit={(event) => void submit(event)}>
          <div className="wizard-progress">
            {["测试强度", "参测组合", "运行确认"].map((label, index) => (
              <div className={step > index + 1 ? "done" : step === index + 1 ? "active" : ""} key={label}>
                <span>{step > index + 1 ? <Check size={13} /> : index + 1}</span><strong>{label}</strong>
              </div>
            ))}
          </div>

          {step === 1 && <div className="wizard-body">
            <div className="wizard-heading"><div><span className="section-kicker">STEP 1</span><h3>你想测到什么程度？</h3></div><small>随时可以创建更多实验，不必一次跑完全部题目。</small></div>
            <div className="suite-groups">
              {suiteGroups.map((group) => <section className="suite-group" key={group.label}>
                <div className="suite-group-heading"><strong>{group.label}</strong><span>{group.hint}</span></div>
                <div className="suite-picker">
                  {group.items.map((suite) => (
                    <button type="button" className={`suite-option${suiteId === suite.id ? " selected" : ""}${(suite.difficulty_max ?? 0) >= 6 ? " suite-option-ultra" : ""}${suite.name.startsWith("专项 ·") ? " suite-option-focus" : ""}`} onClick={() => setSuiteId(suite.id)} key={suite.id}>
                      <div className="suite-option-top"><span className="suite-version">{(suite.difficulty_max ?? 0) >= 6 ? "ULTRA · 3 ROUNDS" : suite.name.startsWith("专项 ·") ? "FOCUS" : `V${suite.version.split(".")[0]}`}</span>{suiteId === suite.id && <Check size={16} />}</div>
                      <strong>{suite.name}</strong><p>{suite.description}</p>
                      <div className="suite-facts">
                        <span><Layers3 size={13} /> {suite.case_count} 题</span>
                        <span><Difficulty min={suite.difficulty_min} max={suite.difficulty_max} /></span>
                        <span><Box size={13} /> {suite.docker_case_count ? `${suite.docker_case_count} 题需 Docker` : "无需 Docker"}</span>
                        {Boolean(suite.judge_case_count) && <span><Sparkles size={13} /> {suite.judge_case_count} 题需裁判</span>}
                      </div>
                    </button>
                  ))}
                </div>
              </section>)}
            </div>
          </div>}

          {step === 2 && <div className="wizard-body">
            <div className="wizard-heading"><div><span className="section-kicker">STEP 2</span><h3>组合模型与执行 Agent</h3></div><small>统一 Agent 用于公平横评；CLI Agent 用于测试完整产品能力。</small></div>
            <div className="participants-field wizard-participants">
              {participants.map((participant, index) => {
                const runner = runners.data?.find((item) => item.id === participant.runner_id);
                return <div className="participant-card" key={index}>
                  <div className="participant-number">{index + 1}</div>
                  <div><label>底层模型</label><select required value={participant.model_id} onChange={(event) => updateParticipant(index, { model_id: event.target.value })}><option value="" disabled>选择模型</option>{models.data?.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></div>
                  <div className="participant-link"><ArrowRight size={15} /></div>
                  <div><label>Agent Runner</label><select required value={participant.runner_id} onChange={(event) => updateParticipant(index, { runner_id: event.target.value })}><option value="" disabled>选择 Agent</option>{runners.data?.map((item) => <option key={item.id} value={item.id}>{item.name}{!item.capability.installed ? " · 本机未检测" : ""}</option>)}</select>{runner && <small className={runner.capability.installed ? "text-ready" : "text-warning"}>{runner.capability.installed ? `已就绪 · ${runner.capability.version ?? "内置"}` : "当前环境不可执行"}</small>}</div>
                  {participants.length > 1 && <button type="button" className="icon-button danger" onClick={() => setParticipants((items) => items.filter((_, i) => i !== index))}><Trash2 size={15} /></button>}
                </div>;
              })}
              <Button type="button" variant="secondary" onClick={() => setParticipants((items) => [...items, { model_id: "", runner_id: "" }])}><Plus size={15} /> 添加参测组合</Button>
            </div>
          </div>}

          {step === 3 && <div className="wizard-body">
            <div className="wizard-heading"><div><span className="section-kicker">STEP 3</span><h3>确认运行规模</h3></div><small>预计任务数会随参测组合和重复次数线性增加。</small></div>
            <div className="review-grid">
              <div className="review-summary">
                <span>测试集</span><strong>{selectedSuite?.name}</strong><small>{selectedSuite?.case_count} 题 · {participants.length} 个参测组合</small>
              </div>
              <div className="review-summary accent">
                <span>预计运行任务</span><strong>{(selectedSuite?.case_count ?? 0) * participants.length}</strong><small>重复次数改变后会自动增加</small>
              </div>
            </div>
            <Field label="实验名称"><input name="name" required defaultValue={`${selectedSuite?.name ?? "能力评测"} · ${new Date().toLocaleDateString("zh-CN")}`} /></Field>
            <div className="form-grid two-columns compact-grid"><Field label="重复次数" hint="建议正式排名至少 3 次"><input name="repetitions" type="number" min="1" max="10" defaultValue="1" /></Field><Field label="并发任务" hint="本机推荐 1–3"><input name="concurrency" type="number" min="1" max="8" defaultValue="2" /></Field></div>
            <label className="start-now"><input type="checkbox" name="start_now" defaultChecked /><span><Play size={16} /><strong>创建后立即运行</strong><small>取消后将保存为草稿，可在详情页手动启动。</small></span></label>
            <div className="participant-review">{selectedParticipants.map((item, index) => <span key={index}><Bot size={13} /> {item.model?.name ?? "未选模型"} <b>×</b> {item.runner?.name ?? "未选 Agent"}</span>)}</div>
          </div>}

          {error && <div className="form-error wizard-error">{error}</div>}
          <div className="wizard-actions">
            <Button type="button" variant="ghost" onClick={step === 1 ? onClose : () => setStep((value) => value - 1)}>{step > 1 && <ArrowLeft size={15} />}{step === 1 ? "取消" : "上一步"}</Button>
            {step < 3 ? <Button type="button" onClick={() => setStep((value) => value + 1)} disabled={step === 1 ? !suiteId : !participantReady}>下一步 <ArrowRight size={15} /></Button> : <Button type="submit" busy={busy}><Play size={15} /> 创建并继续</Button>}
          </div>
        </form>
      )}
    </Modal>
  );
}
