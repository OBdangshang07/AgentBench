from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agentbench.api import create_app
from agentbench.catalog import MOCK_MODEL_ID, QODER_RUNNER_ID, UNIFIED_RUNNER_ID
from agentbench.db import new_id, utc_now
from agentbench.execution import CommandResult, Workspace
from agentbench.model_clients import ModelDecision, ModelUsage
from agentbench.schemas import ExperimentCreate, ModelCreate, Participant, TestCaseImport
from agentbench.service import EvaluationService

JUDGE_JSON = json.dumps(
    {
        "score": 87,
        "summary": "solid",
        "strengths": ["complete"],
        "weaknesses": [],
        "evidence": ["final answer matches"],
    },
    ensure_ascii=False,
)


class SequencedClient:
    def __init__(self, answers: list[str]):
        self.answers = answers
        self.index = 0

    def complete(self, _history, _tools):
        answer = self.answers[min(self.index, len(self.answers) - 1)]
        self.index += 1
        return ModelDecision(
            kind="final", content=answer, usage=ModelUsage(input_tokens=50, output_tokens=10)
        )


def _create_rubric_run(service: EvaluationService) -> str:
    case = service.import_test_case(
        TestCaseImport(
            slug=f"test.rejudge-{new_id()}",
            version="1.0.0",
            category="judge-flow",
            title="Rejudge flow",
            instruction="Return exactly OK.",
            validators=[{"type": "ai_rubric", "weight": 100, "config": {"rubric": "quality"}}],
            limits={"max_steps": 4, "time_target_seconds": 60, "token_budget": 1000},
            attempt_policy={"max_attempts": 1, "pass_threshold": 60},
        )
    )
    suite_id = new_id()
    service.database.execute(
        "INSERT INTO test_suites(id,name,description,version,builtin,created_at) "
        "VALUES (?,?,?,'1.0.0',0,?)",
        (suite_id, "Rejudge Suite", "test", utc_now()),
    )
    service.database.execute(
        "INSERT INTO suite_cases(suite_id,test_case_id,position) VALUES (?,?,0)",
        (suite_id, case["id"]),
    )
    experiment = service.create_experiment(
        ExperimentCreate(
            name="Rejudge test",
            suite_id=suite_id,
            participants=[Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)],
        )
    )
    return service.list_runs(experiment["id"])[0]["id"]


def _enable_native_judge(service: EvaluationService) -> str:
    judge_model = service.create_model(
        ModelCreate(name="Judge model", model_name="judge-model", api_style="mock")
    )
    service.update_settings(
        {
            "allow_native_cli": True,
            "judge_model_id": judge_model["id"],
            "judge_runner_id": QODER_RUNNER_ID,
        }
    )
    return judge_model["id"]


def test_long_judge_prompt_travels_via_stdin_not_argv(settings, monkeypatch):
    service = EvaluationService(settings)
    try:
        _enable_native_judge(service)
        long_instruction = ("请逐条检查以下需求并打分。\n" * 400)
        long_answer = "FINAL ANSWER LINE\n" * 500
        run = {"id": _create_rubric_run(service), "model_id": MOCK_MODEL_ID,
               "final_answer": long_answer}
        definition = {
            "instruction": long_instruction,
            "validators": [
                {"type": "ai_rubric", "weight": 100, "config": {"rubric": "quality"}}
            ],
        }
        workspace = Workspace(settings.workspaces_dir / "run-long")
        workspace.write_file("output.txt", "artifact")

        captured: dict[str, object] = {}

        def fake_run_native_cli(**kwargs):
            captured.update(kwargs)
            judge_workspace: Workspace = kwargs["workspace"]
            captured["judge_workspace_files"] = judge_workspace.list_files()
            captured["judge_prompt_file"] = judge_workspace.read_file("judge_prompt.md")
            stdout_line = json.dumps({"type": "result", "result": JUDGE_JSON})
            return CommandResult(True, 0, stdout_line + "\n", "", 12, None)

        monkeypatch.setattr("agentbench.service.run_native_cli", fake_run_native_cli)

        callback = service._judge_callback(run, definition, workspace, lambda *_args: None)
        assert callback is not None
        result = callback({"rubric": "quality"}, 100.0)

        assert result.status == "passed"
        assert result.score == 87.0
        # Full long prompt goes through stdin and the mirrored workspace file.
        stdin_text = captured["stdin_text"]
        assert isinstance(stdin_text, str)
        assert stdin_text.startswith("You are an anonymous evaluator")
        assert long_instruction in stdin_text
        assert long_answer in stdin_text
        assert "\n" in stdin_text
        assert len(stdin_text) > 8191
        assert captured["judge_prompt_file"] == stdin_text
        assert "judge_prompt.md" in captured["judge_workspace_files"]
        # argv only carries the short guidance text, never the long prompt.
        placeholders = captured["placeholders"]
        assert placeholders["prompt"] == EvaluationService.JUDGE_STDIN_GUIDANCE
        assert len(placeholders["prompt"]) < 500
        rendered = [
            part.replace("{prompt}", placeholders["prompt"])
            .replace("{model_name}", placeholders["model_name"])
            .replace("{workspace}", placeholders["workspace"])
            for part in captured["args"]
        ]
        assert all(long_answer not in part for part in rendered)
        assert len(" ".join(rendered)) < 8191
    finally:
        service.close()


