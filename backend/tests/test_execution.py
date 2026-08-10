from __future__ import annotations

import sys
from subprocess import CompletedProcess

import pytest

from agentbench.execution import (
    DockerExecutor,
    Workspace,
    WorkspaceViolation,
    _npm_native_binary,
    native_cli_status,
    resolve_cli_install_plan,
    run_native_cli,
    safe_workspace_path,
)


def test_cli_install_plan_uses_only_code_owned_argv():
    def resolver(candidate: str):
        return "C:/Program Files/nodejs/npm.cmd" if candidate == "npm.cmd" else None

    plan = resolve_cli_install_plan("codex_cli", resolver)

    assert plan["available"] is True
    assert plan["command"] == "npm install -g @openai/codex"
    assert plan["argv"] == [
        "C:/Program Files/nodejs/npm.cmd",
        "install",
        "-g",
        "@openai/codex",
    ]
    qoder_plan = resolve_cli_install_plan("qoder_cli", resolver)
    assert qoder_plan["supported"] is True
    assert qoder_plan["available"] is True
    assert qoder_plan["command"] == "npm install -g @qodercn-ai/qoderclicn"
    assert qoder_plan["argv"] == [
        "C:/Program Files/nodejs/npm.cmd",
        "install",
        "-g",
        "@qodercn-ai/qoderclicn",
    ]


def test_workspace_rejects_path_escape(tmp_path):
    workspace = Workspace(tmp_path / "run")
    with pytest.raises(WorkspaceViolation):
        safe_workspace_path(workspace.root, "../secret.txt")
    with pytest.raises(WorkspaceViolation):
        workspace.write_file("C:/Windows/System32/test.txt", "unsafe")


def test_workspace_tools_are_scoped(tmp_path):
    workspace = Workspace(tmp_path / "run")
    workspace.write_file("src/example.txt", "Alpha\nBeta\n")
    assert workspace.read_file("src/example.txt") == "Alpha\nBeta\n"
    assert workspace.list_files() == ["src/example.txt"]
    assert workspace.search_text("beta")[0]["line"] == 2


def test_custom_native_cli_is_started_without_shell_interpolation(tmp_path):
    workspace = Workspace(tmp_path / "run")
    result = run_native_cli(
        executable=sys.executable,
        args=["-c", "import json; print(json.dumps({'type':'result','result':'OK'}))"],
        workspace=workspace,
        placeholders={"prompt": "ignored", "model_name": "mock", "workspace": str(workspace.root)},
        extra_env={},
        timeout=10,
    )
    assert result.ok is True
    assert '"result": "OK"' in result.stdout


def test_native_cli_preserves_required_windows_system_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("SYSTEMDRIVE", "Q:")
    monkeypatch.setenv("PROGRAMDATA", "Q:\\ProgramData")
    workspace = Workspace(tmp_path / "windows-env-run")

    result = run_native_cli(
        executable=sys.executable,
        args=[
            "-c",
            "import os; print(os.environ.get('SYSTEMDRIVE')); print(os.environ.get('PROGRAMDATA'))",
        ],
        workspace=workspace,
        placeholders={},
        extra_env={},
        timeout=10,
    )

    assert result.ok is True
    assert result.stdout.splitlines() == ["Q:", "Q:\\ProgramData"]


def test_run_native_cli_delivers_long_stdin_text_without_argv(tmp_path):
    workspace = Workspace(tmp_path / "stdin-run")
    payload = "评审任务行\n" * 3000  # > 8191 chars, multi-line
    result = run_native_cli(
        executable=sys.executable,
        args=["-c", "import sys; sys.stdout.write(sys.stdin.read())"],
        workspace=workspace,
        placeholders={},
        extra_env={},
        timeout=20,
        stdin_text=payload,
    )

    assert result.ok is True
    assert result.stdout == payload


