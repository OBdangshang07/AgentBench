from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agentbench.agent import AgentResult
from agentbench.api import create_app
from agentbench.catalog import MOCK_MODEL_ID, QODER_RUNNER_ID, UNIFIED_RUNNER_ID
from agentbench.db import new_id, utc_now
from agentbench.execution import CommandResult, Workspace
from agentbench.math_rubric import RUBRIC_SCHEMA, structured_rubric_config
from agentbench.model_clients import ModelDecision, ModelUsage
from agentbench.schemas import (
    ExperimentCreate,
    ModelCreate,
    Participant,
    RunnerCreate,
    TestCaseImport,
)
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


def test_structured_judge_retries_legacy_shape_with_corrective_schema_guidance(
    settings, monkeypatch
):
    service = EvaluationService(settings)
    try:
        _enable_native_judge(service)
        run = {
            "id": _create_rubric_run(service),
            "model_id": MOCK_MODEL_ID,
            "final_answer": "完整解答",
        }
        config = structured_rubric_config(
            version="2025.math1.q17.r1",
            source={
                "source_id": "expert-q17",
                "version": "2025.math1.q17.r1",
                "source_tier": "expert_reconstructed",
            },
            scoring_points=[
                {"point_id": "q17.1", "description": "建立方法", "max_points": 3},
                {"point_id": "q17.2", "description": "完成计算", "max_points": 4},
                {"point_id": "q17.3", "description": "得到结论", "max_points": 3},
            ],
        )
        definition = {
            "instruction": "求定积分并写出过程。",
            "validators": [{"type": "ai_rubric", "weight": 100, "config": config}],
        }
        workspace = Workspace(settings.workspaces_dir / "run-structured-retry")
        valid_result = {
            "schema": RUBRIC_SCHEMA,
            "rubric_version": config["rubric_version"],
            "source_tier": config["source_tier"],
            "solution_path": "reference",
            "points": [
                {
                    "point_id": point["point_id"],
                    "awarded_points": point["max_points"],
                    "status": "met",
                    "confidence": 1,
                    "evidence": "候选答案对应步骤",
                    "rationale": "正确",
                    "propagated_error": False,
                    "independent_work": True,
                }
                for point in config["scoring_points"]
            ],
            "overall_confidence": 1,
            "summary": "逐点评分完成",
            "review_flags": [],
        }
        outputs = [JUDGE_JSON, json.dumps(valid_result, ensure_ascii=False)]
        calls: list[dict[str, object]] = []

        def legacy_then_structured(**kwargs):
            calls.append(kwargs)
            result = outputs.pop(0)
            return CommandResult(
                True,
                0,
                json.dumps({"type": "result", "result": result}, ensure_ascii=False),
                "",
                8,
                None,
            )

        monkeypatch.setattr("agentbench.service.run_native_cli", legacy_then_structured)
        callback = service._judge_callback(run, definition, workspace, lambda *_args: None)
        assert callback is not None
        result = callback(config, 100.0)

        assert len(calls) == 2
        assert result.status == "passed"
        assert result.score == 100
        assert "RUBRIC_RESPONSE_SCHEMA" in str(calls[0]["stdin_text"])
        assert "不要输出旧版 score" in str(calls[1]["stdin_text"])
        assert "不要输出旧版 score" in calls[1]["placeholders"]["prompt"]
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


