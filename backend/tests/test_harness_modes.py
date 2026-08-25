from __future__ import annotations

from pathlib import Path

import pytest

from agentbench.agent import AgentResult
from agentbench.catalog import (
    DEEPSEEK_HARNESS_RUNNER_ID,
    MOCK_MODEL_ID,
    SMOKE_SUITE_ID,
)
from agentbench.harness_modes import (
    HarnessModeUnavailableError,
    discover_harness_modes,
    resolve_harness_mode,
)
from agentbench.model_clients import ModelUsage
from agentbench.schemas import ExperimentCreate, Participant
from agentbench.service import EvaluationService


def _write_preset(root: Path, mode_id: str, *, anchored: bool = False) -> None:
    directory = root / mode_id
    directory.mkdir(parents=True)
    (directory / "agent.cordis.yml").write_text(
        "- id: persona\n  name: '@deepseek-ai/dsh-persona'\n",
        encoding="utf-8",
    )
    (directory / "preset.yml").write_text(
        f"name: {mode_id}\ndescription: test preset\n", encoding="utf-8"
    )
    if anchored:
        (directory / "tool-bootstrap.mjs").write_text("export default {}\n", encoding="utf-8")


def test_harness_mode_discovery_includes_official_and_anchored(tmp_path: Path) -> None:
    package_root = tmp_path / "dsh"
    system_root = package_root / "config" / "agent-presets"
    user_home = tmp_path / "home"
    user_root = user_home / ".agent-presets"
    for mode_id in ("standard", "code", "minimal", "cordis"):
        _write_preset(system_root, mode_id)
    _write_preset(user_root, "anchored-standard", anchored=True)

    modes = discover_harness_modes(
        package_root=package_root,
        user_home=user_home,
    )

    assert [mode["id"] for mode in modes] == [
        "standard",
        "code",
        "minimal",
        "cordis",
        "anchored-standard",
    ]
    assert all(mode["available"] for mode in modes)
    assert next(mode for mode in modes if mode["id"] == "code")["tools_mode"] == "code"
    anchored = next(mode for mode in modes if mode["id"] == "anchored-standard")
    assert anchored["source"] == "user"
    assert anchored["experimental"] is True
    assert len(anchored["sha256"]) == 64


def test_missing_or_broken_custom_preset_never_falls_back(
    tmp_path: Path, monkeypatch
) -> None:
    package_root = tmp_path / "dsh"
    system_root = package_root / "config" / "agent-presets"
    for mode_id in ("standard", "code", "minimal", "cordis"):
        _write_preset(system_root, mode_id)
    (package_root / "package.json").write_text(
        '{"name":"@deepseek-ai/dsh"}', encoding="utf-8"
    )
    monkeypatch.setenv("AGENTBENCH_DSH_PACKAGE_ROOT", str(package_root))
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "home"))

    with pytest.raises(HarnessModeUnavailableError, match="anchored-standard"):
        resolve_harness_mode("anchored-standard")


def test_experiment_persists_harness_mode_without_splitting_leaderboard(
    settings, monkeypatch
) -> None:
    service = EvaluationService(settings)

    def fake_mode(mode_id, _executable="dsh"):
        selected = mode_id or "standard"
        return {
            "id": selected,
            "name": selected,
            "source": "user" if selected == "anchored-standard" else "system",
            "tools_mode": "native",
            "sha256": selected.ljust(64, "0")[:64],
            "available": True,
        }

    monkeypatch.setattr("agentbench.service.resolve_harness_mode", fake_mode)
    try:
        experiments = []
        for mode_id in ("standard", "anchored-standard"):
            experiment = service.create_experiment(
                ExperimentCreate(
                    name=f"Harness {mode_id}",
                    suite_id=SMOKE_SUITE_ID,
                    participants=[
                        Participant(
                            model_id=MOCK_MODEL_ID,
                            runner_id=DEEPSEEK_HARNESS_RUNNER_ID,
                            agent_mode=mode_id,
                        )
                    ],
                )
            )
            experiments.append(experiment)
            assert experiment["participants"][0]["agent_mode"] == mode_id
            runs = service.list_runs(experiment["id"])
            assert runs[0]["runtime_identity"]["requested_agent_mode"] == mode_id
            service.database.execute(
                "UPDATE runs SET status='completed',score=80,passed=1,effort_verified=1,"
                "telemetry_status='unavailable' WHERE experiment_id=?",
                (experiment["id"],),
            )

        board = service.leaderboard("native", condition="standard")
        expected_runs = len(service.get_suite(SMOKE_SUITE_ID)["cases"]) * 2
        matching = [
            row
            for row in board
            if row["runner_id"] == DEEPSEEK_HARNESS_RUNNER_ID
            and row["model_id"] == MOCK_MODEL_ID
        ]
        assert len(matching) == 1
        assert matching[0]["runs"] == expected_runs
    finally:
        service.close()