def test_run_native_cli_keeps_devnull_stdin_by_default(tmp_path):
    workspace = Workspace(tmp_path / "stdin-default")
    result = run_native_cli(
        executable=sys.executable,
        args=["-c", "import sys; print('closed' if sys.stdin.read() == '' else 'data')"],
        workspace=workspace,
        placeholders={},
        extra_env={},
        timeout=10,
    )

    assert result.ok is True
    assert result.stdout.strip() == "closed"


def test_verbose_native_cli_does_not_deadlock_when_pipes_fill(tmp_path):
    workspace = Workspace(tmp_path / "verbose-run")
    result = run_native_cli(
        executable=sys.executable,
        args=["-c", "import sys; sys.stdout.write('x' * 2_000_000)"],
        workspace=workspace,
        placeholders={},
        extra_env={},
        timeout=10,
    )

    assert result.ok is True
    assert len(result.stdout) == 500_000
    assert set(result.stdout) == {"x"}


def test_native_cli_streams_lines_and_heartbeats_while_running(tmp_path):
    workspace = Workspace(tmp_path / "stream-run")
    lines: list[tuple[str, str]] = []
    heartbeats: list[int] = []
    result = run_native_cli(
        executable=sys.executable,
        args=[
            "-c",
            "import time; print('first', flush=True); time.sleep(0.7); print('second', flush=True)",
        ],
        workspace=workspace,
        placeholders={},
        extra_env={},
        timeout=10,
        line_callback=lambda stream, line: lines.append((stream, line)),
        heartbeat_callback=heartbeats.append,
        heartbeat_interval=0.2,
    )

    assert result.ok is True
    assert lines == [("stdout", "first"), ("stdout", "second")]
    assert heartbeats
    assert heartbeats == sorted(heartbeats)


def test_native_cli_status_skips_an_unlaunchable_path_alias(monkeypatch):
    candidates = ["blocked-store-alias.exe", "working-cli.cmd"]

    def fake_run(args, **_kwargs):
        if args[0] == candidates[0]:
            raise PermissionError("alias cannot be executed")
        return CompletedProcess(args, 0, "working-cli 2.0.0\n", "")

    monkeypatch.setattr("agentbench.execution._native_cli_candidates", lambda _name: candidates)
    monkeypatch.setattr("agentbench.execution.subprocess.run", fake_run)

    status = native_cli_status("working-cli")

    assert status == {
        "installed": True,
        "executable": candidates[1],
        "version": "working-cli 2.0.0",
        "error": None,
    }


def test_npm_codex_shim_resolves_to_native_binary(tmp_path):
    shim = tmp_path / "codex.cmd"
    shim.write_text("wrapper", encoding="utf-8")
    native = (
        tmp_path
        / "node_modules"
        / "@openai"
        / "codex"
        / "node_modules"
        / "@openai"
        / "codex-win32-x64"
        / "vendor"
        / "x86_64-pc-windows-msvc"
        / "bin"
        / "codex.exe"
    )
    native.parent.mkdir(parents=True)
    native.write_bytes(b"native")

    assert _npm_native_binary(str(shim), "codex") == str(native)


def test_opencode_desktop_is_reported_as_desktop_only(tmp_path, monkeypatch):
    desktop = tmp_path / "OpenCode.exe"
    desktop.write_bytes(b"desktop")
    monkeypatch.setattr("agentbench.execution._native_cli_candidates", lambda _name: [])
    monkeypatch.setattr("agentbench.execution._opencode_desktop_path", lambda: desktop)

    status = native_cli_status("opencode")

    assert status["installed"] is False
    assert status["desktop_installed"] is True
    assert status["desktop_executable"] == str(desktop)
    assert status["install_command"] == "npm install -g opencode-ai"
    assert "桌面版" in status["error"]


