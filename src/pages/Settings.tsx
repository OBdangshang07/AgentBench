import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { Archive, CheckCircle2, Database, FileDown, HardDrive, Save, ShieldAlert, TerminalSquare, Upload } from "lucide-react";
import { api, API_BASE } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { ModelConfig, Runner, SystemStatus } from "../types";
import { Button, Card, ErrorBlock, Field, LoadingBlock } from "../components/ui";
import { useWorkspaceUx } from "../components/WorkspaceUx";

export default function SettingsPage() {
  const ux = useWorkspaceUx();
  const status = useApi<SystemStatus>("/system/status");
  const models = useApi<ModelConfig[]>("/models");
  const runners = useApi<Runner[]>("/runners");
  const [nativeEnabled, setNativeEnabled] = useState(false);
  const [maxRuntime, setMaxRuntime] = useState(7200);
  const [judgeModel, setJudgeModel] = useState("");
  const [judgeRunner, setJudgeRunner] = useState("");
  const [judgeSaveState, setJudgeSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [judgeSaveError, setJudgeSaveError] = useState("");
  const judgeQueue = useRef<Promise<unknown>>(Promise.resolve());
  const latestJudge = useRef({ model: "", runner: "" });
  const [message, setMessage] = useState<{ text: string; kind: "success" | "error" } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (status.data) {
      setNativeEnabled(status.data.native_cli_enabled);
      setMaxRuntime(status.data.settings.default_max_runtime_seconds ?? 7200);
      setJudgeModel(status.data.settings.judge_model_id ?? "");
      setJudgeRunner(status.data.settings.judge_runner_id ?? "");
      latestJudge.current = { model: status.data.settings.judge_model_id ?? "", runner: status.data.settings.judge_runner_id ?? "" };
    }
  }, [status.data]);
  if (status.loading) return <LoadingBlock />;
  if (status.error || !status.data) return <ErrorBlock message={status.error ?? "读取本地状态失败"} retry={() => void status.refresh()} />;

  async function save() {
    setBusy(true); setMessage(null);
    try {
      await api("/settings", { method: "PATCH", body: JSON.stringify({ allow_native_cli: nativeEnabled, default_max_runtime_seconds: maxRuntime, judge_model_id: judgeModel || null, judge_runner_id: judgeRunner || null }) });
      setMessage({ text: "设置已保存", kind: "success" }); await status.refresh();
    } catch (value) { setMessage({ text: value instanceof Error ? value.message : "保存失败", kind: "error" }); } finally { setBusy(false); }
  }
  function saveJudge(model: string, runner: string) {
    setJudgeModel(model); setJudgeRunner(runner); setJudgeSaveState("saving"); setJudgeSaveError("");
    latestJudge.current = { model, runner };
    judgeQueue.current = judgeQueue.current.catch(() => undefined).then(async () => {
      try {
        await api("/settings", { method: "PATCH", body: JSON.stringify({ judge_model_id: model || null, judge_runner_id: runner || null }) });
        if (latestJudge.current.model === model && latestJudge.current.runner === runner) setJudgeSaveState("saved");
      } catch (value) {
        if (latestJudge.current.model === model && latestJudge.current.runner === runner) {
          setJudgeSaveState("error"); setJudgeSaveError(value instanceof Error ? value.message : "自动保存失败");
        }
      }
    });
  }
  async function backup() {
    setBusy(true); setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/system/backup`, { method: "POST" });
      if (!response.ok) throw new Error("备份失败");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
      anchor.href = url; anchor.download = response.headers.get("content-disposition")?.match(/filename="(.+)"/)?.[1] ?? "agentbench-backup.zip"; anchor.click();
      URL.revokeObjectURL(url); setMessage({ text: "备份已创建并保存", kind: "success" });
    } catch (value) { setMessage({ text: value instanceof Error ? value.message : "备份失败", kind: "error" }); } finally { setBusy(false); }
  }
  async function restore(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !await ux.confirm({
      title: "恢复本地数据库？",
      message: "恢复会替换当前数据库。平台会先自动创建安全备份，但正在运行的任务应先停止。",
      detail: file.name,
      confirmLabel: "校验并恢复",
      tone: "danger",
    })) return;
    setBusy(true); setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/system/restore`, { method: "POST", headers: { "Content-Type": "application/zip" }, body: file });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "恢复失败");
      setMessage({ text: `恢复完成；恢复前安全备份：${result.safety_backup}`, kind: "success" });
      await Promise.all([status.refresh(), models.refresh(), runners.refresh()]);
    } catch (value) { setMessage({ text: value instanceof Error ? value.message : "恢复失败", kind: "error" }); } finally { setBusy(false); }
  }
  async function exportDiagnostics() {
    setBusy(true); setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/system/diagnostics`);
      if (!response.ok) throw new Error("生成诊断报告失败");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `agentbench-diagnostics-${new Date().toISOString().slice(0, 10)}.json`; anchor.click();
      URL.revokeObjectURL(url);
      setMessage({ text: "诊断报告已导出；报告不包含 API 密钥、提示词或对话正文", kind: "success" });
    } catch (value) {
      setMessage({ text: value instanceof Error ? value.message : "诊断报告导出失败", kind: "error" });
    } finally { setBusy(false); }
  }
  return (
    <div className="ab-view ab-secondary-view ab-settings-view">
      <header className="ab-view-header">
        <div className="ab-view-title"><span className="ab-view-index">07 / LOCAL SYSTEM</span><div><h1>本地设置</h1><p>执行安全、匿名裁判与数据备份全部保留在这台设备。</p></div></div>
        <div className="ab-header-meta"><span className="ab-meta-pill"><i />LOCAL ONLY</span><button className="ab-run-button" type="button" disabled={busy} onClick={() => void save()}><Save size={14} />{busy ? "保存中…" : "保存设置"}</button></div>
      </header>
      {message && <div className={message.kind === "success" ? "success-banner" : "error-banner settings-message"}>{message.text}</div>}
      <div className="ab-settings-body">
        <aside className="ab-settings-index"><div className="ab-pane-label">SYSTEM MAP</div><a href="#runtime"><span>01</span><div><strong>运行环境</strong><small>数据库、Docker、Agent</small></div></a><a href="#native"><span>02</span><div><strong>原生执行</strong><small>权限与安全看门狗</small></div></a><a href="#judge"><span>03</span><div><strong>匿名裁判</strong><small>模型与 Runner 路由</small></div></a><a href="#data"><span>04</span><div><strong>数据迁移</strong><small>备份、恢复与目录</small></div></a><a href="#diagnostics"><span>05</span><div><strong>诊断支持</strong><small>健康快照与故障信息</small></div></a><section className="ab-side-contract"><label>PRIVACY BOUNDARY</label><strong>DEVICE-LOCAL</strong><p>数据库、工作区、证据与密钥不经过 AgentBench 服务端。</p></section></aside>
        <div className="settings-grid ab-settings-grid">
        <div className="ab-settings-column">
        <Card id="runtime"><div className="card-header"><div><span className="section-kicker">01 / RUNTIME</span><h2>运行环境</h2></div><HardDrive size={19} /></div><div className="status-list"><div><Database size={18} /><div><strong>SQLite 数据库</strong><span>{status.data.database.path}</span></div><CheckCircle2 className="text-green" size={18} /></div><div><ShieldAlert size={18} /><div><strong>Docker 安全沙箱</strong><span>{status.data.docker.available ? status.data.docker.executable : "未检测到 Docker Desktop；命令任务将被阻止"}</span></div><span className={status.data.docker.available ? "dot dot-green" : "dot dot-amber"}>{status.data.docker.available ? "就绪" : "受限"}</span></div>{status.data.runners.map((runner) => <div key={runner.id}><TerminalSquare size={18} /><div><strong>{runner.name}</strong><span>{runner.capability.warning ?? runner.capability.error ?? runner.capability.version ?? "未检测到可执行文件"}</span>{runner.capability.install_command && <code>{runner.capability.install_command}</code>}</div><span className={runner.capability.installed && !runner.capability.warning ? "dot dot-green" : "dot dot-amber"}>{runner.capability.installed ? runner.capability.warning ? "需优化" : "可用" : runner.capability.desktop_installed ? "缺 CLI" : "缺失"}</span></div>)}</div></Card>
        <Card id="diagnostics"><div className="card-header"><div><span className="section-kicker">05 / SUPPORT</span><h2>诊断与支持</h2></div><FileDown size={19} /></div><p className="setting-copy">一键导出版本、数据库完整性、运行环境、MCP 健康和最近失败。不会包含 API 密钥、MCP 环境变量、提示词或对话正文。</p><div className="backup-actions"><Button variant="secondary" busy={busy} onClick={() => void exportDiagnostics()}><FileDown size={16} /> 导出诊断报告</Button></div></Card>
        </div>
        <div className="ab-settings-column">
        <Card id="native"><div className="card-header"><div><span className="section-kicker">02 / NATIVE AGENTS</span><h2>原生 CLI Agent</h2></div></div><p className="setting-copy">Codex、Claude Code、Kimi Code 等在宿主机上使用自身权限系统。启用后，平台才允许启动原生 CLI 赛道。</p><label className="switch-row"><div><strong>允许原生 CLI Runner</strong><span>仅在你信任已安装的 Agent CLI 时开启</span></div><input type="checkbox" checked={nativeEnabled} onChange={(event) => setNativeEnabled(event.target.checked)} /><i /></label><Field label="运行安全看门狗" hint="它不是评分超时；达到时间只会停止疑似永久卡死的进程，并按环境失败处理。"><select value={maxRuntime} onChange={(event) => setMaxRuntime(Number(event.target.value))}><option value={0}>不限制</option><option value={1800}>30 分钟</option><option value={3600}>1 小时</option><option value={7200}>2 小时（推荐）</option><option value={14400}>4 小时</option></select></Field><div className="warning-box"><ShieldAlert size={17} /><span>原生 Agent 与 Docker 沙箱不是同一安全边界。平台会清理继承环境并限定工作目录，但 CLI 本身仍必须启用安全模式。</span></div></Card>
        <Card id="judge"><div className="card-header"><div><span className="section-kicker">03 / JUDGE</span><h2>匿名 AI 裁判</h2></div><span className={`autosave-status autosave-${judgeSaveState}`}>{judgeSaveState === "saving" ? "正在保存…" : judgeSaveState === "saved" ? "已自动保存" : judgeSaveState === "error" ? "保存失败" : "选择后自动保存"}</span></div><div className="form-grid one-column"><Field label="裁判模型"><select value={judgeModel} onChange={(event) => saveJudge(event.target.value, latestJudge.current.runner)}><option value="">不启用主观评分</option>{models.data?.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></Field><Field label="裁判 Agent Runner"><select value={judgeRunner} onChange={(event) => saveJudge(latestJudge.current.model, event.target.value)}><option value="">选择 Runner</option>{runners.data?.map((runner) => <option key={runner.id} value={runner.id}>{runner.name}</option>)}</select></Field><small>裁判输入会移除参测身份；同一模型不能为自己评分。复杂项目可配置原生裁判 Agent。</small>{judgeSaveError && <div className="form-error">{judgeSaveError}</div>}</div></Card>
        <Card id="data"><div className="card-header"><div><span className="section-kicker">04 / DATA</span><h2>备份与迁移</h2></div><Archive size={19} /></div><p className="setting-copy">备份包含一致性 SQLite 快照和校验清单，不包含 Windows Credential Manager 中的 API 密钥。恢复前会再次创建安全备份。</p><div className="data-path"><span>本地数据目录</span><code>{status.data.data_dir}</code></div><div className="backup-actions"><Button variant="secondary" busy={busy} onClick={() => void backup()}><Archive size={16} /> 创建 ZIP 备份</Button><label className="button button-secondary"><Upload size={16} /> 校验并恢复<input type="file" accept=".zip,application/zip" hidden onChange={(event) => void restore(event)} /></label></div></Card>
        </div>
        </div>
      </div>
    </div>
  );
}
