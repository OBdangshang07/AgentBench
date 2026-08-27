from __future__ import annotations

import json
import threading

import pytest

from agentbench.execution import CommandResult, Workspace
from agentbench.service import EvaluationService


@pytest.mark.parametrize(
    ("errors", "expected_detail"),
    [
        (["terminated"], "terminated"),
        (
            ["Malformed tool call stream: content_after_tool_call_start"],
            "Malformed tool call stream",
        ),
    ],
)
def test_qoder_zero_exit_execution_error_is_not_a_success(
    settings, tmp_path, monkeypatch, errors, expected_detail
) -> None:
    captured: dict[str, object] = {}
    events: list[tuple[str, dict]] = []
    output = json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "result": "partial work",
            "errors": errors,
            "credits": 1.25,
            "modelUsage": {"qfmodel": {"credits": 1.25}},
        }
    )

    def fake_run_native_cli(**kwargs):
        captured.update(kwargs)
        return CommandResult(True, 0, output, "", 50)

    monkeypatch.setattr("agentbench.service.run_native_cli", fake_run_native_cli)
    service = EvaluationService(settings)
    monkeypatch.setattr(service, "_native_cli_allowed", lambda: True)
    runtime_root = settings.data_dir / "native-runtime" / "qoder" / "test-runtime"
    runtime_root.mkdir(parents=True)
    monkeypatch.setattr(service, "_prepare_qoder_run_config", lambda: runtime_root)
    try:
        result = service._run_native_agent(
            {
                "runner_type": "qoder_cli",
                "executable": "qoderclicn",
                "args_json": json.dumps(
                    [
                        "--print",
                        "--output-format",
                        "json",
                        "--dangerously-skip-permissions",
                        "--model",
                        "{model_name}",
                        "{prompt}",
                    ]
                ),
                "env_json": "{}",
                "limits_json": "{}",
            },
            {
                "provider": "qoder-cli",
                "model_name": "Qwen3.8-Flash",
                "settings_json": "{}",
            },
            {
                "instruction": "Implement the task",
                "tools": ["filesystem", "shell"],
                "limits": {"timeout_seconds": 30},
                "metadata": {"reasoning_effort": "high"},
            },
            Workspace(tmp_path / "workspace"),
            lambda event_type, payload: events.append((event_type, payload)),
            threading.Event(),
        )

        assert result.ok is False
        assert result.error_code == "native_agent_execution_error"
        assert expected_detail in str(result.error_message)
        assert not any(event_type == "run.validating" for event_type, _ in events)
        error_event = next(
            payload for event_type, payload in events if event_type == "native_cli.result_error"
        )
        assert error_event["subtype"] == "error_during_execution"
        assert error_event["errors"] == errors
        assert error_event["credits"] == 1.25

        args = captured["args"]
        assert args[args.index("--setting-sources") + 1] == ""
        assert args[args.index("--mcp-config") + 1] == '{"mcpServers":{}}'
        assert "--strict-mcp-config" in args
        assert "--disable-builtin-skills" in args
        assert "--headless-fast-hooks" in args
        assert "--no-session-persistence" in args
        assert args[args.index("--config-dir") + 1] == str(runtime_root)
        assert not runtime_root.exists()
    finally:
        service.close()


def test_qoder_success_result_remains_scoreable() -> None:
    output = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "completed",
            "credits": 0.75,
            "modelUsage": {"qfmodel": {"credits": 0.75}},
        }
    )

    assert EvaluationService._native_result_failure("qoder_cli", output) is None
    final, input_tokens, output_tokens, cost, count = EvaluationService._parse_native_output(
        "qoder_cli", output
    )

    assert final == "completed"
    assert (input_tokens, output_tokens, cost, count) == (0, 0, None, 1)


