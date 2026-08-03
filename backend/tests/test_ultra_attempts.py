from __future__ import annotations

import pytest

from agentbench.catalog import MOCK_MODEL_ID, UNIFIED_RUNNER_ID
from agentbench.db import new_id, utc_now
from agentbench.model_clients import ModelClientError, ModelDecision, ModelUsage
from agentbench.schemas import ExperimentCreate, ModelUpdate, Participant, TestCaseImport
from agentbench.service import EvaluationService


class SequencedClient:
    def __init__(self, answers: list[str]):
        self.answers = answers
        self.index = 0

    def complete(self, _history, _tools):
        answer = self.answers[min(self.index, len(self.answers) - 1)]
        self.index += 1
        return ModelDecision(
            kind="final",
            content=answer,
            usage=ModelUsage(input_tokens=100, output_tokens=20),
        )


class UnavailableClient:
    def complete(self, _history, _tools):
        raise ModelClientError("provider temporarily unavailable")


def _create_ultra_run(
    service: EvaluationService, validators: list[dict] | None = None
) -> str:
    case = service.import_test_case(
        TestCaseImport(
            slug=f"test.ultra-{new_id()}",
            version="1.0.0",
            category="ultra-engineering",
            title="Ultra attempt state machine",
            instruction="Return exactly OK.",
            validators=validators
            or [{"type": "exact_match", "weight": 100, "config": {"expected": "OK"}}],
            limits={"max_steps": 4, "time_target_seconds": 60, "token_budget": 1000},
            attempt_policy={
                "max_attempts": 3,
                "pass_threshold": 85,
                "multipliers": [1.0, 0.85, 0.70],
                "hints": ["Check the exact spelling.", "Return only two uppercase letters."],
                "preserve_workspace": True,
            },
            metadata={"difficulty": 6, "tier": "ultra"},
        )
    )
    suite_id = new_id()
    service.database.execute(
        "INSERT INTO test_suites(id,name,description,version,builtin,created_at) "
        "VALUES (?,?,?,'1.0.0',0,?)",
        (suite_id, "Test Ultra Suite", "test", utc_now()),
    )
    service.database.execute(
        "INSERT INTO suite_cases(suite_id,test_case_id,position) VALUES (?,?,0)",
        (suite_id, case["id"]),
    )
    experiment = service.create_experiment(
        ExperimentCreate(
            name="Attempt policy test",
            suite_id=suite_id,
            participants=[Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)],
        )
    )
    return service.list_runs(experiment["id"])[0]["id"]


@pytest.mark.parametrize(
    ("answers", "expected_attempt", "expected_multiplier"),
    [
        (["OK"], 1, 1.0),
        (["WRONG", "OK"], 2, 0.85),
        (["WRONG", "WRONG", "OK"], 3, 0.70),
    ],
)
def test_ultra_attempt_multiplier_and_prompt_ladder(
    settings, answers, expected_attempt, expected_multiplier
):
    service = EvaluationService(settings)
    try:
        run_id = _create_ultra_run(service)
        client = SequencedClient(answers)
        service._model_client = lambda _model, _metadata: client

        service._execute_run(run_id)
        run = service.get_run(run_id)

        assert run["status"] == "completed"
        assert run["passed"] is True
        assert run["attempt_count"] == expected_attempt
        assert len(run["attempts"]) == expected_attempt
        final_attempt = run["attempts"][-1]
        assert final_attempt["passed"] is True
        assert final_attempt["multiplier"] == expected_multiplier
        assert run["score"] == round(final_attempt["raw_score"] * expected_multiplier, 2)
        if expected_attempt > 1:
            assert "上一轮" in final_attempt["prompt"]
            assert "本轮标准提示" in final_attempt["prompt"]
    finally:
        service.close()


def test_environment_failure_does_not_consume_ability_attempt(settings):
    service = EvaluationService(settings)
    try:
        run_id = _create_ultra_run(service)
        service._model_client = lambda _model, _metadata: UnavailableClient()

        service._execute_run(run_id)
        run = service.get_run(run_id)

        assert run["status"] == "environment_unavailable"
        assert run["attempt_count"] == 0
        assert len(run["attempts"]) == 1
        assert run["attempts"][0]["status"] == "environment_unavailable"
        failed_event = next(item for item in run["events"] if item["event_type"] == "run.failed")
        assert failed_event["payload"]["attempt_consumed"] is False
    finally:
        service.close()


def test_validator_platform_failure_does_not_consume_ability_attempt(settings):
    from agentbench.execution import CommandResult

    class BrokenValidatorDocker:
        def run(self, _workspace, _command, _image, **_kwargs):
            return CommandResult(False, 1, "", "bootstrap error", 2)

    service = EvaluationService(settings)
    try:
        run_id = _create_ultra_run(
            service,
            validators=[
                {
                    "type": "command_metrics",
                    "weight": 100,
                    "config": {
                        "command": "python {private_root}/verify.py",
                        "private_files": {"verify.py": "broken"},
                        "metrics": [{"key": "quality", "weight": 100}],
                    },
                }
            ],
        )
        service.scoring.docker = BrokenValidatorDocker()
        service._model_client = lambda _model, _metadata: SequencedClient(["OK"])

        service._execute_run(run_id)
        run = service.get_run(run_id)

        assert run["status"] == "environment_unavailable"
        assert run["attempt_count"] == 0
        assert run["error_code"] == "validator_platform_error"
        assert run["attempts"][0]["status"] == "environment_unavailable"
        failed_event = next(item for item in run["events"] if item["event_type"] == "run.failed")
        assert failed_event["payload"]["attempt_consumed"] is False
        assert failed_event["payload"]["phase"] == "validation"
    finally:
        service.close()


def test_model_price_update_recalculates_unpriced_history(settings):
    service = EvaluationService(settings)
    try:
        run_id = _create_ultra_run(service)
        service.database.execute(
            "UPDATE runs SET tokens_input=1000000,tokens_output=500000,cost_usd=0,"
            "cost_source='unpriced' WHERE id=?",
            (run_id,),
        )

        service.update_model(
            MOCK_MODEL_ID,
            ModelUpdate(input_price=2.0, output_price=8.0),
        )
        repriced = service.get_run(run_id)

        assert repriced["cost_source"] == "configured"
        assert repriced["cost_usd"] == 6.0

        service.database.execute(
            "UPDATE runs SET cost_usd=1.2345,cost_source='reported' WHERE id=?",
            (run_id,),
        )
        service.update_model(
            MOCK_MODEL_ID,
            ModelUpdate(input_price=4.0, output_price=12.0),
        )
        reported = service.get_run(run_id)
        assert reported["cost_source"] == "reported"
        assert reported["cost_usd"] == 1.2345
    finally:
        service.close()
