from __future__ import annotations

import json
import threading
from pathlib import Path

import yaml

from agentbench.execution import CommandResult, Workspace
from agentbench.service import (
    EvaluationService,
    _harness_activity_phase,
    _harness_reasoning_effort,
    _live_workspace_state,
)


def test_harness_effort_profiles_match_supported_values() -> None:
    assert _harness_reasoning_effort("low") == ("off", "快速")
    assert _harness_reasoning_effort("medium") == ("high", "标准")
    assert _harness_reasoning_effort("high") == ("high", "标准")
    assert _harness_reasoning_effort("xhigh") == ("high", "标准")
    assert _harness_reasoning_effort("max") == ("max", "极限")


def test_harness_run_config_is_isolated_and_does_not_copy_credentials(
    settings, tmp_path, monkeypatch
) -> None:
    dsh_home = tmp_path / "dsh-home"
    dsh_home.mkdir()
    source = dsh_home / "settings.yaml"
    original = (
        "agent-default-model:\n"
        "  provider: deepseek-official\n"
        "  model: deepseek-v4-pro\n"
        "  reasoningEffort: max\n"
        "llm-pi-ai:\n"
        "  apiKey: DO-NOT-COPY\n"
        "  apiKeyEnv: THIRD_PARTY_KEY\n"
    )
    source.write_text(original, encoding="utf-8")
    (dsh_home / ".credentials.yaml").write_text(
        "DEEPSEEK_API_KEY: SECRET-NOT-COPIED\n", encoding="utf-8"
    )
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    service = EvaluationService(settings)
    try:
        system_root = tmp_path / "dsh-package" / "config" / "agent-presets"
        user_root = dsh_home / ".agent-presets"
        system_root.mkdir(parents=True)
        user_root.mkdir(parents=True)
        mode_runtime = {
            "id": "standard",
            "name": "标准模式",
            "source": "system",
            "tools_mode": "native",
            "sha256": "a" * 64,
            "_package_root": str(tmp_path / "dsh-package"),
            "_system_root": str(system_root),
            "_user_root": str(user_root),
            "_preset_path": str(system_root / "standard"),
        }
        args, runtime_root, effort, label, resolved_mode = service._prepare_harness_run_config(
            ["--profile", "headless", "{prompt}"],
            "deepseek-official",
            "deepseek-v4-pro",
            "medium",
            "standard",
            "dsh",
            mode_runtime,
        )
        assert effort == "high"
        assert label == "标准"
        assert args[:2] == ["--profile", "headless"]
        assert args[2] == "--patch"
        assert args[-1] == "{prompt}"
        rendered = (runtime_root / "settings.yaml").read_text(encoding="utf-8")
        assert "DO-NOT-COPY" not in rendered
        assert "SECRET-NOT-COPIED" not in rendered
        isolated = yaml.safe_load(rendered)
        assert isolated["agent-default-model"]["reasoningEffort"] == "high"
        assert isolated["llm-pi-ai"]["apiKeyEnv"] == "THIRD_PARTY_KEY"
        assert source.read_text(encoding="utf-8") == original
        assert not (runtime_root / ".credentials.yaml").exists()
        assert resolved_mode == mode_runtime
        patch_text = (runtime_root / "cordis.patch.yml").read_text(encoding="utf-8")
        assert "agent-presets" in patch_text
        assert "agentbench-headless-runner" in patch_text
        assert "preset: 'standard'" in patch_text
        assert "- id: tool-fs\n  disabled: true" in patch_text
        assert (runtime_root / "agentbench-headless-runner.mjs").is_file()
        assert str(runtime_root).startswith(str(settings.data_dir))
        json.dumps(isolated)
    finally:
        service.close()


def test_live_workspace_state_skips_git_dependencies_and_temp_files(tmp_path: Path) -> None:
    for relative in (
        "index.html",
        "src/app.ts",
        ".git/objects/pack/tmp_pack_1",
        "node_modules/pkg/index.js",
        ".tmp-preview.png",
        "__pycache__/debug.pyc",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")

    snapshot = _live_workspace_state(tmp_path)

    assert set(snapshot) == {"index.html", "src/app.ts"}


def test_harness_phase_inference_reports_public_progress() -> None:
    assert _harness_activity_phase([], 10_000)[0] == "planning"
    assert _harness_activity_phase([{"path": "src/app.ts"}], 40_000) == (
        "building",
        "正在生成和迭代任务交付物",
    )
    assert _harness_activity_phase([{"path": "preview.png"}], 40_000)[0] == "rendering"


def test_harness_code_mode_reaches_headless_environment(
    settings, tmp_path, monkeypatch
) -> None:
    service = EvaluationService(settings)
    workspace = Workspace(tmp_path / "workspace")
    runtime_root = settings.data_dir / "native-runtime" / "deepseek-harness" / "runtime"
    runtime_root.mkdir(parents=True)
    captured: dict[str, object] = {}
    mode_runtime = {
        "id": "code",
        "name": "PTC 模式",
        "source": "system",
        "tools_mode": "code",
        "sha256": "c" * 64,
        "_package_root": str(tmp_path / "dsh-package"),
        "_system_root": str(tmp_path / "system-presets"),
        "_user_root": str(tmp_path / "user-presets"),
        "_preset_path": str(tmp_path / "system-presets" / "code"),
    }

    prepared: dict[str, object] = {}

    def fake_prepare(
        args,
        provider,
        model,
        requested_effort,
        agent_mode,
        executable,
        resolved_mode,
    ):
        prepared.update(
            {
                "args": args,
                "provider": provider,
                "model": model,
                "requested_effort": requested_effort,
                "agent_mode": agent_mode,
                "executable": executable,
                "resolved_mode": resolved_mode,
            }
        )
        return ["--profile", "headless", "{prompt}"], runtime_root, "high", "标准", mode_runtime

    def fake_native_cli(**kwargs):
        captured.update(kwargs)
        return CommandResult(True, 0, "OK", "", 12)

    monkeypatch.setattr(service, "_native_cli_allowed", lambda: True)
    monkeypatch.setattr(
        "agentbench.service.deepseek_harness_default_selection",
        lambda: ("deepseek-official", "deepseek-v4-flash", "high"),
    )
    monkeypatch.setattr(service, "_prepare_harness_run_config", fake_prepare)
    monkeypatch.setattr("agentbench.service.run_native_cli", fake_native_cli)
    try:
        result = service._run_native_agent(
            {
                "runner_type": "deepseek_harness",
                "executable": "dsh",
                "args_json": json.dumps(["--profile", "headless", "{prompt}"]),
                "env_json": "{}",
                "limits_json": "{}",
            },
            {
                "provider": "deepseek-harness",
                "model_name": "deepseek-v4-pro",
                "settings_json": json.dumps({"agent_provider": "opencode-go"}),
            },
            {
                "instruction": "Return OK",
                "limits": {"timeout_seconds": 30},
                "metadata": {
                    "reasoning_effort": "high",
                    "agent_mode": "code",
                    "_harness_mode_runtime": mode_runtime,
                },
            },
            workspace,
            lambda *_args: None,
            threading.Event(),
        )
        assert result.ok is True
        assert captured["extra_env"]["DSH_TOOLS_MODE"] == "code"
        assert captured["extra_env"]["AGENTBENCH_DSH_PACKAGE_ROOT"] == str(
            tmp_path / "dsh-package"
        )
        assert prepared["provider"] == "opencode-go"
        assert prepared["model"] == "deepseek-v4-pro"
        assert prepared["agent_mode"] == "code"
        assert prepared["resolved_mode"] == mode_runtime
    finally:
        service.close()
