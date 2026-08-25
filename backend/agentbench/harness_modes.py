from __future__ import annotations

import hashlib
import json
import os
import shutil
from contextlib import suppress
from pathlib import Path
from typing import Any

import yaml

HARNESS_DEFAULT_MODE = "standard"

_MODE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "standard",
        "name": "标准模式",
        "description": "完整工具集，适合常规编码、推理与长任务。",
        "source": "system",
        "tools_mode": "native",
        "experimental": False,
    },
    {
        "id": "code",
        "name": "PTC 模式",
        "description": "通过 Code Mode SDK 组合多步工具调用。",
        "source": "system",
        "tools_mode": "code",
        "experimental": False,
    },
    {
        "id": "minimal",
        "name": "极简模式",
        "description": "仅提供持久 Shell 与 str_replace_editor。",
        "source": "system",
        "tools_mode": "native",
        "experimental": False,
    },
    {
        "id": "cordis",
        "name": "创造模式",
        "description": "完整能力，并加入插件实验与 preset 创作能力。",
        "source": "system",
        "tools_mode": "native",
        "experimental": False,
    },
    {
        "id": "anchored-standard",
        "name": "Anchored Standard",
        "description": "首次持久工具调用前仅暴露 Shell/Read，随后开放标准工具集。",
        "source": "user",
        "tools_mode": "native",
        "experimental": True,
        "required_files": ("tool-bootstrap.mjs",),
    },
)


class HarnessModeUnavailableError(ValueError):
    """The requested Harness preset cannot be mounted on this installation."""


class _HarnessYamlLoader(yaml.SafeLoader):
    pass


_HarnessYamlLoader.add_constructor(
    "tag:yaml.org,2002:js",
    lambda loader, node: loader.construct_scalar(node),
)


