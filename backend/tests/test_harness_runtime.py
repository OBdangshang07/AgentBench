from __future__ import annotations

import json
from pathlib import Path

import yaml

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
        args, runtime_root, effort, label = service._prepare_harness_run_config(
            ["--profile", "headless", "{prompt}"],
            "deepseek-official",
            "deepseek-v4-pro",
            "medium",
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
