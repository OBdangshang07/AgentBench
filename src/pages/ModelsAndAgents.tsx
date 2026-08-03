import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Archive, ArchiveRestore, Bot, CheckCircle2, CircleDollarSign, Cpu, Download, KeyRound, PackageCheck, Plus, Radio, RefreshCw, Search, ShieldCheck, TerminalSquare, Trash2, Unplug, Zap } from "lucide-react";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { DiscoveredModel, ModelConfig, ModelDiscoveryResult, ModelSource, Runner, RunnerInstallJob } from "../types";
import { Button, Card, ErrorBlock, Field, LoadingBlock, Modal, PageHeader } from "../components/ui";

const runnerMeta: Record<Runner["runner_type"], { label: string; description: string }> = {
  unified: { label: "公平基准", description: "平台统一控制工具、步骤和工作区，适合比较底层模型本身。" },
  codex_cli: { label: "原生编码 Agent", description: "通过 Codex CLI 执行完整项目任务，使用 Codex 自身登录和工具能力。" },
  claude_code_cli: { label: "原生编码 Agent", description: "通过 Claude Code 执行项目并返回结构化轨迹，支持其兼容模型映射。" },
  opencode_cli: { label: "开放 Agent", description: "通过 OpenCode run 模式执行，适合比较多供应商模型和开放工具链。" },
  reasonix_cli: { label: "推理 Agent", description: "通过 Reasonix 非交互运行模式执行，保留结构化输出与工作区证据。" },
  gemini_cli: { label: "原生编码 Agent", description: "通过 Gemini CLI 的 stream-json 模式执行长上下文和项目任务。" },
  aider_cli: { label: "代码编辑 Agent", description: "通过 Aider 消息模式修改项目，适合代码库维护与隐藏测试。" },
  kimi_code_cli: { label: "原生编码 Agent", description: "通过 Kimi Code CLI 非交互模式执行长上下文与完整项目任务。" },
  qoder_cli: { label: "原生编码 Agent", description: "通过 Qoder 非交互 CLI 执行；仅安装桌面 IDE 时会明确提示缺少自动评测 CLI。" },
  command: { label: "兼容适配器", description: "使用参数数组接入任意非交互 CLI，不经过 Shell 字符串拼接。" },
};

const modelSources: Array<{
  value: ModelSource;
  label: string;
  description: string;
  runnerType?: Runner["runner_type"];
}> = [
  { value: "api", label: "API 接口", description: "从 OpenAI / Anthropic 兼容模型目录读取" },
  { value: "codex-cli", label: "Codex CLI", description: "读取 Codex 本机模型缓存与 Provider 配置", runnerType: "codex_cli" },
  { value: "claude-code", label: "Claude Code", description: "读取 Claude Code 模型映射与内置别名", runnerType: "claude_code_cli" },
  { value: "opencode-cli", label: "OpenCode", description: "调用 OpenCode 模型目录", runnerType: "opencode_cli" },
  { value: "reasonix-cli", label: "Reasonix", description: "读取本机 Reasonix Provider 与底层模型映射", runnerType: "reasonix_cli" },
  { value: "gemini-cli", label: "Gemini CLI", description: "识别本机 Gemini 能力", runnerType: "gemini_cli" },
  { value: "aider-cli", label: "Aider", description: "识别本机 Aider 能力", runnerType: "aider_cli" },
  { value: "kimi-code", label: "Kimi Code", description: "识别 Kimi Code CLI 模型或当前登录配置", runnerType: "kimi_code_cli" },
  { value: "qoder-cli", label: "Qoder", description: "识别 Qoder 非交互 CLI；桌面版不会被误当成 CLI", runnerType: "qoder_cli" },
];

function discoveryValue(model: DiscoveredModel): string {
  return JSON.stringify([model.provider_id, model.id]);
}

function isAgentProvider(provider: string): boolean {
  return modelSources.some((item) => item.value !== "api" && item.value === provider);
}