def test_rejudge_recovers_candidate_answer_after_judge_phase_crash(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        run_id = _create_rubric_run(service)
        before = service.get_run(run_id)
        workspace = settings.workspaces_dir / run_id
        workspace.mkdir(parents=True)
        service.database.execute(
            "UPDATE runs SET status='failed',final_answer=NULL,workspace_path=?,"
            "error_code='internal_error',error_message='[Errno 22] Invalid argument' WHERE id=?",
            (str(workspace), run_id),
        )
        service.database.execute(
            "INSERT INTO run_events(run_id,seq,event_type,payload_json,created_at) "
            "VALUES (?,?,?,?,?)",
            (
                run_id,
                1,
                "live.message",
                json.dumps(
                    {
                        "runner_type": "unified",
                        "text": "OK",
                        "status": "completed",
                    }
                ),
                utc_now(),
            ),
        )
        service.database.execute(
            "INSERT INTO run_events(run_id,seq,event_type,payload_json,created_at) "
            "VALUES (?,?,?,?,?)",
            (run_id, 2, "run.validating", "{}", utc_now()),
        )
        judge_model = service.create_model(
            ModelCreate(name="Judge model", model_name="judge-model", api_style="mock")
        )
        service.update_settings(
            {"judge_model_id": judge_model["id"], "judge_runner_id": UNIFIED_RUNNER_ID}
        )
        service._model_client = lambda _model, _metadata: SequencedClient([JUDGE_JSON])

        response = client.post(f"/api/v1/runs/{run_id}/rejudge")

        assert response.status_code == 200
        recovered = response.json()
        after = recovered
        assert recovered["status"] == "completed"
        assert recovered["final_answer"] == "OK"
        assert recovered["error_code"] is None
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
            "DELETE FROM run_events WHERE run_id=? AND "
            "event_type IN ('run.validating','run.judging')",
            (run_id,),
        )
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

        service._model_client = lambda _model, _metadata: (_ for _ in ()).throw(
            AssertionError("stored structured judge evidence should be reused")
        )
        reused = service.rejudge_run(run_id, reuse_judge=True)
        assert reused["status"] == "completed"
        assert reused["score"] == after["score"]
        stored_validator = service.database.fetch_one(
            "SELECT evidence_json FROM validator_results "
            "WHERE run_id=? AND validator_type='ai_rubric'",
            (run_id,),
        )
        assert json.loads(stored_validator["evidence_json"])["reused_for_revalidation"] is True
    finally:
        service.close()


def test_timeout_with_preserved_workspace_is_scored_automatically(settings, monkeypatch):
    """A watchdog stop must not turn an already-written coding submission into 0."""
    service = EvaluationService(settings)
    try:
        runner = service.create_runner(
            RunnerCreate(name="Timeout native runner", runner_type="command", executable="native")
        )
        expected_answer = (
            "Agent reached the runtime safety limit; score the preserved workspace "
            "as the submitted coding result."
        )
        case = service.import_test_case(
            TestCaseImport(
                slug=f"test.timeout-salvage-{new_id()}",
                version="1.0.0",
                category="ultra-backend",
                title="Timeout workspace salvage",
                instruction="Write the solution and finish the task.",
                initial_files={"starter.txt": "unchanged"},
                validators=[
                    {
                        "type": "exact_match",
                        "weight": 100,
                        "config": {"expected": expected_answer},
                    }
                ],
                limits={"max_steps": 4, "time_target_seconds": 60},
                attempt_policy={
                    "max_attempts": 1,
                    "pass_threshold": 60,
                    "preserve_workspace": True,
                },
            )
        )
        suite_id = new_id()
        service.database.execute(
            "INSERT INTO test_suites(id,name,description,version,builtin,created_at) "
            "VALUES (?,?,?,'1.0.0',0,?)",
            (suite_id, "Timeout salvage suite", "test", utc_now()),
        )
        service.database.execute(
            "INSERT INTO suite_cases(suite_id,test_case_id,position) VALUES (?,?,0)",
            (suite_id, case["id"]),
        )
        experiment = service.create_experiment(
            ExperimentCreate(
                name="Timeout salvage test",
                suite_id=suite_id,
                participants=[
                    Participant(model_id=MOCK_MODEL_ID, runner_id=runner["id"])
                ],
            )
        )
        run_id = service.list_runs(experiment["id"])[0]["id"]

        def timed_out_native_agent(_runner, _model, _definition, workspace, _events, _cancel):
            workspace.write_file("solution.txt", "written before watchdog")
            return AgentResult(
                False,
                "",
                3,
                ModelUsage(input_tokens=12, output_tokens=8),
                1234,
                "runtime_safety_limit",
                "watchdog",
            )

        monkeypatch.setattr(service, "_run_native_agent", timed_out_native_agent)
        service._execute_run(run_id)

        run = service.get_run(run_id)
        assert run["status"] == "completed"
        assert run["score"] > 95.0
        objective = next(
            item for item in run["score_dimensions"] if item["dimension"] == "objective_quality"
        )
        assert objective["score"] == 100.0
        assert run["passed"] is True
        assert run["error_code"] is None
        assert run["final_answer"] == expected_answer
        event_types = {item["event_type"] for item in run["events"]}
        assert {"run.failed", "rejudge.started", "run.timeout_workspace_salvaged"} <= event_types
        # The model attempt remains auditable as a timeout even though its workspace
        # was successfully scored afterwards.
        assert run["attempts"][0]["status"] == "failed"
        assert run["attempts"][0]["raw_score"] > 95.0
        assert (settings.workspaces_dir / run_id / "solution.txt").read_text(encoding="utf-8") == (
            "written before watchdog"
        )
    finally:
        service.close()
