from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest

from agentbench.agent import AgentHarness
from agentbench.catalog import FRONTEND_FULL_SUITE_ID
from agentbench.config import Settings
from agentbench.execution import DockerExecutor, Workspace
from agentbench.model_clients import ModelClientError, ModelDecision, ModelUsage
from agentbench.schemas import ExperimentCreate, Participant
from agentbench.service import EvaluationService


@pytest.fixture
def service(settings: Settings) -> Iterator[EvaluationService]:
    value = EvaluationService(settings)
    try:
        yield value
    finally:
        value.close()


def _create_experiment(service: EvaluationService, name: str = "pause-resume") -> dict:
    unified_runner = next(
        item for item in service.list_runners() if item["runner_type"] == "unified"
    )
    return service.create_experiment(
        ExperimentCreate(
            name=name,
            suite_id=FRONTEND_FULL_SUITE_ID,
            participants=[
                Participant(
                    model_id=service.list_models()[0]["id"],
                    runner_id=unified_runner["id"],
                )
            ],
            repetitions=1,
            concurrency=1,
        )
    )


def test_pause_arriving_during_provider_call_preserves_final_answer(tmp_path) -> None:
    pause_requested = threading.Event()

    class FinalClient:
        def complete(self, _history, _tools):
            pause_requested.set()
            return ModelDecision(
                kind="final",
                content="candidate final answer",
                usage=ModelUsage(input_tokens=12, output_tokens=34),
            )

    harness = AgentHarness(
        client=FinalClient(),
        workspace=Workspace(tmp_path),
        docker=DockerExecutor(executable="missing-docker"),
        allowed_capabilities=[],
        limits={"max_steps": 1},
        system_prompt="",
        event_sink=lambda _kind, _payload: None,
        cancellation_check=pause_requested.is_set,
    )

    result = harness.run("solve")

    assert result.ok is True
    assert result.final_answer == "candidate final answer"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 34