export default function ModelsAndAgents() {
  const [tab, setTab] = useState<"models" | "runners">("models");
  const [modelModal, setModelModal] = useState(false);
  const [runnerModal, setRunnerModal] = useState(false);
  const models = useApi<ModelConfig[]>("/models?include_archived=true");
  const runners = useApi<Runner[]>("/runners", 10_000);

  return (
    <div className="page">
      <PageHeader
        eyebrow="PARTICIPANTS"
        title="参测配置"
        description="先配置“测谁”，再选择“让它怎样工作”。模型身份与 Agent Runner 相互独立，可自由组合。"
        actions={
          <Button onClick={() => (tab === "models" ? setModelModal(true) : setRunnerModal(true))}>
            <Plus size={16} /> {tab === "models" ? "添加模型" : "添加 Runner"}
          </Button>
        }
      />
      <div className="segmented">
        <button className={tab === "models" ? "active" : ""} onClick={() => setTab("models")}><Cpu size={16} /> 1. 参测模型</button>
        <button className={tab === "runners" ? "active" : ""} onClick={() => setTab("runners")}><TerminalSquare size={16} /> 2. 执行 Agent</button>
      </div>

      {tab === "models" ? (
        <ModelsPanel state={models} />
      ) : (
        <RunnersPanel state={runners} />
      )}

      {modelModal && <ModelModal runners={runners.data ?? []} onClose={() => setModelModal(false)} onSaved={() => { setModelModal(false); void models.refresh(); }} />}
      {runnerModal && <RunnerModal onClose={() => setRunnerModal(false)} onSaved={() => { setRunnerModal(false); void runners.refresh(); }} />}
    </div>
  );
}

function ModelsPanel({ state }: { state: ReturnType<typeof useApi<ModelConfig[]>> }) {
  const [testing, setTesting] = useState<string | null>(null);
  const [message, setMessage] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [pricingModel, setPricingModel] = useState<ModelConfig | null>(null);
  if (state.loading) return <LoadingBlock />;
  if (state.error || !state.data) return <ErrorBlock message={state.error ?? "读取模型失败"} retry={() => void state.refresh()} />;

  const activeModels = state.data.filter((model) => model.enabled);
  const archivedModels = state.data.filter((model) => !model.enabled);
  const visibleModels = showArchived ? archivedModels : activeModels;

  async function test(id: string) {
    setTesting(id);
    try {
      const result = await api<{ response: string; latency_ms: number; tokens_input?: number; tokens_output?: number }>(`/models/${id}/test`, { method: "POST" });
      const tokens = (result.tokens_input ?? 0) + (result.tokens_output ?? 0);
      setMessage((old) => ({ ...old, [id]: `真实任务成功 · ${result.latency_ms} ms${tokens ? ` · ${tokens} Token` : ""} · ${result.response}` }));
    } catch (error) {
      setMessage((old) => ({ ...old, [id]: error instanceof Error ? error.message : "连接失败" }));
    } finally {
      setTesting(null);
    }
  }

  async function remove(model: ModelConfig) {
    if (model.builtin || !window.confirm(`移除模型“${model.name}”？已有实验记录时会安全归档，否则永久删除。`)) return;
    setNotice("");
    try {
      const result = await api<{ action: "archived" | "deleted"; run_references: number }>(`/models/${model.id}`, { method: "DELETE" });
      setNotice(result.action === "archived" ? `“${model.name}”已有 ${result.run_references} 条运行记录，已归档并从参测下拉中移除。` : `“${model.name}”已永久删除。`);
      await state.refresh();
    } catch (error) {
      setNotice(error instanceof Error ? `移除失败：${error.message}` : "移除模型失败");
    }
  }

  async function restore(model: ModelConfig) {
    setNotice("");
    try {
      await api(`/models/${model.id}`, { method: "PATCH", body: JSON.stringify({ enabled: true }) });
      setNotice(`“${model.name}”已恢复，可重新用于实验和裁判。`);
      await state.refresh();
    } catch (error) {
      setNotice(error instanceof Error ? `恢复失败：${error.message}` : "恢复模型失败");
    }
  }

  return (
    <><div className="configuration-explainer"><div><Cpu size={17} /><span><strong>模型身份</strong>决定模型 ID、接口或 CLI 模型名。</span></div><div><Zap size={17} /><span><strong>执行方式</strong>在创建实验时选择，不必为每个 Agent 重复添加模型。</span></div></div>
      <div className="model-management-bar"><div><strong>{activeModels.length}</strong><span>个启用模型</span><small>{archivedModels.length} 个已归档</small></div><Button variant="secondary" onClick={() => setShowArchived((value) => !value)}>{showArchived ? <Cpu size={15} /> : <Archive size={15} />}{showArchived ? "返回启用模型" : `管理归档 (${archivedModels.length})`}</Button></div>
      {notice && <div className="inline-notice">{notice}</div>}
      <div className="model-grid">
      {visibleModels.map((model) => (
        <Card key={model.id} className={`model-card ${model.enabled ? "" : "model-card-archived"}`}>
          <div className="model-card-top">
            <div className={`model-logo provider-${model.api_style}`}><Bot size={22} /></div>
            <div className="model-state"><span className={`dot ${model.enabled ? "dot-green" : "dot-amber"}`}>{model.enabled ? "启用" : "已归档"}</span></div>
          </div>
          <h3>{model.name}</h3>
          <p>{model.provider} · <code>{model.model_name}</code></p>
          <div className="model-meta">
            <span><KeyRound size={14} /> {model.api_style === "mock" ? "无需密钥" : isAgentProvider(model.provider) ? "使用 Agent 登录" : model.has_secret ? "凭据已保存" : "未设置密钥"}</span>
            <span><Radio size={14} /> {model.settings.max_tokens?.toLocaleString() ?? "—"} max tokens</span>
            <span><CircleDollarSign size={14} /> {model.input_price || model.output_price ? `$${model.input_price} / $${model.output_price} 每 1M` : "未配置价格 · 费用无法估算"}</span>
          </div>
          {message[model.id] && <div className="inline-message">{message[model.id]}</div>}
          <div className="card-actions">
            {model.enabled ? <Button variant="secondary" busy={testing === model.id} onClick={() => void test(model.id)}>执行真实测试</Button> : <Button variant="secondary" onClick={() => void restore(model)}><ArchiveRestore size={15} /> 恢复模型</Button>}
            {model.enabled && model.api_style !== "mock" && <button className="icon-button" title="配置 Token 单价并回算历史费用" onClick={() => setPricingModel(model)}><CircleDollarSign size={16} /></button>}
            {!model.builtin && model.enabled && <button className="icon-button danger" title="删除或归档" onClick={() => void remove(model)}><Trash2 size={16} /></button>}
          </div>
        </Card>
      ))}
      {!visibleModels.length && <Card className="model-empty-state"><Archive size={24} /><strong>{showArchived ? "暂无归档模型" : "暂无启用模型"}</strong><span>{showArchived ? "移除有历史记录的模型后会显示在这里。" : "点击右上角添加模型开始配置。"}</span></Card>}
    </div>{pricingModel && <PricingModal model={pricingModel} onClose={() => setPricingModel(null)} onSaved={async () => { setPricingModel(null); await state.refresh(); setNotice("价格已保存，能够取得 Token 的历史运行费用已自动回算。"); }} />}</>
  );
}

