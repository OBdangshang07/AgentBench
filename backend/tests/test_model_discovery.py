from __future__ import annotations

import json
import threading
from subprocess import CompletedProcess

import httpx
from fastapi.testclient import TestClient

from agentbench.api import create_app
from agentbench.execution import CommandResult, Workspace
from agentbench.model_discovery import discover_models
from agentbench.schemas import ModelCreate
from agentbench.service import EvaluationService


def _installed_cli(executable: str | None) -> dict[str, object]:
    return {
        "installed": True,
        "executable": executable or "codex",
        "version": "test-cli 1.0",
        "error": None,
    }


def test_deepseek_harness_discovery_reads_default_and_provider_catalog(tmp_path, monkeypatch):
    dsh_home = tmp_path / "dsh-home"
    dsh_home.mkdir()
    (dsh_home / "settings.yaml").write_text(
        """
agent-default-model:
  provider: deepseek-official
  model: deepseek-v4-pro
llm-deepseek:
  models:
    - id: deepseek-v4-flash
      name: DeepSeek V4 Flash
    - id: deepseek-v4-pro
      name: DeepSeek V4 Pro
llm-pi-ai:
  providers:
    third-party:
      displayName: Third Party
      apiKey: DO-NOT-EXPOSE
      models:
        - id: fable-5
          name: Fable 5
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    monkeypatch.setattr("agentbench.model_discovery.native_cli_status", _installed_cli)

    result = discover_models(source="deepseek-harness")
    by_key = {(item["provider_id"], item["id"]): item for item in result["models"]}

    assert by_key[("deepseek-official", "deepseek-v4-pro")]["is_default"] is True
    assert ("deepseek-official", "deepseek-v4-flash") in by_key
    assert ("third-party", "fable-5") in by_key
    assert "DO-NOT-EXPOSE" not in json.dumps(result)
    assert any("Developer Preview" in warning for warning in result["warnings"])


def test_deepseek_harness_discovery_survives_malformed_yaml(tmp_path, monkeypatch):
    dsh_home = tmp_path / "dsh-home"
    dsh_home.mkdir()
    (dsh_home / "settings.yaml").write_text("models: [", encoding="utf-8")
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    monkeypatch.setattr("agentbench.model_discovery.native_cli_status", _installed_cli)

    result = discover_models(source="deepseek-harness")

    assert any(item["id"] == "deepseek-v4-flash" for item in result["models"])
    assert any("settings.yaml" in warning for warning in result["warnings"])


def test_deepseek_harness_plain_text_output_is_final_answer():
    output = "正在整理最终回答。\n\n这是 Harness 的最终结果。"

    final, input_tokens, output_tokens, cost, count = EvaluationService._parse_native_output(
        "deepseek_harness", output
    )

    assert final == output
    assert (input_tokens, output_tokens, cost, count) == (0, 0, None, 1)


def test_codex_discovery_reads_visible_cache_and_configured_providers(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        """
model = "gpt-5.6-sol"
model_provider = "openai_http"

[model_providers.openai_http]
name = "OpenAI Login"
base_url = "https://chatgpt.com/backend-api/codex"
wire_api = "responses"
requires_openai_auth = true

[model_providers.deepseek]
name = "DeepSeek Provider"
base_url = "https://api.deepseek.example/v1"
env_key = "DEEPSEEK_API_KEY"

[profiles.deepseek]
model = "deepseek-v4"
model_provider = "deepseek"
""",
        encoding="utf-8",
    )
    (codex_home / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {"slug": "gpt-5.6-sol", "display_name": "GPT-5.6-Sol", "visibility": "list"},
                    {"slug": "gpt-5.6-terra", "display_name": "GPT-5.6-Terra", "visibility": "list"},
                    {"slug": "gpt-5.6-luna", "display_name": "GPT-5.6-Luna", "visibility": "list"},
                    {"slug": "hidden-review", "display_name": "Hidden", "visibility": "hide"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("agentbench.model_discovery.native_cli_status", _installed_cli)

    result = discover_models(source="codex-cli")
    by_key = {(item["provider_id"], item["id"]): item for item in result["models"]}

    assert ("openai_http", "gpt-5.6-sol") in by_key
    assert ("openai_http", "gpt-5.6-terra") in by_key
    assert ("openai_http", "gpt-5.6-luna") in by_key
    assert ("openai_http", "hidden-review") not in by_key
    assert by_key[("deepseek", "deepseek-v4")]["configured"] is True
    assert {item["id"] for item in result["providers"]} == {"openai_http", "deepseek"}
    assert result["capability"]["installed"] is True


def test_api_discovery_parses_openai_compatible_catalog(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={"data": [{"id": "fable-5", "name": "Fable 5"}, {"id": "fable-5-mini"}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("agentbench.model_discovery.httpx.get", fake_get)

    result = discover_models(
        source="api",
        provider="fable-cloud",
        base_url="https://api.fable.example/v1",
        api_style="openai",
        api_key="secret-value",
    )

    assert [item["id"] for item in result["models"]] == ["fable-5", "fable-5-mini"]
    assert calls[0]["url"] == "https://api.fable.example/v1/models"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-value"
    assert "secret-value" not in json.dumps(result)


def test_reasonix_discovery_reads_doctor_provider_routes(monkeypatch):
    doctor = {
        "config": {"default_model": "deepseek-responses"},
        "providers": [
            {
                "name": "deepseek-responses",
                "model": "deepseek-v4-flash",
                "models": ["deepseek-v4-flash"],
                "key_present": True,
                "is_default": True,
            },
            {
                "name": "deepseek-pro",
                "model": "deepseek-v4-pro",
                "models": ["deepseek-v4-pro"],
                "key_present": True,
                "is_default": False,
            },
        ],
    }
    monkeypatch.setattr("agentbench.model_discovery.native_cli_status", _installed_cli)
    monkeypatch.setattr(
        "agentbench.model_discovery.subprocess.run",
        lambda args, **_kwargs: CompletedProcess(args, 0, json.dumps(doctor), ""),
    )

    result = discover_models(source="reasonix-cli")

    assert [item["id"] for item in result["models"]] == [
        "deepseek-responses",
        "deepseek-pro",
    ]
    assert result["models"][0]["label"] == "deepseek-v4-flash（deepseek-responses）"
    assert result["providers"][0]["is_default"] is True


def test_claude_discovery_offers_fable_5_and_latest_alias(tmp_path, monkeypatch):
    claude_home = tmp_path / "claude"
    claude_home.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
    monkeypatch.setattr("agentbench.model_discovery.native_cli_status", _installed_cli)

    result = discover_models(source="claude-code")
    ids = {item["id"] for item in result["models"]}

    assert {"fable", "sonnet", "opus", "haiku"} <= ids
    assert "claude-fable-5" not in ids


def test_opencode_discovery_marks_authenticated_providers(monkeypatch):
    def fake_run(args, **_kwargs):
        if args[1:3] == ["auth", "list"]:
            return CompletedProcess(args, 0, "• DeepSeek api\n• OpenCode Zen api\n", "")
        return CompletedProcess(
            args,
            0,
            "deepseek/deepseek-v4-flash\nopencode/claude-fable-5\nother/model-x\n",
            "",
        )

    monkeypatch.setattr("agentbench.model_discovery.native_cli_status", _installed_cli)
    monkeypatch.setattr("agentbench.model_discovery.subprocess.run", fake_run)

    result = discover_models(source="opencode-cli")
    configured = {item["id"] for item in result["models"] if item["configured"]}

    assert configured == {"deepseek/deepseek-v4-flash", "opencode/claude-fable-5"}


def test_opencode_output_parser_reads_text_and_nested_tokens():
    output = "\n".join(
        [
            json.dumps({"type": "text", "part": {"type": "text", "text": "OK"}}),
            json.dumps(
                {
                    "type": "step_finish",
                    "part": {
                        "type": "step-finish",
                        "tokens": {"input": 9264, "output": 9, "reasoning": 17},
                    },
                }
            ),
        ]
    )

    final, input_tokens, output_tokens, reported_cost, event_count = EvaluationService._parse_native_output(
        "opencode_cli", output, lambda *_args: None
    )

    assert final == "OK"
    assert input_tokens == 9264
    assert output_tokens == 26
    assert reported_cost is None
    assert event_count == 2


def test_native_output_parser_prefers_cli_reported_cost():
    output = json.dumps(
        {
            "type": "result",
            "result": "OK",
            "usage": {"input_tokens": 1000, "output_tokens": 200},
            "total_cost_usd": 0.03125,
        }
    )

    _, input_tokens, output_tokens, reported_cost, _ = EvaluationService._parse_native_output(
        "claude_code_cli", output, lambda *_args: None
    )

    assert (input_tokens, output_tokens) == (1000, 200)
    assert reported_cost == 0.03125


def test_reasonix_stream_output_keeps_live_text_final_usage_and_cost():
    output = "\n".join(
        [
            json.dumps({"kind": "text", "text": "STREAM"}),
            json.dumps({"kind": "message", "text": "STREAM_OK"}),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "result": "STREAM_OK",
                    "total_cost_usd": 0.000043,
                    "usage": {"input_tokens": 13220, "output_tokens": 7},
                }
            ),
        ]
    )

    final, input_tokens, output_tokens, reported_cost, event_count = (
        EvaluationService._parse_native_output("reasonix_cli", output, lambda *_args: None)
    )

    assert final == "STREAM_OK"
    assert (input_tokens, output_tokens) == (13220, 7)
    assert reported_cost == 0.000043
    assert event_count == 3


def test_kimi_discovery_uses_cli_catalog(monkeypatch):
    monkeypatch.setattr("agentbench.model_discovery.native_cli_status", _installed_cli)
    monkeypatch.setattr(
        "agentbench.model_discovery.subprocess.run",
        lambda args, **_kwargs: CompletedProcess(
            args,
            0,
            json.dumps({"models": [{"id": "kimi-k2.5", "label": "Kimi K2.5"}]}),
            "",
        ),
    )

    result = discover_models(source="kimi-code")

    assert result["models"][0]["id"] == "kimi-k2.5"
    assert result["models"][0]["configured"] is True


def test_qoder_discovery_falls_back_to_current_login(monkeypatch):
    monkeypatch.setattr("agentbench.model_discovery.native_cli_status", _installed_cli)
    monkeypatch.setattr(
        "agentbench.model_discovery.subprocess.run",
        lambda args, **_kwargs: CompletedProcess(args, 1, "", "unsupported"),
    )

    result = discover_models(source="qoder-cli")

    assert result["models"][0]["id"] == "auto"
    assert "当前登录配置" in result["models"][0]["label"]
    assert result["warnings"]


def test_cursor_discovery_uses_account_model_catalog(monkeypatch):
    monkeypatch.setattr("agentbench.model_discovery.native_cli_status", _installed_cli)
    monkeypatch.setattr(
        "agentbench.model_discovery.subprocess.run",
        lambda args, **_kwargs: CompletedProcess(
            args,
            0,
            json.dumps({"models": [{"id": "auto", "label": "Auto"}, {"id": "composer-1", "label": "Composer 1"}]}),
            "",
        ),
    )

    result = discover_models(source="cursor-cli")

    assert result["source_label"] == "Cursor Agent"
    assert [model["id"] for model in result["models"]] == ["auto", "composer-1"]
    assert result["models"][0]["configured"] is True


def test_cursor_discovery_parses_human_readable_model_catalog(monkeypatch):
    monkeypatch.setattr("agentbench.model_discovery.native_cli_status", _installed_cli)
    monkeypatch.setattr(
        "agentbench.model_discovery.subprocess.run",
        lambda args, **_kwargs: CompletedProcess(
            args,
            0,
            "Available models:\n* auto  Auto (recommended)\n  composer-1  Composer 1\n  claude-4.5-sonnet - Claude 4.5 Sonnet\n",
            "",
        ),
    )

    result = discover_models(source="cursor-cli")

    assert [model["id"] for model in result["models"]] == [
        "auto",
        "claude-4.5-sonnet",
        "composer-1",
    ]
    assert result["models"][0]["label"] == "Auto (recommended)"


def test_cursor_stream_parser_accumulates_partial_assistant_output():
    output = "\n".join(
        [
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp_ms": 1,
                    "message": {"content": [{"type": "text", "text": "答"}]},
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp_ms": 2,
                    "message": {"content": [{"type": "text", "text": "案"}]},
                }
            ),
            json.dumps({"type": "result", "duration_ms": 10}),
        ]
    )

    final, _input, _output, _cost, count = EvaluationService._parse_native_output(
        "cursor_cli", output
    )

    assert final == "答案"
    assert count == 3


def test_discovery_rejects_link_local_metadata_address(monkeypatch):
    def should_not_call(*_args, **_kwargs):
        raise AssertionError("HTTP client must not access link-local metadata")

    monkeypatch.setattr("agentbench.model_discovery.httpx.get", should_not_call)
    result = discover_models(
        source="api",
        provider="unsafe",
        base_url="http://169.254.169.254/v1",
        api_style="openai",
    )

    assert result["models"] == []
    assert "链路本地" in result["warnings"][0]


def test_discovery_api_and_model_provider_are_exposed(settings, tmp_path, monkeypatch):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'model = "gpt-5.6-sol"\nmodel_provider = "openai_http"\n', encoding="utf-8"
    )
    (codex_home / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {"slug": "gpt-5.6-sol", "display_name": "GPT-5.6-Sol", "visibility": "list"}
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr("agentbench.model_discovery.native_cli_status", _installed_cli)

    with TestClient(create_app(settings)) as client:
        discovery = client.post("/api/v1/models/discover", json={"source": "codex-cli"})
        assert discovery.status_code == 200
        assert discovery.json()["models"][0]["id"] == "gpt-5.6-sol"

        created = client.post(
            "/api/v1/models",
            json={
                "name": "Codex Sol",
                "provider": "codex-cli",
                "model_name": "gpt-5.6-sol",
                "api_style": "openai",
                "agent_provider": "openai_http",
            },
        )
        assert created.status_code == 201
        assert created.json()["settings"]["agent_provider"] == "openai_http"


def test_codex_runner_receives_selected_provider(settings, tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_run_native_cli(**kwargs):
        captured.update(kwargs)
        return CommandResult(
            ok=True,
            exit_code=0,
            stdout='{"type":"result","result":"OK"}\n',
            stderr="",
            duration_ms=5,
        )

    monkeypatch.setattr("agentbench.service.run_native_cli", fake_run_native_cli)
    service = EvaluationService(settings)
    monkeypatch.setattr(service, "_native_cli_allowed", lambda: True)
    workspace = Workspace(tmp_path / "workspace")
    runner = {
        "runner_type": "codex_cli",
        "executable": "codex",
        "args_json": json.dumps(["exec", "--json", "--model", "{model_name}", "{prompt}"]),
        "env_json": "{}",
        "limits_json": "{}",
    }
    model = {
        "provider": "codex-cli",
        "model_name": "deepseek-v4",
        "settings_json": json.dumps({"agent_provider": "deepseek"}),
    }

    result = service._run_native_agent(
        runner,
        model,
        {"instruction": "Return OK", "tools": [], "limits": {}},
        workspace,
        lambda *_args: None,
        threading.Event(),
    )
    service.close()

    assert result.ok is True
    assert captured["args"][:3] == ["exec", "-c", 'model_provider="deepseek"']


def test_cli_model_test_executes_a_real_non_git_task(settings, monkeypatch):
    captured: dict[str, object] = {}

    def fake_run_native_cli(**kwargs):
        captured.update(kwargs)
        return CommandResult(
            ok=True,
            exit_code=0,
            stdout=(
                '{"type":"item.completed","item":{"type":"agent_message",'
                '"text":"AGENTBENCH-OK"},"usage":{"input_tokens":12,"output_tokens":4}}\n'
            ),
            stderr="",
            duration_ms=12,
        )

    monkeypatch.setattr("agentbench.service.native_cli_status", _installed_cli)
    monkeypatch.setattr("agentbench.service.run_native_cli", fake_run_native_cli)
    service = EvaluationService(settings)
    try:
        service.update_settings({"allow_native_cli": True})
        model = service.create_model(
            ModelCreate(
                name="Codex smoke",
                provider="codex-cli",
                model_name="gpt-test",
                agent_provider="openai",
            )
        )

        result = service.test_model(model["id"])

        assert result["ok"] is True
        assert result["runner_type"] == "codex_cli"
        assert result["tokens_input"] == 12
        assert result["tokens_output"] == 4
        assert "--skip-git-repo-check" in captured["args"]
        assert captured["placeholders"]["prompt"] == "Return exactly AGENTBENCH-OK and nothing else."
        workspace = captured["workspace"]
        assert isinstance(workspace, Workspace)
        assert not workspace.root.exists()
        assert not (workspace.root / ".git").exists()
    finally:
        service.close()