def test_qoder_desktop_is_not_mistaken_for_headless_cli(tmp_path, monkeypatch):
    desktop = tmp_path / "Qoder.exe"
    desktop.write_bytes(b"desktop")
    monkeypatch.setattr("agentbench.execution._native_cli_candidates", lambda _name: [])
    monkeypatch.setattr("agentbench.execution._qoder_desktop_path", lambda: desktop)

    status = native_cli_status("qoderclicn")

    assert status["installed"] is False
    assert status["desktop_installed"] is True
    assert status["desktop_executable"] == str(desktop)
    assert "qoderclicn" in status["error"]
    assert "GUI" in status["error"]
    assert status["install_command"] == "npm install -g @qodercn-ai/qoderclicn"


def test_international_qodercli_alone_suggests_domestic_package(monkeypatch):
    monkeypatch.setattr("agentbench.execution._native_cli_candidates", lambda _name: [])
    monkeypatch.setattr("agentbench.execution._qoder_desktop_path", lambda: None)
    monkeypatch.setattr(
        "agentbench.execution.shutil.which",
        lambda name: "C:/nodejs/qodercli.cmd" if name == "qodercli" else None,
    )

    status = native_cli_status("qoderclicn")

    assert status["installed"] is False
    assert "国际版" in status["note"]
    assert "@qodercn-ai/qoderclicn" in status["note"]
    assert status["install_command"] == "npm install -g @qodercn-ai/qoderclicn"


def test_reasonix_npx_cache_is_available_but_marked_temporary(monkeypatch):
    cached = r"C:\Users\test\AppData\Local\npm-cache\_npx\abc\reasonix.exe"
    monkeypatch.setattr("agentbench.execution._native_cli_candidates", lambda _name: [cached])
    monkeypatch.setattr(
        "agentbench.execution.subprocess.run",
        lambda args, **_kwargs: CompletedProcess(args, 0, "reasonix 1.19.0\n", ""),
    )

    status = native_cli_status("reasonix")

    assert status["installed"] is True
    assert status["installation"] == "temporary_npx"
    assert status["install_command"] == "npm install -g reasonix"
    assert "一次性 npx" in status["warning"]


def test_native_cli_run_skips_an_unlaunchable_path_alias(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "run")
    candidates = ["blocked-store-alias.exe", sys.executable]
    real_popen = __import__("subprocess").Popen
    attempted: list[str] = []
    launch_options: dict[str, object] = {}

    def fallback_popen(args, **kwargs):
        attempted.append(args[0])
        launch_options.update(kwargs)
        if args[0] == candidates[0]:
            raise PermissionError("alias cannot be executed")
        return real_popen(args, **kwargs)

    monkeypatch.setattr("agentbench.execution._native_cli_candidates", lambda _name: candidates)
    monkeypatch.setattr("agentbench.execution.subprocess.Popen", fallback_popen)

    result = run_native_cli(
        executable="working-cli",
        args=["-c", "print('fallback-ok')"],
        workspace=workspace,
        placeholders={},
        extra_env={},
        timeout=10,
    )

    assert attempted == candidates
    assert result.ok is True
    assert result.stdout.strip() == "fallback-ok"
    assert launch_options["stdin"] == __import__("subprocess").DEVNULL


def test_docker_executor_applies_isolation_flags(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        if args[1] == "info":
            return CompletedProcess(args, 0, "27.0", "")
        return CompletedProcess(args, 0, "validator-ok", "")

    monkeypatch.setattr("agentbench.execution.subprocess.run", fake_run)
    workspace = Workspace(tmp_path / "run")
    result = DockerExecutor(executable="docker").run(
        workspace, "python -m pytest", "python:3.12-alpine", network="disabled"
    )
    assert result.ok is True
    command = calls[-1]
    assert command[
        command.index("--network") : command.index("--network") + 2
    ] == ["--network", "none"]
    assert "--read-only" in command
    assert command[
        command.index("--cap-drop") : command.index("--cap-drop") + 2
    ] == ["--cap-drop", "ALL"]
    assert "no-new-privileges" in command
    assert str(workspace.root) in " ".join(command)