function PricingModal({ model, onClose, onSaved }: { model: ModelConfig; onClose: () => void; onSaved: () => void | Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    try {
      await api(`/models/${model.id}`, { method: "PATCH", body: JSON.stringify({ input_price: Number(form.get("input_price")), output_price: Number(form.get("output_price")) }) });
      await onSaved();
    } catch (value) { setError(value instanceof Error ? value.message : "价格保存失败"); setBusy(false); }
  }
  return <Modal title={`费用配置 · ${model.name}`} description="填写美元 / 1M Token。原生 Agent 若直接上报实际费用，将优先使用 Agent 数据；否则按这里的单价估算并回算历史记录。" onClose={onClose}><form className="form-grid one-column" onSubmit={(event) => void submit(event)}><Field label="输入价格 / 1M Token"><input name="input_price" type="number" min="0" step="0.000001" defaultValue={model.input_price} /></Field><Field label="输出价格 / 1M Token"><input name="output_price" type="number" min="0" step="0.000001" defaultValue={model.output_price} /></Field>{error && <div className="form-error">{error}</div>}<div className="modal-actions"><Button variant="ghost" type="button" onClick={onClose}>取消</Button><Button busy={busy} type="submit">保存并回算</Button></div></form></Modal>;
}

function RunnersPanel({ state }: { state: ReturnType<typeof useApi<Runner[]>> }) {
  const [installRunner, setInstallRunner] = useState<Runner | null>(null);
  if (state.loading) return <LoadingBlock />;
  if (state.error || !state.data) return <ErrorBlock message={state.error ?? "读取 Runner 失败"} retry={() => void state.refresh()} />;
  const readyCount = state.data.filter((runner) => runner.capability.installed).length;
  const quickInstallCount = state.data.filter((runner) => runner.install.supported).length;
  const sorted = [...state.data].sort((left, right) => Number(right.capability.installed) - Number(left.capability.installed));
  return (
    <><div className="runner-summary-strip"><div><CheckCircle2 size={18} /><strong>{readyCount}</strong><span>个 Agent 已就绪</span><i>{quickInstallCount} 个支持快捷安装</i></div><p>安装器仅执行内置白名单命令；完成后会自动重新检测本机 Agent。</p><Button variant="secondary" onClick={() => void state.refresh()}><RefreshCw size={14} /> 重新检测</Button></div><div className="runner-list">
      {sorted.map((runner) => {
        const meta = runnerMeta[runner.runner_type];
        const desktopOnly = runner.capability.desktop_installed && !runner.capability.installed;
        const statusLabel = runner.capability.installed
          ? runner.capability.warning ? "可运行 · 待优化" : "可以运行"
          : desktopOnly ? "桌面版已装 · CLI 缺失" : "本机未检测";
        return (
        <Card key={runner.id} className="runner-card">
          <div className={`runner-icon runner-${runner.runner_type}`}><TerminalSquare size={20} /></div>
          <div className="runner-body">
            <div className="runner-title"><h3>{runner.name}</h3><span className="runner-kind">{meta.label}</span></div>
            <p>{meta.description}</p>
            <div className="tag-row">
              {runner.tools.map((tool) => <span className="tag" key={tool}>{tool}</span>)}
              <span className="tag">{runner.model_override_supported ? "支持模型覆盖" : "固定模型"}</span>
            </div>
          </div>
          <div className={`runner-capability ${runner.capability.installed && !runner.capability.warning ? "ready" : "missing"}`}>
            {runner.capability.installed ? <CheckCircle2 size={18} /> : <Unplug size={18} />}
            <strong>{statusLabel}</strong>
            <span title={runner.capability.error ?? runner.capability.warning}>{runner.capability.warning ?? runner.capability.error ?? runner.capability.version ?? runner.executable ?? "等待本机环境"}</span>
            {runner.install.supported ? (
              <button className="runner-install-button" disabled={!runner.install.available} title={runner.install.unavailable_reason ?? runner.install.command} onClick={() => setInstallRunner(runner)}>
                <Download size={13} /> {runner.capability.installed ? "升级 CLI" : runner.install.available ? "快捷安装" : `缺少 ${runner.install.manager}`}
              </button>
            ) : runner.install.manual_instructions ? <small className="runner-manual-note" title={runner.install.manual_instructions}>仅支持手动配置</small> : null}
          </div>
        </Card>
      );})}
    </div>{installRunner && <RunnerInstallModal runner={installRunner} onClose={() => setInstallRunner(null)} onCompleted={() => state.refresh()} />}</>
  );
}