def test_judge_failure_retries_once_and_keeps_cli_output_in_evidence(settings, monkeypatch):
    service = EvaluationService(settings)
    try:
        _enable_native_judge(service)
        run = {"id": _create_rubric_run(service), "model_id": MOCK_MODEL_ID,
               "final_answer": "OK"}
        definition = {
            "instruction": "Return OK.",
            "validators": [
                {"type": "ai_rubric", "weight": 100, "config": {"rubric": "quality"}}
            ],
        }
        workspace = Workspace(settings.workspaces_dir / "run-retry")
        calls: list[dict[str, object]] = []

        def failing_twice(**kwargs):
            calls.append(kwargs)
            return CommandResult(False, 1, "", "The command line is too long", 9, "cli_failed")

        monkeypatch.setattr("agentbench.service.run_native_cli", failing_twice)
        callback = service._judge_callback(run, definition, workspace, lambda *_args: None)
        result = callback({}, 100.0)

        assert len(calls) == 2  # retried exactly once
        assert result.status == "needs_review"
        assert "The command line is too long" in result.evidence["reason"]
        assert result.evidence["judge_cli_stderr"].endswith("The command line is too long")
        assert result.evidence["judge_attempts"] == 2

        # Garbled (non-JSON) judge output: raw stdout must survive into evidence.
        calls.clear()

        def garbled(**kwargs):
            calls.append(kwargs)
            return CommandResult(True, 0, "Sorry, I cannot output JSON.", "", 9, None)

        monkeypatch.setattr("agentbench.service.run_native_cli", garbled)
        callback = service._judge_callback(run, definition, workspace, lambda *_args: None)
        result = callback({}, 100.0)

        assert len(calls) == 2
        assert result.status == "needs_review"
        assert result.evidence["judge_cli_stdout"] == "Sorry, I cannot output JSON."

        # Recovery on the retry must score normally.
        calls.clear()
        sequence = [
            CommandResult(False, 1, "", "transient failure", 5, "cli_failed"),
            CommandResult(True, 0, json.dumps({"type": "result", "result": JUDGE_JSON}), "", 8, None),
        ]

        def flaky(**kwargs):
            calls.append(kwargs)
            return sequence.pop(0)

        monkeypatch.setattr("agentbench.service.run_native_cli", flaky)
        callback = service._judge_callback(run, definition, workspace, lambda *_args: None)
        result = callback({}, 100.0)

        assert len(calls) == 2
        assert result.status == "passed"
        assert result.score == 87.0
    finally:
        service.close()