def test_qoder_result_error_is_visible_as_failed_live_phase() -> None:
    normalized = EvaluationService._normalize_native_live_event(
        "qoder_cli",
        "stdout",
        json.dumps(
            {
                "type": "result",
                "subtype": "error_during_execution",
                "is_error": True,
                "errors": ["terminated"],
            }
        ),
        1,
    )

    assert normalized is not None
    event_type, payload = normalized
    assert event_type == "live.phase"
    assert payload["status"] == "failed"
    assert payload["subtype"] == "error_during_execution"
    assert payload["detail"] == "terminated"


def test_qoder_ephemeral_config_copies_login_but_excludes_personal_extensions(
    settings, tmp_path
) -> None:
    source = tmp_path / "qoder-user"
    (source / ".auth").mkdir(parents=True)
    (source / ".auth" / "user").write_text("test-login", encoding="utf-8")
    (source / ".models").mkdir()
    (source / ".models" / "default").write_text("Qwen3.8-Flash", encoding="utf-8")
    (source / "plugins" / "hyperframes").mkdir(parents=True)
    (source / "skills" / "hyperframes").mkdir(parents=True)
    (source / "settings.json").write_text('{"enabledPlugins":["hyperframes"]}', encoding="utf-8")
    (source / "installation_id").write_text("installation", encoding="utf-8")

    service = EvaluationService(settings)
    try:
        runtime_root = service._prepare_qoder_run_config(source)

        assert (runtime_root / ".auth" / "user").read_text(encoding="utf-8") == "test-login"
        assert (runtime_root / ".models" / "default").is_file()
        assert (runtime_root / "installation_id").is_file()
        assert not (runtime_root / "plugins").exists()
        assert not (runtime_root / "skills").exists()
        assert not (runtime_root / "settings.json").exists()
    finally:
        service.close()


def test_qoder_private_coding_task_retries_zero_change_completion(
    settings, tmp_path, monkeypatch
) -> None:
    calls: list[dict] = []
    output = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "Now writing the implementation.",
        }
    )

    def fake_run_native_cli(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            kwargs["workspace"].write_file("solution.py", "IMPLEMENTED = True\n")
            completed = json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "Implemented and verified.",
                }
            )
            return CommandResult(True, 0, completed, "", 2_000)
        return CommandResult(True, 0, output, "", 1_000)

    monkeypatch.setattr("agentbench.service.run_native_cli", fake_run_native_cli)
    service = EvaluationService(settings)
    monkeypatch.setattr(service, "_native_cli_allowed", lambda: True)
    runtime_root = settings.data_dir / "native-runtime" / "qoder" / "retry-runtime"
    runtime_root.mkdir(parents=True)
    monkeypatch.setattr(service, "_prepare_qoder_run_config", lambda: runtime_root)
    events: list[tuple[str, dict]] = []
    try:
        result = service._run_native_agent(
            {
                "runner_type": "qoder_cli",
                "executable": "qoderclicn",
                "args_json": json.dumps(
                    ["--print", "--output-format", "json", "{prompt}"]
                ),
                "env_json": "{}",
                "limits_json": "{}",
            },
            {
                "provider": "qoder-cli",
                "model_name": "Qwen3.8-Flash",
                "settings_json": "{}",
            },
            {
                "instruction": "Implement the task",
                "tools": ["filesystem", "shell"],
                "initial_files": {"solution.py": "# TODO\n"},
                "limits": {"timeout_seconds": 120},
                "metadata": {
                    "reasoning_effort": "high",
                    "private_validation": True,
                },
            },
            Workspace(tmp_path / "retry-workspace"),
            lambda event_type, payload: events.append((event_type, payload)),
            threading.Event(),
        )

        assert result.ok is True
        assert result.duration_ms == 3_000
        assert len(calls) == 2
        assert "RECOVERY TURN" in calls[1]["placeholders"]["prompt"]
        assert calls[1]["timeout"] == 119
        assert any(event_type == "native_cli.completion_retry" for event_type, _ in events)
        assert (tmp_path / "retry-workspace" / "solution.py").is_file()
    finally:
        service.close()


