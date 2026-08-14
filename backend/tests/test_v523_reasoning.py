from __future__ import annotations

import json
import threading

from agentbench.catalog import MOCK_MODEL_ID, SMOKE_SUITE_ID, UNIFIED_RUNNER_ID
from agentbench.execution import CommandResult, Workspace, native_cli_status
from agentbench.model_clients import ModelUsage
from agentbench.schemas import ExperimentCreate, Participant
from agentbench.service import EvaluationService, benchmark_reasoning_condition


def test_agent_specific_reasoning_conditions_are_explicit() -> None:
    assert benchmark_reasoning_condition("codex_cli", "maximum", "max")["effective"] == "xhigh"
    assert benchmark_reasoning_condition("deepseek_harness", "maximum", "max") == {
        "requested": "max",
        "effective": "max",
        "source": "direct",
        "verified": True,
        "note": "Harness 实际使用 MAX 档",
    }
    assert benchmark_reasoning_condition("qoder_cli", "maximum", "max")["effective"] == "high"
    assert benchmark_reasoning_condition("cursor_cli", "standard", "high")["effective"] is None
    assert benchmark_reasoning_condition("opencode_cli", "standard", "high")["verified"] is False


def test_v15_schema_and_new_experiment_runtime_snapshot(settings) -> None:
    service = EvaluationService(settings)
    try:
        experiment = service.create_experiment(
            ExperimentCreate(
                name="5.2.3 condition snapshot",
                suite_id=SMOKE_SUITE_ID,
                participants=[Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)],
                reasoning_policy="maximum",
                judge_reasoning_effort="xhigh",
            )
        )
        assert experiment["reasoning_policy"] == "maximum"
        assert experiment["reasoning_effort"] == "max"
        assert experiment["strict_fairness"] is True
        assert experiment["judge_reasoning_effort"] == "xhigh"
        assert experiment["runtime_config_version"] == "5.2.3"

        run = service.list_runs(experiment["id"])[0]
        assert run["requested_reasoning_effort"] == "max"
        assert run["effective_reasoning_effort"] == "max"
        assert run["telemetry_status"] == "pending"
        assert run["runtime_identity"]["model_name"] == "mock-v1"

        run_columns = {row["name"] for row in service.database.fetch_all("PRAGMA table_info(runs)")}
        assert {"runtime_identity_json", "telemetry_status", "failure_class"} <= run_columns
    finally:
        service.close()


def test_native_benchmark_uses_workspace_temp_and_reasoning_options(
    settings, tmp_path, monkeypatch
) -> None:
    service = EvaluationService(settings)
    workspace = Workspace(tmp_path / "workspace")
    task_temp = workspace.root / ".agentbench-tmp"
    task_temp.mkdir()
    captured: dict[str, object] = {}

    def fake_native_cli(**kwargs):
        captured.update(kwargs)
        return CommandResult(True, 0, '{"type":"result","result":"OK"}', "", 20)

    monkeypatch.setattr(service, "_native_cli_allowed", lambda: True)
    monkeypatch.setattr("agentbench.service.run_native_cli", fake_native_cli)
    result = service._run_native_agent(
        {
            "runner_type": "reasonix_cli",
            "executable": "reasonix",
            "args_json": json.dumps(["exec", "--json", "{prompt}"]),
            "env_json": "{}",
            "limits_json": "{}",
        },
        {"model_name": "deepseek-v4-pro", "settings_json": "{}"},
        {
            "instruction": "Return OK",
            "limits": {"timeout_seconds": 91},
            "metadata": {"task_temp": str(task_temp), "reasoning_effort": "high"},
        },
        workspace,
        lambda *_args: None,
        threading.Event(),
    )
    try:
        assert result.ok is True
        assert captured["extra_env"] == {
            "TEMP": str(task_temp),
            "TMP": str(task_temp),
            "TMPDIR": str(task_temp),
        }
        assert "high" in captured["args"]
        assert captured["timeout"] == 91
    finally:
        service.close()


def test_ultra_feedback_exposes_safe_timeout_and_contract_diagnostics() -> None:
    class Component:
        validator_type = "command_metrics"
        score = 10.0
        status = "failed"
        evidence = {
            "stderr": "worker timed out after 150 seconds; KeyError: 'payload'",
        }

    class Score:
        components = [Component()]

    feedback = EvaluationService._attempt_feedback(Score())
    assert "算法复杂度和终止条件" in feedback
    assert "缺少 payload 字段" in feedback
    assert "worker" not in feedback


def test_leaderboard_separates_standard_maximum_and_history(settings) -> None:
    service = EvaluationService(settings)
    try:
        for policy in ("standard", "maximum"):
            experiment = service.create_experiment(
                ExperimentCreate(
                    name=f"{policy} board",
                    suite_id=SMOKE_SUITE_ID,
                    participants=[
                        Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)
                    ],
                    reasoning_policy=policy,
                )
            )
            service.database.execute(
                "UPDATE runs SET status='completed',score=80,passed=1,effort_verified=1,"
                "telemetry_status='unavailable' WHERE experiment_id=?",
                (experiment["id"],),
            )

        standard = service.leaderboard("unified", condition="standard")
        maximum = service.leaderboard("unified", condition="maximum")
        historical = service.leaderboard("unified", condition="historical")
        expected_runs = len(service.get_suite(SMOKE_SUITE_ID)["cases"])
        assert sum(row["runs"] for row in standard) == expected_runs
        assert sum(row["runs"] for row in maximum) == expected_runs
        assert historical == []
        assert standard[0]["avg_tokens"] is None
        assert standard[0]["telemetry_runs"] == 0
    finally:
        service.close()


def test_codex_desktop_config_is_not_mistaken_for_standalone_cli(tmp_path, monkeypatch) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text('model = "gpt-5"\n', encoding="utf-8")
    alias = tmp_path / "WindowsApps" / "codex.exe"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr("agentbench.execution._native_cli_candidates", lambda _value: [str(alias)])
    monkeypatch.setattr("agentbench.execution.subprocess.run", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("Access is denied")))

    status = native_cli_status("codex")

    assert status["installed"] is False
    assert status["desktop_installed"] is True
    assert status["desktop_configured"] is True
    assert "独立 Codex CLI" in status["note"]


def test_failure_and_telemetry_classification_are_not_conflated() -> None:
    assert EvaluationService._failure_class("command_timeout", "", phase="execution") == "agent_timeout"
    assert EvaluationService._failure_class(
        "validator_platform_error", "", phase="validation"
    ) == "validator_infrastructure_failure"
    assert EvaluationService._failure_class(
        "cli_missing", "", phase="execution"
    ) == "runtime_environment_failure"
    assert EvaluationService._failure_class(
        "command_failed", "Access is denied", phase="execution"
    ) == "permission_mismatch"
    assert EvaluationService._telemetry_status(ModelUsage()) == "unavailable"
    assert EvaluationService._telemetry_status(ModelUsage(input_tokens=10)) == "partial"
    assert EvaluationService._telemetry_status(
        ModelUsage(input_tokens=10, output_tokens=5)
    ) == "reported"