def test_provider_quota_exhaustion_auto_pauses_instead_of_failing_remaining_runs(
    service: EvaluationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create_experiment(service, "quota-auto-pause")
    runs = service.list_runs(created["id"])
    target = runs[0]
    service.database.execute(
        "UPDATE experiments SET status='running' WHERE id=?", (created["id"],)
    )

    class ExhaustedClient:
        reasoning_status = None

        def complete(self, _history, _tools):
            raise ModelClientError(
                "HTTP 429: insufficient_quota; your credit balance is exhausted"
            )

    monkeypatch.setattr(service, "_model_client", lambda *_args, **_kwargs: ExhaustedClient())

    service._execute_run(target["id"])

    paused = service.get_experiment(created["id"])
    result = service.get_run(target["id"])
    assert paused["status"] == "paused"
    assert result["status"] == "interrupted"
    assert result["error_code"] == "model_capacity_exhausted"
    assert "恢复额度后可继续" in result["error_message"]
    assert {item["status"] for item in service.list_runs(created["id"])[1:]} == {"queued"}


def test_pause_preserves_finished_runs_and_resume_dispatches_only_remaining(
    service: EvaluationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create_experiment(service)
    runs = service.list_runs(created["id"])
    completed, executing, validating = runs[:3]
    original_started_at = "2026-08-31T01:02:03+00:00"
    service.database.execute(
        "UPDATE experiments SET status='running',started_at=? WHERE id=?",
        (original_started_at, created["id"]),
    )
    service.database.execute(
        "UPDATE runs SET status='completed',score=88,completed_at=? WHERE id=?",
        (completed["created_at"], completed["id"]),
    )
    service.database.execute(
        "UPDATE runs SET status='running',started_at=? WHERE id=?",
        (executing["created_at"], executing["id"]),
    )
    service.database.execute(
        "UPDATE runs SET status='validating',final_answer='durable candidate answer' WHERE id=?",
        (validating["id"],),
    )
    execution_cancel = threading.Event()
    service._cancel_events[executing["id"]] = execution_cancel

    pause_requested = service.pause_experiment(created["id"])

    assert pause_requested["status"] == "pausing"
    assert execution_cancel.is_set()
    assert service.pause_experiment(created["id"])["status"] == "pausing"
    paused_runs = {item["id"]: item for item in service.list_runs(created["id"])}
    assert paused_runs[completed["id"]]["status"] == "completed"
    assert paused_runs[completed["id"]]["score"] == 88
    assert paused_runs[validating["id"]]["status"] == "validating"
    assert {item["status"] for item in paused_runs.values() if item["id"] not in {
        completed["id"], executing["id"], validating["id"]
    }} == {"queued"}

    service.database.execute(
        "UPDATE runs SET status='interrupted',error_code='suite_paused',completed_at=? WHERE id=?",
        (executing["created_at"], executing["id"]),
    )
    service.database.execute(
        "UPDATE runs SET status='completed',score=91,completed_at=? WHERE id=?",
        (validating["created_at"], validating["id"]),
    )
    service._refresh_experiment(created["id"])
    assert service.get_experiment(created["id"])["status"] == "paused"

    submitted: list[str] = []
    monkeypatch.setattr(
        service,
        "preflight_experiment",
        lambda _experiment_id: {"ok": True, "errors": [], "warnings": [], "checks": {}},
    )
    monkeypatch.setattr(
        service.executor,
        "submit",
        lambda _callable, run_id, _semaphore: submitted.append(run_id),
    )

    resumed = service.start_experiment(created["id"])

    assert resumed["status"] == "running"
    assert resumed["started_at"] == original_started_at
    assert len(submitted) == len(runs) - 2
    assert completed["id"] not in submitted
    assert validating["id"] not in submitted
    assert executing["id"] in submitted
    service.start_experiment(created["id"])
    assert len(submitted) == len(runs) - 2


def test_restart_finishes_pending_pause_without_losing_submission(settings: Settings) -> None:
    first = EvaluationService(settings)
    try:
        created = _create_experiment(first, "restart-during-pause")
        runs = first.list_runs(created["id"])
        submitted = runs[0]
        first.database.execute(
            "UPDATE experiments SET status='pausing' WHERE id=?", (created["id"],)
        )
        first.database.execute(
            "UPDATE runs SET status='judging',final_answer='answer survives restart' WHERE id=?",
            (submitted["id"],),
        )
        first.database.execute(
            "INSERT INTO run_attempts(id,run_id,attempt_no,status,prompt,created_at) "
            "VALUES ('attempt-restart',?,1,'running','prompt',?)",
            (submitted["id"], submitted["created_at"]),
        )
    finally:
        first.close()

    second = EvaluationService(settings)
    try:
        recovered_experiment = second.get_experiment(created["id"])
        recovered_run = second.get_run(submitted["id"])
        assert recovered_experiment["status"] == "paused"
        assert recovered_run["status"] == "interrupted"
        assert recovered_run["final_answer"] == "answer survives restart"
        assert recovered_run["error_code"] == "app_restarted_during_validation"
        assert recovered_run["attempts"][0]["status"] == "interrupted"
        assert {item["status"] for item in second.list_runs(created["id"])[1:]} == {"queued"}
    finally:
        second.close()


def test_resume_after_submission_skips_candidate_model(
    service: EvaluationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create_experiment(service, "resume-validation-only")
    runs = service.list_runs(created["id"])
    target = runs[0]
    service.database.execute(
        "UPDATE experiments SET status='running' WHERE id=?", (created["id"],)
    )
    service.database.execute(
        "UPDATE runs SET status='interrupted',final_answer='preserved answer',"
        "error_code='suite_paused_after_submission',workspace_path=? WHERE id=?",
        (str(service.settings.workspaces_dir / target["id"]), target["id"]),
    )
    (service.settings.workspaces_dir / target["id"]).mkdir(parents=True, exist_ok=True)
    service.database.execute(
        "INSERT INTO run_attempts(id,run_id,attempt_no,status,prompt,created_at) "
        "VALUES ('attempt-preserved',?,1,'interrupted','prompt',?)",
        (target["id"], target["created_at"]),
    )
    for item in runs[1:]:
        service.database.execute(
            "UPDATE runs SET status='completed',score=80,completed_at=? WHERE id=?",
            (item["created_at"], item["id"]),
        )

    model_calls = 0
    validation_calls = 0

    def fail_if_candidate_model_is_called(*_args, **_kwargs):
        nonlocal model_calls
        model_calls += 1
        raise AssertionError("candidate model must not be called after its answer was preserved")

    def finish_validation(run_id: str, **_kwargs):
        nonlocal validation_calls
        validation_calls += 1
        assert run_id == target["id"]
        assert service.get_run(run_id)["final_answer"] == "preserved answer"
        service.database.execute(
            "UPDATE runs SET status='completed',score=87,passed=1,completed_at=? WHERE id=?",
            (target["created_at"], run_id),
        )
        return service.get_run(run_id)

    monkeypatch.setattr(service, "_model_client", fail_if_candidate_model_is_called)
    monkeypatch.setattr(service, "rejudge_run", finish_validation)

    service._run_with_semaphore(target["id"], threading.Semaphore(1))

    result = service.get_run(target["id"])
    assert model_calls == 0
    assert validation_calls == 1
    assert result["status"] == "completed"
    assert result["attempts"][0]["status"] == "completed"
    resumed_event = next(item for item in result["events"] if item["event_type"] == "run.validating")
    assert resumed_event["payload"]["candidate_model_rerun"] is False
    assert service.get_experiment(created["id"])["status"] == "completed"