def harness_home() -> Path:
    configured = os.getenv("DSH_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".dsh"


def _valid_package_root(path: Path) -> bool:
    package_file = path / "package.json"
    try:
        payload = json.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return payload.get("name") == "@deepseek-ai/dsh"


def locate_dsh_package_root(executable: str | None = "dsh") -> Path | None:
    """Locate the installed npm package without changing or invoking Harness."""
    configured = os.getenv("AGENTBENCH_DSH_PACKAGE_ROOT", "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())

    executable_value = str(executable or "dsh").strip() or "dsh"
    located = shutil.which(executable_value)
    if located:
        wrapper = Path(located)
        with_resolved = [wrapper]
        with suppress(OSError):
            with_resolved.append(wrapper.resolve())
        for item in with_resolved:
            candidates.extend(
                (
                    item.parent / "node_modules" / "@deepseek-ai" / "dsh",
                    item.parent.parent / "lib" / "node_modules" / "@deepseek-ai" / "dsh",
                    item.parent.parent / "node_modules" / "@deepseek-ai" / "dsh",
                )
            )

    seen: set[str] = set()
    for candidate in candidates:
        try:
            normalized = candidate.resolve()
        except OSError:
            normalized = candidate.absolute()
        marker = str(normalized).lower()
        if marker in seen:
            continue
        seen.add(marker)
        if _valid_package_root(normalized):
            return normalized
    return None


def _preset_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    total = 0
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    if not files:
        raise HarnessModeUnavailableError("preset 目录为空")
    for path in files:
        relative = path.relative_to(directory).as_posix().encode("utf-8")
        data = path.read_bytes()
        total += len(data)
        if total > 10_000_000:
            raise HarnessModeUnavailableError("preset 文件总量超过 10 MB")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _preset_error(directory: Path, required_files: tuple[str, ...]) -> str | None:
    composition = directory / "agent.cordis.yml"
    if not composition.is_file():
        return "缺少 agent.cordis.yml"
    for name in required_files:
        if not (directory / name).is_file():
            return f"缺少 {name}"
    try:
        if composition.stat().st_size > 5_000_000:
            return "agent.cordis.yml 超过 5 MB"
        parsed = yaml.load(
            composition.read_text(encoding="utf-8"), Loader=_HarnessYamlLoader
        )
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return f"无法解析 preset：{exc}"
    if not isinstance(parsed, list) or not parsed:
        return "agent.cordis.yml 没有可挂载条目"
    return None


def discover_harness_modes(
    executable: str | None = "dsh",
    *,
    package_root: Path | None = None,
    user_home: Path | None = None,
) -> list[dict[str, Any]]:
    package = package_root or locate_dsh_package_root(executable)
    home = user_home or harness_home()
    system_root = package / "config" / "agent-presets" if package else None
    user_root = home / ".agent-presets"
    modes: list[dict[str, Any]] = []
    for definition in _MODE_DEFINITIONS:
        mode = dict(definition)
        mode.pop("required_files", None)
        root = system_root if definition["source"] == "system" else user_root
        directory = root / str(definition["id"]) if root else None
        error = (
            "未找到 DeepSeek Harness npm 安装目录"
            if directory is None
            else _preset_error(directory, tuple(definition.get("required_files") or ()))
        )
        sha256: str | None = None
        if error is None and directory is not None:
            try:
                sha256 = _preset_hash(directory)
            except (OSError, HarnessModeUnavailableError) as exc:
                error = str(exc)
        mode.update(
            {
                "available": error is None,
                "error": error,
                "sha256": sha256,
                "_package_root": str(package) if package else None,
                "_system_root": str(system_root) if system_root else None,
                "_user_root": str(user_root),
                "_preset_path": str(directory) if directory else None,
            }
        )
        modes.append(mode)
    return modes


def public_harness_modes(executable: str | None = "dsh") -> list[dict[str, Any]]:
    return [
        {key: value for key, value in mode.items() if not key.startswith("_")}
        for mode in discover_harness_modes(executable)
    ]


def resolve_harness_mode(mode_id: str | None, executable: str | None = "dsh") -> dict[str, Any]:
    requested = str(mode_id or HARNESS_DEFAULT_MODE).strip().lower()
    modes = discover_harness_modes(executable)
    mode = next((item for item in modes if item["id"] == requested), None)
    if mode is None:
        available_ids = ", ".join(item["id"] for item in modes)
        raise HarnessModeUnavailableError(
            f"未知 DeepSeek Harness 模式 {requested!r}；可选：{available_ids}"
        )
    if not mode["available"]:
        raise HarnessModeUnavailableError(
            f"DeepSeek Harness 模式 {requested!r} 不可用：{mode['error']}"
        )
    return mode


HARNESS_DRIVER_SOURCE = r'''import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const dshRoot = process.env.AGENTBENCH_DSH_PACKAGE_ROOT;
if (!dshRoot) throw new Error("agentbench-headless-runner: AGENTBENCH_DSH_PACKAGE_ROOT is missing");
const requireFromDsh = createRequire(pathToFileURL(join(dshRoot, "package.json")));
const load = async (name) => import(pathToFileURL(requireFromDsh.resolve(name)).href);
const [{ default: z }, { installModelSelection }, { createUserMessage }, { SessionId }] = await Promise.all([
  load("@deepseek-ai/schemastery"),
  load("@deepseek-ai/dsh-agent"),
  load("@deepseek-ai/dsh-llm"),
  load("@deepseek-ai/dsh-session"),
]);

export const name = "agentbench-headless-runner";
export const inject = ["agentDefaultModel", "agentPresets", "agents", "sessions"];
export const Config = z.object({ task: z.string().required(), preset: z.string().required() });

function summarize(events, firstSeq) {
  let started = false;
  let text = "";
  let reason;
  for (const event of events) {
    if (event.seq < firstSeq) continue;
    if (event.type === "turn/start") { started = true; continue; }
    if (!started) continue;
    if (event.type === "assistant/message") {
      const joined = event.data.message.content
        .filter((block) => block.type === "text")
        .map((block) => block.text)
        .join("");
      if (joined !== "") text = joined;
    }
    if (event.type === "turn/end") reason = event.data.reason;
  }
  return { text, reason };
}

async function run(ctx, config, io) {
  await ctx.get("loader")?.await();
  const agents = ctx.get("agents");
  const presets = ctx.get("agentPresets");
  const defaultModel = ctx.get("agentDefaultModel");
  const sessions = ctx.get("sessions");
  if (!agents || !presets || !defaultModel || !sessions) {
    throw new Error("required Harness services are unavailable");
  }
  const selection = defaultModel.currentSelection();
  const { agent } = await agents.create({
    sessionId: SessionId(`session-${randomUUID()}`),
    meta: { cwd: process.cwd(), agentPreset: config.preset },
    agentOptions: { provider: selection.provider, model: selection.model },
    setup: async (agentCtx) => {
      installModelSelection(agentCtx, { current: selection, assembled: undefined });
      await presets.mount(agentCtx, config.preset);
    },
  });
  await agent.whenIdle();
  if (process.env.AGENTBENCH_DSH_PROBE_ONLY === "1") {
    io.stdout.write(`AGENTBENCH_PRESET_MOUNTED:${config.preset}\n`);
    io.exit(0);
    return;
  }
  const firstSeq = agent.session.seq;
  agent.followup(createUserMessage({
    content: [{ type: "text", text: config.task }],
    source: { kind: "user" },
  }));
  await agent.whenIdle();
  await sessions.flush(agent.session);
  const outcome = summarize(agent.session.events, firstSeq);
  io.stdout.write(outcome.text + "\n");
  if (outcome.reason?.kind === "error") {
    io.stderr.write(`dsh: ${outcome.reason.error.code}: ${outcome.reason.error.message}\n`);
  }
  io.exit(outcome.reason?.kind === "completed" ? 0 : 1);
}

export function apply(ctx, config) {
  const exit = ctx.get("appExit");
  if (!exit) throw new Error("agentbench-headless-runner: appExit is unavailable");
  run(ctx, config, { stdout: process.stdout, stderr: process.stderr, exit }).catch((error) => {
    process.stderr.write(`dsh: ${error instanceof Error ? error.message : String(error)}\n`);
    exit(1);
  });
}
'''


def harness_driver_sha256() -> str:
    return hashlib.sha256(HARNESS_DRIVER_SOURCE.encode("utf-8")).hexdigest()


_DISABLED_AGENT_ROWS = (
    "tool-bash",
    "tool-pwsh",
    "tool-jobs",
    "tool-fs",
    "tool-fs-search",
    "tool-str-replace-editor",
    "skill-filesystem",
    "tool-skill",
    "tool-goal",
    "plan-mode",
    "compaction-basic",
    "command-compact",
    "tool-result-pruner",
    "tool-subagent-control",
    "tool-subagent-list-agents",
    "tool-subagent",
    "tool-subagent-fork",
    "workflow-worker-thread",
    "tool-workflow",
    "tool-ralph",
    "agent-instructions",
    "tool-todo",
    "tool-web",
)


def _yaml_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_harness_patch(
    *,
    settings_path: Path,
    driver_path: Path,
    mode: dict[str, Any],
) -> str:
    system_root = str(mode["_system_root"]).replace("\\", "/")
    driver_url = driver_path.resolve().as_uri()
    lines = [
        "# AgentBench per-run Harness preset overlay. Does not modify global settings.",
        "- id: settings",
        "  config:",
        f"    path: {_yaml_quote(str(settings_path).replace(chr(92), '/'))}",
        "    watch: false",
        "",
        "- id: headless-runner",
        "  disabled: true",
        "",
    ]
    for row_id in _DISABLED_AGENT_ROWS:
        lines.extend((f"- id: {row_id}", "  disabled: true", ""))
    lines.extend(
        (
            "- insert:",
            "    - id: agent-presets",
            "      name: '@deepseek-ai/dsh-agent-presets'",
            "      config:",
            f"        default: {_yaml_quote(str(mode['id']))}",
            "        roots:",
            f"          - path: {_yaml_quote(system_root)}",
            "            trust: system",
            "        includeUserRoot: true",
            "",
        )
    )
    if mode["id"] == "cordis":
        lines.extend(
            (
                "    - id: cordis-host-runner",
                "      name: '@deepseek-ai/dsh-cordis-host-runner'",
                "",
            )
        )
    lines.extend(
        (
            "    - id: agentbench-headless-runner",
            f"      name: {_yaml_quote(driver_url)}",
            "      inject: [headlessStartup]",
            "      config:",
            "        task: !!js ctx.headlessStartup.task",
            f"        preset: {_yaml_quote(str(mode['id']))}",
            "",
        )
    )
    return "\n".join(lines)