function RunnerInstallModal({ runner, onClose, onCompleted }: { runner: Runner; onClose: () => void; onCompleted: () => void | Promise<void> }) {
  const [job, setJob] = useState<RunnerInstallJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const refreshedJob = useRef<string | null>(null);
  const active = job?.status === "queued" || job?.status === "running";

  useEffect(() => {
    if (!job || !active) return;
    let disposed = false;
    async function poll() {
      try {
        const next = await api<RunnerInstallJob>(`/runners/installations/${job!.id}`);
        if (disposed) return;
        setJob(next);
        if ((next.status === "completed" || next.status === "failed") && refreshedJob.current !== next.id) {
          refreshedJob.current = next.id;
          await onCompleted();
        }
      } catch (value) {
        if (!disposed) setError(value instanceof Error ? value.message : "读取安装进度失败");
      }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), 900);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [active, job?.id, onCompleted]);

  async function start() {
    setStarting(true); setError("");
    try {
      const next = await api<RunnerInstallJob>(`/runners/${runner.id}/install`, { method: "POST" });
      setJob(next);
    } catch (value) {
      setError(value instanceof Error ? value.message : "启动安装失败");
    } finally {
      setStarting(false);
    }
  }

  const finished = job?.status === "completed" || job?.status === "failed";
  return (
    <Modal title={`${runner.capability.installed ? "升级" : "安装"} · ${runner.name}`} description="安装会修改当前电脑的全局 CLI 环境，请确认来源与完整命令。" onClose={active ? () => undefined : onClose}>
      <div className="runner-install-modal">
        <div className="install-security-note"><ShieldCheck size={20} /><span><strong>白名单安全执行</strong><small>参数数组直接传给包管理器，不经过 Shell，也不接受自定义命令。</small></span></div>
        <div className="install-command-card"><span>软件来源</span><strong>{runner.install.source}</strong><span>将执行命令</span><code>{runner.install.command}</code></div>
        {job && <div className={`install-job-status install-job-${job.status}`}>
          {job.status === "completed" ? <PackageCheck size={18} /> : active ? <RefreshCw className="spin" size={18} /> : <Unplug size={18} />}
          <span><strong>{job.status === "queued" ? "等待安装" : job.status === "running" ? "正在安装" : job.status === "completed" ? "安装完成，已重新检测" : "安装失败"}</strong><small>{job.exit_code == null ? `由 ${job.manager} 执行` : `退出码 ${job.exit_code} · ${(job.duration_ms / 1000).toFixed(1)} 秒`}</small></span>
        </div>}
        {job && <div className="install-output-grid"><div><span>标准输出</span><pre>{job.stdout || "等待安装器输出…"}</pre></div><div><span>错误输出</span><pre>{job.stderr || job.error || "暂无错误输出"}</pre></div></div>}
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          {!job && <><Button variant="ghost" onClick={onClose}>取消</Button><Button busy={starting} onClick={() => void start()}><Download size={15} /> 确认并开始</Button></>}
          {job && active && <Button busy disabled>安装进行中</Button>}
          {finished && <Button variant={job.status === "completed" ? "primary" : "secondary"} onClick={onClose}>完成</Button>}
        </div>
      </div>
    </Modal>
  );
}