def test_execute_run_persists_effective_harness_mode_audit(
    settings, monkeypatch
) -> None:
    service = EvaluationService(settings)
    mode_runtime = {
        "id": "anchored-standard",
        "name": "Anchored Standard",
        "source": "user",
        "tools_mode": "native",
        "sha256": "a" * 64,
        "available": True,
        "_package_root": str(settings.data_dir / "dsh-package"),
        "_system_root": str(settings.data_dir / "system-presets"),
        "_user_root": str(settings.data_dir / "user-presets"),
        "_preset_path": str(settings.data_dir / "user-presets" / "anchored-standard"),
    }
    monkeypatch.setattr(
        "agentbench.service.resolve_harness_mode",
        lambda *_args, **_kwargs: dict(mode_runtime),
    )
    monkeypatch.setattr(
        service,
        "_run_native_agent",
        lambda *_args, **_kwargs: AgentResult(
            False,
            "",
            0,
            ModelUsage(),
            1,
            "cli_failed",
            "synthetic execution stop",
        ),
    )
    try:
        experiment = service.create_experiment(
            ExperimentCreate(
                name="Harness mode runtime audit",
                suite_id=SMOKE_SUITE_ID,
                participants=[
                    Participant(
                        model_id=MOCK_MODEL_ID,
                        runner_id=DEEPSEEK_HARNESS_RUNNER_ID,
                        agent_mode="anchored-standard",
                    )
                ],
            )
        )
        run_id = service.list_runs(experiment["id"])[0]["id"]

        service._execute_run(run_id)
        run = service.get_run(run_id)
        identity = run["runtime_identity"]

        assert identity["requested_agent_mode"] == "anchored-standard"
        assert identity["effective_agent_mode"] == "anchored-standard"
        assert identity["agent_mode_source"] == "user"
        assert identity["agent_mode_sha256"] == "a" * 64
        assert identity["agent_mode_verified"] is True
        assert identity["headless_driver"] == "agentbench-preset-v1"
        assert len(identity["headless_driver_sha256"]) == 64
    finally:
        service.close()


def test_preset_removed_before_run_is_environment_failure(settings, monkeypatch) -> None:
    service = EvaluationService(settings)
    available_mode = {
        "id": "anchored-standard",
        "name": "Anchored Standard",
        "source": "user",
        "tools_mode": "native",
        "sha256": "b" * 64,
        "available": True,
    }
    monkeypatch.setattr(
        "agentbench.service.resolve_harness_mode",
        lambda *_args, **_kwargs: dict(available_mode),
    )
    try:
        experiment = service.create_experiment(
            ExperimentCreate(
                name="Harness missing preset audit",
                suite_id=SMOKE_SUITE_ID,
                participants=[
                    Participant(
                        model_id=MOCK_MODEL_ID,
                        runner_id=DEEPSEEK_HARNESS_RUNNER_ID,
                        agent_mode="anchored-standard",
                    )
                ],
            )
        )
        run_id = service.list_runs(experiment["id"])[0]["id"]

        def unavailable(*_args, **_kwargs):
            raise HarnessModeUnavailableError("anchored-standard preset was removed")

        monkeypatch.setattr("agentbench.service.resolve_harness_mode", unavailable)
        service._execute_run(run_id)
        run = service.get_run(run_id)

        assert run["status"] == "environment_unavailable"
        assert run["error_code"] == "harness_preset_unavailable"
        assert run["attempt_count"] == 0
        assert run["runtime_identity"]["agent_mode_verified"] is False
        assert run["runtime_identity"]["effective_agent_mode"] is None
        failed = next(
            event for event in run["events"] if event["event_type"] == "run.failed"
        )
        assert failed["payload"]["attempt_consumed"] is False
    finally:
        service.close()
