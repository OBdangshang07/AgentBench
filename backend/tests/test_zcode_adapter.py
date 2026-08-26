from __future__ import annotations

import json
import threading
from pathlib import Path
from subprocess import CompletedProcess

from agentbench.agent import AgentResult
from agentbench.execution import CommandResult, Workspace, native_cli_status
from agentbench.model_discovery import discover_models
from agentbench.schemas import ModelCreate
from agentbench.service import EvaluationService, runner_adapter_capabilities


def _desktop_config(secret: str = "SECRET-NOT-FOR-UI") -> dict:
    return {
        "provider": {
            "builtin:zai": {
                "name": "Z.AI",
                "kind": "openai-compatible",
                "enabled": True,
                "options": {
                    "apiKey": secret,
                    "baseURL": "https://api.z.ai/api/coding/paas/v4",
                },
                "models": {
                    "GLM-5.3": {
                        "reasoning": {
                            "enabled": True,
                            "variants": ["low", "high", "max"],
                            "defaultVariant": "high",
                        },
                        "zcode": {"priority": 100},
                    },
                    "GLM-5.3-Flash": {"zcode": {"priority": 50}},
                },
            },
            "disabled": {
                "enabled": False,
                "options": {"apiKey": "OTHER-SECRET"},
                "models": {"hidden": {}},
            },
        }
    }