function ModelModal({ runners, onClose, onSaved }: { runners: Runner[]; onClose: () => void; onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const initialSource = modelSources.find((item) => item.runnerType && runners.some((runner) => runner.runner_type === item.runnerType && runner.capability.installed))?.value ?? "api";
  const [source, setSource] = useState<ModelSource>(initialSource);
  const [style, setStyle] = useState<"openai" | "anthropic">("openai");
  const [provider, setProvider] = useState("openai-compatible");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [discovery, setDiscovery] = useState<ModelDiscoveryResult | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [selectedValue, setSelectedValue] = useState("");
  const [manual, setManual] = useState(false);
  const [manualModel, setManualModel] = useState("");
  const [manualProvider, setManualProvider] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const requestSequence = useRef(0);

  const groupedModels = useMemo(() => {
    const groups = new Map<string, DiscoveredModel[]>();
    for (const model of discovery?.models ?? []) {
      const key = model.provider_label || model.provider_id;
      groups.set(key, [...(groups.get(key) ?? []), model]);
    }
    return [...groups.entries()];
  }, [discovery]);

  const selectedModel = discovery?.models.find((model) => discoveryValue(model) === selectedValue);
  const sourceMeta = modelSources.find((item) => item.value === source) ?? modelSources[0];

  async function runDiscovery(targetSource: ModelSource = source) {
    const sequence = ++requestSequence.current;
    setDiscovering(true);
    setError("");
    try {
      const result = await api<ModelDiscoveryResult>("/models/discover", {
        method: "POST",
        body: JSON.stringify({
          source: targetSource,
          provider: provider.trim() || "openai-compatible",
          api_style: style,
          base_url: targetSource === "api" && baseUrl.trim() ? baseUrl.trim() : null,
          api_key: targetSource === "api" && apiKey ? apiKey : null,
        }),
      });
      if (requestSequence.current !== sequence) return;
      setDiscovery(result);
      const preferred = result.models.find((model) => model.configured) ?? result.models[0];
      if (preferred) {
        setSelectedValue(discoveryValue(preferred));
        setManualProvider(preferred.provider_id);
        setManual(false);
        if (!nameTouched) setDisplayName(`${preferred.label} via ${result.source_label}`);
      } else {
        setSelectedValue("");
        setManualProvider(result.providers.find((item) => item.is_default)?.id ?? result.providers[0]?.id ?? "");
        setManual(true);
      }
    } catch (value) {
      if (requestSequence.current !== sequence) return;
      setDiscovery(null);
      setManual(true);
      setError(value instanceof Error ? value.message : "模型识别失败");
    } finally {
      if (requestSequence.current === sequence) setDiscovering(false);
    }
  }

  useEffect(() => {
    setDiscovery(null);
    setSelectedValue("");
    setManual(false);
    setManualModel("");
    setManualProvider("");
    if (source !== "api") void runDiscovery(source);
    return () => { requestSequence.current += 1; };
    // API 模式由用户填完地址和凭据后主动识别，避免输入过程中发送请求。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  function chooseModel(value: string) {
    setSelectedValue(value);
    const chosen = discovery?.models.find((model) => discoveryValue(model) === value);
    if (!chosen) return;
    setManualProvider(chosen.provider_id);
    if (!nameTouched) setDisplayName(`${chosen.label} via ${discovery?.source_label ?? sourceMeta.label}`);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    try {
      const modelName = (manual ? manualModel : selectedModel?.id)?.trim();
      if (!modelName) throw new Error("请从识别结果中选择模型，或切换为手动输入");
      const resolvedName = displayName.trim() || `${modelName} via ${sourceMeta.label}`;
      const agentProvider = source === "api" ? null : (manual ? manualProvider : selectedModel?.provider_id) || null;
      await api("/models", {
        method: "POST",
        body: JSON.stringify({
          name: resolvedName,
          provider: source === "api" ? provider.trim() || "openai-compatible" : source,
          model_name: modelName,
          agent_provider: agentProvider,
          base_url: source === "api" && baseUrl.trim() ? baseUrl.trim() : null,
          api_style: source === "api" ? style : "openai",
          api_key: source === "api" && apiKey ? apiKey : null,
          temperature: Number(form.get("temperature")), max_tokens: Number(form.get("max_tokens")),
          input_price: Number(form.get("input_price")), output_price: Number(form.get("output_price")),
        }),
      });
      onSaved();
    } catch (value) { setError(value instanceof Error ? value.message : "保存失败"); setBusy(false); }
  }
  return (
    <Modal title="添加参测模型" description="先选择 API 或 Agent，AgentBench 会在本机识别可用模型；密钥不会显示在识别结果中。" onClose={onClose}>
      <form className="form-grid" onSubmit={(event) => void submit(event)}>
        <Field label="接入来源" hint={sourceMeta.description}>
          <select value={source} onChange={(event) => setSource(event.target.value as ModelSource)}>
            {modelSources.map((item) => {
              const capability = item.runnerType ? runners.find((runner) => runner.runner_type === item.runnerType)?.capability : null;
              const state = item.value === "api" ? "" : capability?.installed ? " · 已安装" : " · 未检测";
              return <option key={item.value} value={item.value}>{item.label}{state}</option>;
            })}
          </select>
        </Field>
        <Field label="显示名称"><input value={displayName} onChange={(event) => { setDisplayName(event.target.value); setNameTouched(true); }} placeholder="选择模型后自动生成，也可修改" /></Field>

        {source === "api" && <>
          <Field label="供应商"><input value={provider} onChange={(event) => setProvider(event.target.value)} required placeholder="openai-compatible" /></Field>
          <Field label="API 协议"><select value={style} onChange={(event) => setStyle(event.target.value as typeof style)}><option value="openai">OpenAI compatible</option><option value="anthropic">Anthropic</option></select></Field>
          <Field label="Base URL" hint="留空使用协议默认地址"><input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} type="url" placeholder="https://api.example.com/v1" /></Field>
          <Field label="API Key"><input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" autoComplete="off" /></Field>
        </>}

        <div className="model-discovery-bar">
          <div><Search size={16} /><span><strong>{discovery ? `识别到 ${discovery.models.length} 个模型` : "等待识别模型"}</strong><small>{discovery?.capability.version ?? (source === "api" ? "填写接口信息后开始识别" : sourceMeta.description)}</small></span></div>
          <Button variant="secondary" type="button" busy={discovering} onClick={() => void runDiscovery()}><RefreshCw size={14} /> {discovery ? "刷新" : "识别模型"}</Button>
        </div>

        <div className="form-span-two model-choice-area">
          <Field label="模型" hint={manual ? "保留手动输入，兼容尚未出现在目录中的模型" : "按 Agent Provider 分组；选择后会保存对应路由"}>
            {manual ? (
              <input value={manualModel} onChange={(event) => setManualModel(event.target.value)} required placeholder="例如 gpt-5.6-sol / fable-5" />
            ) : (
              <select value={selectedValue} onChange={(event) => chooseModel(event.target.value)} required disabled={!discovery?.models.length}>
                {!discovery?.models.length && <option value="">请先识别可用模型</option>}
                {groupedModels.map(([group, models]) => <optgroup key={group} label={group}>{models.map((model) => <option key={discoveryValue(model)} value={discoveryValue(model)}>{model.label}{model.label !== model.id ? ` · ${model.id}` : ""}{model.configured ? " · 当前配置" : ""}</option>)}</optgroup>)}
              </select>
            )}
          </Field>
          <label className="manual-model-toggle"><input type="checkbox" checked={manual} onChange={(event) => setManual(event.target.checked)} /> 手动填写未列出的模型</label>
        </div>

        {source !== "api" && manual && (discovery?.providers.length ?? 0) > 0 && <Field label="Agent Provider" hint="Codex 多 Provider 场景会同时保存此路由"><select value={manualProvider} onChange={(event) => setManualProvider(event.target.value)}>{discovery?.providers.map((item) => <option key={item.id} value={item.id}>{item.label}{item.is_default ? " · 默认" : ""}</option>)}</select></Field>}
        {selectedModel && !manual && <div className="model-route-note"><Radio size={14} /><span>模型来源：{selectedModel.source}<br />执行路由：{selectedModel.provider_label}</span></div>}
        {(discovery?.warnings.length ?? 0) > 0 && <div className="model-discovery-warnings">{discovery?.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div>}

        <Field label="Temperature"><input name="temperature" type="number" min="0" max="2" step="0.1" defaultValue="0" /></Field>
        <Field label="最大输出 Token"><input name="max_tokens" type="number" min="64" defaultValue="4096" /></Field>
        <Field label="输入价 / 1M"><input name="input_price" type="number" min="0" step="0.001" defaultValue="0" /></Field>
        <Field label="输出价 / 1M"><input name="output_price" type="number" min="0" step="0.001" defaultValue="0" /></Field>
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions"><Button variant="ghost" type="button" onClick={onClose}>取消</Button><Button busy={busy} type="submit">保存模型</Button></div>
      </form>
    </Modal>
  );
}

function RunnerModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const defaultArgs = useMemo(() => '["{prompt}"]', []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    try {
      await api("/runners", { method: "POST", body: JSON.stringify({
        name: form.get("name"), runner_type: "command", executable: form.get("executable"),
        args: JSON.parse(String(form.get("args"))), tools: ["native-cli"],
        model_override_supported: form.get("model_override") === "on",
      }) });
      onSaved();
    } catch (value) { setError(value instanceof Error ? value.message : "保存失败"); setBusy(false); }
  }
  return (
    <Modal title="添加自定义 Agent Runner" description="命令以参数数组启动，不经过 Shell 拼接；支持 {prompt}、{model_name}、{workspace} 占位符。" onClose={onClose}>
      <form className="form-grid one-column" onSubmit={(event) => void submit(event)}>
        <Field label="Runner 名称"><input name="name" required placeholder="例如 Fable Agent CLI" /></Field>
        <Field label="可执行文件"><input name="executable" required placeholder="agent-cli.exe" /></Field>
        <Field label="参数 JSON 数组"><textarea name="args" rows={4} defaultValue={defaultArgs} /></Field>
        <label className="check-field"><input type="checkbox" name="model_override" defaultChecked /> 允许实验指定底层模型</label>
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions"><Button variant="ghost" type="button" onClick={onClose}>取消</Button><Button busy={busy} type="submit">保存 Runner</Button></div>
      </form>
    </Modal>
  );
}
