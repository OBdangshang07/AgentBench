from __future__ import annotations

import time

import pytest

from agentbench.catalog import (
    CODEX_RUNNER_ID,
    MOCK_MODEL_ID,
    SMOKE_SUITE_ID,
    UNIFIED_RUNNER_ID,
    V2_QUICK_SUITE_ID,
)
from agentbench.schemas import ExperimentCreate, Participant
from agentbench.service import EvaluationService


@pytest.mark.parametrize("suite_id,expected_count", [(SMOKE_SUITE_ID, 12), (V2_QUICK_SUITE_ID, 20)])
def test_mock_experiment_runs_to_completion(settings, suite_id, expected_count):
    service = EvaluationService(settings)
    try:
        experiment = service.create_experiment(
            ExperimentCreate(
                name="Smoke test",
                suite_id=suite_id,
                participants=[Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)],
                repetitions=1,
                concurrency=2,
            )
        )
        service.start_experiment(experiment["id"])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            current = service.get_experiment(experiment["id"])
            if current["status"] == "completed":
                break
            time.sleep(0.05)
        current = service.get_experiment(experiment["id"])
        assert current["status"] == "completed"
        runs = service.list_runs(experiment["id"])
        assert len(runs) == expected_count
        assert all(run["status"] == "completed" for run in runs)
        assert min(run["score"] for run in runs) >= 90
        assert all(run["token_score"] is not None for run in runs)
        if expected_count > 12:
            assert len({run["score"] for run in runs}) > 1
        detail = service.get_run(runs[0]["id"])
        assert detail["events"]
        assert detail["validators"]
        assert {
            "objective_quality",
            "time_efficiency",
            "step_efficiency",
            "token_efficiency",
        } <= {component["dimension"] for component in detail["score_dimensions"]}
    finally:
        service.close()


def test_backup_round_trip_and_judge_json_parser(settings):
    service = EvaluationService(settings)
    try:
        service.update_settings({"default_concurrency": 4})
        backup = service.backup()
        content = backup.read_bytes()
        service.update_settings({"default_concurrency": 1})
        restored = service.restore(content)
        assert restored["ok"] is True
        assert service.get_setting("default_concurrency") == 4
        parsed = service._parse_json_object(
            '```json\n{"score": 88, "evidence": ["tests passed"]}\n```'
        )
        assert parsed["score"] == 88
    finally:
        service.close()


def test_preflight_blocks_native_batch_before_any_run_starts(settings, monkeypatch):
    monkeypatch.setattr(
        "agentbench.service.native_cli_status",
        lambda executable: {
            "installed": False,
            "executable": executable,
            "version": None,
            "install_command": "npm install -g @openai/codex",
        },
    )
    service = EvaluationService(settings)
    try:
        experiment = service.create_experiment(
            ExperimentCreate(
                name="Blocked native batch",
                suite_id=SMOKE_SUITE_ID,
                participants=[Participant(model_id=MOCK_MODEL_ID, runner_id=CODEX_RUNNER_ID)],
                repetitions=1,
                concurrency=2,
            )
        )

        preflight = service.preflight_experiment(experiment["id"])
        assert preflight["ok"] is False
        assert any("尚未启用" in item for item in preflight["errors"])
        assert any("npm install" in item for item in preflight["errors"])
        with pytest.raises(ValueError, match="启动前检查未通过"):
            service.start_experiment(experiment["id"])

        current = service.get_experiment(experiment["id"])
        runs = service.list_runs(experiment["id"])
        assert current["status"] == "draft"
        assert all(run["status"] == "queued" for run in runs)
    finally:
        service.close()