def test_zcode_status_uses_official_desktop_runtime(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "ZCode.exe"
    script = tmp_path / "zcode.cjs"
    executable.write_bytes(b"desktop")
    script.write_text("", encoding="utf-8")
    runtime = {
        "executable": str(executable),
        "script": str(script),
        "desktop_config": str(tmp_path / "config.json"),
    }
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr("agentbench.execution.zcode_desktop_runtime", lambda: runtime)

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return CompletedProcess(args, 0, "0.16.3\n", "")

    monkeypatch.setattr("agentbench.execution.subprocess.run", fake_run)

    status = native_cli_status("zcode")

    assert status["installed"] is True
    assert status["version"] == "0.16.3"
    assert status["runtime_script"] == str(script)
    assert calls[0][0] == [str(executable), str(script), "--version"]
    assert calls[0][1]["env"]["ELECTRON_RUN_AS_NODE"] == "1"


def test_zcode_discovery_reads_catalog_without_exposing_keys(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps(_desktop_config()), encoding="utf-8")
    monkeypatch.setattr(
        "agentbench.model_discovery.zcode_desktop_runtime",
        lambda: {
            "executable": "ZCode.exe",
            "script": "zcode.cjs",
            "desktop_config": str(config),
        },
    )
    monkeypatch.setattr(
        "agentbench.model_discovery.native_cli_status",
        lambda _name: {"installed": True, "executable": "ZCode.exe", "version": "0.16.3"},
    )

    result = discover_models(source="zcode-cli")

    assert [item["id"] for item in result["models"]] == ["GLM-5.3", "GLM-5.3-Flash"]
    assert result["models"][0]["provider_id"] == "builtin:zai"
    assert result["models"][0]["is_default"] is True
    assert "SECRET-NOT-FOR-UI" not in json.dumps(result)
    assert "OTHER-SECRET" not in json.dumps(result)


def test_zcode_discovery_excludes_provider_missing_required_credentials(
    monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "config.json"
    provider = _desktop_config()["provider"]["builtin:zai"]
    provider["name"] = "Z.ai - Coding Plan"
    provider["options"]["apiKey"] = ""
    provider["options"]["apiKeyRequired"] = True
    config.write_text(
        json.dumps({"provider": {"builtin:zai-coding-plan": provider}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agentbench.model_discovery.zcode_desktop_runtime",
        lambda: {
            "executable": "ZCode.exe",
            "script": "zcode.cjs",
            "desktop_config": str(config),
        },
    )
    monkeypatch.setattr(
        "agentbench.model_discovery.native_cli_status",
        lambda _name: {"installed": True, "executable": "ZCode.exe", "version": "0.16.3"},
    )

    result = discover_models(source="zcode-cli")

    assert result["models"] == []
    assert result["providers"] == []
    assert any("尚未完成凭据登录" in warning for warning in result["warnings"])


def test_zcode_run_config_is_isolated_and_maps_reasoning(settings, tmp_path, monkeypatch) -> None:
    source = tmp_path / "desktop-config.json"
    original = json.dumps(_desktop_config())
    source.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "agentbench.service.zcode_desktop_runtime",
        lambda: {
            "executable": "ZCode.exe",
            "script": "zcode.cjs",
            "desktop_config": str(source),
        },
    )
    service = EvaluationService(settings)
    try:
        runtime_root, effort, script = service._prepare_zcode_run_config(
            "builtin:zai", "GLM-5.3", "max"
        )
        isolated = json.loads(
            (runtime_root / ".zcode" / "cli" / "config.json").read_text(encoding="utf-8")
        )

        assert effort == "max"
        assert script == "zcode.cjs"
        assert isolated["model"]["main"] == "builtin:zai/GLM-5.3"
        assert list(isolated["provider"]) == ["builtin:zai"]
        assert list(isolated["provider"]["builtin:zai"]["models"]) == ["GLM-5.3"]
        assert (
            isolated["provider"]["builtin:zai"]["models"]["GLM-5.3"]
            ["reasoning"]["defaultVariant"]
            == "max"
        )
        assert source.read_text(encoding="utf-8") == original
    finally:
        service.close()


def test_zcode_run_config_explicitly_enables_implicit_desktop_provider(
    settings, tmp_path, monkeypatch
) -> None:
    provider = _desktop_config()["provider"]["builtin:zai"]
    provider.pop("enabled")
    source = tmp_path / "desktop-config.json"
    source.write_text(
        json.dumps({"provider": {"builtin:zai-coding-plan": provider}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agentbench.service.zcode_desktop_runtime",
        lambda: {
            "executable": "ZCode.exe",
            "script": "zcode.cjs",
            "desktop_config": str(source),
        },
    )
    service = EvaluationService(settings)
    try:
        runtime_root, _effort, _script = service._prepare_zcode_run_config(
            "builtin:zai-coding-plan", "GLM-5.3-Flash", "high"
        )
        isolated = json.loads(
            (runtime_root / ".zcode" / "cli" / "config.json").read_text(
                encoding="utf-8"
            )
        )

        assert isolated["provider"]["builtin:zai-coding-plan"]["enabled"] is True
    finally:
        service.close()


def test_zcode_permissions_attachments_and_capabilities_are_honest() -> None:
    configured = EvaluationService._studio_native_options(
        ["{zcode_cli}", "--json", "--mode", "edit", "--prompt", "{prompt}"],
        "zcode_cli",
        "readonly",
        "high",
        [{"absolute_path": "D:/work/input.png"}],
    )

    assert configured[configured.index("--mode") + 1] == "plan"
    assert configured[configured.index("--attach") + 1] == "D:/work/input.png"
    capability = runner_adapter_capabilities("zcode_cli", ["native-cli", "filesystem", "shell"])
    assert capability["native_resume"] is False
    assert capability["conversation_mode"] == "history_replay"
    assert capability["structured_events"] == "stream"
    assert capability["visible_browser"] is False


def test_zcode_native_run_uses_ephemeral_home_and_cleans_it(
    settings, tmp_path, monkeypatch
) -> None:
    source = tmp_path / "desktop-config.json"
    source.write_text(json.dumps(_desktop_config()), encoding="utf-8")
    monkeypatch.setattr(
        "agentbench.service.zcode_desktop_runtime",
        lambda: {
            "executable": "ZCode.exe",
            "script": "zcode.cjs",
            "desktop_config": str(source),
        },
    )
    captured: dict[str, object] = {}

    def fake_run_native_cli(**kwargs):
        captured.update(kwargs)
        return CommandResult(
            True,
            0,
            json.dumps({"type": "result", "result": "OK", "session_id": "sess_test"}),
            "",
            10,
        )

    monkeypatch.setattr("agentbench.service.run_native_cli", fake_run_native_cli)
    service = EvaluationService(settings)
    monkeypatch.setattr(service, "_native_cli_allowed", lambda: True)
    try:
        result = service._run_native_agent(
            {
                "runner_type": "zcode_cli",
                "executable": "zcode",
                "args_json": json.dumps(
                    ["{zcode_cli}", "--json", "--mode", "edit", "--prompt", "{prompt}"]
                ),
                "env_json": "{}",
                "limits_json": "{}",
            },
            {
                "provider": "zcode-cli",
                "model_name": "GLM-5.3",
                "settings_json": json.dumps({"agent_provider": "builtin:zai"}),
            },
            {
                "instruction": "Return OK",
                "limits": {"timeout_seconds": 30},
                "metadata": {"reasoning_effort": "high"},
            },
            Workspace(tmp_path / "workspace"),
            lambda *_args: None,
            threading.Event(),
        )

        assert result.ok is True
        assert result.final_answer == "OK"
        assert captured["extra_env"]["ELECTRON_RUN_AS_NODE"] == "1"
        runtime_home = Path(captured["extra_env"]["USERPROFILE"])
        assert captured["placeholders"]["zcode_cli"] == "zcode.cjs"
        assert not runtime_home.exists()
    finally:
        service.close()


def test_zcode_pretty_json_output_is_parsed_as_public_result() -> None:
    output = json.dumps(
        {
            "sessionId": "sess_real_shape",
            "response": "OK",
            "usage": {"inputTokens": 12829, "outputTokens": 17},
            "eventCount": 26,
        },
        indent=2,
    )

    final, input_tokens, output_tokens, cost, count = EvaluationService._parse_native_output(
        "zcode_cli", output
    )

    assert final == "OK"
    assert input_tokens == 12829
    assert output_tokens == 17
    assert cost is None
    assert count == 26
    assert EvaluationService._extract_native_session_id(output) == "sess_real_shape"


def test_zcode_result_event_becomes_live_message() -> None:
    normalized = EvaluationService._normalize_native_live_event(
        "zcode_cli",
        "stdout",
        json.dumps({"response": "OK", "usage": {"inputTokens": 10, "outputTokens": 2}}),
        1,
    )

    assert normalized is not None
    event_type, payload = normalized
    assert event_type == "live.message"
    assert payload["text"] == "OK"
    assert payload["usage"]["input_tokens"] == 10
    assert payload["usage"]["output_tokens"] == 2


def test_zcode_model_test_uses_native_runner(settings, monkeypatch) -> None:
    captured: dict[str, object] = {}
    service = EvaluationService(settings)
    monkeypatch.setattr(service, "_native_cli_allowed", lambda: True)
    monkeypatch.setattr(service, "_check_runner", lambda _runner: ([], []))

    def fake_run_native_agent(
        runner, model, definition, workspace, _event_sink, _cancel_event
    ):
        captured.update(
            {
                "runner": runner,
                "model": model,
                "definition": definition,
                "workspace": workspace,
            }
        )
        return AgentResult(
            True,
            "AGENTBENCH-OK",
            1,
            service._empty_usage(),
            12,
        )

    monkeypatch.setattr(service, "_run_native_agent", fake_run_native_agent)
    try:
        service.update_settings({"allow_native_cli": True})
        model = service.create_model(
            ModelCreate(
                name="ZCode smoke",
                provider="zcode-cli",
                model_name="GLM-5.3-Flash",
                agent_provider="builtin:zai",
            )
        )

        result = service.test_model(model["id"])

        assert result["ok"] is True
        assert result["runner_type"] == "zcode_cli"
        assert captured["runner"]["runner_type"] == "zcode_cli"
        assert captured["model"]["provider"] == "zcode-cli"
        assert captured["definition"]["instruction"] == (
            "Return exactly AGENTBENCH-OK and nothing else."
        )
        workspace = captured["workspace"]
        assert isinstance(workspace, Workspace)
        assert not workspace.root.exists()
    finally:
        service.close()