def test_qoder_private_coding_task_zero_change_is_not_scored(
    settings, tmp_path, monkeypatch
) -> None:
    calls = 0
    output = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "I will implement it next.",
        }
    )

    def fake_run_native_cli(**_kwargs):
        nonlocal calls
        calls += 1
        return CommandResult(True, 0, output, "", 1_000)

    monkeypatch.setattr("agentbench.service.run_native_cli", fake_run_native_cli)
    service = EvaluationService(settings)
    monkeypatch.setattr(service, "_native_cli_allowed", lambda: True)
    runtime_root = settings.data_dir / "native-runtime" / "qoder" / "empty-runtime"
    runtime_root.mkdir(parents=True)
    monkeypatch.setattr(service, "_prepare_qoder_run_config", lambda: runtime_root)
    events: list[tuple[str, dict]] = []
    try:
        result = service._run_native_agent(
            {
                "runner_type": "qoder_cli",
                "executable": "qoderclicn",
                "args_json": json.dumps(
                    ["--print", "--output-format", "json", "{prompt}"]
                ),
                "env_json": "{}",
                "limits_json": "{}",
            },
            {
                "provider": "qoder-cli",
                "model_name": "Qwen3.8-Flash",
                "settings_json": "{}",
            },
            {
                "instruction": "Implement the task",
                "tools": ["filesystem", "shell"],
                "initial_files": {"solution.py": "# TODO\n"},
                "limits": {"timeout_seconds": 120},
                "metadata": {
                    "reasoning_effort": "high",
                    "private_validation": True,
                },
            },
            Workspace(tmp_path / "empty-workspace"),
            lambda event_type, payload: events.append((event_type, payload)),
            threading.Event(),
        )

        assert calls == 2
        assert result.ok is False
        assert result.error_code == "native_agent_no_workspace_changes"
        assert "not scored" in str(result.error_message)
        error = next(
            payload
            for event_type, payload in events
            if event_type == "native_cli.result_error"
            and payload.get("subtype") == "no_workspace_changes"
        )
        assert error["is_error"] is True
    finally:
        service.close()


def test_qoder_private_answer_task_does_not_require_workspace_changes(
    settings, tmp_path, monkeypatch
) -> None:
    calls: list[dict] = []
    output = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": '{"answer":"B"}',
        }
    )

    def fake_run_native_cli(**kwargs):
        calls.append(kwargs)
        return CommandResult(True, 0, output, "", 1_000)

    monkeypatch.setattr("agentbench.service.run_native_cli", fake_run_native_cli)
    service = EvaluationService(settings)
    monkeypatch.setattr(service, "_native_cli_allowed", lambda: True)
    runtime_root = settings.data_dir / "native-runtime" / "qoder" / "answer-runtime"
    runtime_root.mkdir(parents=True)
    monkeypatch.setattr(service, "_prepare_qoder_run_config", lambda: runtime_root)
    try:
        result = service._run_native_agent(
            {
                "runner_type": "qoder_cli",
                "executable": "qoderclicn",
                "args_json": json.dumps(["--print", "--output-format", "json", "{prompt}"]),
                "env_json": "{}",
                "limits_json": "{}",
            },
            {
                "provider": "qoder-cli",
                "model_name": "Qwen3.8-Flash",
                "settings_json": "{}",
            },
            {
                "instruction": "Question line one\nReturn strict JSON on line two",
                "tools": ["filesystem", "search", "shell"],
                "initial_files": {},
                "limits": {"timeout_seconds": 120},
                "metadata": {
                    "reasoning_effort": "high",
                    "private_validation": True,
                },
            },
            Workspace(tmp_path / "answer-workspace"),
            lambda _event_type, _payload: None,
            threading.Event(),
        )

        assert result.ok is True
        assert result.final_answer == '{"answer":"B"}'
        assert len(calls) == 1
        rendered_prompt = calls[0]["placeholders"]["prompt"]
        assert "Question line one" in rendered_prompt
        assert "Return strict JSON on line two" in rendered_prompt
        if __import__("os").name == "nt":
            assert "\n" not in rendered_prompt
    finally:
        service.close()
