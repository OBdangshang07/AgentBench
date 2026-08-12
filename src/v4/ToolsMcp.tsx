import {
  AlertTriangle,
  Bot,
  Braces,
  Camera,
  Check,
  Copy,
  Database,
  Globe2,
  HardDrive,
  KeyRound,
  Play,
  Plus,
  Power,
  RefreshCw,
  ServerCog,
  TerminalSquare,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { FormEvent, useState } from "react";
import { useWorkspaceUx } from "../components/WorkspaceUx";
import { api, downloadUrl } from "../lib/api";
import { useApi } from "../lib/useApi";
import type { Runner } from "../types";
import type { BrowserSnapshot, BrowserStatus, McpServer, SkillPack, ToolGatewayStatus } from "./types";
import RuntimeProfilesPanel from "./RuntimeProfilesPanel";
import JsonSchemaForm from "./JsonSchemaForm";

const builtinIcons = {
  filesystem: HardDrive,
  "git-workspace": Database,
  browser: Globe2,
  terminal: TerminalSquare,
};

interface McpForm {
  name: string;
  transport: "stdio" | "sse" | "streamable_http";
  command: string;
  args: string;
  url: string;
  env: string;
  remove_env_keys: string[];
  enabled: boolean;
}

interface McpEnvRow {
  id: number;
  key: string;
  value: string;
}

const mcpTemplates: Array<{ name: string; description: string; form: Partial<McpForm>; env?: string[] }> = [
  {
    name: "Filesystem",
    description: "将指定目录作为受控文件工具开放给 Agent",
    form: { name: "Filesystem MCP", command: "npx", args: "-y @modelcontextprotocol/server-filesystem D:\\path\\to\\project" },
  },
  {
    name: "GitHub",
    description: "访问仓库、Issue 与 Pull Request",
    form: { name: "GitHub MCP", command: "npx", args: "-y @modelcontextprotocol/server-github" },
    env: ["GITHUB_PERSONAL_ACCESS_TOKEN"],
  },
  {
    name: "Fetch",
    description: "读取公开网页并转换为适合模型的内容",
    form: { name: "Fetch MCP", command: "uvx", args: "mcp-server-fetch" },
  },
];

interface SkillForm {
  name: string;
  description: string;
  content: string;
  tools: string;
  permission_profile: string;
}

const emptyMcpForm: McpForm = {
  name: "",
  transport: "stdio",
  command: "",
  args: "",
  url: "",
  env: "",
  remove_env_keys: [],
  enabled: true,
};

const emptySkillForm: SkillForm = {
  name: "",
  description: "",
  content: "",
  tools: "filesystem_read, filesystem_write, search, shell",
  permission_profile: "standard",
};

export default function ToolsMcp() {
  const ux = useWorkspaceUx();
  const { data: servers, refresh: refreshServers } = useApi<McpServer[]>("/mcp-servers", 5_000);
  const { data: runners } = useApi<Runner[]>("/runners", 10_000);
  const { data: builtins, refresh: refreshBuiltins } = useApi<ToolGatewayStatus[]>("/tools/status", 10_000);
  const { data: skills, refresh: refreshSkills } = useApi<SkillPack[]>("/skill-packs", 10_000);
  const { data: browserStatus, refresh: refreshBrowserStatus } = useApi<BrowserStatus>("/browser/status", 3_000);
  const [mcpOpen, setMcpOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<McpServer | null>(null);
  const [mcpForm, setMcpForm] = useState<McpForm>(emptyMcpForm);
  const [envRows, setEnvRows] = useState<McpEnvRow[]>([{ id: 1, key: "", value: "" }]);
  const [mcpImportOpen, setMcpImportOpen] = useState(false);
  const [mcpImportText, setMcpImportText] = useState("");
  const [toolTestServer, setToolTestServer] = useState<McpServer | null>(null);
  const [toolTestName, setToolTestName] = useState("");
  const [toolTestArgs, setToolTestArgs] = useState("{}");
  const [toolTestValues, setToolTestValues] = useState<Record<string, unknown>>({});
  const [toolTestResult, setToolTestResult] = useState<string | null>(null);
  const [skillOpen, setSkillOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillPack | null>(null);
  const [skillForm, setSkillForm] = useState<SkillForm>(emptySkillForm);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserUrl, setBrowserUrl] = useState("https://example.com");
  const [browserPageId, setBrowserPageId] = useState<string>();
  const [browserSnapshot, setBrowserSnapshot] = useState<BrowserSnapshot | null>(null);
  const [browserImage, setBrowserImage] = useState<string | null>(null);
  const [browserSelector, setBrowserSelector] = useState("");
  const [browserValue, setBrowserValue] = useState("");

  function openCreateServer(template?: typeof mcpTemplates[number]) {
    setEditingServer(null);
    setMcpForm(template ? { ...emptyMcpForm, ...template.form } : emptyMcpForm);
    setEnvRows((template?.env?.length ? template.env : [""]).map((key, index) => ({ id: Date.now() + index, key, value: "" })));
    setMcpOpen(true);
  }

  function openEditServer(server: McpServer) {
    setEditingServer(server);
    setMcpForm({
      name: server.name,
      transport: server.transport,
      command: server.command ?? "",
      args: server.args.join(" "),
      url: server.url ?? "",
      env: "",
      remove_env_keys: [],
      enabled: server.enabled,
    });
    setEnvRows([{ id: Date.now(), key: "", value: "" }]);
    setMcpOpen(true);
  }

  async function submitServer(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy("mcp-form");
    try {
      const payload = {
        name: mcpForm.name,
        transport: mcpForm.transport,
        command: mcpForm.transport === "stdio" ? mcpForm.command : null,
        args: mcpForm.args.match(/(?:[^\s"]+|"[^"]*")+/g)?.map((item) => item.replace(/^"|"$/g, "")) ?? [],
        url: mcpForm.transport === "stdio" ? null : mcpForm.url,
        env: Object.fromEntries(envRows.filter((row) => row.key.trim()).map((row) => [row.key.trim(), row.value])),
        ...(editingServer ? {
          remove_env_keys: mcpForm.remove_env_keys,
          enabled: mcpForm.enabled,
        } : {}),
      };
      await api(editingServer ? `/mcp-servers/${editingServer.id}` : "/mcp-servers", {
        method: editingServer ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
      setMcpOpen(false);
      await refreshServers();
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法保存 MCP Server");
    } finally {
      setBusy(null);
    }
  }

  async function importMcpJson(event: FormEvent) {
    event.preventDefault();
    setBusy("mcp-import");
    setError(null);
    try {
      const parsed = JSON.parse(mcpImportText) as Record<string, unknown>;
      const collection = (parsed.mcpServers ?? parsed.servers ?? parsed) as Record<string, Record<string, unknown>>;
      const entries = Object.entries(collection).filter(([, value]) => value && typeof value === "object");
      if (!entries.length) throw new Error("没有找到 mcpServers 配置");
      for (const [name, config] of entries) {
        const url = typeof config.url === "string" ? config.url : null;
        const transport = url ? String(config.transport ?? "streamable_http") : "stdio";
        await api("/mcp-servers", {
          method: "POST",
          body: JSON.stringify({
            name,
            transport,
            command: url ? null : String(config.command ?? ""),
            args: Array.isArray(config.args) ? config.args.map(String) : [],
            url,
            env: config.env && typeof config.env === "object" ? config.env : {},
          }),
        });
      }
      setMcpImportOpen(false);
      setMcpImportText("");
      await refreshServers();
      ux.notify({ title: `已导入 ${entries.length} 个 MCP Server`, message: "建议立即运行健康检查", kind: "success" });
    } catch (value) {
      setError(value instanceof Error ? value.message : "MCP JSON 导入失败");
    } finally {
      setBusy(null);
    }
  }

  async function testMcpTool(event: FormEvent) {
    event.preventDefault();
    if (!toolTestServer || !toolTestName) return;
    setBusy("mcp-tool-test");
    setToolTestResult(null);
    try {
      const argumentsValue = JSON.parse(toolTestArgs || "{}") as Record<string, unknown>;
      const result = await api<Record<string, unknown>>(`/mcp-servers/${toolTestServer.id}/tools/call`, {
        method: "POST",
        body: JSON.stringify({ tool_name: toolTestName, arguments: argumentsValue }),
      });
      setToolTestResult(JSON.stringify(result, null, 2));
    } catch (value) {
      setToolTestResult(`ERROR\n${value instanceof Error ? value.message : "工具调用失败"}`);
    } finally {
      setBusy(null);
    }
  }

  function openToolTest(server: McpServer) {
    setToolTestServer(server);
    setToolTestName(server.tools[0]?.name ?? "");
    setToolTestArgs("{}");
    setToolTestValues({});
    setToolTestResult(null);
  }

  function diagnosticAdvice(server: McpServer) {
    const value = (server.last_error ?? "").toLowerCase();
    if (!value) return "先运行健康检查以发现工具和连接状态。";
    if (value.includes("not found") || value.includes("找不到") || value.includes("enoent")) return "命令不存在：请安装对应运行时，或在配置中填写可执行文件绝对路径。";
    if (value.includes("timed out") || value.includes("timeout") || value.includes("超时")) return "服务启动超时：请先在终端单独运行命令，检查是否等待交互输入。";
    if (value.includes("401") || value.includes("403") || value.includes("auth")) return "鉴权失败：请更新凭据环境变量，凭据不会写入数据库或日志。";
    if (value.includes("address") || value.includes("port") || value.includes("端口")) return "端口可能被占用：关闭旧进程或修改 Server URL 后重试。";
    return "可复制错误信息到终端复现；检查参数、网络代理和必需环境变量。";
  }

  async function checkHealth(serverId?: string) {
    setChecking(true);
    setError(null);
    try {
      await api(serverId ? `/mcp-servers/${serverId}/health` : "/mcp-servers/health", { method: "POST" });
      await Promise.all([refreshServers(), refreshBuiltins()]);
    } catch (value) {
      setError(value instanceof Error ? value.message : "MCP 健康检查失败");
    } finally {
      setChecking(false);
    }
  }

  async function toggleServer(server: McpServer) {
    setBusy(server.id);
    try {
      await api(`/mcp-servers/${server.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !server.enabled }) });
      await refreshServers();
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法切换 Server 状态");
    } finally {
      setBusy(null);
    }
  }

  async function removeServer(server: McpServer) {
    if (!await ux.confirm({ title: "删除 MCP Server？", message: "保存的本机凭据和工具发现结果也会一并移除。", confirmLabel: "删除 Server", tone: "danger", detail: server.name })) return;
    setBusy(server.id);
    try {
      await api(`/mcp-servers/${server.id}`, { method: "DELETE" });
      await refreshServers();
      ux.notify({ kind: "success", title: "MCP Server 已删除", message: server.name });
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法删除 Server");
    } finally {
      setBusy(null);
    }
  }

  function openCreateSkill(source?: SkillPack) {
    setEditingSkill(null);
    setSkillForm(source ? {
      name: `${source.name} 副本`,
      description: source.description,
      content: source.content,
      tools: source.tools.join(", "),
      permission_profile: source.permission_profile ?? "workspace",
    } : emptySkillForm);
    setSkillOpen(true);
  }

  function openEditSkill(skill: SkillPack) {
    if (skill.builtin) {
      openCreateSkill(skill);
      return;
    }
    setEditingSkill(skill);
    setSkillForm({
      name: skill.name,
      description: skill.description,
      content: skill.content,
      tools: skill.tools.join(", "),
      permission_profile: skill.permission_profile ?? "workspace",
    });
    setSkillOpen(true);
  }

  async function submitSkill(event: FormEvent) {
    event.preventDefault();
    setBusy("skill-form");
    setError(null);
    try {
      await api(editingSkill ? `/skill-packs/${editingSkill.id}` : "/skill-packs", {
        method: editingSkill ? "PATCH" : "POST",
        body: JSON.stringify({
          ...skillForm,
          tools: skillForm.tools.split(/[\s,]+/).filter(Boolean),
          permission_profile: skillForm.permission_profile || null,
        }),
      });
      setSkillOpen(false);
      await refreshSkills();
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法保存能力包");
    } finally {
      setBusy(null);
    }
  }

  async function removeSkill(skill: SkillPack) {
    if (skill.builtin || !await ux.confirm({ title: "删除能力包？", message: "使用该能力包的已有会话不会被删除，新会话将不能再选择它。", confirmLabel: "删除能力包", tone: "danger", detail: skill.name })) return;
    setBusy(skill.id);
    try {
      await api(`/skill-packs/${skill.id}`, { method: "DELETE" });
      await refreshSkills();
      ux.notify({ kind: "success", title: "能力包已删除", message: skill.name });
    } catch (value) {
      setError(value instanceof Error ? value.message : "无法删除能力包");
    } finally {
      setBusy(null);
    }
  }

  async function captureBrowser(pageId = browserPageId) {
    if (!pageId) return;
    const [snapshot, screenshot] = await Promise.all([
      api<BrowserSnapshot>(`/browser/snapshot?page_id=${encodeURIComponent(pageId)}`),
      api<{ id: string }>(`/browser/screenshots?page_id=${encodeURIComponent(pageId)}`, { method: "POST" }),
    ]);
    setBrowserSnapshot(snapshot);
    setBrowserImage(`${downloadUrl(`/browser/artifacts/${screenshot.id}`)}?t=${Date.now()}`);
    setBrowserUrl(snapshot.url);
  }

  async function launchBrowser() {
    setBusy("browser");
    setError(null);
    try {
      const status = await api<BrowserStatus>("/browser/launch", { method: "POST", body: JSON.stringify({ url: "about:blank" }) });
      const pageId = status.pages[0]?.id;
      setBrowserPageId(pageId);
      await refreshBrowserStatus();
      if (pageId) await captureBrowser(pageId);
    } catch (value) {
      setError(value instanceof Error ? value.message : "浏览器启动失败");
    } finally {
      setBusy(null);
    }
  }

  async function navigateBrowser(event?: FormEvent) {
    event?.preventDefault();
    setBusy("browser");
    setError(null);
    try {
      if (!browserStatus?.running) await launchBrowser();
      const status = await api<BrowserStatus>("/browser/status");
      const pageId = browserPageId || status.pages[0]?.id;
      if (!pageId) throw new Error("浏览器没有可用页面");
      setBrowserPageId(pageId);
      const snapshot = await api<BrowserSnapshot>("/browser/navigate", { method: "POST", body: JSON.stringify({ url: browserUrl, page_id: pageId }) });
      setBrowserSnapshot(snapshot);
      const screenshot = await api<{ id: string }>(`/browser/screenshots?page_id=${encodeURIComponent(pageId)}`, { method: "POST" });
      setBrowserImage(`${downloadUrl(`/browser/artifacts/${screenshot.id}`)}?t=${Date.now()}`);
      await refreshBrowserStatus();
    } catch (value) {
      setError(value instanceof Error ? value.message : "网页导航失败");
    } finally {
      setBusy(null);
    }
  }

  async function browserAction(action: "click" | "fill") {
    if (!browserPageId || !browserSelector) return;
    setBusy("browser-action");
    try {
      const snapshot = await api<BrowserSnapshot>("/browser/actions", { method: "POST", body: JSON.stringify({ action, selector: browserSelector, value: action === "fill" ? browserValue : null, page_id: browserPageId }) });
      setBrowserSnapshot(snapshot);
      await captureBrowser(browserPageId);
    } catch (value) {
      setError(value instanceof Error ? value.message : "浏览器交互失败");
    } finally {
      setBusy(null);
    }
  }

  async function closeBrowser() {
    setBusy("browser");
    try {
      await api("/browser/close", { method: "POST" });
      setBrowserSnapshot(null);
      setBrowserImage(null);
      setBrowserPageId(undefined);
      await refreshBrowserStatus();
    } finally {
      setBusy(null);
    }
  }

  async function showBrowser() {
    setBrowserOpen(true);
    const pageId = browserPageId || browserStatus?.pages[0]?.id;
    if (pageId) {
      setBrowserPageId(pageId);
      try { await captureBrowser(pageId); } catch { /* The runtime may be starting. */ }
    }
  }

  const connected = (builtins?.filter((item) => item.status === "online" || item.status === "approval").length ?? 0)
    + (servers?.filter((item) => item.enabled && item.health_status === "online").length ?? 0);

  return <div className="v4-page">
    <header className="v4-page-head"><div><span>TOOL GATEWAY</span><h1>工具与 MCP</h1><p>管理真实平台运行时、MCP Server、能力包与不同 Agent 的兼容情况。</p></div><div><button className="v4-button secondary" type="button" onClick={() => setMcpImportOpen(true)}><Braces size={15} />导入 JSON</button><button className="v4-button secondary" type="button" onClick={() => void checkHealth()} disabled={checking}><Check size={16} />{checking ? "检查中…" : "运行健康检查"}</button><button className="v4-button primary" type="button" onClick={() => openCreateServer()}><Plus size={16} />添加 MCP Server</button></div></header>
    {error && <div className="v4-error">{error}</div>}
    <RuntimeProfilesPanel />
    <section className="v5-mcp-quickstart"><header><div><strong>快速配置</strong><small>从常用模板开始，所有命令和目录都可在保存前检查</small></div><KeyRound size={17} /></header>{mcpTemplates.map((template) => <button type="button" key={template.name} onClick={() => openCreateServer(template)}><span><ServerCog size={15} /></span><div><strong>{template.name}</strong><small>{template.description}</small></div><Plus size={14} /></button>)}</section>
    <section className="v4-tools-grid">
      <article className="v4-panel v4-tool-gateway"><header className="v4-panel-head"><div><strong>平台工具网关</strong><small>状态来自本地后端探测，不再硬编码</small></div><span className="v4-status green"><i />{connected} CONNECTED</span></header><div className="v4-tool-cards">
        {builtins?.map((tool) => {
          const Icon = builtinIcons[tool.id];
          return <section key={tool.id}><header><span><Icon size={19} /></span><div><strong>{tool.name}</strong><small>builtin://{tool.id}</small></div><b className={tool.status === "online" ? "online" : tool.status === "offline" || tool.status === "unavailable" ? "offline" : "approval"}><i />{tool.status.toUpperCase()}</b></header><p>{tool.detail}</p><footer><span>平台运行时</span><button type="button" disabled={tool.id === "browser" && tool.status === "unavailable"} onClick={tool.id === "browser" ? () => void showBrowser() : undefined}>{tool.id === "browser" ? "打开浏览器" : "由会话授权"}</button></footer></section>;
        })}
        {servers?.map((server) => <section className={!server.enabled ? "disabled" : ""} key={server.id}><header><span><ServerCog size={19} /></span><div><strong>{server.name}</strong><small>{server.transport}://{server.command || server.url}</small></div><b className={server.health_status === "online" ? "online" : server.health_status === "offline" ? "offline" : "approval"}><i />{server.enabled ? server.health_status.toUpperCase() : "DISABLED"}</b></header><p>{server.last_error || (server.tools.length ? `${server.tools.length} 个工具：${server.tools.slice(0, 3).map((tool) => tool.name).join("、")}` : "尚未执行健康检查")}</p>{server.health_status !== "online" && <div className="v5-mcp-diagnostic"><AlertTriangle size={13} /><span>{diagnosticAdvice(server)}</span></div>}<footer><span>{server.env_keys.length ? `${server.env_keys.length} 个安全凭据` : "无凭据"}</span><div>{server.tools.length > 0 && <button type="button" disabled={!server.enabled} onClick={() => openToolTest(server)}><Play size={11} />测试工具</button>}<button type="button" disabled={busy === server.id || !server.enabled} onClick={() => void checkHealth(server.id)}>检查</button><button type="button" onClick={() => openEditServer(server)}>配置</button><button type="button" title={server.enabled ? "停用" : "启用"} onClick={() => void toggleServer(server)}><Power size={12} /></button><button className="danger" type="button" title="删除" onClick={() => void removeServer(server)}><Trash2 size={12} /></button></div></footer></section>)}
      </div></article>
      <article className="v4-panel v4-skills-panel"><header className="v4-panel-head"><div><strong>能力包</strong><small>真实提示词、工具与权限组合</small></div><button type="button" onClick={() => openCreateSkill()}><Plus size={13} />新建</button></header><div>{skills?.map((skill) => <section key={skill.id}><span><Wrench size={15} /></span><button type="button" onClick={() => openEditSkill(skill)}><strong>{skill.name}</strong><small>{skill.description || skill.content}</small></button><b>{skill.builtin ? "BUILTIN" : `${skill.tools.length} TOOLS`}</b>{skill.builtin ? <button type="button" title="复制为自定义能力包" onClick={() => openCreateSkill(skill)}><Copy size={12} /></button> : <button className="danger" type="button" title="删除能力包" disabled={busy === skill.id} onClick={() => void removeSkill(skill)}><Trash2 size={12} /></button>}</section>)}</div></article>
    </section>
    {browserOpen && <section className="v4-panel v4-browser-console"><header className="v4-panel-head"><div><strong>内置浏览器控制台</strong><small>{browserStatus?.engine ?? "Chromium CDP"} · 独立配置文件 · 本机可见窗口</small></div><span className={`v4-status ${browserStatus?.running ? "green" : "amber"}`}><i />{browserStatus?.running ? "LIVE / 可随时接管" : "STOPPED"}</span><button className="v4-button secondary" type="button" disabled={busy === "browser"} onClick={browserStatus?.running ? () => void closeBrowser() : () => void launchBrowser()}><Power size={14} />{browserStatus?.running ? "关闭" : "启动"}</button><button className="v4-icon-button" type="button" onClick={() => setBrowserOpen(false)}><X size={15} /></button></header><form onSubmit={navigateBrowser}><input value={browserUrl} onChange={(event) => setBrowserUrl(event.target.value)} placeholder="https://example.com" /><button className="v4-button primary" type="submit" disabled={busy === "browser"}>访问</button><button className="v4-button secondary" type="button" disabled={!browserPageId} onClick={() => void captureBrowser()}><RefreshCw size={14} />刷新快照</button></form><div className="v4-browser-grid"><section className="v4-browser-viewport">{browserImage ? <img src={browserImage} alt="浏览器当前页面截图" /> : <div><Globe2 size={32} /><strong>启动浏览器后显示实时截图</strong><span>浏览器窗口保持可见，你可以直接接管鼠标和键盘。</span></div>}</section><section className="v4-browser-inspector"><header><div><strong>{browserSnapshot?.title || "DOM / ACCESSIBILITY SNAPSHOT"}</strong><small>{browserSnapshot?.url || "尚未读取页面"}</small></div><span>{browserSnapshot?.controls.length ?? 0} CONTROLS</span></header><div className="v4-browser-actions"><input value={browserSelector} onChange={(event) => setBrowserSelector(event.target.value)} placeholder="已选元素；高级用户也可输入 selector" /><input value={browserValue} onChange={(event) => setBrowserValue(event.target.value)} placeholder="填充值" /><button type="button" disabled={!browserSelector || busy === "browser-action"} onClick={() => void browserAction("click")}>点击</button><button type="button" disabled={!browserSelector || busy === "browser-action"} onClick={() => void browserAction("fill")}>填写</button><button type="button" disabled={!browserPageId} onClick={() => void captureBrowser()}><Camera size={13} />截图</button></div><div className="v5-browser-controls"><label>可操作元素</label>{browserSnapshot?.controls.slice(0, 80).map((control) => <button className={control.selector === browserSelector ? "active" : ""} type="button" disabled={control.disabled} key={`${control.index}-${control.selector}`} onClick={() => setBrowserSelector(control.selector || "")}><b>{control.index + 1}</b><span><strong>{control.text || control.tag}</strong><small>{control.tag}{control.type ? ` · ${control.type}` : ""}</small></span></button>)}{browserSnapshot && !browserSnapshot.controls.length && <p>当前页面没有可操作表单控件。</p>}</div><details className="v5-browser-text"><summary>页面文本快照</summary><pre>{browserSnapshot?.text || "页面文本、链接和控件会在这里呈现给用户与 Agent。"}</pre></details></section></div></section>}
    <section className="v4-panel v4-capability-panel"><header className="v4-panel-head"><div><strong>Agent 能力矩阵</strong><small>依据真实适配器能力提供原生或降级体验</small></div><span>LAST PROBE / LIVE</span></header><div><table><thead><tr><th>AGENT ADAPTER</th><th>适配模式</th><th>已安装</th><th>多轮</th><th>结构化事件</th><th>MCP</th><th>模型覆盖</th><th>状态</th></tr></thead><tbody>{runners?.map((runner) => <tr key={runner.id}><td><Bot size={14} />{runner.name}</td><td><code>{runner.runner_type === "unified" ? "UNIFIED API" : "NATIVE CLI"}</code></td><td>{runner.capability.installed ? "● 已安装" : "○ 未安装"}</td><td>{runner.adapter?.native_resume ? "● 原生恢复" : "◐ 历史重放"}</td><td>{runner.adapter?.structured_events === "full" ? "● 完整" : runner.adapter?.structured_events === "stream" ? "● 流式" : "◐ 过滤输出"}</td><td>{runner.adapter?.mcp ? "● 原生" : "◐ 平台网关"}</td><td>{runner.adapter?.model_override ? "● 支持" : "◐ CLI 决定"}</td><td><span className={`v4-status ${runner.capability.installed ? "green" : "amber"}`}><i />{runner.capability.installed ? "READY" : "SETUP"}</span></td></tr>)}</tbody></table></div></section>

    {mcpOpen && <div className="v4-modal-backdrop" onMouseDown={() => setMcpOpen(false)}><form className="v4-modal small" onSubmit={submitServer} onMouseDown={(event) => event.stopPropagation()}><header><div><strong>{editingServer ? "配置 MCP Server" : "添加 MCP Server"}</strong><small>凭据保存到系统凭据存储，不写入 SQLite</small></div><button type="button" onClick={() => setMcpOpen(false)}><X size={18} /></button></header><div className="v4-form-grid"><label className="full"><span>名称</span><input required value={mcpForm.name} onChange={(event) => setMcpForm({ ...mcpForm, name: event.target.value })} /></label><label className="full"><span>传输方式</span><select value={mcpForm.transport} onChange={(event) => setMcpForm({ ...mcpForm, transport: event.target.value as McpForm["transport"] })}><option value="stdio">stdio</option><option value="sse">SSE</option><option value="streamable_http">Streamable HTTP</option></select></label>{mcpForm.transport === "stdio" ? <><label className="full"><span>命令</span><input required value={mcpForm.command} onChange={(event) => setMcpForm({ ...mcpForm, command: event.target.value })} placeholder="npx" /></label><label className="full"><span>参数</span><input value={mcpForm.args} onChange={(event) => setMcpForm({ ...mcpForm, args: event.target.value })} placeholder="-y @modelcontextprotocol/server-filesystem" /></label></> : <label className="full"><span>Server URL</span><input required type="url" value={mcpForm.url} onChange={(event) => setMcpForm({ ...mcpForm, url: event.target.value })} /></label>}<fieldset className="full v5-env-editor"><legend>新增或更新凭据</legend><p>密钥值只写入系统凭据存储；保存后界面不会再次显示原值。</p>{envRows.map((row) => <div key={row.id}><input aria-label="环境变量名称" value={row.key} onChange={(event) => setEnvRows((items) => items.map((item) => item.id === row.id ? { ...item, key: event.target.value.toUpperCase() } : item))} placeholder="API_KEY" /><input aria-label="环境变量密钥" type="password" value={row.value} onChange={(event) => setEnvRows((items) => items.map((item) => item.id === row.id ? { ...item, value: event.target.value } : item))} placeholder="安全值" /><button type="button" aria-label="删除环境变量" disabled={envRows.length === 1} onClick={() => setEnvRows((items) => items.filter((item) => item.id !== row.id))}><Trash2 size={13} /></button></div>)}<button type="button" onClick={() => setEnvRows((items) => [...items, { id: Date.now(), key: "", value: "" }])}><Plus size={13} />添加变量</button></fieldset>{editingServer?.env_keys.length ? <fieldset className="full v4-secret-keys"><legend>现有凭据</legend>{editingServer.env_keys.map((key) => <label key={key}><input type="checkbox" checked={mcpForm.remove_env_keys.includes(key)} onChange={(event) => setMcpForm({ ...mcpForm, remove_env_keys: event.target.checked ? [...mcpForm.remove_env_keys, key] : mcpForm.remove_env_keys.filter((item) => item !== key) })} />删除 {key}</label>)}</fieldset> : null}<label className="full v4-inline-check"><input type="checkbox" checked={mcpForm.enabled} onChange={(event) => setMcpForm({ ...mcpForm, enabled: event.target.checked })} /><span>启用此 Server</span></label></div><footer><button className="v4-button secondary" type="button" onClick={() => setMcpOpen(false)}>取消</button><button className="v4-button primary" type="submit" disabled={busy === "mcp-form"}><ServerCog size={16} />保存 Server</button></footer></form></div>}

    {mcpImportOpen && <div className="v4-modal-backdrop" onMouseDown={() => setMcpImportOpen(false)}><form className="v4-modal small" onSubmit={importMcpJson} onMouseDown={(event) => event.stopPropagation()}><header><div><strong>导入标准 MCP JSON</strong><small>支持 mcpServers、servers 或单层 Server 映射</small></div><button type="button" onClick={() => setMcpImportOpen(false)}><X size={18} /></button></header><div className="v5-mcp-import"><p>导入前请检查其中是否包含明文密钥。导入后的环境变量会转存到系统凭据存储。</p><textarea aria-label="MCP JSON" required value={mcpImportText} onChange={(event) => setMcpImportText(event.target.value)} spellCheck={false} placeholder={'{\n  "mcpServers": {\n    "filesystem": { "command": "npx", "args": ["-y", "..."] }\n  }\n}'} /></div><footer><button className="v4-button secondary" type="button" onClick={() => setMcpImportOpen(false)}>取消</button><button className="v4-button primary" type="submit" disabled={busy === "mcp-import"}><Braces size={15} />验证并导入</button></footer></form></div>}

    {toolTestServer && <div className="v4-modal-backdrop" onMouseDown={() => setToolTestServer(null)}><form className="v4-modal" onSubmit={testMcpTool} onMouseDown={(event) => event.stopPropagation()}><header><div><strong>工具调用测试台</strong><small>{toolTestServer.name} · 测试会真实调用所选工具</small></div><button type="button" onClick={() => setToolTestServer(null)}><X size={18} /></button></header><div className="v4-form-grid"><label className="full"><span>工具</span><select required value={toolTestName} onChange={(event) => { setToolTestName(event.target.value); setToolTestArgs("{}"); setToolTestValues({}); }}>{toolTestServer.tools.map((tool) => <option key={tool.name} value={tool.name}>{tool.name}</option>)}</select></label><div className="full"><JsonSchemaForm schema={toolTestServer.tools.find((tool) => tool.name === toolTestName)?.inputSchema} value={toolTestValues} onChange={(value) => { setToolTestValues(value); setToolTestArgs(JSON.stringify(value, null, 2)); }} /></div><details className="full v5-schema-advanced"><summary><Braces size={13} />高级 JSON</summary><textarea className="v5-code-input" value={toolTestArgs} onChange={(event) => { setToolTestArgs(event.target.value); try { setToolTestValues(JSON.parse(event.target.value)); } catch { /* Validated on submit. */ } }} spellCheck={false} /></details>{toolTestResult && <pre className="full v5-mcp-tool-result">{toolTestResult}</pre>}</div><footer><button className="v4-button secondary" type="button" onClick={() => setToolTestServer(null)}>关闭</button><button className="v4-button primary" type="submit" disabled={busy === "mcp-tool-test" || !toolTestName}><Play size={15} />调用工具</button></footer></form></div>}

    {skillOpen && <div className="v4-modal-backdrop" onMouseDown={() => setSkillOpen(false)}><form className="v4-modal small" onSubmit={submitSkill} onMouseDown={(event) => event.stopPropagation()}><header><div><strong>{editingSkill ? "编辑能力包" : "创建能力包"}</strong><small>能力包可在 Agent Studio 会话中随时选择</small></div><button type="button" onClick={() => setSkillOpen(false)}><X size={18} /></button></header><div className="v4-form-grid"><label className="full"><span>名称</span><input required value={skillForm.name} onChange={(event) => setSkillForm({ ...skillForm, name: event.target.value })} /></label><label className="full"><span>说明</span><input value={skillForm.description} onChange={(event) => setSkillForm({ ...skillForm, description: event.target.value })} /></label><label className="full"><span>工作指令</span><textarea required value={skillForm.content} onChange={(event) => setSkillForm({ ...skillForm, content: event.target.value })} /></label><label className="full"><span>允许工具（逗号分隔）</span><input value={skillForm.tools} onChange={(event) => setSkillForm({ ...skillForm, tools: event.target.value })} /></label><label className="full"><span>默认权限</span><select value={skillForm.permission_profile} onChange={(event) => setSkillForm({ ...skillForm, permission_profile: event.target.value })}><option value="readonly">只读</option><option value="workspace">工作区</option><option value="standard">标准开发</option><option value="full">完全访问</option></select></label></div><footer><button className="v4-button secondary" type="button" onClick={() => setSkillOpen(false)}>取消</button><button className="v4-button primary" type="submit" disabled={busy === "skill-form"}><Wrench size={16} />保存能力包</button></footer></form></div>}
  </div>;
}
