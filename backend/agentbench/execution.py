from __future__ import annotations

import base64
import fnmatch
import hashlib
import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WorkspaceViolation(ValueError):
    pass


def safe_workspace_path(root: Path, raw_path: str) -> Path:
    candidate_path = Path(raw_path)
    if candidate_path.is_absolute() or candidate_path.drive:
        raise WorkspaceViolation("Absolute paths are not allowed")
    root = root.resolve()
    candidate = (root / candidate_path).resolve()
    if not candidate.is_relative_to(root):
        raise WorkspaceViolation("Path escapes the run workspace")
    return candidate


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def seed(self, files: dict[str, str]) -> None:
        for relative, content in files.items():
            self.write_file(relative, content)

    def read_file(self, path: str, max_chars: int = 100_000) -> str:
        target = safe_workspace_path(self.root, path)
        if not target.is_file():
            raise FileNotFoundError(path)
        return target.read_text(encoding="utf-8", errors="replace")[:max_chars]

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        target = safe_workspace_path(self.root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if content.startswith("base64:"):
            target.write_bytes(base64.b64decode(content[len("base64:"):]))
        else:
            target.write_text(content, encoding="utf-8")
        return {"path": path, "bytes": target.stat().st_size}

    def list_files(self, path: str = ".", max_items: int = 500) -> list[str]:
        base = safe_workspace_path(self.root, path)
        if not base.exists():
            return []
        if base.is_file():
            return [str(base.relative_to(self.root)).replace("\\", "/")]
        files: list[str] = []
        for item in base.rglob("*"):
            if item.is_file():
                files.append(str(item.relative_to(self.root)).replace("\\", "/"))
                if len(files) >= max_items:
                    break
        return sorted(files)

    def search_text(
        self, query: str, path: str = ".", max_results: int = 100
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for relative in self.list_files(path):
            target = safe_workspace_path(self.root, relative)
            try:
                lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, 1):
                if query.lower() in line.lower():
                    results.append({"path": relative, "line": line_number, "text": line[:500]})
                    if len(results) >= max_results:
                        return results
        return results

    def changed_files(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for relative in self.list_files():
            target = safe_workspace_path(self.root, relative)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            output.append({"path": relative, "size": target.stat().st_size, "sha256": digest})
        return output

    def matches_any(self, patterns: list[str]) -> list[str]:
        return [
            path for path in self.list_files() if any(fnmatch.fnmatch(path, p) for p in patterns)
        ]


@dataclass(slots=True)
class CommandResult:
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
        }


class DockerExecutor:
    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("docker")

    @property
    def available(self) -> bool:
        if not self.executable:
            return False
        try:
            result = subprocess.run(
                [self.executable, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def status(self) -> dict[str, Any]:
        return {
            "installed": bool(self.executable),
            "available": self.available,
            "executable": self.executable,
        }

    def run(
        self,
        workspace: Workspace,
        command: str,
        image: str,
        timeout: int = 120,
        network: str = "disabled",
    ) -> CommandResult:
        if not self.available:
            return CommandResult(
                ok=False,
                exit_code=None,
                stdout="",
                stderr="Docker Desktop is unavailable; host execution was not used.",
                duration_ms=0,
                error_code="sandbox_unavailable",
            )
        start = time.perf_counter()
        network_args = ["--network", "none"] if network == "disabled" else []
        args = [
            str(self.executable),
            "run",
            "--rm",
            *network_args,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--cpus",
            "1.0",
            "--memory",
            "768m",
            "--pids-limit",
            "128",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m",
            "-v",
            f"{workspace.root}:/workspace:rw",
            "-w",
            "/workspace",
            image,
            "sh",
            "-lc",
            command,
        ]
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return CommandResult(
                ok=result.returncode == 0,
                exit_code=result.returncode,
                stdout=result.stdout[-100_000:],
                stderr=result.stderr[-100_000:],
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                ok=False,
                exit_code=None,
                stdout=(exc.stdout or "")[-100_000:] if isinstance(exc.stdout, str) else "",
                stderr="Command timed out",
                duration_ms=int((time.perf_counter() - start) * 1000),
                error_code="command_timeout",
            )


SAFE_ENV_KEYS = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "PROGRAMDATA",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "LANG",
}

CLI_INSTALL_RECIPES: dict[str, dict[str, Any]] = {
    "codex_cli": {
        "manager": "npm",
        "manager_candidates": ["npm.cmd", "npm"],
        "args": ["install", "-g", "@openai/codex"],
        "command": "npm install -g @openai/codex",
        "source": "npm 官方包 · @openai/codex",
    },
    "claude_code_cli": {
        "manager": "winget",
        "manager_candidates": ["winget.exe", "winget"],
        "args": [
            "install",
            "--id",
            "Anthropic.ClaudeCode",
            "--exact",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ],
        "command": (
            "winget install --id Anthropic.ClaudeCode --exact "
            "--accept-package-agreements --accept-source-agreements"
        ),
        "source": "Windows Package Manager · Anthropic.ClaudeCode",
    },
    "opencode_cli": {
        "manager": "npm",
        "manager_candidates": ["npm.cmd", "npm"],
        "args": ["install", "-g", "opencode-ai"],
        "command": "npm install -g opencode-ai",
        "source": "npm 官方包 · opencode-ai",
    },
    "reasonix_cli": {
        "manager": "npm",
        "manager_candidates": ["npm.cmd", "npm"],
        "args": ["install", "-g", "reasonix"],
        "command": "npm install -g reasonix",
        "source": "npm 包 · reasonix",
    },
    "qoder_cli": {
        "manager": "npm",
        "manager_candidates": ["npm.cmd", "npm"],
        "args": ["install", "-g", "@qodercn-ai/qoderclicn"],
        "command": "npm install -g @qodercn-ai/qoderclicn",
        "source": "npm 官方包 · @qodercn-ai/qoderclicn（Qoder 国内版 CLI）",
    },
    "gemini_cli": {
        "manager": "npm",
        "manager_candidates": ["npm.cmd", "npm"],
        "args": ["install", "-g", "@google/gemini-cli"],
        "command": "npm install -g @google/gemini-cli",
        "source": "npm 官方包 · @google/gemini-cli",
    },
    "aider_cli": {
        "manager": "uv",
        "manager_candidates": ["uv.exe", "uv"],
        "args": ["tool", "install", "--python", "3.12", "aider-chat"],
        "command": "uv tool install --python 3.12 aider-chat",
        "source": "PyPI · aider-chat（由 uv tool 隔离安装）",
    },
    "kimi_code_cli": {
        "manager": "uv",
        "manager_candidates": ["uv.exe", "uv"],
        "args": ["tool", "install", "--python", "3.13", "kimi-cli"],
        "command": "uv tool install --python 3.13 kimi-cli",
        "source": "PyPI · kimi-cli（由 uv tool 隔离安装）",
    },
    "cursor_cli": {
        "manager": "powershell",
        "manager_candidates": ["powershell.exe", "powershell"],
        "args": [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "irm 'https://cursor.com/install?win32=true' | iex",
        ],
        "command": "irm 'https://cursor.com/install?win32=true' | iex",
        "source": "Cursor 官方 Windows 安装器 · cursor.com/install",
    },
}

MANUAL_INSTALL_GUIDANCE = {
    "command": "自定义 Runner 由用户自行提供可执行文件，AgentBench 不会安装任意第三方命令。",
}

INSTALL_COMMAND_BY_EXECUTABLE = {
    "codex": CLI_INSTALL_RECIPES["codex_cli"]["command"],
    "claude": CLI_INSTALL_RECIPES["claude_code_cli"]["command"],
    "opencode": CLI_INSTALL_RECIPES["opencode_cli"]["command"],
    "reasonix": CLI_INSTALL_RECIPES["reasonix_cli"]["command"],
    "gemini": CLI_INSTALL_RECIPES["gemini_cli"]["command"],
    "aider": CLI_INSTALL_RECIPES["aider_cli"]["command"],
    "kimi": CLI_INSTALL_RECIPES["kimi_code_cli"]["command"],
    "qoderclicn": CLI_INSTALL_RECIPES["qoder_cli"]["command"],
    "agent": CLI_INSTALL_RECIPES["cursor_cli"]["command"],
}


def resolve_cli_install_plan(
    runner_type: str,
    resolver: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """Resolve a code-owned install recipe without accepting shell input."""
    recipe = CLI_INSTALL_RECIPES.get(runner_type)
    if not recipe:
        return {
            "supported": False,
            "available": False,
            "manual_instructions": MANUAL_INSTALL_GUIDANCE.get(
                runner_type,
                "此 Runner 没有内置安装方案，请按其官方文档手动安装。",
            ),
        }
    resolved = next(
        (
            path
            for candidate in recipe["manager_candidates"]
            if (path := resolver(str(candidate)))
        ),
        None,
    )
    return {
        "supported": True,
        "available": bool(resolved),
        "manager": recipe["manager"],
        "manager_executable": resolved,
        "source": recipe["source"],
        "command": recipe["command"],
        "argv": [resolved, *recipe["args"]] if resolved else None,
        "unavailable_reason": None
        if resolved
        else f"未检测到 {recipe['manager']}；请先安装该包管理器。",
    }


def _executable_name(executable: str | None) -> str:
    if not executable:
        return ""
    return Path(executable).stem.lower()


def _reasonix_npx_candidates() -> list[str]:
    """Find a cached npx Reasonix binary, while marking it as non-portable later."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        return []
    cache_root = Path(local_app_data) / "npm-cache" / "_npx"
    if not cache_root.is_dir():
        return []
    matches = list(
        cache_root.glob("*/node_modules/@reasonix/cli-win32-x64/bin/reasonix.exe")
    )
    matches.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
    return [str(path) for path in matches]


def _opencode_desktop_path() -> Path | None:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        return None
    candidate = (
        Path(local_app_data)
        / "Programs"
        / "@opencode-aidesktop"
        / "OpenCode.exe"
    )
    return candidate if candidate.is_file() else None


def _qoder_desktop_path() -> Path | None:
    resolved = shutil.which("qoder")
    if resolved:
        return Path(resolved)
    local_app_data = os.getenv("LOCALAPPDATA")
    program_files = os.getenv("PROGRAMFILES")
    candidates = [
        Path(local_app_data) / "Programs" / "Qoder" / "Qoder.exe"
        if local_app_data
        else None,
        Path(program_files) / "Qoder" / "Qoder.exe" if program_files else None,
    ]
    return next((item for item in candidates if item and item.is_file()), None)


def _npm_native_binary(shim: str, executable: str | None) -> str | None:
    """Resolve known npm .cmd shims to binaries that preserve multiline arguments."""
    shim_path = Path(shim)
    if shim_path.suffix.lower() not in {".cmd", ".bat"}:
        return None
    root = shim_path.parent
    patterns = {
        "codex": "node_modules/@openai/codex/node_modules/@openai/codex-*/vendor/*/bin/codex.exe",
        "claude": "node_modules/@anthropic-ai/claude-code/bin/claude.exe",
        "opencode": "node_modules/opencode-ai/bin/opencode.exe",
        "reasonix": "node_modules/reasonix/node_modules/@reasonix/cli-*/bin/reasonix.exe",
        # qoderclicn currently ships a Node bundle (no native main binary), so
        # this pattern only future-proofs resolution if a native exe is bundled.
        "qoderclicn": "node_modules/@qodercn-ai/qoderclicn/bin/qoderclicn.exe",
    }
    pattern = patterns.get(_executable_name(executable))
    if not pattern:
        return None
    matches = sorted(root.glob(pattern))
    return str(matches[0]) if matches else None


def _native_cli_candidates(executable: str | None) -> list[str]:
    """Return every PATH match in launch order, not only the first one.

    Windows Store app aliases can appear before a real npm-installed CLI and
    still be returned by ``shutil.which`` even when the alias cannot be
    executed by the desktop sidecar.  Keep the first match for compatibility,
    then inspect every PATH entry so callers can fall back to a working CLI.
    Explicit paths remain explicit and are never replaced with another binary.
    """
    if not executable:
        return []

    raw = Path(executable)
    explicit_path = raw.is_absolute() or bool(raw.drive) or raw.parent != Path(".")
    search_paths: list[str | None] = [None]
    if not explicit_path:
        search_paths.extend(os.get_exec_path())

    candidates: list[str] = []
    seen: set[str] = set()
    for search_path in search_paths:
        resolved = (
            shutil.which(executable)
            if search_path is None
            else shutil.which(executable, path=search_path)
        )
        if not resolved:
            continue
        key = os.path.normcase(os.path.abspath(resolved))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(resolved)
    if not explicit_path and _executable_name(executable) == "reasonix":
        for resolved in _reasonix_npx_candidates():
            key = os.path.normcase(os.path.abspath(resolved))
            if key not in seen:
                seen.add(key)
                candidates.append(resolved)
    if not explicit_path and _executable_name(executable) == "agent":
        # Cursor's official Windows installer updates the user PATH, which a
        # running desktop process may not inherit until restart. Probe its
        # documented install directory as a portable fallback.
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            cursor_root = Path(local_app_data) / "cursor-agent"
            for filename in ("agent.exe", "cursor-agent.exe", "agent.cmd"):
                resolved = cursor_root / filename
                if resolved.is_file():
                    key = os.path.normcase(os.path.abspath(resolved))
                    if key not in seen:
                        seen.add(key)
                        candidates.append(str(resolved))
    expanded: list[str] = []
    expanded_seen: set[str] = set()
    for candidate in candidates:
        native = _npm_native_binary(candidate, executable)
        for resolved in (native, candidate):
            if not resolved:
                continue
            key = os.path.normcase(os.path.abspath(resolved))
            if key in expanded_seen:
                continue
            expanded_seen.add(key)
            expanded.append(resolved)
    return expanded


def native_cli_status(executable: str | None) -> dict[str, Any]:
    candidates = _native_cli_candidates(executable)
    if not candidates:
        name = _executable_name(executable)
        result: dict[str, Any] = {
            "installed": False,
            "executable": executable,
            "version": None,
        }
        if name in INSTALL_COMMAND_BY_EXECUTABLE:
            result["install_command"] = INSTALL_COMMAND_BY_EXECUTABLE[name]
        if name == "opencode":
            desktop_path = _opencode_desktop_path()
            if desktop_path:
                result.update(
                    {
                        "desktop_installed": True,
                        "desktop_executable": str(desktop_path),
                        "error": "已安装 OpenCode 桌面版，但评测需要单独安装 opencode CLI",
                    }
                )
        if name == "qoderclicn":
            desktop_path = _qoder_desktop_path()
            if desktop_path:
                result.update(
                    {
                        "desktop_installed": True,
                        "desktop_executable": str(desktop_path),
                        "error": "已安装 Qoder 桌面版，但自动评测需要可返回结果的 qoderclicn，不能用 GUI chat 子命令代替",
                    }
                )
            if shutil.which("qodercli"):
                result["note"] = (
                    "检测到国际版 qodercli，但 AgentBench 需要国内版 Qoder CLI "
                    "（npm 包 @qodercn-ai/qoderclicn，命令 qoderclicn）；两者账号体系不互通"
                )
        return result

    last_failure: dict[str, Any] | None = None
    for resolved in candidates:
        try:
            result = subprocess.run(
                [resolved, "--version"], capture_output=True, text=True, timeout=5, check=False
            )
        except OSError as exc:
            last_failure = {
                "installed": False,
                "executable": resolved,
                "version": None,
                "error": str(exc),
            }
            continue
        except subprocess.TimeoutExpired:
            last_failure = {
                "installed": False,
                "executable": resolved,
                "version": None,
                "error": "Version check timed out",
            }
            continue

        version_text = (result.stdout or result.stderr).strip()
        version = version_text.splitlines()[0][:200] if version_text else None
        if result.returncode == 0:
            if _executable_name(executable) == "agent":
                cursor_identity = "cursor" in (version_text + " " + resolved).lower()
                if not cursor_identity:
                    try:
                        help_result = subprocess.run(
                            [resolved, "--help"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                            check=False,
                        )
                        help_text = (help_result.stdout or help_result.stderr).lower()
                        cursor_identity = "cursor agent" in help_text or all(
                            marker in help_text
                            for marker in ("create-chat", "install-shell-integration", "models")
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        cursor_identity = False
                if not cursor_identity:
                    last_failure = {
                        "installed": False,
                        "executable": resolved,
                        "version": version or None,
                        "error": "检测到同名 agent 命令，但它不是 Cursor Agent CLI",
                        "install_command": INSTALL_COMMAND_BY_EXECUTABLE["agent"],
                    }
                    continue
            status = {
                "installed": True,
                "executable": resolved,
                "version": version or None,
                "error": None,
            }
            if _executable_name(executable) == "reasonix" and "\\_npx\\" in resolved.lower():
                status.update(
                    {
                        "installation": "temporary_npx",
                        "warning": "Reasonix 来自一次性 npx 缓存，建议全局安装后再进行正式评测",
                        "install_command": INSTALL_COMMAND_BY_EXECUTABLE["reasonix"],
                    }
                )
            return status
        last_failure = {
            "installed": False,
            "executable": resolved,
            "version": version or None,
            "error": f"Version check exited {result.returncode}",
        }

    return last_failure or {"installed": False, "executable": executable, "version": None}


def run_native_cli(
    *,
    executable: str,
    args: list[str],
    workspace: Workspace,
    placeholders: dict[str, str],
    extra_env: dict[str, str],
    timeout: int,
    cancel_event: threading.Event | None = None,
    stdin_text: str | None = None,
    line_callback: Callable[[str, str], None] | None = None,
    heartbeat_callback: Callable[[int], None] | None = None,
    heartbeat_interval: float = 5.0,
) -> CommandResult:
    candidates = _native_cli_candidates(executable)
    if not candidates:
        return CommandResult(
            False, None, "", f"Executable not found: {executable}", 0, "cli_missing"
        )
    rendered: list[str] = []
    for part in args:
        value = part
        for key, replacement in placeholders.items():
            value = value.replace("{" + key + "}", replacement)
        rendered.append(value)
    environment = {key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV_KEYS}
    environment.update(extra_env)
    start = time.perf_counter()
    process: subprocess.Popen[str] | None = None
    last_start_error: OSError | None = None
    popen_options: dict[str, Any] = {}
    if os.name == "nt":
        popen_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_options["start_new_session"] = True
    for resolved in candidates:
        try:
            process = subprocess.Popen(
                [resolved, *rendered],
                cwd=workspace.root,
                env=environment,
                # stdin_text feeds large prompts (e.g. judge rubrics) through stdin so
                # they never hit Windows cmd.exe's 8191-char command line limit.
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **popen_options,
            )
            break
        except OSError as exc:
            last_start_error = exc

    if process is None:
        return CommandResult(
            False,
            None,
            "",
            f"Could not start {executable}: {last_start_error}",
            int((time.perf_counter() - start) * 1000),
            "cli_unavailable",
        )
    deadline = time.monotonic() + timeout if timeout > 0 else None
    output_parts: dict[str, list[str]] = {"stdout": [], "stderr": []}

    def drain(stream_name: str, stream) -> None:
        if stream is None:
            return
        try:
            for chunk in iter(stream.readline, ""):
                output_parts[stream_name].append(chunk)
                if line_callback is not None:
                    with suppress(Exception):
                        line_callback(stream_name, chunk.rstrip("\r\n"))
        finally:
            stream.close()

    readers = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()

    if stdin_text is not None and process.stdin is not None:
        try:
            process.stdin.write(stdin_text)
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()

    error_code: str | None = None
    next_heartbeat = time.monotonic() + max(0.5, heartbeat_interval)
    while process.poll() is None:
        now = time.monotonic()
        if cancel_event and cancel_event.is_set():
            error_code = "cancelled"
            _terminate_process_tree(process)
            break
        if deadline is not None and now > deadline:
            error_code = "runtime_safety_limit"
            _terminate_process_tree(process)
            break
        if heartbeat_callback is not None and now >= next_heartbeat:
            with suppress(Exception):
                heartbeat_callback(int((time.perf_counter() - start) * 1000))
            next_heartbeat = now + max(0.5, heartbeat_interval)
        time.sleep(0.1)

    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)
    if process.poll() is None:
        process.kill()
        process.wait()
    for reader in readers:
        reader.join(timeout=5)

    stdout = "".join(output_parts["stdout"])
    stderr = "".join(output_parts["stderr"])
    if error_code is not None:
        return CommandResult(
            False,
            None,
            stdout[-500_000:],
            stderr[-100_000:],
            int((time.perf_counter() - start) * 1000),
            error_code,
        )
    return CommandResult(
        process.returncode == 0,
        process.returncode,
        stdout[-500_000:],
        stderr[-100_000:],
        int((time.perf_counter() - start) * 1000),
        None if process.returncode == 0 else "cli_failed",
    )


def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    """Stop a CLI and every helper it spawned without targeting unrelated processes."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        with suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    else:
        with suppress(OSError):
            os.killpg(process.pid, signal.SIGTERM)
    if process.poll() is None:
        with suppress(OSError):
            process.terminate()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=3)
    if process.poll() is None:
        with suppress(OSError):
            process.kill()