def test_rejudge_endpoint_rescores_needs_review_run(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        run_id = _create_rubric_run(service)
        service._model_client = lambda _model, _metadata: SequencedClient(["OK"])
        service._execute_run(run_id)
        before = service.get_run(run_id)
        assert before["status"] == "needs_review"
        assert before["final_answer"] == "OK"
        assert before["score"] is None

        judge_model = service.create_model(
            ModelCreate(name="Judge model", model_name="judge-model", api_style="mock")
        )
        service.update_settings(
            {"judge_model_id": judge_model["id"], "judge_runner_id": UNIFIED_RUNNER_ID}
        )
        service._model_client = lambda _model, _metadata: SequencedClient([JUDGE_JSON])

        response = client.post(f"/api/v1/runs/{run_id}/rejudge")
        assert response.status_code == 200
        after = response.json()
        assert after["status"] == "completed"
        assert after["score"] is not None and after["score"] > 0
        assert after["passed"] is True
        assert after["final_answer"] == "OK"  # reused, model not re-run
        assert len(after["judge_reviews"]) == 1
        assert {event["event_type"] for event in after["events"]} >= {
            "rejudge.started",
            "run.rejudged",
        }
        ai_component = next(
            item for item in after["validators"] if item["validator_type"] == "ai_rubric"
        )
        assert ai_component["status"] == "passed"
        # experiment aggregation stays consistent
        experiment = service.get_experiment(before["experiment_id"])
        assert experiment["status"] == "completed"


def test_experiment_rejudge_recovers_structured_answers_without_rerunning_model(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        case = service.import_test_case(
            TestCaseImport(
                slug=f"test.structured-rejudge-{new_id()}",
                version="1.0.0",
                category="postgraduate-math",
                title="Structured rejudge",
                instruction='Return {"answer":"B"}.',
                validators=[
                    {
                        "type": "symbolic_json",
                        "weight": 100,
                        "config": {
                            "fields": {
                                "answer": {"kind": "literal", "expected": "B"}
                            }
                        },
                    }
                ],
                limits={"max_steps": 4, "time_target_seconds": 60},
            )
        )
        suite_id = new_id()
        service.database.execute(
            "INSERT INTO test_suites(id,name,description,version,builtin,created_at) "
            "VALUES (?,?,?,'1.0.0',0,?)",
            (suite_id, "Structured Suite", "test", utc_now()),
        )
        service.database.execute(
            "INSERT INTO suite_cases(suite_id,test_case_id,position) VALUES (?,?,0)",
            (suite_id, case["id"]),
        )
        experiment = service.create_experiment(
            ExperimentCreate(
                name="Structured history repair",
                suite_id=suite_id,
                participants=[
                    Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)
                ],
            )
        )
        run_id = service.list_runs(experiment["id"])[0]["id"]
        service._model_client = lambda _model, _metadata: SequencedClient(
            ['分析完成。\n```json\n{"answer":"B"}\n```']
        )
        service._execute_run(run_id)
        service.database.execute("UPDATE runs SET score=5.5,passed=0 WHERE id=?", (run_id,))

        response = client.post(f"/api/v1/experiments/{experiment['id']}/rejudge")

        assert response.status_code == 200
        payload = response.json()
        assert payload["updated"] == 1
        assert payload["failed"] == 0
        assert payload["runs"][0]["previous_score"] == 5.5
        assert payload["runs"][0]["score"] > 99
        repaired = service.get_run(run_id)
        assert repaired["passed"] is True
        assert repaired["final_answer"].startswith("分析完成")


def test_rejudge_endpoint_rejects_missing_final_answer_or_wrong_status(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        run_id = _create_rubric_run(service)
        service._model_client = lambda _model, _metadata: SequencedClient(["OK"])
        service._execute_run(run_id)

        # no final_answer -> 409
        service.database.execute(
            "UPDATE runs SET final_answer=NULL,status='completed' WHERE id=?", (run_id,)
        )
        response = client.post(f"/api/v1/runs/{run_id}/rejudge")
        assert response.status_code == 409
        assert response.json()["detail"] == "run_has_no_final_answer"

        # terminal non-reviewable status -> 409
        service.database.execute(
            "UPDATE runs SET final_answer='OK',status='failed' WHERE id=?", (run_id,)
        )
        response = client.post(f"/api/v1/runs/{run_id}/rejudge")
        assert response.status_code == 409
        assert response.json()["detail"] == "run_not_rejudgeable"

        # unknown run -> 404
        missing = client.post("/api/v1/runs/run-missing/rejudge")
        assert missing.status_code == 404


def test_rejudge_keeps_attempt_multiplier(settings):
    service = EvaluationService(settings)
    try:
        run_id = _create_rubric_run(service)
        service._model_client = lambda _model, _metadata: SequencedClient(["OK"])
        service._execute_run(run_id)
        service.database.execute(
            "UPDATE run_attempts SET multiplier=0.85 WHERE run_id=?", (run_id,)
        )
        judge_model = service.create_model(
            ModelCreate(name="Judge model", model_name="judge-model", api_style="mock")
        )
        service.update_settings(
            {"judge_model_id": judge_model["id"], "judge_runner_id": UNIFIED_RUNNER_ID}
        )
        service._model_client = lambda _model, _metadata: SequencedClient([JUDGE_JSON])

        after = service.rejudge_run(run_id)

        raw_attempt = service.database.fetch_one(
            "SELECT raw_score,adjusted_score FROM run_attempts WHERE run_id=?", (run_id,)
        )
        assert after["score"] == round(raw_attempt["raw_score"] * 0.85, 2)
        assert raw_attempt["adjusted_score"] == after["score"]
    finally:
        service.close()
